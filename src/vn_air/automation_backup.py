"""Phase 11 project-scoped PostgreSQL logical backup and restore verification.

Uses PostgreSQL-native custom-format archives and libpq environment mapping.
The dump tool never receives a URI, password or shell string in argv; ambient
``PG*`` service/passfile/options routing is stripped and credentials are mapped
from the operator's explicit ``DATABASE_URL`` into a sanitized child
environment. The manifest records tool/server versions, schema revision, UTC
time, sizes and SHA-256 without recording connection identifiers.

Restore verification targets a new private socket-only cluster created from
native binaries, never the configured project database. Checksum/listing checks
alone report ``checksum_verified``; only a real dump/restore round trip reports
``restore_verified``. This is a project logical backup, not a physical or
Supabase-managed backup, and no automatic deletion is implemented.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from vn_air.automation import (
    AUTOMATION_VERSION,
    AutomationError,
    iso,
    reserve_output_dir,
    utc_now,
)
from vn_air.database.setup import database_engine
from vn_air.automation_environment import safe_runtime_environment

BACKUP_VERSION = AUTOMATION_VERSION
BACKUP_MANIFEST_NAME = "phase_11_backup_manifest.json"
BACKUP_FAILED_NAME = "phase_11_backup_failed.json"
BACKUP_SCHEMA_ARCHIVE = "vn_air_schema.dump"
BACKUP_MIGRATION_ARCHIVE = "vn_air_migration.dump"
BACKUP_SCOPE = "project_logical"
BACKUP_FORMAT = "custom"

BACKUP_ARCHIVE_PLAN = (
    {"role": "vn_air_schema", "file": BACKUP_SCHEMA_ARCHIVE, "restore_order": 1},
    {"role": "public_migration_table", "file": BACKUP_MIGRATION_ARCHIVE, "restore_order": 2},
)
BACKUP_ARCHIVE_ROLES = {entry["role"]: entry for entry in BACKUP_ARCHIVE_PLAN}
BACKUP_ARCHIVE_NAMES = tuple(entry["file"] for entry in BACKUP_ARCHIVE_PLAN)

BACKUP_DUMP_TIMEOUT_SECONDS = 900
BACKUP_LIST_TIMEOUT_SECONDS = 120
BACKUP_TOOL_VERSION_TIMEOUT_SECONDS = 30
MAX_LISTING_BYTES = 4 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024

RESTORE_DRILL_PREFIX = "vnair_drill_"
RESTORE_DRILL_ROLE = "vn_restore"
RESTORE_DRILL_DATABASE = "vn_air_restore"
RESTORE_DRILL_INIT_TIMEOUT_SECONDS = 180
RESTORE_DRILL_START_TIMEOUT_SECONDS = 60
RESTORE_DRILL_TOOL_TIMEOUT_SECONDS = 900
RESTORE_DRILL_MAX_SOCKET_PATH_BYTES = 104

ALLOWED_URL_QUERY_OPTIONS = frozenset({
    "host", "port", "sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout",
})
SUPABASE_HOST_SUFFIXES = (".supabase.co", ".supabase.com")
SUPABASE_REQUIRED_SSLMODES = frozenset({"require", "verify-ca", "verify-full"})

CONTENT_PROBE_QUERIES = {
    "reference_configs": "SELECT count(*) FROM vn_air.reference_configs",
    "source_products": "SELECT count(*) FROM vn_air.source_products",
    "variables": "SELECT count(*) FROM vn_air.variables",
    "locations": "SELECT count(*) FROM vn_air.locations",
    "sensors": "SELECT count(*) FROM vn_air.sensors",
    "ingestion_runs": "SELECT count(*) FROM vn_air.ingestion_runs",
    "source_responses": "SELECT count(*) FROM vn_air.source_responses",
    "source_responses_with_body": "SELECT count(*) FROM vn_air.source_responses WHERE body IS NOT NULL",
    "source_response_body_hashes": "SELECT count(DISTINCT body_sha256) FROM vn_air.source_responses WHERE body IS NOT NULL",
    "air_quality_observations": "SELECT count(*) FROM vn_air.air_quality_observations",
    "air_quality_intervals": "SELECT count(DISTINCT (sensor_id, period_start, period_end)) FROM vn_air.air_quality_observations",
    "air_quality_max_revision": "SELECT coalesce(max(revision), 0) FROM vn_air.air_quality_observations",
    "model_snapshots": "SELECT count(*) FROM vn_air.model_snapshots",
    "modeled_values": "SELECT count(*) FROM vn_air.modeled_values",
    "modeled_values_finite": "SELECT count(*) FROM vn_air.modeled_values WHERE value IS NOT NULL",
    "ingestion_checkpoints": "SELECT count(*) FROM vn_air.ingestion_checkpoints",
    "data_quality_issues": "SELECT count(*) FROM vn_air.data_quality_issues",
    "quarantined_records": "SELECT count(*) FROM vn_air.quarantined_records",
}

REQUIRED_SCHEMA_LISTING = (
    "SCHEMA - vn_air",
    "FUNCTION vn_air require_usable_response()",
    "FUNCTION vn_air reject_mutation()",
    "FUNCTION vn_air check_observation()",
    "FUNCTION vn_air check_modeled_value()",
    "FUNCTION vn_air check_prediction()",
    "VIEW vn_air latest_air_quality",
    "VIEW vn_air weather_observations",
    "VIEW vn_air modeled_air_quality",
    "TABLE vn_air air_quality_observations",
    "TABLE vn_air source_responses",
    "TABLE vn_air ingestion_checkpoints",
)
REQUIRED_MIGRATION_LISTING = (
    "TABLE public vn_air_schema_version",
    "TABLE DATA public vn_air_schema_version",
)
REQUIRED_LISTING = {
    BACKUP_SCHEMA_ARCHIVE: REQUIRED_SCHEMA_LISTING,
    BACKUP_MIGRATION_ARCHIVE: REQUIRED_MIGRATION_LISTING,
}

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
VERSION_PATTERN = re.compile(r"([0-9]+(?:\.[0-9]+)+)")

MANIFEST_NOTES = (
    "Project logical backup: includes schema vn_air and public.vn_air_schema_version only.",
    "Excludes Supabase-managed schemas, unrelated schemas, cluster roles, auth and storage objects.",
    "No automatic deletion; retention and off-site copies are operator responsibilities.",
    "Archives are custom-format and may differ in bytes between runs; this is not analytical replay.",
)


class ToolRunner:
    """Bounded shell-free tool invocation; never persists stdout/stderr content."""

    def run(self, argv: list[str], *, env: dict, timeout: float) -> dict:
        try:
            completed = subprocess.run(
                list(argv), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=timeout, check=False, close_fds=True)
        except subprocess.TimeoutExpired:
            return {"returncode": None, "timed_out": True, "stdout": b"", "stderr": b""}
        except OSError:
            raise AutomationError("automation_tool_spawn_failed") from None
        return {"returncode": completed.returncode, "timed_out": False,
                "stdout": completed.stdout or b"", "stderr": completed.stderr or b""}


def sanitized_base_environment(environ: dict) -> dict:
    return safe_runtime_environment(environ)


def libpq_environment(url_value: str, environ: dict) -> tuple[dict, dict]:
    """Map a validated SQLAlchemy URL into a sanitized libpq environment.

    Returns ``(environment, metadata)``. The URL value, password and host are
    never placed in argv and never returned in metadata.
    """
    try:
        parsed = make_url(url_value)
    except Exception:
        raise AutomationError("automation_backup_url_invalid") from None
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"} or not parsed.database:
        raise AutomationError("automation_backup_url_invalid")
    if parsed.database in {"template0", "template1"}:
        raise AutomationError("automation_backup_template_database")
    if parsed.host and "," in parsed.host:
        raise AutomationError("automation_backup_url_invalid")
    query: dict[str, str] = {}
    for key, value in dict(parsed.query or {}).items():
        if not isinstance(value, str):
            raise AutomationError("automation_backup_url_option_unsupported")
        query[key] = value
    unsupported = set(query) - ALLOWED_URL_QUERY_OPTIONS
    if unsupported:
        raise AutomationError("automation_backup_url_option_unsupported")
    host = query.get("host") or parsed.host or ""
    sslmode = query.get("sslmode")
    if host.lower().endswith(SUPABASE_HOST_SUFFIXES):
        if sslmode is None:
            sslmode = "require"
        elif sslmode not in SUPABASE_REQUIRED_SSLMODES:
            raise AutomationError("automation_backup_tls_required")
    environment = sanitized_base_environment(environ)
    if host:
        environment["PGHOST"] = host
    port = query.get("port") or parsed.port
    if port:
        environment["PGPORT"] = str(port)
    environment["PGDATABASE"] = parsed.database
    if parsed.username:
        environment["PGUSER"] = parsed.username
    if parsed.password:
        environment["PGPASSWORD"] = parsed.password
    if sslmode:
        environment["PGSSLMODE"] = sslmode
    for option, target in (("sslrootcert", "PGSSLROOTCERT"), ("sslcert", "PGSSLCERT"), ("sslkey", "PGSSLKEY")):
        if query.get(option):
            environment[target] = query[option]
    environment["PGCONNECT_TIMEOUT"] = str(query.get("connect_timeout") or 10)
    environment["PGAPPNAME"] = "vn_air_phase11_backup"
    metadata = {"format": BACKUP_FORMAT,
                "connects_over_socket": parsed.host is None and "host" in query}
    return environment, metadata


def require_tool(name: str, lookup: Callable) -> str:
    executable = lookup(name)
    if executable is None:
        raise AutomationError("automation_restore_tools_missing", f"missing={name}")
    return executable


def _check_tool_outcome(outcome: dict, code: str) -> dict:
    if outcome.get("timed_out"):
        raise AutomationError(f"{code}_timeout")
    if outcome.get("returncode") != 0:
        raise AutomationError(code)
    return outcome


def tool_version(runner, executable: str, env: dict, *, timeout: float) -> str:
    outcome = _check_tool_outcome(runner.run([executable, "--version"], env=env, timeout=timeout),
                                  "automation_backup_tool_failed")
    match = VERSION_PATTERN.search((outcome.get("stdout") or b"").decode("utf-8", errors="ignore"))
    if match is None:
        raise AutomationError("automation_backup_tool_failed")
    return match.group(1)


def probe_database(engine_factory: Callable, *, expected_revision: str) -> dict:
    try:
        engine = engine_factory()
    except ValueError:
        raise AutomationError("database_url_missing") from None
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SELECT set_config('statement_timeout', '30000', true)"))
            installed = connection.execute(
                text("SELECT to_regclass('public.vn_air_schema_version')")).scalar_one()
            if installed is None:
                raise AutomationError("schema_revision_missing")
            revision = connection.execute(
                text("SELECT version_num FROM public.vn_air_schema_version")).scalar_one_or_none()
            if revision != expected_revision:
                raise AutomationError("schema_revision_mismatch")
            server_version = int(connection.execute(
                text("SELECT current_setting('server_version_num')")).scalar_one())
            probe = {}
            for name, sql in CONTENT_PROBE_QUERIES.items():
                value = connection.execute(text(sql)).scalar_one()
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    raise AutomationError("automation_backup_probe_failed")
                probe[name] = value
    except AutomationError:
        raise
    except SQLAlchemyError:
        raise AutomationError("database_unavailable") from None
    finally:
        engine.dispose()
    return {"schema_revision": revision, "server_version_num": server_version, "content_probe": probe}


def parse_listing(stdout: bytes) -> tuple[list[str], list[str]]:
    if len(stdout) > MAX_LISTING_BYTES:
        raise AutomationError("automation_backup_listing_failed")
    text_value = stdout.decode("utf-8", errors="ignore")
    entries = []
    header = []
    for line in text_value.splitlines():
        if line.startswith(";"):
            header.append(line.lstrip("; ").strip())
            continue
        if line.strip():
            entries.append(line)
    return header, entries


def _listing_facts(runner, executable: str, archive: Path, env: dict) -> dict:
    outcome = _check_tool_outcome(
        runner.run([executable, "--list", str(archive)], env=env, timeout=BACKUP_LIST_TIMEOUT_SECONDS),
        "automation_backup_listing_failed")
    _, entries = parse_listing(outcome.get("stdout") or b"")
    if not entries:
        raise AutomationError("automation_backup_listing_failed")
    return {"entries": len(entries), "lines": entries}


def _required_listing_present(entries: list[str], required: tuple[str, ...]) -> list[str]:
    missing = []
    for marker in required:
        if not any(marker in entry for entry in entries):
            missing.append(marker)
    return missing


def _regular_file(path: Path, *, allow_missing: bool = False) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return allow_missing
    return stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode)


def _mode_is_owner_only(path: Path) -> bool:
    return stat.S_IMODE(path.lstat().st_mode) & 0o077 == 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_exclusive_json(path: Path, document: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
        handle.write("\n")


def write_failure_marker(output_dir: Path, code: str, *, now: datetime) -> None:
    try:
        write_exclusive_json(output_dir / BACKUP_FAILED_NAME, {
            "automation_version": BACKUP_VERSION,
            "command": "backup",
            "status": "failed",
            "error_code": code,
            "failed_at_utc": iso(now),
            "note": "This directory is NOT a valid backup; do not restore or copy it as one.",
        })
    except OSError:
        pass


def create_backup(config, study, *, output_dir: Path, environ: dict | None = None,
                  tool_runner=None, tool_lookup: Callable | None = None,
                  engine_factory: Callable | None = None, now: Callable = utc_now) -> dict:
    runner = tool_runner or ToolRunner()
    lookup = tool_lookup or shutil.which
    environment = dict(os.environ if environ is None else environ)
    url_value = environment.get("DATABASE_URL")
    if not url_value:
        raise AutomationError("database_url_missing")
    tool_env, _ = libpq_environment(url_value, environment)
    output = reserve_output_dir(output_dir)
    factory = engine_factory or (lambda: database_engine(url_value))
    try:
        return _create_backup_into(config, output, tool_env, runner, lookup, factory, now)
    except AutomationError as error:
        write_failure_marker(output, error.code, now=now())
        raise
    except Exception:
        write_failure_marker(output, "internal_error", now=now())
        raise AutomationError("internal_error") from None


def _create_backup_into(config, output: Path, tool_env: dict, runner, lookup, engine_factory,
                        now: Callable) -> dict:
    created = now().astimezone(timezone.utc)
    pg_dump = require_tool("pg_dump", lookup)
    pg_restore = require_tool("pg_restore", lookup)
    dump_version = tool_version(runner, pg_dump, tool_env, timeout=BACKUP_TOOL_VERSION_TIMEOUT_SECONDS)
    probe = probe_database(engine_factory, expected_revision=config.readiness.schema_revision)

    archives = []
    for plan in BACKUP_ARCHIVE_PLAN:
        archive = output / plan["file"]
        temporary = None
        descriptor = None
        try:
            try:
                archive.lstat()
            except FileNotFoundError:
                pass
            except OSError:
                raise AutomationError("automation_backup_archive_exists") from None
            else:
                raise AutomationError("automation_backup_archive_exists")
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{plan['file']}.", suffix=".partial", dir=output)
            temporary = Path(temporary_name)
            original = os.fstat(descriptor)
            if plan["role"] == "vn_air_schema":
                selection = ["--schema", "vn_air"]
            else:
                selection = ["--table", "public.vn_air_schema_version"]
            argv = [pg_dump, "--format", BACKUP_FORMAT, "--no-password", *selection,
                    "--file", str(temporary)]
            outcome = runner.run(argv, env=tool_env, timeout=BACKUP_DUMP_TIMEOUT_SECONDS)
            _check_tool_outcome(outcome, "automation_backup_dump_failed")
            captured = temporary.lstat()
            if (not stat.S_ISREG(captured.st_mode)
                    or (captured.st_dev, captured.st_ino) != (original.st_dev, original.st_ino)):
                raise AutomationError("automation_backup_dump_missing")
            if captured.st_size <= 0:
                raise AutomationError("automation_backup_dump_empty")
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
            try:
                os.link(temporary, archive, follow_symlinks=False)
            except FileExistsError:
                raise AutomationError("automation_backup_archive_exists") from None
            except OSError:
                raise AutomationError("automation_backup_publish_failed") from None
            os.unlink(temporary)
            temporary = None
            if not _regular_file(archive) or archive.is_symlink():
                raise AutomationError("automation_backup_dump_missing")
            listing = _listing_facts(runner, pg_restore, archive, tool_env)
            missing = _required_listing_present(listing["lines"], REQUIRED_LISTING[plan["file"]])
            if missing:
                raise AutomationError("automation_backup_listing_missing_objects")
            archives.append({
                "role": plan["role"],
                "file": plan["file"],
                "format": BACKUP_FORMAT,
                "bytes": archive.stat().st_size,
                "sha256": sha256_file(archive),
                "restore_order": plan["restore_order"],
                "listing_entries": listing["entries"],
            })
        except OSError:
            raise AutomationError("automation_backup_archive_io_failed") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    raise AutomationError("automation_backup_temp_cleanup_failed") from None

    manifest = {
        "automation_version": BACKUP_VERSION,
        "artifact_version": 1,
        "command": "backup",
        "scope": BACKUP_SCOPE,
        "created_at_utc": iso(created),
        "database": {
            "schema_revision": probe["schema_revision"],
            "server_version_num": probe["server_version_num"],
            "dump_tool": "pg_dump",
            "dump_tool_version": dump_version,
            "format": BACKUP_FORMAT,
        },
        "content_probe": probe["content_probe"],
        "archives": archives,
        "restore_order": list(BACKUP_ARCHIVE_NAMES),
        "included": ["schema vn_air (tables, data, functions, triggers, views, constraints, sequences)",
                     "public.vn_air_schema_version (migration revision)"],
        "excluded": ["Supabase-managed schemas", "cluster roles and role memberships",
                     "unrelated application schemas", "response bodies are included as retained raw evidence",
                     "no connection identifier, host or password is recorded"],
        "notes": list(MANIFEST_NOTES),
    }
    write_exclusive_json(output / BACKUP_MANIFEST_NAME, manifest)
    os.chmod(output / BACKUP_MANIFEST_NAME, 0o600)
    return {"status": "backup_created", "output_dir": str(output),
            "manifest": BACKUP_MANIFEST_NAME, "file_count": len(archives),
            "total_bytes": sum(archive["bytes"] for archive in archives)}


def _strict_keys(document, allowed: set, *, context: str) -> dict:
    if not isinstance(document, dict) or set(document) - allowed:
        raise AutomationError("automation_backup_manifest_invalid", f"field={context}")
    return document


def _strict_str(document, key: str, *, maximum: int = 200) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise AutomationError("automation_backup_manifest_invalid", f"field={key}")
    return value


def _strict_int(document, key: str, *, minimum: int = 0) -> int:
    value = document.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AutomationError("automation_backup_manifest_invalid", f"field={key}")
    return value


def validate_manifest_document(document: dict) -> dict:
    _strict_keys(document, {
        "automation_version", "artifact_version", "command", "scope", "created_at_utc",
        "database", "content_probe", "archives", "restore_order", "included", "excluded", "notes",
    }, context="top_level")
    if document.get("automation_version") != BACKUP_VERSION:
        raise AutomationError("automation_backup_manifest_invalid", "field=automation_version")
    if document.get("artifact_version") != 1 or isinstance(document.get("artifact_version"), bool):
        raise AutomationError("automation_backup_manifest_invalid", "field=artifact_version")
    if document.get("command") != "backup" or document.get("scope") != BACKUP_SCOPE:
        raise AutomationError("automation_backup_manifest_invalid", "field=command")
    created_text = _strict_str(document, "created_at_utc", maximum=64)
    try:
        created = datetime.fromisoformat(created_text)
    except ValueError:
        raise AutomationError("automation_backup_manifest_invalid", "field=created_at_utc") from None
    if created.utcoffset() is None:
        raise AutomationError("automation_backup_manifest_invalid", "field=created_at_utc")

    database = _strict_keys(document.get("database"),
                            {"schema_revision", "server_version_num", "dump_tool", "dump_tool_version", "format"},
                            context="database")
    _strict_str(database, "schema_revision")
    _strict_int(database, "server_version_num", minimum=150000)
    if database.get("dump_tool") != "pg_dump" or database.get("format") != BACKUP_FORMAT:
        raise AutomationError("automation_backup_manifest_invalid", "field=database")
    _strict_str(database, "dump_tool_version", maximum=40)

    probe = _strict_keys(document.get("content_probe"), set(CONTENT_PROBE_QUERIES), context="content_probe")
    for key in CONTENT_PROBE_QUERIES:
        _strict_int(probe, key)

    archives = document.get("archives")
    if not isinstance(archives, list) or len(archives) != len(BACKUP_ARCHIVE_PLAN):
        raise AutomationError("automation_backup_manifest_invalid", "field=archives")
    seen = set()
    for entry in archives:
        entry = _strict_keys(entry, {"role", "file", "format", "bytes", "sha256", "restore_order", "listing_entries"},
                             context="archives")
        role = _strict_str(entry, "role", maximum=64)
        if role not in BACKUP_ARCHIVE_ROLES:
            raise AutomationError("automation_backup_manifest_invalid", "field=role")
        plan = BACKUP_ARCHIVE_ROLES[role]
        if entry.get("file") != plan["file"] or entry.get("restore_order") != plan["restore_order"]:
            raise AutomationError("automation_backup_manifest_invalid", "field=file")
        if role in seen:
            raise AutomationError("automation_backup_manifest_invalid", "field=role")
        seen.add(role)
        if entry.get("format") != BACKUP_FORMAT:
            raise AutomationError("automation_backup_manifest_invalid", "field=format")
        _strict_int(entry, "bytes", minimum=1)
        _strict_int(entry, "listing_entries", minimum=1)
        digest = _strict_str(entry, "sha256", maximum=64)
        if not SHA256_PATTERN.fullmatch(digest):
            raise AutomationError("automation_backup_manifest_invalid", "field=sha256")
    if seen != set(BACKUP_ARCHIVE_ROLES):
        raise AutomationError("automation_backup_manifest_invalid", "field=archives")
    if document.get("restore_order") != list(BACKUP_ARCHIVE_NAMES):
        raise AutomationError("automation_backup_manifest_invalid", "field=restore_order")
    for key in ("included", "excluded", "notes"):
        value = document.get(key)
        if (not isinstance(value, list) or not value
                or not all(isinstance(item, str) and item for item in value)):
            raise AutomationError("automation_backup_manifest_invalid", f"field={key}")
    return {"created_at": created}


def load_backup_manifest(backup_dir: Path) -> dict:
    directory = Path(backup_dir)
    if directory.is_symlink() or not directory.is_dir():
        raise AutomationError("automation_backup_dir_invalid")
    manifest_path = directory / BACKUP_MANIFEST_NAME
    if manifest_path.is_symlink() or not _regular_file(manifest_path):
        raise AutomationError("automation_backup_manifest_missing")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise AutomationError("automation_backup_manifest_invalid")
    try:
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        raise AutomationError("automation_backup_manifest_invalid") from None
    validate_manifest_document(document)
    return document


def verify_backup_directory(backup_dir: Path, *, tool_runner=None, tool_lookup: Callable | None = None,
                            restore_drill: bool = False, config=None, study=None,
                            environ: dict | None = None, now: Callable = utc_now,
                            drill_base_parent: Path | None = None,
                            drill_engine_factory: Callable | None = None) -> dict:
    runner = tool_runner or ToolRunner()
    lookup = tool_lookup or shutil.which
    directory = Path(backup_dir)
    document = load_backup_manifest(directory)
    if not _mode_is_owner_only(directory / BACKUP_MANIFEST_NAME):
        raise AutomationError("automation_backup_permissions_insecure", f"file={BACKUP_MANIFEST_NAME}")
    expected_names = {BACKUP_MANIFEST_NAME, *BACKUP_ARCHIVE_NAMES}
    present = {}
    for child in directory.iterdir():
        if child.is_symlink() or not child.is_file():
            raise AutomationError("automation_backup_file_unsafe", f"name={child.name}")
        present[child.name] = child
    if set(present) - expected_names:
        raise AutomationError("automation_backup_file_extra", f"count={len(set(present) - expected_names)}")
    missing = expected_names - set(present)
    if missing:
        raise AutomationError("automation_backup_file_missing", f"count={len(missing)}")

    verification = []
    for entry in document["archives"]:
        path = directory / entry["file"]
        if not _mode_is_owner_only(path):
            raise AutomationError("automation_backup_permissions_insecure", f"file={entry['file']}")
        if path.stat().st_size != entry["bytes"]:
            raise AutomationError("automation_backup_size_mismatch", f"file={entry['file']}")
        if sha256_file(path) != entry["sha256"]:
            raise AutomationError("automation_backup_checksum_mismatch", f"file={entry['file']}")
        verification.append(entry["file"])

    pg_restore = require_tool("pg_restore", lookup)
    sanitized = sanitized_base_environment(dict(os.environ if environ is None else environ))
    listing_entries = {}
    for entry in sorted(document["archives"], key=lambda item: item["restore_order"]):
        listing = _listing_facts(runner, pg_restore, directory / entry["file"], sanitized)
        if len(listing["lines"]) != entry["listing_entries"]:
            raise AutomationError("automation_backup_listing_failed", f"file={entry['file']}")
        missing_objects = _required_listing_present(listing["lines"], REQUIRED_LISTING[entry["file"]])
        if missing_objects:
            raise AutomationError("automation_backup_listing_missing_objects", f"file={entry['file']}")
        listing_entries[entry["file"]] = listing["entries"]

    result = {
        "automation_version": BACKUP_VERSION,
        "command": "backup-verify",
        "status": "checksum_verified",
        "checksum_verified": True,
        "listing_verified": True,
        "restore_verified": False,
        "manifest": BACKUP_MANIFEST_NAME,
        "archives": [{"file": entry["file"], "bytes": entry["bytes"], "sha256": entry["sha256"],
                      "listing_entries": entry["listing_entries"]} for entry in document["archives"]],
        "notes": ["Checksum/listing verification only; restore verification requires --restore-drill."],
    }
    if not restore_drill:
        return result
    if config is None or study is None:
        raise AutomationError("automation_backup_config_required")
    drill = RestoreDrill(runner=runner, lookup=lookup, base_parent=drill_base_parent,
                         engine_factory=drill_engine_factory)
    evidence = drill.run(directory, document, config=config, study=study, now=now)
    result.update({
        "status": "restore_verified",
        "restore_verified": True,
        "restore_evidence": evidence,
        "notes": ["Checksum/listing verification plus a real dump/restore round trip in a disposable cluster."],
    })
    return result


class RestoreDrill:
    """Real restore into a new private socket-only cluster; never the project DB."""

    def __init__(self, *, runner, lookup: Callable, base_parent: Path | None = None,
                 engine_factory: Callable | None = None):
        self.runner = runner
        self.lookup = lookup
        self.base_parent = Path(base_parent) if base_parent is not None else None
        self.engine_factory = engine_factory

    def run(self, backup_dir: Path, document: dict, *, config, study, now: Callable) -> dict:
        initdb = require_tool("initdb", self.lookup)
        pg_ctl = require_tool("pg_ctl", self.lookup)
        createdb = require_tool("createdb", self.lookup)
        pg_restore = require_tool("pg_restore", self.lookup)
        base = Path(tempfile.mkdtemp(prefix=RESTORE_DRILL_PREFIX, dir=self.base_parent))
        data = base / "data"
        socket = base / "socket"
        socket.mkdir(mode=0o700)
        if len(os.fsencode(str(socket))) + 20 >= RESTORE_DRILL_MAX_SOCKET_PATH_BYTES:
            shutil.rmtree(base, ignore_errors=True)
            raise AutomationError("automation_restore_path_too_long")
        sanitized = sanitized_base_environment(dict(os.environ))
        drill_env = dict(sanitized)
        drill_env.update({"PGHOST": str(socket), "PGUSER": RESTORE_DRILL_ROLE,
                          "PGDATABASE": RESTORE_DRILL_DATABASE, "PGCONNECT_TIMEOUT": "10",
                          "PGAPPNAME": "vn_air_phase11_restore_drill"})
        started = False
        engine = None
        outcome = None
        try:
            _check_tool_outcome(self.runner.run(
                [initdb, "-D", str(data), "--auth-local=trust", "--auth-host=reject",
                 "--username", RESTORE_DRILL_ROLE, "--encoding=UTF8", "--no-locale"],
                env=sanitized, timeout=RESTORE_DRILL_INIT_TIMEOUT_SECONDS), "automation_restore_drill_failed")
            _check_tool_outcome(self.runner.run(
                [pg_ctl, "-D", str(data), "-l", str(base / "postgres.log"), "-o",
                 f"-k {socket} -c listen_addresses='' -c fsync=off", "-w", "start"],
                env=sanitized, timeout=RESTORE_DRILL_START_TIMEOUT_SECONDS), "automation_restore_drill_failed")
            started = True
            _check_tool_outcome(self.runner.run(
                [createdb, "--host", str(socket), "--username", RESTORE_DRILL_ROLE, RESTORE_DRILL_DATABASE],
                env=sanitized, timeout=RESTORE_DRILL_START_TIMEOUT_SECONDS), "automation_restore_drill_failed")
            for name in document["restore_order"]:
                _check_tool_outcome(self.runner.run(
                    [pg_restore, "--no-owner", "--no-privileges", "--exit-on-error", "--no-password",
                     "-d", RESTORE_DRILL_DATABASE, str(backup_dir / name)],
                    env=drill_env, timeout=RESTORE_DRILL_TOOL_TIMEOUT_SECONDS), "automation_restore_drill_failed")
            engine = (self.engine_factory or (lambda: database_engine(
                f"postgresql+psycopg://{RESTORE_DRILL_ROLE}@/{RESTORE_DRILL_DATABASE}?host={socket}")))()
            outcome = self._verify(engine, document, config=config, study=study, now=now)
            return outcome
        except AutomationError:
            raise
        except SQLAlchemyError:
            raise AutomationError("automation_restore_drill_failed") from None
        finally:
            if engine is not None:
                engine.dispose()
            if started:
                self.runner.run([pg_ctl, "-D", str(data), "-m", "fast", "-w", "stop"],
                                env=sanitized, timeout=RESTORE_DRILL_START_TIMEOUT_SECONDS)
            self._cleanup(base)

    def _cleanup(self, base: Path) -> None:
        parent = base.parent.resolve()
        allowed = {Path(tempfile.gettempdir()).resolve()}
        if self.base_parent is not None:
            allowed.add(Path(self.base_parent).resolve())
        if not base.name.startswith(RESTORE_DRILL_PREFIX) or parent not in allowed:
            raise AutomationError("automation_restore_cleanup_failed")
        try:
            shutil.rmtree(base)
        except OSError:
            raise AutomationError("automation_restore_cleanup_failed") from None

    def _verify(self, engine, document: dict, *, config, study, now: Callable) -> dict:
        expected_counts = {
            "source_products": len(study.products),
            "variables": len(study.variables),
            "locations": len(study.locations),
            "sensors": len(study.sensors),
        }
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SELECT set_config('statement_timeout', '30000', true)"))
            revision = connection.execute(
                text("SELECT version_num FROM public.vn_air_schema_version")).scalar_one_or_none()
            probe = {}
            for name, sql in CONTENT_PROBE_QUERIES.items():
                probe[name] = int(connection.execute(text(sql)).scalar_one())
            view_counts = {}
            for view in ("latest_air_quality", "weather_observations", "modeled_air_quality"):
                view_counts[view] = int(connection.execute(
                    text(f"SELECT count(*) FROM vn_air.{view}")).scalar_one())
            unexpected_schemas = int(connection.execute(text("""
                SELECT count(*) FROM pg_namespace
                WHERE nspname NOT IN ('pg_catalog', 'information_schema', 'public', 'pg_toast', 'vn_air')
                  AND nspname NOT LIKE 'pg_temp%' AND nspname NOT LIKE 'pg_toast_temp%'
            """)).scalar_one())
            public_relations = int(connection.execute(text("""
                SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
            """)).scalar_one())
        constraint_probes = {
            "append_only_trigger": _expect_sqlstate(engine, """
                UPDATE vn_air.locations SET name = name
                WHERE id = (SELECT id FROM vn_air.locations LIMIT 1)
            """, "23514"),
            "foreign_key": _expect_sqlstate(engine, """
                INSERT INTO vn_air.quarantined_records (response_id, record_locator, reason_code, details)
                VALUES ('00000000-0000-0000-0000-000000000000', 'drill', 'drill', '{}'::jsonb)
            """, "23503"),
        }
        if revision != document["database"]["schema_revision"]:
            raise AutomationError("automation_restore_content_mismatch", "field=schema_revision")
        if any(probe[name] != value for name, value in document["content_probe"].items()):
            raise AutomationError("automation_restore_content_mismatch", "field=content_probe")
        for name, expected in expected_counts.items():
            if probe[name] != expected:
                raise AutomationError("automation_restore_content_mismatch", f"field={name}")
        if not all(constraint_probes.values()):
            raise AutomationError("automation_restore_constraint_probe_failed")
        if unexpected_schemas != 0:
            raise AutomationError("automation_restore_unexpected_schemas")
        if public_relations != 1:
            raise AutomationError("automation_restore_unexpected_schemas", "field=public")
        return {
            "schema_revision": revision,
            "reference_counts": expected_counts,
            "content_probe": probe,
            "view_row_counts": view_counts,
            "unrelated_schemas_absent": unexpected_schemas == 0,
            "project_public_relations_only": public_relations == 1,
            "constraint_probes": constraint_probes,
            "verified_at_utc": iso(now()),
            "notes": [
                "Cluster was created from native binaries for this drill only and removed afterwards.",
                "No migration or reseeding repaired the restored database.",
            ],
        }


def _expect_sqlstate(engine, sql: str, expected: str) -> bool:
    try:
        with engine.begin() as connection:
            connection.execute(text(sql))
    except DBAPIError as error:
        return getattr(getattr(error, "orig", None), "sqlstate", None) == expected
    return False


BACKUP_CONFIG_ERROR_CODES = frozenset({
    "database_url_missing", "automation_backup_url_invalid", "automation_backup_url_option_unsupported",
    "automation_backup_template_database", "automation_backup_tls_required",
    "automation_execute_required", "automation_output_required", "automation_output_exists",
    "automation_output_parent_invalid", "automation_output_broad", "automation_backup_config_required",
})


def backup_command(config, study, *, output_dir: Path | None, execute: bool,
                   environ: dict | None = None, tool_runner=None, tool_lookup=None,
                   engine_factory: Callable | None = None, now: Callable = utc_now) -> int:
    if not execute:
        print("automation: automation_execute_required", file=sys.stderr)
        return 3
    if output_dir is None:
        print("automation: automation_output_required", file=sys.stderr)
        return 3
    try:
        result = create_backup(config, study, output_dir=Path(output_dir), environ=environ,
                               tool_runner=tool_runner, tool_lookup=tool_lookup,
                               engine_factory=engine_factory, now=now)
    except AutomationError as error:
        print(f"automation: {error.code}", file=sys.stderr)
        return 3 if error.code in BACKUP_CONFIG_ERROR_CODES else 1
    except Exception:
        print("automation: internal_error", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    print(f"automation backup: status=backup_created files={result['file_count']} "
          f"bytes={result['total_bytes']} manifest={result['manifest']}", file=sys.stderr)
    return 0


def backup_verify_command(config, study, *, backup_dir: Path | None, restore_drill: bool = False,
                          tool_runner=None, tool_lookup=None, environ: dict | None = None,
                          now: Callable = utc_now) -> int:
    if backup_dir is None:
        print("automation: automation_backup_dir_required", file=sys.stderr)
        return 3
    try:
        result = verify_backup_directory(Path(backup_dir), tool_runner=tool_runner,
                                         tool_lookup=tool_lookup, restore_drill=restore_drill,
                                         config=config, study=study, environ=environ, now=now)
    except AutomationError as error:
        print(json.dumps({"automation_version": BACKUP_VERSION, "command": "backup-verify",
                          "status": "verification_failed", "error_code": error.code,
                          "restore_verified": False}, sort_keys=True))
        print(f"automation backup-verify: verification_failed {error.code}", file=sys.stderr)
        return 3 if error.code in {"automation_backup_config_required"} else 1
    except OSError:
        print(json.dumps({"automation_version": BACKUP_VERSION, "command": "backup-verify",
                          "status": "verification_failed", "error_code": "automation_backup_dir_invalid",
                          "restore_verified": False}, sort_keys=True))
        print("automation backup-verify: verification_failed automation_backup_dir_invalid", file=sys.stderr)
        return 1
    except Exception:
        print(json.dumps({"automation_version": BACKUP_VERSION, "command": "backup-verify",
                          "status": "verification_failed", "error_code": "internal_error",
                          "restore_verified": False}, sort_keys=True))
        print("automation backup-verify: verification_failed internal_error", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    print(f"automation backup-verify: status={result['status']} "
          f"checksum_verified={result['checksum_verified']} restore_verified={result['restore_verified']}",
          file=sys.stderr)
    return 0


__all__ = [
    "BACKUP_ARCHIVE_NAMES", "BACKUP_ARCHIVE_PLAN", "BACKUP_FAILED_NAME", "BACKUP_MANIFEST_NAME",
    "BACKUP_SCHEMA_ARCHIVE", "BACKUP_MIGRATION_ARCHIVE", "BACKUP_SCOPE", "BACKUP_VERSION",
    "CONTENT_PROBE_QUERIES", "RestoreDrill", "ToolRunner", "backup_command", "backup_verify_command",
    "create_backup", "libpq_environment", "load_backup_manifest", "probe_database",
    "sanitized_base_environment", "validate_manifest_document", "verify_backup_directory",
    "write_failure_marker",
]
