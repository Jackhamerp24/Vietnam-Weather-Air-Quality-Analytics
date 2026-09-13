"""Offline Phase 11 backup/verify/restore-drill tests with fake tools and fake
database responses. No real dump, restore, database, network or credential use."""

import contextlib
import io
import json
import os
import shutil
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.exc import DBAPIError

from vn_air import automation_backup as backup_module
from vn_air.automation import AutomationError, load_automation_config, load_study_config
from vn_air.automation_backup import (
    BACKUP_ARCHIVE_NAMES,
    BACKUP_FAILED_NAME,
    BACKUP_MANIFEST_NAME,
    BACKUP_MIGRATION_ARCHIVE,
    BACKUP_SCHEMA_ARCHIVE,
    CONTENT_PROBE_QUERIES,
    REQUIRED_LISTING,
    RestoreDrill,
    backup_command,
    backup_verify_command,
    create_backup,
    libpq_environment,
    load_backup_manifest,
    sanitized_base_environment,
    validate_manifest_document,
    verify_backup_directory,
    _create_backup_into,
)
from vn_air.automation_health import inspect_backup_evidence


ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_PATH = ROOT / "configs/automation.json"
STUDY_PATH = ROOT / "configs/study.json"
UTC = timezone.utc
FIXED_NOW = datetime(2026, 9, 12, 11, 0, tzinfo=UTC)
PROBE = {name: index + 1 for index, name in enumerate(CONTENT_PROBE_QUERIES)}
PROBE.update({"source_products": 4, "variables": 16, "locations": 5, "sensors": 2})
SOCKET_URL = "postgresql+psycopg://vn_test@/vn_air_test?host=/private/tmp/vnpg"
PASSWORD_URL = "postgresql+psycopg://vn_user:canary-password@db.example.test:5433/vn_air_db?sslmode=require"


def reviewed_configs():
    return load_automation_config(AUTOMATION_PATH), load_study_config(STUDY_PATH)


class FakeResult:
    def __init__(self, value=None):
        self.value = value

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value


class FakeToolRunner:
    def __init__(self, *, fail_on=None, timeout_on=None, listing=None):
        self.calls = []
        self.fail_on = fail_on
        self.timeout_on = timeout_on
        self.listing = listing if listing is not None else listing_text

    def run(self, argv, *, env, timeout):
        argv = [str(argument) for argument in argv]
        self.calls.append({"argv": argv, "env": dict(env), "timeout": timeout})
        if self.timeout_on is not None and self.timeout_on(argv):
            return {"returncode": None, "timed_out": True, "stdout": b"", "stderr": b""}
        if self.fail_on is not None and self.fail_on(argv):
            return {"returncode": 1, "timed_out": False, "stdout": b"", "stderr": b"failure detail"}
        if "--version" in argv:
            return {"returncode": 0, "timed_out": False,
                    "stdout": b"pg_dump (PostgreSQL) 15.17\n", "stderr": b""}
        if "--list" in argv:
            archive = Path(argv[argv.index("--list") + 1]).name
            return {"returncode": 0, "timed_out": False,
                    "stdout": self.listing(archive), "stderr": b""}
        if "--file" in argv:
            target = Path(argv[argv.index("--file") + 1])
            target.write_bytes(b"synthetic archive " + target.name.encode())
            return {"returncode": 0, "timed_out": False, "stdout": b"", "stderr": b""}
        if Path(argv[0]).name == "initdb":
            Path(argv[argv.index("-D") + 1]).mkdir(parents=True, exist_ok=True)
        return {"returncode": 0, "timed_out": False, "stdout": b"", "stderr": b""}


def listing_text(archive):
    role_archive = (BACKUP_SCHEMA_ARCHIVE if "vn_air_schema" in archive
                    else BACKUP_MIGRATION_ARCHIVE if "vn_air_migration" in archive
                    else archive)
    markers = REQUIRED_LISTING.get(role_archive)
    lines = ["; synthetic listing", "; Selected TOC Entries:"]
    if markers:
        lines.extend(f"42; 1259 1 {marker} owner" for marker in markers)
    else:
        lines.append("42; 1259 1 TABLE synthetic owner")
    return ("\n".join(lines) + "\n").encode()


