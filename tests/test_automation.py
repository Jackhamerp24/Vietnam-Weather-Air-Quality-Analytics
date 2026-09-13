"""Offline Phase 11 automation tests with fake clocks, subprocess runners and
database responses. No database, network, scheduler or credential access."""

import contextlib
import copy
import io
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.exc import OperationalError

from vn_air import automation as automation_module
from vn_air.automation import (
    AUTOMATION_VERSION,
    CYCLE_ALERTS_NAME,
    CYCLE_SUMMARY_NAME,
    CYCLE_SUCCESS_NAME,
    MAX_CONFIG_BYTES,
    AutomationError,
    CycleLock,
    SubprocessSupervisor,
    automation_command,
    build_plan,
    database_preflight,
    environment_secrets,
    extract_event,
    extract_stderr_codes,
    load_automation_config,
    load_study_config,
    reserve_output_dir,
    run_cycle,
    sanitize_event,
    scrub_text,
    validate_config_targets,
)


ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_PATH = ROOT / "configs/automation.json"
STUDY_PATH = ROOT / "configs/study.json"
UTC = timezone.utc
FIXED_NOW = datetime(2026, 9, 12, 10, 30, tzinfo=UTC)
OK_PREFLIGHT = {"status": "ok", "schema_revision": "0003_response_integrity",
                "database_bytes": 4096, "server_version_num": 150000}
LOCK_HELPER = (
    "import sys\n"
    "from pathlib import Path\n"
    "from vn_air.automation import CycleLock\n"
    "lock = CycleLock(Path(sys.argv[1]))\n"
    "print('acquired' if lock.acquire() else 'contended')\n"
)
LOCK_HOLDER = (
    "import sys, time\n"
    "from pathlib import Path\n"
    "from vn_air.automation import CycleLock\n"
    "lock = CycleLock(Path(sys.argv[1]))\n"
    "print('acquired' if lock.acquire() else 'contended', flush=True)\n"
    "time.sleep(30)\n"
)


class FakeClock:
    def __init__(self, *values):
        self.values = list(values) or [0.0]
        self.index = 0

    def __call__(self):
        if self.index < len(self.values) - 1:
            value = self.values[self.index]
            self.index += 1
            return value
        return self.values[-1]


class FakeSupervisor:
    executable = sys.executable

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def run(self, argv, *, timeout_seconds=None, grace_seconds=None, env=None):
        self.calls.append({"argv": list(argv), "timeout_seconds": timeout_seconds,
                           "grace_seconds": grace_seconds})
        if not self.outcomes:
            raise AssertionError("unexpected supervisor call")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        document = {"exit_code": 0, "timed_out": False, "duration_seconds": 0.25,
                    "events": [], "stderr_error_codes": [], "stdout_bytes": 0,
                    "stderr_bytes": 0, "invalid_stdout_lines": 0, "invalid_stderr_lines": 0}
        document.update(outcome)
        return document


class FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value


class FakeConnection:
    def __init__(self, *, installed="public.vn_air_schema_version",
                 revision="0003_response_integrity", size=4096, server_version=150000):
        self.installed, self.revision, self.size, self.server_version = installed, revision, size, server_version
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if "server_version_num" in sql:
            return FakeResult(self.server_version)
        if "to_regclass" in sql:
            return FakeResult(self.installed)
        if "FROM public.vn_air_schema_version" in sql:
            return FakeResult(self.revision)
        if "pg_database_size" in sql:
            return FakeResult(self.size)
        return FakeResult(None)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeEngine:
    def __init__(self, connection=None, connect_error=None):
        self.connection = connection or FakeConnection()
        self.connect_error = connect_error
        self.disposed = False

    def connect(self):
        if self.connect_error is not None:
            raise self.connect_error
        return self.connection

    def dispose(self):
        self.disposed = True


def reviewed_configs():
    return load_automation_config(AUTOMATION_PATH), load_study_config(STUDY_PATH)


class AutomationTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.config, self.study = reviewed_configs()

    def invalid(self, document, name="invalid", code="automation_config_invalid"):
        path = self.base / f"{name}.json"
        path.write_text(json.dumps(document))
        with self.assertRaises(AutomationError) as context:
            load_automation_config(path)
        self.assertEqual(context.exception.code, code)
        return context.exception

    def budget(self, document):
        return json.loads(json.dumps(document))

    def run_fake_cycle(self, outcomes, *, name="cycle", config=None, clock=None,
                      preflight=None, secrets=()):
        supervisor = FakeSupervisor(outcomes)
        result = run_cycle(
            config or self.config, self.study, output_dir=self.base / name, execute=True,
            lock_path=self.base / "lock" / "cycle.lock", supervisor=supervisor,
            preflight=preflight or (lambda remaining: dict(OK_PREFLIGHT)),
            clock=clock or FakeClock(0.0), now=lambda: FIXED_NOW, cycle_id="cycle-test",
            secrets=secrets)
        return supervisor, result

    def read_evidence(self, result):
        root = Path(result["summary_path"]).parent
        return root, json.loads((root / CYCLE_SUMMARY_NAME).read_text())