def fake_lookup(name):
    return f"/fake/bin/{name}" if name in {"pg_dump", "pg_restore", "initdb", "pg_ctl", "createdb"} else None


def short_drill_parent(testcase, name):
    parent = Path("/tmp") / f"vnair_drill_{name}_{os.getpid()}"
    parent.mkdir(mode=0o700, exist_ok=True)
    testcase.addCleanup(lambda: shutil.rmtree(parent, ignore_errors=True))
    return parent


class FakeProbeConnection:
    def __init__(self, *, probe=None, revision="0003_response_integrity"):
        self.probe = dict(probe or PROBE)
        self.revision = revision
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append(sql)
        if "SET TRANSACTION READ ONLY" in sql or "set_config" in sql:
            return FakeResult(None)
        if "to_regclass" in sql:
            return FakeResult("public.vn_air_schema_version")
        if "FROM public.vn_air_schema_version" in sql:
            return FakeResult(self.revision)
        if "server_version_num" in sql:
            return FakeResult(150017)
        for name, query in CONTENT_PROBE_QUERIES.items():
            if sql.strip() == query:
                return FakeResult(self.probe[name])
        raise AssertionError(f"unexpected probe SQL: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposed = True


class FakeOrig(Exception):
    def __init__(self, sqlstate):
        self.sqlstate = sqlstate
        super().__init__(sqlstate)


class FakeDrillConnection:
    def __init__(self, probe=None):
        self.probe = dict(probe or PROBE)
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append(sql)
        stripped = sql.strip().upper()
        if stripped.startswith("UPDATE"):
            raise DBAPIError(sql, {}, FakeOrig("23514"))
        if stripped.startswith("INSERT"):
            raise DBAPIError(sql, {}, FakeOrig("23503"))
        if "SET TRANSACTION" in sql or "set_config" in sql:
            return FakeResult(None)
        if "FROM public.vn_air_schema_version" in sql:
            return FakeResult("0003_response_integrity")
        if "latest_air_quality" in sql or "weather_observations" in sql or "modeled_air_quality" in sql:
            return FakeResult(3)
        if "pg_class" in sql:
            return FakeResult(1)
        if "pg_namespace" in sql:
            return FakeResult(0)
        for name, query in CONTENT_PROBE_QUERIES.items():
            if sql.strip() == query:
                return FakeResult(self.probe[name])
        raise AssertionError(f"unexpected drill SQL: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeDrillEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False

    def connect(self):
        return self.connection

    @contextlib.contextmanager
    def begin(self):
        yield self.connection

    def dispose(self):
        self.disposed = True


class BackupTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.config, self.study = reviewed_configs()
        self.runner = FakeToolRunner(listing=listing_text)
        self.environ = {"DATABASE_URL": SOCKET_URL, "PATH": "/usr/bin", "HOME": str(self.base),
                        "PGHOST": "/ambient", "PGSERVICE": "ambient", "PGPASSFILE": "/ambient/pgpass",
                        "PGOPTIONS": "-c search_path=evil", "PGPASSWORD": "ambient-canary",
                        "OPENAQ_API_KEY": "unneeded-openaq-canary",
                        "UNRELATED_SECRET": "unrelated-secret-canary",
                        "UNRELATED_TOKEN": "unrelated-token-canary",
                        "SUPABASE_SECRET_KEY": "unneeded-supabase-canary"}

    def engine_factory(self, probe=None, revision="0003_response_integrity"):
        return lambda: FakeEngine(FakeProbeConnection(probe=probe, revision=revision))

    def create(self, name="backup", runner=None, environ=None, tool_lookup=None, engine_factory=None):
        return create_backup(self.config, self.study, output_dir=self.base / name,
                             environ=self.environ if environ is None else environ,
                             tool_runner=runner or self.runner,
                             tool_lookup=tool_lookup or fake_lookup,
                             engine_factory=engine_factory or self.engine_factory(),
                             now=lambda: FIXED_NOW)

    def verify(self, backup_dir, *, runner=None, restore_drill=False, lookup=None,
               engine_factory=None, parent=None):
        return verify_backup_directory(backup_dir, tool_runner=runner or self.runner,
                                       tool_lookup=lookup or fake_lookup, restore_drill=restore_drill,
                                       config=self.config, study=self.study, environ=self.environ,
                                       now=lambda: FIXED_NOW, drill_base_parent=parent,
                                       drill_engine_factory=engine_factory)


class EnvironmentTests(BackupTestCase):
    def test_sanitized_environment_strips_pg_and_project_urls(self):
        environment = sanitized_base_environment(self.environ)
        for leaked in ("DATABASE_URL", "PGHOST", "PGSERVICE", "PGPASSFILE", "PGOPTIONS", "PGPASSWORD"):
            self.assertNotIn(leaked, environment)
        for leaked in ("OPENAQ_API_KEY", "UNRELATED_SECRET", "UNRELATED_TOKEN", "SUPABASE_SECRET_KEY"):
            self.assertNotIn(leaked, environment)
        self.assertEqual(environment["PATH"], "/usr/bin")

    def test_libpq_environment_maps_password_without_exposing_it(self):
        environment, metadata = libpq_environment(PASSWORD_URL, self.environ)
        self.assertEqual(environment["PGHOST"], "db.example.test")
        self.assertEqual(environment["PGPORT"], "5433")
        self.assertEqual(environment["PGDATABASE"], "vn_air_db")
        self.assertEqual(environment["PGUSER"], "vn_user")
        self.assertEqual(environment["PGPASSWORD"], "canary-password")
        self.assertEqual(environment["PGSSLMODE"], "require")
        self.assertNotIn("canary-password", json.dumps(metadata))
        self.assertNotIn("db.example.test", json.dumps(metadata))

    def test_socket_url_maps_to_pghost_query(self):
        environment, metadata = libpq_environment(SOCKET_URL, self.environ)
        self.assertEqual(environment["PGHOST"], "/private/tmp/vnpg")
        self.assertEqual(environment["PGDATABASE"], "vn_air_test")
        self.assertTrue(metadata["connects_over_socket"])

    def test_unsupported_query_options_and_unsafe_targets_rejected(self):
        cases = {
            "options": "postgresql+psycopg://u@h/db?options=-csearch_path%3Devil",
            "service": "postgresql+psycopg://u@h/db?service=prod",
            "passfile": "postgresql+psycopg://u@h/db?passfile=/tmp/pgpass",
            "multiple_hosts": "postgresql+psycopg://u@h1,h2/db",
            "template": "postgresql+psycopg://u@h/template1",
            "wrong_driver": "mysql://u@h/db",
            "missing_database": "postgresql+psycopg://u@h/",
            "target_session_attrs": "postgresql+psycopg://u@h/db?target_session_attrs=read-write",
        }
        for name, url in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(AutomationError):
                    libpq_environment(url, self.environ)

    def test_supabase_hosts_require_tls(self):
        with self.assertRaises(AutomationError) as context:
            libpq_environment("postgresql+psycopg://u:p@db.abcdefg.supabase.co/db?sslmode=disable",
                              self.environ)
        self.assertEqual(context.exception.code, "automation_backup_tls_required")
        environment, _ = libpq_environment("postgresql+psycopg://u:p@db.abcdefg.supabase.co/db",
                                           self.environ)
        self.assertEqual(environment["PGSSLMODE"], "require")


class CreateBackupTests(BackupTestCase):
    def test_backup_creates_manifest_and_owner_only_archives(self):
        result = self.create()
        self.assertEqual(result["status"], "backup_created")
        root = self.base / "backup"
        self.assertEqual(sorted(path.name for path in root.iterdir()),
                         sorted([BACKUP_FAILED_NAME, BACKUP_MANIFEST_NAME, *BACKUP_ARCHIVE_NAMES])[1:])
        manifest = load_backup_manifest(root)
        self.assertEqual(manifest["scope"], "project_logical")
        self.assertEqual(manifest["database"]["schema_revision"], "0003_response_integrity")
        self.assertEqual(manifest["database"]["dump_tool_version"], "15.17")
        self.assertEqual(manifest["content_probe"], PROBE)
        self.assertEqual([entry["file"] for entry in manifest["archives"]], list(BACKUP_ARCHIVE_NAMES))
        for entry in manifest["archives"]:
            archive = root / entry["file"]
            self.assertEqual(archive.stat().st_size, entry["bytes"])
            self.assertEqual(backup_module.sha256_file(archive), entry["sha256"])
            self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((root / BACKUP_MANIFEST_NAME).stat().st_mode), 0o600)
        self.assertFalse((root / BACKUP_FAILED_NAME).exists())
        self.assertNotIn("canary-password", json.dumps(manifest))
        self.assertNotIn("/private/tmp/vnpg", json.dumps(manifest))

    def test_backup_uses_two_project_scoped_archives_not_a_combined_selection(self):
        self.create()
        dump_calls = [call for call in self.runner.calls if "--file" in call["argv"]]
        self.assertEqual(len(dump_calls), 2)
        schema_argv, migration_argv = dump_calls[0]["argv"], dump_calls[1]["argv"]
        self.assertIn("--schema", schema_argv)
        self.assertIn("vn_air", schema_argv)
        self.assertNotIn("--table", schema_argv)
        self.assertIn("--table", migration_argv)
        self.assertIn("public.vn_air_schema_version", migration_argv)
        self.assertNotIn("--schema", migration_argv)
        for call in dump_calls:
            joined = " ".join(call["argv"])
            self.assertNotIn("postgresql", joined)
            self.assertNotIn("canary-password", joined)
            self.assertNotIn("ambient", call["env"].get("PGHOST", ""))

    def test_backup_environment_is_sanitized_for_tools(self):
        self.create()
        for call in self.runner.calls:
            self.assertNotIn("PGSERVICE", call["env"])
            self.assertNotIn("PGOPTIONS", call["env"])
            self.assertNotIn("UNRELATED_SECRET", call["env"])
            self.assertNotIn("SUPABASE_SECRET_KEY", call["env"])
            self.assertNotEqual(call["env"].get("PGPASSWORD"), "ambient-canary")
            self.assertEqual(call["env"].get("PGHOST"), "/private/tmp/vnpg")

    def test_backup_does_not_pass_final_archive_paths_to_pg_dump(self):
        self.create()
        dump_calls = [call for call in self.runner.calls if "--file" in call["argv"]]
        self.assertEqual(len(dump_calls), 2)
        for call in dump_calls:
            target = Path(call["argv"][call["argv"].index("--file") + 1])
            self.assertNotIn(target.name, BACKUP_ARCHIVE_NAMES)
            self.assertTrue(target.name.endswith(".partial"))

    def test_backup_rejects_archive_created_during_dump(self):
        class RaceRunner(FakeToolRunner):
            def run(self, argv, *, env, timeout):
                if "--file" in argv:
                    temporary = Path(argv[argv.index("--file") + 1])
                    (temporary.parent / BACKUP_SCHEMA_ARCHIVE).write_bytes(b"race")
                return super().run(argv, env=env, timeout=timeout)

        with self.assertRaises(AutomationError) as context:
            self.create(name="race", runner=RaceRunner(listing=listing_text))
        self.assertEqual(context.exception.code, "automation_backup_archive_exists")
        root = self.base / "race"
        self.assertEqual((root / BACKUP_SCHEMA_ARCHIVE).read_bytes(), b"race")
        self.assertFalse((root / BACKUP_MANIFEST_NAME).exists())
        self.assertFalse(any(path.name.endswith(".partial") for path in root.iterdir()))

    def test_backup_rejects_preexisting_archive(self):
        output = self.base / "occupied-archive"
        output.mkdir(mode=0o700)
        (output / BACKUP_SCHEMA_ARCHIVE).write_bytes(b"old")
        tool_env, _ = libpq_environment(SOCKET_URL, self.environ)
        with self.assertRaises(AutomationError) as context:
            _create_backup_into(self.config, output, tool_env, self.runner, fake_lookup,
                                self.engine_factory(), lambda: FIXED_NOW)
        self.assertEqual(context.exception.code, "automation_backup_archive_exists")

    def test_backup_rejects_symlink_final_archive_without_touching_destination(self):
        output = self.base / "symlink-archive"
        output.mkdir(mode=0o700)
        victim = self.base / "preserved"
        victim.write_bytes(b"original")
        (output / BACKUP_SCHEMA_ARCHIVE).symlink_to(victim)
        tool_env, _ = libpq_environment(SOCKET_URL, self.environ)
        with self.assertRaises(AutomationError) as context:
            _create_backup_into(self.config, output, tool_env, self.runner, fake_lookup,
                                self.engine_factory(), lambda: FIXED_NOW)
        self.assertEqual(context.exception.code, "automation_backup_archive_exists")
        self.assertEqual(victim.read_bytes(), b"original")
        self.assertFalse(any("--file" in call["argv"] for call in self.runner.calls))

    def test_backup_timeout_cleans_partial_without_publishing(self):
        runner = FakeToolRunner(timeout_on=lambda argv: "--file" in argv)
        with self.assertRaises(AutomationError) as context:
            self.create(name="timeout", runner=runner)
        self.assertEqual(context.exception.code, "automation_backup_dump_failed_timeout")
        self.assertEqual({path.name for path in (self.base / "timeout").iterdir()}, {BACKUP_FAILED_NAME})

    def test_backup_failure_leaves_a_failed_marker_and_no_manifest(self):
        def fail_dump(argv):
            return "--file" in argv and "--schema" in argv
        runner = FakeToolRunner(fail_on=fail_dump, listing=listing_text)
        with self.assertRaises(AutomationError) as context:
            self.create(name="failed", runner=runner)
        self.assertEqual(context.exception.code, "automation_backup_dump_failed")
        root = self.base / "failed"
        self.assertTrue((root / BACKUP_FAILED_NAME).is_file())
        self.assertFalse((root / BACKUP_MANIFEST_NAME).exists())
        marker = json.loads((root / BACKUP_FAILED_NAME).read_text())
        self.assertEqual(marker["status"], "failed")
        self.assertIn("NOT a valid backup", marker["note"])
        self.assertFalse(any(path.name.endswith(".partial") for path in root.iterdir()))

    def test_backup_rejects_empty_dump_missing_tools_and_bad_listing(self):
        empty_runner = FakeToolRunner(listing=listing_text)
        original_run = empty_runner.run

        def run_and_truncate(argv, *, env, timeout):
            outcome = original_run(argv, env=env, timeout=timeout)
            if "--file" in argv:
                Path(argv[argv.index("--file") + 1]).write_bytes(b"")
            return outcome
        empty_runner.run = run_and_truncate
        with self.assertRaises(AutomationError) as context:
            self.create(name="empty", runner=empty_runner)
        self.assertEqual(context.exception.code, "automation_backup_dump_empty")

        with self.assertRaises(AutomationError) as context:
            self.create(name="notools", tool_lookup=lambda name: None)
        self.assertEqual(context.exception.code, "automation_restore_tools_missing")

        bad_listing = FakeToolRunner(listing=lambda archive: b"; nothing\n")
        with self.assertRaises(AutomationError) as context:
            self.create(name="badlisting", runner=bad_listing)
        self.assertEqual(context.exception.code, "automation_backup_listing_failed")

        incomplete_listing = FakeToolRunner(listing=lambda archive: b"1; 1259 1 TABLE synthetic owner\n")
        with self.assertRaises(AutomationError) as context:
            self.create(name="incomplete", runner=incomplete_listing)
        self.assertEqual(context.exception.code, "automation_backup_listing_missing_objects")

    def test_backup_rejects_mismatched_schema_revision_and_existing_output(self):
        with self.assertRaises(AutomationError) as context:
            self.create(name="mismatch", engine_factory=self.engine_factory(revision="0002_ingestion"))
        self.assertEqual(context.exception.code, "schema_revision_mismatch")
        self.assertTrue((self.base / "mismatch" / BACKUP_FAILED_NAME).is_file())

        existing = self.base / "occupied"
        existing.mkdir()
        with self.assertRaises(AutomationError) as context:
            self.create(name="occupied")
        self.assertEqual(context.exception.code, "automation_output_exists")
        self.assertEqual(list(existing.iterdir()), [])

    def test_backup_command_requires_execute_and_output_directory(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(backup_command(self.config, self.study, output_dir=self.base / "x",
                                            execute=False, environ=self.environ,
                                            tool_runner=self.runner, tool_lookup=fake_lookup),
                             3)
            self.assertEqual(backup_command(self.config, self.study, output_dir=None, execute=True,
                                            environ=self.environ, tool_runner=self.runner,
                                            tool_lookup=fake_lookup), 3)
        self.assertIn("automation_execute_required", stderr.getvalue())
        self.assertIn("automation_output_required", stderr.getvalue())
        self.assertFalse((self.base / "x").exists())

    def test_backup_command_returns_zero_for_success(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = backup_command(self.config, self.study, output_dir=self.base / "command",
                                  execute=True, environ=self.environ, tool_runner=self.runner,
                                  tool_lookup=fake_lookup, engine_factory=self.engine_factory(),
                                  now=lambda: FIXED_NOW)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "backup_created")


class VerifyBackupTests(BackupTestCase):
    def test_checksum_verified_without_restore_drill(self):
        self.create()
        result = self.verify(self.base / "backup")
        self.assertEqual(result["status"], "checksum_verified")
        self.assertTrue(result["checksum_verified"])
        self.assertTrue(result["listing_verified"])
        self.assertFalse(result["restore_verified"])

    def test_tampered_missing_extra_and_symlinked_files_are_rejected(self):
        self.create()
        root = self.base / "backup"
        original = (root / BACKUP_SCHEMA_ARCHIVE).read_bytes()

        (root / BACKUP_SCHEMA_ARCHIVE).write_bytes(original + b"tamper")
        with self.assertRaises(AutomationError) as context:
            self.verify(root)
        self.assertEqual(context.exception.code, "automation_backup_size_mismatch")
        (root / BACKUP_SCHEMA_ARCHIVE).write_bytes(original)

        (root / BACKUP_MIGRATION_ARCHIVE).write_bytes(b"different bytes")
        with self.assertRaises(AutomationError) as context:
            self.verify(root)
        self.assertEqual(context.exception.code, "automation_backup_size_mismatch")

        self.create(name="extras")
        (self.base / "extras" / "extra.txt").write_text("extra")
        with self.assertRaises(AutomationError) as context:
            self.verify(self.base / "extras")
        self.assertEqual(context.exception.code, "automation_backup_file_extra")

        self.create(name="linked")
        link = self.base / "linked" / BACKUP_SCHEMA_ARCHIVE
        target = self.base / "outside.dump"
        target.write_bytes(b"x")
        link.unlink()
        link.symlink_to(target)
        with self.assertRaises(AutomationError) as context:
            self.verify(self.base / "linked")
        self.assertEqual(context.exception.code, "automation_backup_file_unsafe")

        self.create(name="missing")
        (self.base / "missing" / BACKUP_SCHEMA_ARCHIVE).unlink()
        with self.assertRaises(AutomationError) as context:
            self.verify(self.base / "missing")
        self.assertEqual(context.exception.code, "automation_backup_file_missing")

        self.create(name="insecure")
        os.chmod(self.base / "insecure" / BACKUP_SCHEMA_ARCHIVE, 0o644)
        with self.assertRaises(AutomationError) as context:
            self.verify(self.base / "insecure")
        self.assertEqual(context.exception.code, "automation_backup_permissions_insecure")

    def test_manifest_mutations_are_rejected(self):
        document = {
            "automation_version": backup_module.BACKUP_VERSION, "artifact_version": 1,
            "command": "backup", "scope": "project_logical", "created_at_utc": "2026-09-12T11:00:00+00:00",
            "database": {"schema_revision": "0003_response_integrity", "server_version_num": 150017,
                         "dump_tool": "pg_dump", "dump_tool_version": "15.17", "format": "custom"},
            "content_probe": dict(PROBE),
            "archives": [
                {"role": "vn_air_schema", "file": BACKUP_SCHEMA_ARCHIVE, "format": "custom", "bytes": 10,
                 "sha256": "a" * 64, "restore_order": 1, "listing_entries": 3},
                {"role": "public_migration_table", "file": BACKUP_MIGRATION_ARCHIVE, "format": "custom",
                 "bytes": 10, "sha256": "b" * 64, "restore_order": 2, "listing_entries": 3},
            ],
            "restore_order": list(BACKUP_ARCHIVE_NAMES),
            "included": ["a"], "excluded": ["b"], "notes": ["c"],
        }
        validate_manifest_document(document)
        mutations = {
            "bool_bytes": lambda row: row["archives"][0].update(bytes=True),
            "bool_version": lambda row: row.update(artifact_version=True),
            "extra_field": lambda row: row.update(unexpected=1),
            "hash_case": lambda row: row["archives"][0].update(sha256="A" * 64),
            "role_rename": lambda row: row["archives"][0].update(role="renamed"),
            "restore_order": lambda row: row.update(restore_order=list(reversed(BACKUP_ARCHIVE_NAMES))),
            "naive_time": lambda row: row.update(created_at_utc="2026-09-12T11:00:00"),
            "probe_missing": lambda row: row["content_probe"].pop("sensors"),
            "probe_bool": lambda row: row["content_probe"].update(sensors=True),
            "empty_included": lambda row: row.update(included=[]),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                candidate = json.loads(json.dumps(document))
                mutate(candidate)
                with self.assertRaises(AutomationError) as context:
                    validate_manifest_document(candidate)
                self.assertEqual(context.exception.code, "automation_backup_manifest_invalid")

    def test_restore_drill_runs_isolated_and_reports_evidence(self):
        self.create()
        drill_connection = FakeDrillConnection()
        engine = FakeDrillEngine(drill_connection)
        factory_calls = []

        def factory():
            factory_calls.append(True)
            return engine

        parent = short_drill_parent(self, "ok")
        result = self.verify(self.base / "backup", restore_drill=True, engine_factory=factory,
                             parent=parent)
        self.assertEqual(result["status"], "restore_verified")
        self.assertTrue(result["restore_verified"])
        evidence = result["restore_evidence"]
        self.assertEqual(evidence["schema_revision"], "0003_response_integrity")
        self.assertTrue(evidence["unrelated_schemas_absent"])
        self.assertTrue(evidence["project_public_relations_only"])
        self.assertTrue(all(evidence["constraint_probes"].values()))
        self.assertEqual(list(parent.iterdir()), [])
        self.assertEqual(factory_calls, [True])
        restore_calls = [call for call in self.runner.calls
                         if Path(call["argv"][0]).name == "pg_restore" and "-d" in call["argv"]]
        self.assertEqual(len(restore_calls), 2)
        for call in restore_calls:
            self.assertIn("--no-owner", call["argv"])
            self.assertIn("--no-privileges", call["argv"])
            self.assertIn("--exit-on-error", call["argv"])
            self.assertIn("vn_air_restore", call["argv"])
            self.assertNotIn("DATABASE_URL", call["env"])
            self.assertNotIn("PGSERVICE", call["env"])
        initdb = [call for call in self.runner.calls if Path(call["argv"][0]).name == "initdb"]
        self.assertEqual(len(initdb), 1)
        self.assertIn("--auth-host=reject", initdb[0]["argv"])
        pg_ctl = [call for call in self.runner.calls if Path(call["argv"][0]).name == "pg_ctl"]
        self.assertTrue(any("listen_addresses=''" in argument for call in pg_ctl for argument in call["argv"]))
        self.assertTrue(any("-k " in argument for call in pg_ctl for argument in call["argv"]))

    def test_restore_drill_failure_reports_and_cleans_up(self):
        self.create()
        def fail_restore(argv):
            return Path(argv[0]).name == "pg_restore" and "-d" in argv
        runner = FakeToolRunner(fail_on=fail_restore, listing=listing_text)
        parent = short_drill_parent(self, "fail")
        with self.assertRaises(AutomationError) as context:
            self.verify(self.base / "backup", runner=runner, restore_drill=True, parent=parent)
        self.assertEqual(context.exception.code, "automation_restore_drill_failed")
        self.assertEqual(list(parent.iterdir()), [])

    def test_restore_drill_requires_configuration(self):
        self.create()
        with self.assertRaises(AutomationError) as context:
            verify_backup_directory(self.base / "backup", tool_runner=self.runner,
                                    tool_lookup=fake_lookup, restore_drill=True)
        self.assertEqual(context.exception.code, "automation_backup_config_required")

    def test_backup_verify_command_exit_codes(self):
        self.create()
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = backup_verify_command(self.config, self.study, backup_dir=self.base / "backup",
                                         tool_runner=self.runner, tool_lookup=fake_lookup,
                                         environ=self.environ)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "checksum_verified")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(backup_verify_command(self.config, self.study, backup_dir=None), 3)
        missing = self.base / "does-not-exist"
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            code = backup_verify_command(self.config, self.study, backup_dir=missing,
                                         tool_runner=self.runner, tool_lookup=fake_lookup,
                                         environ=self.environ)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "verification_failed")


class HealthBackupInspectionTests(BackupTestCase):
    def test_health_backup_evidence_current_and_stale(self):
        self.create()
        current = inspect_backup_evidence(self.base / "backup", as_of=FIXED_NOW,
                                          stale_after_seconds=129600)
        self.assertEqual(current["status"], "current")
        self.assertFalse(current["checksum_verified"])
        stale = inspect_backup_evidence(self.base / "backup", as_of=FIXED_NOW + timedelta(days=7),
                                        stale_after_seconds=129600)
        self.assertEqual(stale["status"], "stale")
        missing = inspect_backup_evidence(self.base / "none", as_of=FIXED_NOW,
                                          stale_after_seconds=129600)
        self.assertEqual(missing["status"], "missing")

    def test_health_backup_evidence_rejects_invalid_manifest(self):
        self.create()
        manifest_path = self.base / "backup" / BACKUP_MANIFEST_NAME
        document = json.loads(manifest_path.read_text())
        document["artifact_version"] = True
        manifest_path.write_text(json.dumps(document))
        result = inspect_backup_evidence(self.base / "backup", as_of=FIXED_NOW,
                                         stale_after_seconds=129600)
        self.assertEqual(result["status"], "invalid")

    def test_health_backup_evidence_rejects_inconsistent_files(self):
        self.create()
        archive = self.base / "backup" / BACKUP_SCHEMA_ARCHIVE
        archive.write_bytes(archive.read_bytes() + b"tamper")
        result = inspect_backup_evidence(self.base / "backup", as_of=FIXED_NOW,
                                         stale_after_seconds=129600)
        self.assertEqual(result["status"], "invalid")
        self.assertFalse(result["checksum_verified"])


class DispatchTests(BackupTestCase):
    def test_automation_command_dispatches_new_actions(self):
        from unittest.mock import patch

        from vn_air.automation import automation_command

        captured = {}

        def backup_stub(config, study, **kwargs):
            captured["backup"] = kwargs
            return 0

        def verify_stub(config, study, **kwargs):
            captured["verify"] = kwargs
            return 0

        def health_stub(config, study, **kwargs):
            captured["health"] = kwargs
            return 0

        def recover_stub(config, study, **kwargs):
            captured["recover"] = kwargs
            return 0

        with patch("vn_air.automation_backup.backup_command", side_effect=backup_stub), \
                patch("vn_air.automation_backup.backup_verify_command", side_effect=verify_stub), \
                patch("vn_air.automation_health.health_command", side_effect=health_stub), \
                patch("vn_air.automation_health.recover_command", side_effect=recover_stub):
            self.assertEqual(automation_command(
                action="backup", automation_config=AUTOMATION_PATH, study_config=STUDY_PATH,
                output_dir=self.base / "out", execute=True), 0)
            self.assertEqual(automation_command(
                action="backup-verify", automation_config=AUTOMATION_PATH, study_config=STUDY_PATH,
                backup_dir=self.base / "b", restore_drill=True), 0)
            self.assertEqual(automation_command(
                action="health", automation_config=AUTOMATION_PATH, study_config=STUDY_PATH,
                backup_dir=self.base / "b", output=self.base / "health.json"), 0)
            self.assertEqual(automation_command(
                action="recover", automation_config=AUTOMATION_PATH, study_config=STUDY_PATH,
                output=self.base / "recover.json"), 0)
        self.assertTrue(captured["backup"]["execute"])
        self.assertEqual(captured["backup"]["output_dir"], self.base / "out")
        self.assertTrue(captured["verify"]["restore_drill"])
        self.assertEqual(captured["verify"]["backup_dir"], self.base / "b")
        self.assertEqual(captured["health"]["output"], self.base / "health.json")
        self.assertEqual(captured["recover"]["output"], self.base / "recover.json")


class ModuleSafetyTests(unittest.TestCase):
    def test_module_never_reads_dotenv_or_uses_a_shell(self):
        source = Path(backup_module.__file__).read_text()
        self.assertNotIn("dotenv", source)
        self.assertNotIn('".env"', source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system", source)


if __name__ == "__main__":
    unittest.main()