class ConfigTests(AutomationTestCase):
    def test_reviewed_profile_matches_gate_zero_decisions(self):
        self.assertEqual([job.id for job in self.config.jobs],
                         ["openaq_poll", "weather_poll", "cams_poll"])
        self.assertEqual([job.source for job in self.config.jobs], ["openaq", "weather", "cams"])
        self.assertEqual([job.max_requests for job in self.config.jobs], [10, 5, 5])
        self.assertEqual(self.config.jobs[0].targets, ["openaq_11357424", "openaq_14581375"])
        self.assertEqual(self.config.jobs[1].targets, ["cmt8", "oceanpark"])
        self.assertEqual(self.config.jobs[2].targets, ["hanoi", "hcmc", "da_nang"])
        self.assertEqual(self.config.cycle.job_timeout_seconds, 900)
        self.assertEqual(self.config.cycle.cycle_timeout_seconds, 2700)
        self.assertEqual(self.config.cycle.terminate_grace_seconds, 5)
        self.assertEqual(self.config.cycle.expected_cadence_seconds, 3600)
        self.assertTrue(self.config.cycle.stop_on_failure)
        self.assertEqual(self.config.readiness.schema_revision, "0003_response_integrity")
        self.assertEqual(self.config.readiness.max_database_mib, 400)
        self.assertEqual(self.config.readiness.openaq_min_accepted_intervals, 18)
        self.assertEqual(self.config.readiness.stale_running_age_seconds, 1800)
        self.assertEqual(self.config.output.root, ".local/automation")
        self.assertFalse(self.config.backup.automatic_deletion)

    def test_missing_config_fails_closed(self):
        with self.assertRaises(AutomationError) as context:
            load_automation_config(self.base / "missing.json")
        self.assertEqual(context.exception.code, "automation_config_missing")

    def test_duplicate_keys_are_rejected(self):
        path = self.base / "duplicate.json"
        path.write_text('{"version": 1, "version": 1}')
        with self.assertRaises(AutomationError) as context:
            load_automation_config(path)
        self.assertEqual(context.exception.code, "automation_config_duplicate_key")

    def test_invalid_json_is_rejected(self):
        path = self.base / "broken.json"
        path.write_text("{not json")
        with self.assertRaises(AutomationError) as context:
            load_automation_config(path)
        self.assertEqual(context.exception.code, "automation_config_invalid_json")

    def test_unknown_fields_types_and_budgets_are_rejected(self):
        document = json.loads(AUTOMATION_PATH.read_text())
        mutations = {
            "unknown_top_level": lambda row: row.update(unexpected=True),
            "boolean_budget": lambda row: row["jobs"][0].update(max_requests=True),
            "boolean_timeout": lambda row: row["cycle"].update(job_timeout_seconds=True),
            "string_budget": lambda row: row["jobs"][0].update(max_requests="10"),
            "zero_budget": lambda row: row["jobs"][0].update(max_requests=0),
            "oversize_budget": lambda row: row["jobs"][0].update(max_requests=501),
            "negative_timeout": lambda row: row["cycle"].update(job_timeout_seconds=-1),
            "duplicate_job_id": lambda row: row["jobs"][1].update(id="openaq_poll"),
            "duplicate_target": lambda row: row["jobs"][0].update(targets=["openaq_11357424", "openaq_11357424"]),
            "duplicate_job_work_renamed": lambda row: row["jobs"].__setitem__(
                1, dict(row["jobs"][0], id="renamed_openaq_work")),
            "target_in_two_jobs": lambda row: row["jobs"][1].update(targets=["cmt8", "openaq_11357424"]),
            "wrong_window": lambda row: row["jobs"][1].update(window="openaq_last_72_complete_utc_hours"),
            "automatic_deletion": lambda row: row["backup"].update(automatic_deletion=True),
            "automatic_deletion_zero": lambda row: row["backup"].update(automatic_deletion=0),
            "duplicate_backup_age": lambda row: row["backup"].update(stale_after_seconds=129600),
            "output_traversal": lambda row: row["output"].update(root="../escape"),
            "output_absolute": lambda row: row["output"].update(root="/var/tmp/evidence"),
            "unknown_override_field": lambda row: row["readiness"]["overrides"].update(
                {"cmt8": {"unknown_threshold": 10}}),
            "cycle_shorter_than_job": lambda row: row["cycle"].update(cycle_timeout_seconds=100),
            "unknown_job_field": lambda row: row["jobs"][0].update(shell="sh"),
            "bool_version": lambda row: row.update(version=True),
            "float_version": lambda row: row.update(version=1.0),
            "bool_schema_revision": lambda row: row["readiness"].update(schema_revision=True),
            "bool_source": lambda row: row["jobs"][0].update(source=True),
            "bool_window": lambda row: row["jobs"][0].update(window=True),
            "bool_coverage_window": lambda row: row["readiness"].update(openaq_coverage_window_hours=True),
            "bool_backup_scope": lambda row: row["backup"].update(scope=True),
            "job_timeout_above_cycle_cap": lambda row: row["cycle"].update(job_timeout_seconds=10),
            "coverage_above_window": lambda row: row["readiness"].update(openaq_min_accepted_intervals=168),
            "override_above_window": lambda row: row["readiness"].update(
                overrides={"cmt8": {"openaq_min_accepted_intervals": 25}}),
            "override_boolean_interval": lambda row: row["readiness"].update(
                overrides={"cmt8": {"openaq_min_accepted_intervals": True}}),
            "database_budget_above_worker_stop": lambda row: row["readiness"].update(max_database_mib=401),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                candidate = copy.deepcopy(document)
                mutate(candidate)
                self.invalid(candidate, name=name)

    def test_unconfigured_targets_are_rejected(self):
        job = self.config.jobs[0].model_copy(update={"targets": ["da_nang"]})
        unconfigured = self.config.model_copy(update={"jobs": [job]})
        with self.assertRaises(AutomationError) as context:
            validate_config_targets(unconfigured, self.study)
        self.assertEqual(context.exception.code, "automation_target_unconfigured")
        readiness = self.config.readiness.model_copy(update={"overrides": {"ghost_target": {}}})
        overspecified = self.config.model_copy(update={"readiness": readiness})
        with self.assertRaises(AutomationError) as context:
            validate_config_targets(overspecified, self.study)
        self.assertEqual(context.exception.code, "automation_override_unknown_target")

    def test_shell_metacharacter_target_is_rejected_by_config(self):
        document = json.loads(AUTOMATION_PATH.read_text())
        document["jobs"][0]["targets"] = ["openaq_11357424; rm -rf /"]
        self.invalid(document, name="shell_target")

    def test_config_file_safety_checks(self):
        invalid_utf8 = self.base / "invalid_utf8.json"
        invalid_utf8.write_bytes(b"\xff\xfe{\x00")
        with self.assertRaises(AutomationError) as context:
            load_automation_config(invalid_utf8)
        self.assertEqual(context.exception.code, "automation_config_unreadable")
        oversize = self.base / "oversize.json"
        oversize.write_bytes(b"{" + b"x" * (MAX_CONFIG_BYTES + 1) + b"}")
        with self.assertRaises(AutomationError) as context:
            load_automation_config(oversize)
        self.assertEqual(context.exception.code, "automation_config_too_large")
        link = self.base / "linked.json"
        link.symlink_to(AUTOMATION_PATH)
        with self.assertRaises(AutomationError) as context:
            load_automation_config(link)
        self.assertEqual(context.exception.code, "automation_config_unsafe")
        directory = self.base / "directory.json"
        directory.mkdir()
        with self.assertRaises(AutomationError) as context:
            load_automation_config(directory)
        self.assertEqual(context.exception.code, "automation_config_unsafe")


class PlanTests(AutomationTestCase):
    def plan_command(self, **kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = automation_command(action="plan", automation_config=AUTOMATION_PATH,
                                      study_config=STUDY_PATH, now=FIXED_NOW, **kwargs)
        return code, json.loads(output.getvalue())

    def test_plan_is_deterministic_and_offline(self):
        with patch("vn_air.automation.database_engine",
                   side_effect=AssertionError("plan must not create a database engine")) as engine:
            first_code, first = self.plan_command()
            second_code, second = self.plan_command()
        self.assertEqual((first_code, second_code), (0, 0))
        self.assertFalse(engine.called)
        self.assertEqual(first, second)
        self.assertEqual(first["planning_clock"], "explicit --now")
        self.assertEqual(first["preflight"]["network_calls"], 0)
        self.assertEqual(first["preflight"]["schema_check"], "unperformed")
        self.assertEqual(first["preflight"]["role_check"], "unperformed")
        self.assertEqual(list(self.base.iterdir()), [])

    def test_plan_preserves_source_order_and_poll_windows(self):
        code, plan = self.plan_command()
        self.assertEqual(code, 0)
        self.assertEqual([job["source"] for job in plan["jobs"]], ["openaq", "weather", "cams"])
        openaq = plan["jobs"][0]["planned_window"]
        self.assertEqual(openaq["start"], "2026-09-09T10:00:00+00:00")
        self.assertEqual(openaq["end"], "2026-09-12T10:00:00+00:00")
        self.assertEqual(openaq["label"], "planned_parent_preview")
        models = plan["jobs"][1]["planned_window"]
        self.assertEqual(models["start"], "2026-09-12T00:00:00+00:00")
        self.assertEqual(models["end"], "2026-09-15T00:00:00+00:00")
        for job in plan["jobs"]:
            self.assertIn("ingest", job["argv"])
            self.assertIn("poll", job["argv"])
            self.assertNotIn("backfill", job["argv"])
            self.assertNotIn("--resume", job["argv"])

    def test_plan_uses_current_clock_label_without_now(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = automation_command(action="plan", automation_config=AUTOMATION_PATH,
                                      study_config=STUDY_PATH)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["planning_clock"], "current clock")

    def test_run_requires_execute_and_output_before_any_side_effect(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(automation_command(action="run", automation_config=AUTOMATION_PATH,
                                                study_config=STUDY_PATH), 3)
            self.assertEqual(automation_command(action="run", automation_config=AUTOMATION_PATH,
                                                study_config=STUDY_PATH, execute=True), 3)
        self.assertIn("automation_execute_required", stderr.getvalue())
        self.assertIn("automation_output_required", stderr.getvalue())
        self.assertEqual(list(self.base.iterdir()), [])


class CycleTests(AutomationTestCase):
    def test_success_writes_evidence_and_releases_lock(self):
        supervisor, result = self.run_fake_cycle([
            {"exit_code": 0, "events": [{"event": "ingestion_finished", "status": "succeeded",
                                         "inserted": 4, "unchanged": 0, "quarantined": 0}]},
            {"exit_code": 0}, {"exit_code": 0}])
        self.assertEqual((result["status"], result["exit_code"]), ("succeeded", 0))
        root, summary = self.read_evidence(result)
        self.assertEqual(sorted(path.name for path in root.iterdir()),
                         sorted([CYCLE_ALERTS_NAME, CYCLE_SUMMARY_NAME, CYCLE_SUCCESS_NAME]))
        self.assertEqual([job["status"] for job in summary["jobs"]],
                         ["succeeded", "succeeded", "succeeded"])
        self.assertEqual(summary["alerts"], [])
        self.assertEqual(summary["automation_version"], AUTOMATION_VERSION)
        self.assertEqual(summary["schema_revision"], "0003_response_integrity")
        self.assertTrue(summary["operational_timestamps"])
        self.assertEqual(summary["cycle_id"], "cycle-test")
        success = json.loads((root / CYCLE_SUCCESS_NAME).read_text())
        self.assertEqual(success["status"], "succeeded")
        self.assertEqual(success["summary_sha256"],
                         automation_module.sha256_file(root / CYCLE_SUMMARY_NAME))
        mode = stat.S_IMODE(os.stat(root).st_mode)
        self.assertEqual(mode, 0o700)
        self.assertEqual([call["argv"][4:8] for call in supervisor.calls],
                         [["ingest", "poll", "--source", "openaq"],
                          ["ingest", "poll", "--source", "weather"],
                          ["ingest", "poll", "--source", "cams"]])
        self.assertEqual(supervisor.calls[0]["timeout_seconds"], 900)
        self.assertEqual(supervisor.calls[0]["grace_seconds"], 5)
        lock = CycleLock(self.base / "lock" / "cycle.lock")
        self.assertTrue(lock.acquire())
        lock.release()

    def test_failed_job_stops_cycle_and_marks_remaining_not_attempted(self):
        supervisor, result = self.run_fake_cycle([
            {"exit_code": 1, "stderr_error_codes": ["provider_cooldown"],
             "events": [{"event": "ingestion_failed", "error_code": "provider_cooldown"}]},
        ])
        self.assertEqual((result["status"], result["exit_code"]), ("failed", 1))
        root, summary = self.read_evidence(result)
        self.assertNotIn(CYCLE_SUCCESS_NAME, [path.name for path in root.iterdir()])
        self.assertEqual([job["status"] for job in summary["jobs"]],
                         ["failed", "not_attempted", "not_attempted"])
        self.assertEqual(summary["jobs"][0]["error_code"], "provider_cooldown")
        self.assertEqual(summary["jobs"][1]["error_code"], "previous_job_not_successful")
        self.assertFalse(summary["jobs"][1]["attempted"])
        self.assertEqual(len(supervisor.calls), 1)
        self.assertEqual(summary["alerts"][0]["severity"], "error")
        self.assertEqual(summary["alerts"][0]["code"], "provider_cooldown")
        alerts = json.loads((root / CYCLE_ALERTS_NAME).read_text())
        self.assertEqual(alerts["alerts"], summary["alerts"])

    def test_partial_job_is_non_successful_and_stops_cycle(self):
        supervisor, result = self.run_fake_cycle([
            {"exit_code": 2, "events": [{"event": "ingestion_finished", "status": "partial",
                                         "quarantined": 2}]},
        ])
        self.assertEqual((result["status"], result["exit_code"]), ("partial", 2))
        root, summary = self.read_evidence(result)
        self.assertNotIn(CYCLE_SUCCESS_NAME, [path.name for path in root.iterdir()])
        self.assertEqual(summary["jobs"][0]["status"], "partial")
        self.assertEqual(summary["jobs"][0]["error_code"], "partial_ingestion")
        self.assertEqual(summary["jobs"][1]["status"], "not_attempted")
        self.assertEqual(summary["alerts"][0]["severity"], "warning")

    def test_continue_on_failure_attempts_remaining_jobs(self):
        cycle = self.config.cycle.model_copy(update={"stop_on_failure": False})
        config = self.config.model_copy(update={"cycle": cycle})
        supervisor, result = self.run_fake_cycle(
            [{"exit_code": 1}, {"exit_code": 0}, {"exit_code": 0}], config=config)
        self.assertEqual((result["status"], result["exit_code"]), ("failed", 1))
        _, summary = self.read_evidence(result)
        self.assertEqual([job["status"] for job in summary["jobs"]],
                         ["failed", "succeeded", "succeeded"])
        self.assertEqual(len(supervisor.calls), 3)

    def test_cycle_deadline_marks_pending_jobs_not_attempted(self):
        cycle = self.config.cycle.model_copy(update={"cycle_timeout_seconds": 60,
                                                     "job_timeout_seconds": 10})
        config = self.config.model_copy(update={"cycle": cycle})
        _, result = self.run_fake_cycle([{"exit_code": 0}], config=config,
                                        clock=FakeClock(0.0, 0.0, 0.0, 9999.0))
        _, summary = self.read_evidence(result)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual([job["status"] for job in summary["jobs"]],
                         ["succeeded", "not_attempted", "not_attempted"])
        self.assertEqual(summary["jobs"][1]["error_code"], "cycle_deadline_exceeded")

    def test_concurrent_cycle_is_excluded_without_touching_output(self):
        lock = CycleLock(self.base / "lock" / "cycle.lock")
        self.assertTrue(lock.acquire())
        try:
            result = run_cycle(self.config, self.study, output_dir=self.base / "blocked", execute=True,
                               lock_path=self.base / "lock" / "cycle.lock",
                               supervisor=FakeSupervisor([]), preflight=lambda remaining: dict(OK_PREFLIGHT),
                               clock=FakeClock(0.0), now=lambda: FIXED_NOW)
        finally:
            lock.release()
        self.assertEqual((result["status"], result["exit_code"]), ("already_running", 4))
        self.assertIsNone(result["summary_path"])
        self.assertFalse((self.base / "blocked").exists())

    def test_preflight_receives_bounded_remaining_budget(self):
        seen = {}

        def preflight(remaining):
            seen["remaining"] = remaining
            return dict(OK_PREFLIGHT)

        supervisor, result = self.run_fake_cycle(
            [{"exit_code": 0}, {"exit_code": 0}, {"exit_code": 0}], name="budget",
            preflight=preflight)
        self.assertEqual(result["exit_code"], 0)
        self.assertGreater(seen["remaining"], 0)
        self.assertLessEqual(seen["remaining"], self.config.cycle.cycle_timeout_seconds)
        self.assertEqual(len(supervisor.calls), 3)

    def test_expired_preflight_starts_no_child_and_writes_failure(self):
        supervisor, result = self.run_fake_cycle([], name="expired", clock=FakeClock(0.0, 9999.0),
                                                 preflight=lambda remaining: dict(OK_PREFLIGHT))
        self.assertEqual((result["status"], result["exit_code"]), ("failed", 1))
        _, summary = self.read_evidence(result)
        self.assertEqual(summary["error_code"], "cycle_deadline_exceeded")
        self.assertEqual(summary["jobs"], [])
        self.assertEqual(len(supervisor.calls), 0)
        root = Path(result["summary_path"]).parent
        self.assertNotIn(CYCLE_SUCCESS_NAME, [path.name for path in root.iterdir()])

    def test_cleanup_allowance_prevents_starting_a_job_at_the_deadline(self):
        cycle = self.config.cycle.model_copy(update={"cycle_timeout_seconds": 60, "job_timeout_seconds": 10,
                                                     "terminate_grace_seconds": 5})
        config = self.config.model_copy(update={"cycle": cycle})
        supervisor, result = self.run_fake_cycle([], name="allowance", config=config,
                                                 clock=FakeClock(0.0, 50.0, 50.0))
        self.assertEqual((result["status"], result["exit_code"]), ("failed", 1))
        _, summary = self.read_evidence(result)
        self.assertEqual(summary["jobs"][0]["status"], "not_attempted")
        self.assertEqual(summary["jobs"][0]["error_code"], "cycle_deadline_exceeded")
        self.assertEqual(len(supervisor.calls), 0)

    def test_internal_preflight_error_writes_failure_without_children(self):
        def broken(remaining):
            raise RuntimeError("unexpected preflight failure")
        supervisor, result = self.run_fake_cycle([], name="broken-preflight", preflight=broken)
        self.assertEqual((result["status"], result["exit_code"]), ("failed", 1))
        _, summary = self.read_evidence(result)
        self.assertEqual(summary["error_code"], "internal_error")
        self.assertEqual(summary["preflight"], {"status": "failed", "error_code": "internal_error"})
        self.assertEqual(summary["jobs"], [])
        self.assertEqual(len(supervisor.calls), 0)

    def test_preflight_failure_writes_failed_summary_without_jobs(self):
        def failing_preflight(remaining):
            raise AutomationError("schema_revision_mismatch")
        supervisor, result = self.run_fake_cycle([], preflight=failing_preflight)
        self.assertEqual((result["status"], result["exit_code"]), ("failed", 1))
        root, summary = self.read_evidence(result)
        self.assertEqual(summary["error_code"], "schema_revision_mismatch")
        self.assertEqual(summary["preflight"], {"status": "failed",
                                                "error_code": "schema_revision_mismatch"})
        self.assertEqual(summary["jobs"], [])
        self.assertEqual(len(supervisor.calls), 0)
        self.assertNotIn(CYCLE_SUCCESS_NAME, [path.name for path in root.iterdir()])

    def test_internal_supervisor_failure_uses_stable_code(self):
        supervisor, result = self.run_fake_cycle([RuntimeError("private detail")])
        self.assertEqual((result["status"], result["exit_code"]), ("failed", 1))
        _, summary = self.read_evidence(result)
        self.assertEqual(summary["error_code"], "internal_error")
        self.assertNotIn("private detail", json.dumps(summary))
        self.assertEqual(len(supervisor.calls), 1)

    def test_summary_is_deterministic_for_fixed_clock_and_cycle_id(self):
        outcomes = [{"exit_code": 0}, {"exit_code": 0}, {"exit_code": 0}]
        _, first = self.run_fake_cycle(outcomes, name="first", clock=FakeClock(0.0))
        _, second = self.run_fake_cycle(outcomes, name="second", clock=FakeClock(0.0))
        first_root = Path(first["summary_path"]).parent
        second_root = Path(second["summary_path"]).parent
        self.assertEqual((first_root / CYCLE_SUMMARY_NAME).read_bytes(),
                         (second_root / CYCLE_SUMMARY_NAME).read_bytes())
        self.assertEqual((first_root / CYCLE_ALERTS_NAME).read_bytes(),
                         (second_root / CYCLE_ALERTS_NAME).read_bytes())

    def test_effective_timeout_cap_is_applied_and_reported(self):
        cycle = self.config.cycle.model_copy(update={"job_timeout_seconds": 15})
        job = self.config.jobs[0].model_copy(update={"timeout_seconds": 30})
        config = self.config.model_copy(update={"cycle": cycle, "jobs": [job]})
        supervisor, result = self.run_fake_cycle([{"exit_code": 0}], config=config)
        self.assertEqual(supervisor.calls[0]["timeout_seconds"], 15)
        _, summary = self.read_evidence(result)
        self.assertEqual(summary["jobs"][0]["effective_timeout_seconds"], 15)
        plan = build_plan(config, self.study, now=FIXED_NOW, study_path=STUDY_PATH)
        self.assertEqual(plan["jobs"][0]["effective_timeout_seconds"], 15)

    def test_output_directory_must_be_new_and_not_a_symlink(self):
        existing = self.base / "existing"
        existing.mkdir()
        with self.assertRaises(AutomationError) as context:
            reserve_output_dir(existing)
        self.assertEqual(context.exception.code, "automation_output_exists")
        target = self.base / "target"
        target.mkdir()
        link = self.base / "link"
        link.symlink_to(target)
        with self.assertRaises(AutomationError) as context:
            reserve_output_dir(link)
        self.assertEqual(context.exception.code, "automation_output_exists")
        dangling = self.base / "dangling"
        dangling.symlink_to(self.base / "missing")
        with self.assertRaises(AutomationError) as context:
            reserve_output_dir(dangling)
        self.assertEqual(context.exception.code, "automation_output_exists")
        with self.assertRaises(AutomationError) as context:
            reserve_output_dir(self.base / "missing_parent" / "cycle")
        self.assertEqual(context.exception.code, "automation_output_parent_invalid")

    def test_run_never_overwrites_existing_output(self):
        output = self.base / "occupied"
        output.mkdir()
        with self.assertRaises(AutomationError) as context:
            run_cycle(self.config, self.study, output_dir=output, execute=True,
                      lock_path=self.base / "lock" / "cycle.lock",
                      supervisor=FakeSupervisor([]), preflight=lambda remaining: dict(OK_PREFLIGHT),
                      clock=FakeClock(0.0), now=lambda: FIXED_NOW)
        self.assertEqual(context.exception.code, "automation_output_exists")
        self.assertEqual(list(output.iterdir()), [])


class SupervisorTests(AutomationTestCase):
    def test_timeout_terminates_kills_reaps_and_lock_releases_after_child_gone(self):
        pidfile = self.base / "child.pid"
        child_code = ("import os, sys, time; "
                      "open(sys.argv[1], 'w').write(str(os.getpid())); "
                      "time.sleep(30)")
        argv = [sys.executable, "-B", "-c", child_code, str(pidfile)]
        supervisor = SubprocessSupervisor(cwd=ROOT, secrets=())
        cycle = self.config.cycle.model_copy(update={"terminate_grace_seconds": 1})
        job = self.config.jobs[0].model_copy(update={"timeout_seconds": 0.5})
        config = self.config.model_copy(update={"cycle": cycle, "jobs": [job]})
        started = time.monotonic()
        result = run_cycle(config, self.study, output_dir=self.base / "timeout", execute=True,
                           lock_path=self.base / "lock" / "cycle.lock", supervisor=supervisor,
                           preflight=lambda remaining: dict(OK_PREFLIGHT), argv_builder=lambda job, path: list(argv),
                           clock=time.monotonic, now=lambda: FIXED_NOW, cycle_id="timeout-test")
        elapsed = time.monotonic() - started
        self.assertEqual((result["status"], result["exit_code"]), ("failed", 1))
        _, summary = self.read_evidence(result)
        self.assertTrue(summary["jobs"][0]["timed_out"])
        self.assertEqual(summary["jobs"][0]["error_code"], "job_timeout")
        pid = int(pidfile.read_text().strip())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        lock = CycleLock(self.base / "lock" / "cycle.lock")
        self.assertTrue(lock.acquire())
        lock.release()
        self.assertLess(elapsed, 20)

    def test_timeout_kills_retained_group_after_leader_exits(self):
        pidfile = self.base / "grandchild.pid"
        grandchild_code = ("import signal, time; "
                           "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                           "time.sleep(30)")
        leader_code = ("import subprocess, sys, time; "
                       "child = subprocess.Popen([sys.executable, '-B', '-c', sys.argv[2]]); "
                       "open(sys.argv[1], 'w').write(str(child.pid)); "
                       "time.sleep(30)")
        argv = [sys.executable, "-B", "-c", leader_code, str(pidfile), grandchild_code]
        supervisor = SubprocessSupervisor(cwd=ROOT, secrets=())
        cycle = self.config.cycle.model_copy(update={"terminate_grace_seconds": 1})
        job = self.config.jobs[0].model_copy(update={"timeout_seconds": 2})
        config = self.config.model_copy(update={"cycle": cycle, "jobs": [job]})
        result = run_cycle(config, self.study, output_dir=self.base / "group", execute=True,
                           lock_path=self.base / "lock" / "cycle.lock", supervisor=supervisor,
                           preflight=lambda remaining: dict(OK_PREFLIGHT),
                           argv_builder=lambda job, path: list(argv),
                           clock=time.monotonic, now=lambda: FIXED_NOW, cycle_id="group-test")
        _, summary = self.read_evidence(result)
        self.assertTrue(summary["jobs"][0]["timed_out"])
        grandchild = int(pidfile.read_text().strip())
        with self.assertRaises(ProcessLookupError):
            os.kill(grandchild, 0)
        lock = CycleLock(self.base / "lock" / "cycle.lock")
        self.assertTrue(lock.acquire())
        lock.release()

    def test_supervisor_keeps_allowlisted_events_and_bounds_output(self):
        child_code = ("import json; "
                      "print(json.dumps({'event': 'ingestion_finished', 'status': 'succeeded', 'inserted': 1})); "
                      "print('x' * 20000); "
                      "print(json.dumps({'event': 'unknown_event', 'secret': 'value'})); "
                      "print('raw non-json output')")
        supervisor = SubprocessSupervisor(cwd=ROOT, output_limit_bytes=4096, secrets=())
        outcome = supervisor.run([sys.executable, "-B", "-c", child_code],
                                 timeout_seconds=10, grace_seconds=1)
        self.assertEqual(outcome["exit_code"], 0)
        self.assertEqual(outcome["events"], [{"event": "ingestion_finished",
                                              "status": "succeeded", "inserted": 1}])
        self.assertGreater(outcome["invalid_stdout_lines"], 0)
        self.assertGreater(outcome["stdout_bytes"], 4096)

    def test_supervisor_rejects_non_array_argv(self):
        supervisor = SubprocessSupervisor(cwd=ROOT, secrets=())
        with self.assertRaises(AutomationError) as context:
            supervisor.run("python -c pass", timeout_seconds=1, grace_seconds=1)
        self.assertEqual(context.exception.code, "automation_argv_invalid")

    def test_child_environment_binds_only_checkout_source(self):
        supervisor = SubprocessSupervisor(cwd=ROOT, secrets=())
        environment = supervisor.child_environment({"PYTHONPATH": "/elsewhere"})
        self.assertEqual(environment["PYTHONPATH"], str(ROOT / "src"))
        self.assertNotIn("OPENAQ_API_KEY", supervisor.child_environment({}))

    def test_child_environment_is_explicitly_allowlisted(self):
        supervisor = SubprocessSupervisor(cwd=ROOT, secrets=())
        environment = supervisor.child_environment({
            "DATABASE_URL": "postgresql://operator@localhost/db",
            "OPENAQ_API_KEY": "synthetic-openaq-key",
            "UNRELATED_SECRET": "must-not-inherit",
            "UNRELATED_TOKEN": "must-not-inherit",
            "SUPABASE_SECRET_KEY": "must-not-inherit",
            "PGSERVICE": "must-not-inherit",
            "PYTHONSTARTUP": "must-not-inherit",
        })
        self.assertEqual(environment["DATABASE_URL"], "postgresql://operator@localhost/db")
        self.assertEqual(environment["OPENAQ_API_KEY"], "synthetic-openaq-key")
        for name in ("UNRELATED_SECRET", "UNRELATED_TOKEN", "SUPABASE_SECRET_KEY",
                     "PGSERVICE", "PYTHONSTARTUP"):
            self.assertNotIn(name, environment)

    def test_real_child_and_cycle_evidence_do_not_inherit_unrelated_secrets(self):
        canaries = {"UNRELATED_SECRET": "synthetic-unrelated-73",
                    "UNRELATED_TOKEN": "synthetic-token-29", "SUPABASE_SECRET_KEY": "synthetic-supa-37"}
        child = ("import os,json; "
                 "names=('UNRELATED_SECRET','UNRELATED_TOKEN','SUPABASE_SECRET_KEY'); "
                 "print(json.dumps({'event':'ingestion_finished','status':'succeeded',"
                 "'inserted':sum(name in os.environ for name in names)}))")
        config = self.config.model_copy(update={"jobs": [self.config.jobs[0]]})
        with patch.dict(os.environ, canaries):
            result = run_cycle(config, self.study, output_dir=self.base / "canary", execute=True,
                               lock_path=self.base / "lock" / "cycle.lock",
                               preflight=lambda remaining: dict(OK_PREFLIGHT), secrets=tuple(canaries.values()),
                               argv_builder=lambda job, path: [sys.executable, "-B", "-c", child])
        root, summary = self.read_evidence(result)
        self.assertEqual(summary["jobs"][0]["events"][0]["inserted"], 0)
        for path in root.iterdir():
            serialized = path.read_text()
            for value in canaries.values():
                self.assertNotIn(value, serialized)


class PreflightTests(AutomationTestCase):
    def test_missing_database_url_fails_closed(self):
        def missing():
            raise ValueError("Set DATABASE_URL explicitly")
        with self.assertRaises(AutomationError) as context:
            database_preflight(self.config, engine_factory=missing)
        self.assertEqual(context.exception.code, "database_url_missing")

    def test_database_error_maps_to_stable_code(self):
        error = OperationalError("SELECT 1", {}, Exception("connection refused"))
        engine = FakeEngine(connect_error=error)
        with self.assertRaises(AutomationError) as context:
            database_preflight(self.config, engine_factory=lambda: engine)
        self.assertEqual(context.exception.code, "database_unavailable")
        self.assertTrue(engine.disposed)

    def test_missing_schema_table_is_reported(self):
        engine = FakeEngine(FakeConnection(installed=None))
        with self.assertRaises(AutomationError) as context:
            database_preflight(self.config, engine_factory=lambda: engine)
        self.assertEqual(context.exception.code, "schema_revision_missing")
        self.assertTrue(engine.disposed)

    def test_schema_revision_mismatch_is_reported(self):
        engine = FakeEngine(FakeConnection(revision="0002_ingestion"))
        with self.assertRaises(AutomationError) as context:
            database_preflight(self.config, engine_factory=lambda: engine)
        self.assertEqual(context.exception.code, "schema_revision_mismatch")

    def test_database_size_budget_is_enforced(self):
        engine = FakeEngine(FakeConnection(size=500 * 1024 * 1024))
        with self.assertRaises(AutomationError) as context:
            database_preflight(self.config, engine_factory=lambda: engine)
        self.assertEqual(context.exception.code, "database_size_budget_exhausted")

    def test_successful_preflight_reports_read_only_facts(self):
        engine = FakeEngine(FakeConnection(revision="0003_response_integrity"))
        report = database_preflight(self.config, engine_factory=lambda: engine)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["schema_revision"], "0003_response_integrity")
        self.assertEqual(report["database_bytes"], 4096)
        self.assertTrue(engine.disposed)

    def test_expired_preflight_stops_before_any_engine(self):
        def forbidden():
            raise AssertionError("engine factory must not be called")
        with self.assertRaises(AutomationError) as context:
            database_preflight(self.config, engine_factory=forbidden, remaining_seconds=0)
        self.assertEqual(context.exception.code, "cycle_deadline_exceeded")

    def test_preflight_bounds_connect_and_statement_timeouts(self):
        captured = {}
        connection = FakeConnection()
        engine = FakeEngine(connection)

        def factory(*, connect_timeout):
            captured["connect_timeout"] = connect_timeout
            return engine

        with patch("vn_air.automation.database_engine", side_effect=factory):
            report = database_preflight(self.config, remaining_seconds=4)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(captured["connect_timeout"], 4)
        statements = [parameters for sql, parameters in connection.calls if "set_config" in sql]
        self.assertEqual(statements, [{"ms": "4000"}])


class SecretTests(AutomationTestCase):
    def test_event_values_require_reviewed_contracts(self):
        canary = "canary-token-Qq7"
        run_id = "0d0f8f2e-4a2b-4c3d-8e4f-5a6b7c8d9e0f"
        line = json.dumps({
            "event": "ingestion_failed",
            "error_code": canary,
            "target": "openaq_11357424",
            "run_id": run_id,
            "start": "2026-09-12T00:00:00+00:00",
            "request_path": f"postgresql+psycopg://user:{canary}@host/db",
            "headers": f"Bearer {canary}",
        }).encode()
        event = extract_event(line, (canary,))
        self.assertEqual(event, {"event": "ingestion_failed", "error_code": "unrecognized_child_error",
                                 "target": "openaq_11357424", "run_id": run_id})
        self.assertIsNone(extract_event(json.dumps({"event": "raw_payload", "body": canary}).encode(), (canary,)))
        self.assertEqual(scrub_text(f"postgresql://u:{canary}@h/db", (canary,)), "[redacted-connection]")

        rejection = {
            "wrong_status": {"event": "ingestion_finished", "status": "mystery"},
            "nan_status": {"event": "ingestion_finished", "status": float("nan")},
            "string_count": {"event": "ingestion_finished", "inserted": "5"},
            "boolean_count": {"event": "ingestion_finished", "inserted": True},
            "negative_count": {"event": "ingestion_finished", "inserted": -1},
            "float_count": {"event": "ingestion_finished", "inserted": 1.5},
            "unreviewed_target_shape": {"event": "ingestion_failed", "target": "Not A Target"},
            "long_target": {"event": "ingestion_failed", "target": "a" * 65},
            "naive_timestamp": {"event": "ingestion_started", "start": "2026-09-12T00:00:00"},
            "bad_timestamp": {"event": "ingestion_started", "start": "x" * 100},
            "bad_run_id": {"event": "ingestion_started", "run_id": canary},
            "unreviewed_product": {"event": "ingestion_started", "product": "ghost_product"},
            "unreviewed_source": {"event": "ingestion_summary", "source": "ghost"},
            "bad_http_status": {"event": "http_attempt", "http_status": 9999},
        }
        for name, record in rejection.items():
            with self.subTest(name=name):
                self.assertIsNone(sanitize_event(record, (canary,)))

        context = {"targets": frozenset({"openaq_11357424"}),
                   "products": frozenset({"openaq_airgradient_hourly"})}
        reviewed = {"event": "ingestion_failed", "target": "openaq_11357424",
                    "product": "openaq_airgradient_hourly", "error_code": "provider_cooldown"}
        self.assertEqual(sanitize_event(reviewed, (), context), reviewed)
        unreviewed = dict(reviewed, target="oceanpark")
        self.assertIsNone(sanitize_event(unreviewed, (), context))

    def test_real_phase3_event_shapes_keep_their_meaning(self):
        run_id = "0d0f8f2e-4a2b-4c3d-8e4f-5a6b7c8d9e0f"
        context = {"targets": frozenset({"openaq_11357424"}),
                   "products": frozenset({"openaq_airgradient_hourly"})}
        cases = {
            "ingestion_started": (
                {"event": "ingestion_started", "run_id": run_id, "product": "openaq_airgradient_hourly",
                 "target": "openaq_11357424", "start": "2026-09-12 06:00:00+00:00",
                 "end": "2026-09-12 06:07:00+00:00"},
                {"event": "ingestion_started", "run_id": run_id, "product": "openaq_airgradient_hourly",
                 "target": "openaq_11357424", "start": "2026-09-12T06:00:00+00:00",
                 "end": "2026-09-12T06:07:00+00:00"}),
            "ingestion_finished": (
                {"event": "ingestion_finished", "run_id": run_id, "product": "openaq_airgradient_hourly",
                 "target": "openaq_11357424", "status": "succeeded", "inserted": 72, "unchanged": 0,
                 "quarantined": 0, "missing_hours": 0},
                {"event": "ingestion_finished", "run_id": run_id, "product": "openaq_airgradient_hourly",
                 "target": "openaq_11357424", "status": "succeeded", "inserted": 72, "unchanged": 0,
                 "quarantined": 0, "missing_hours": 0}),
            "checkpoint_skipped": (
                {"event": "checkpoint_skipped", "product": "openaq_airgradient_hourly",
                 "target": "openaq_11357424", "start": "2026-09-12 06:00:00+00:00",
                 "end": "2026-09-12 06:07:00+00:00"},
                {"event": "checkpoint_skipped", "product": "openaq_airgradient_hourly",
                 "target": "openaq_11357424", "start": "2026-09-12T06:00:00+00:00",
                 "end": "2026-09-12T06:07:00+00:00"}),
            "orphaned_run_recovered": (
                {"event": "orphaned_run_recovered", "run_id": run_id},
                {"event": "orphaned_run_recovered", "run_id": run_id}),
            "run_finalization_failed": (
                {"event": "run_finalization_failed", "run_id": run_id, "error_code": "database_unavailable"},
                {"event": "run_finalization_failed", "run_id": run_id, "error_code": "database_unavailable"}),
            "ingestion_summary": (
                {"event": "ingestion_summary", "source": "openaq", "chunks": 4, "requests": 9,
                 "inserted": 200, "unchanged": 12, "quarantined": 1},
                {"event": "ingestion_summary", "source": "openaq", "chunks": 4, "requests": 9,
                 "inserted": 200, "unchanged": 12, "quarantined": 1}),
            "http_attempt": (
                {"event": "http_attempt", "run_id": run_id, "product": "openaq_airgradient_hourly",
                 "attempt": 1, "http_status": 200, "error_code": None, "elapsed_ms": 145,
                 "page": 1, "window_start": "2026-09-12T06:00:00+00:00"},
                {"event": "http_attempt", "run_id": run_id, "product": "openaq_airgradient_hourly",
                 "attempt": 1, "http_status": 200, "elapsed_ms": 145,
                 "page": 1, "window_start": "2026-09-12T06:00:00+00:00"}),
            "http_attempt_model_date": (
                {"event": "http_attempt", "run_id": run_id, "product": "openaq_airgradient_hourly",
                 "attempt": 2, "http_status": 429, "error_code": "http_429", "elapsed_ms": 300,
                 "window_start": "2026-09-12"},
                {"event": "http_attempt", "run_id": run_id, "product": "openaq_airgradient_hourly",
                 "attempt": 2, "http_status": 429, "error_code": "http_429", "elapsed_ms": 300,
                 "window_start": "2026-09-12"}),
        }
        for name, (record, expected) in cases.items():
            with self.subTest(name=name):
                self.assertEqual(sanitize_event(record, (), context), expected)

    def test_stderr_codes_are_normalized_to_a_bounded_registry(self):
        canary = "canary-stderr-77"
        self.assertEqual(extract_stderr_codes(b"Ingestion stopped: provider_cooldown"),
                         ["provider_cooldown"])
        self.assertEqual(extract_stderr_codes(f"Ingestion stopped: {canary}".encode()),
                         ["unrecognized_child_error"])
        self.assertEqual(extract_stderr_codes(b"Database operation failed (23503)"),
                         ["database_error_23503"])
        self.assertEqual(extract_stderr_codes(b"arbitrary raw text"), [])
        _, result = self.run_fake_cycle([{"exit_code": 1, "stderr_error_codes": [canary, "00000"]}],
                                        secrets=(canary,))
        _, summary = self.read_evidence(result)
        self.assertEqual(summary["jobs"][0]["error_code"], "database_error_00000")
        self.assertNotIn(canary, json.dumps(summary))

    def test_cycle_evidence_never_contains_secret_canary(self):
        canary = "canary-secret-Zx9"
        events = [{"event": "ingestion_failed", "error_code": canary,
                   "target": canary,
                   "run_id": canary,
                   "request_path": f"postgresql+psycopg://user:{canary}@host/db",
                   "response_body": canary}]
        _, result = self.run_fake_cycle([{"exit_code": 1, "events": events}], secrets=(canary,))
        root = Path(result["summary_path"]).parent
        contents = "\n".join(path.read_text() for path in sorted(root.iterdir()))
        self.assertNotIn(canary, contents)
        summary = json.loads((root / CYCLE_SUMMARY_NAME).read_text())
        self.assertEqual(summary["jobs"][0]["status"], "failed")
        self.assertNotIn("response_body", json.dumps(summary))
        self.assertNotIn("request_path", json.dumps(summary))

    def test_environment_secrets_include_env_values_and_url_password(self):
        canary = "canary-env-123"
        environment = {"OPENAQ_API_KEY": canary,
                       "DATABASE_URL": f"postgresql+psycopg://user:{canary}@host:5432/db"}
        secrets = environment_secrets(environment)
        self.assertIn(canary, secrets)
        self.assertIn(f"postgresql+psycopg://user:{canary}@host:5432/db", secrets)

    def test_module_never_reads_dotenv_or_uses_a_shell(self):
        source = Path(automation_module.__file__).read_text()
        self.assertNotIn("dotenv", source)
        self.assertNotIn('".env"', source)
        self.assertNotIn("shell=True", source)
        self.assertNotIn("os.system", source)

    def test_lock_rejects_symlinked_leaf_and_parent(self):
        real = self.base / "real.lock"
        real.write_text("")
        leaf = self.base / "leaf.lock"
        leaf.symlink_to(real)
        with self.assertRaises(AutomationError) as context:
            CycleLock(leaf).acquire()
        self.assertEqual(context.exception.code, "automation_lock_unsafe")
        directory = self.base / "directory"
        directory.mkdir()
        parent_link = self.base / "parent_link"
        parent_link.symlink_to(directory)
        with self.assertRaises(AutomationError) as context:
            CycleLock(parent_link / "cycle.lock").acquire()
        self.assertEqual(context.exception.code, "automation_lock_unsafe")


class SignalTests(AutomationTestCase):
    def test_external_signal_cleans_child_writes_interrupted_evidence_and_releases_lock(self):
        for sig, name in ((signal.SIGINT, "sigint"), (signal.SIGTERM, "sigterm")):
            with self.subTest(signal=name):
                pidfile = self.base / f"{name}.pid"
                child_code = ("import os, sys, time; "
                              "open(sys.argv[1], 'w').write(str(os.getpid())); "
                              "time.sleep(30)")
                argv = [sys.executable, "-B", "-c", child_code, str(pidfile)]
                cycle = self.config.cycle.model_copy(update={"terminate_grace_seconds": 1})
                job = self.config.jobs[0].model_copy(update={"timeout_seconds": 60})
                config = self.config.model_copy(update={"cycle": cycle, "jobs": [job]})
                stop = threading.Event()

                def sender():
                    while not stop.is_set() and not pidfile.exists():
                        stop.wait(0.02)
                    if not stop.is_set() and pidfile.exists():
                        os.kill(os.getpid(), sig)

                previous_handler = signal.signal(sig, lambda signum, frame: None)
                thread = threading.Thread(target=sender, daemon=True)
                thread.start()
                try:
                    result = run_cycle(config, self.study, output_dir=self.base / name, execute=True,
                                       lock_path=self.base / "lock" / "cycle.lock",
                                       supervisor=SubprocessSupervisor(cwd=ROOT, secrets=()),
                                       preflight=lambda remaining: dict(OK_PREFLIGHT),
                                       argv_builder=lambda job, path: list(argv),
                                       clock=time.monotonic, now=lambda: FIXED_NOW, cycle_id=name)
                finally:
                    stop.set()
                    thread.join(timeout=2)
                    signal.signal(sig, previous_handler)
                self.assertEqual((result["status"], result["exit_code"]), ("failed", 1))
                root, summary = self.read_evidence(result)
                self.assertEqual(summary["error_code"], "cycle_interrupted")
                self.assertEqual(summary["alerts"][-1]["code"], "cycle_interrupted")
                self.assertNotIn(CYCLE_SUCCESS_NAME, [path.name for path in root.iterdir()])
                child = int(pidfile.read_text().strip())
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
                lock = CycleLock(self.base / "lock" / "cycle.lock")
                self.assertTrue(lock.acquire())
                lock.release()


class LockProcessTests(AutomationTestCase):
    def helper(self, path):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        return subprocess.run([sys.executable, "-B", "-c", LOCK_HELPER, str(path)],
                              cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60)

    def test_cross_process_lock_exclusion_and_owner_death_release(self):
        path = self.base / "lock" / "cycle.lock"
        lock = CycleLock(path)
        self.assertTrue(lock.acquire())
        try:
            self.assertEqual(self.helper(path).stdout.strip(), "contended")
        finally:
            lock.release()
        self.assertEqual(self.helper(path).stdout.strip(), "acquired")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        holder = subprocess.Popen([sys.executable, "-B", "-c", LOCK_HOLDER, str(path)],
                                  cwd=ROOT, env=environment, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "acquired")
            self.assertEqual(self.helper(path).stdout.strip(), "contended")
            holder.kill()
            holder.wait(timeout=10)
            self.assertEqual(self.helper(path).stdout.strip(), "acquired")
        finally:
            if holder.poll() is None:
                holder.kill()
                holder.wait()
            holder.stdout.close()


class CommandTests(AutomationTestCase):
    def test_run_command_fails_closed_when_database_url_is_missing(self):
        output = self.base / "nodatabase"
        with patch.dict(os.environ):
            os.environ.pop("DATABASE_URL", None)
            with patch("vn_air.automation.default_lock_path",
                       return_value=self.base / "lock" / "cycle.lock"):
                code = automation_command(action="run", automation_config=AUTOMATION_PATH,
                                          study_config=STUDY_PATH, output_dir=output, execute=True)
        self.assertEqual(code, 1)
        summary = json.loads((output / CYCLE_SUMMARY_NAME).read_text())
        self.assertEqual(summary["error_code"], "database_url_missing")
        self.assertEqual(summary["jobs"], [])
        self.assertFalse((output / CYCLE_SUCCESS_NAME).exists())

    def test_cli_plan_and_run_switch_exit_codes(self):
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment.pop("DATABASE_URL", None)
        plan = subprocess.run(
            [sys.executable, "-B", "-m", "vn_air.cli", "automation", "plan",
             "--now", "2026-09-12T10:30:00Z"],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(plan.returncode, 0)
        self.assertEqual(json.loads(plan.stdout)["preflight"]["network_calls"], 0)
        missing = subprocess.run(
            [sys.executable, "-B", "-m", "vn_air.cli", "automation", "run"],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(missing.returncode, 3)
        self.assertIn("automation_execute_required", missing.stderr)


if __name__ == "__main__":
    unittest.main()
