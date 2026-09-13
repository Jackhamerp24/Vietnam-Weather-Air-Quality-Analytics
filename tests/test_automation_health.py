"""Offline Phase 11 health and recovery tests with fake read-only database
responses. No database, network, scheduler or credential access."""

import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from vn_air.automation import (
    AutomationError,
    automation_command,
    load_automation_config,
    load_study_config,
)
from vn_air.automation_health import (
    HEALTH_EXIT_DEGRADED,
    HEALTH_EXIT_FAILED,
    HEALTH_EXIT_HEALTHY,
    HEALTH_EXIT_INVALID,
    PROVIDER_GROUPS,
    assess_health,
    build_recovery_guidance,
    configured_health_targets,
    health_command,
    health_snapshot,
    recover_command,
)
from vn_air.ingestion.pipeline import PRODUCTS


ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_PATH = ROOT / "configs/automation.json"
STUDY_PATH = ROOT / "configs/study.json"
UTC = timezone.utc
AS_OF = datetime(2026, 9, 12, 10, 30, tzinfo=UTC)


def reviewed_configs():
    return load_automation_config(AUTOMATION_PATH), load_study_config(STUDY_PATH)


def healthy_facts(config, study, *, as_of=AS_OF):
    targets = configured_health_targets(config, study)
    facts = {
        "server_version_num": 150017,
        "schema": {"installed": True, "revision": "0003_response_integrity",
                   "expected": "0003_response_integrity"},
        "database_bytes": 8 * 1024 * 1024,
        "targets": [],
        "fetch": [],
        "openaq": [],
        "modeled": [],
        "stale_running": [],
        "quality_issues": [],
    }
    for target in targets:
        facts["targets"].append({**target, "runs": {
            "count": 2, "latest_status": "succeeded", "latest_error_code": None,
            "latest_started_at": as_of - timedelta(minutes=8),
            "latest_finished_at": as_of - timedelta(minutes=7),
            "last_success_at": as_of - timedelta(minutes=7), "last_partial_at": None,
            "last_failure_at": None, "latest_age_seconds": 480.0,
        }})
    for source in ("openaq", "weather", "cams"):
        for target in [row for row in targets if row["source"] == source]:
            facts["fetch"].append({
                "source": source, "product": PRODUCTS[source],
                "provider_group": PROVIDER_GROUPS[source], "target": target["target"],
                "target_kind": target["target_kind"],
                "latest_success_at": as_of - timedelta(minutes=15), "successes": 3,
            })

    for target in targets:
        if target["source"] == "openaq":
            facts["openaq"].append({
                "sensor": target["target"], "accepted_intervals": 24,
                "latest_accepted_end": as_of - timedelta(hours=1),
                "latest_accepted_within_lookback": as_of - timedelta(hours=1),
                "latest_revision_period_end": as_of - timedelta(hours=1),
                "latest_revision_status": "accepted",
            })
        else:
            facts["modeled"].append({**target, "latest_snapshot": {
                "recorded_at": as_of - timedelta(minutes=20),
                "retrieved_at": as_of - timedelta(minutes=19),
                "data_kind": "forecast", "accepted_values": 4,
            }})
    return facts


def mutate_facts(config, study, **changes):
    facts = healthy_facts(config, study)
    for key, value in changes.items():
        if callable(value):
            value(facts)
        else:
            facts[key] = value
    return facts


def target_key(facts, source, target):
    for record in facts["targets"]:
        if record["source"] == source and record["target"] == target:
            return record
    raise AssertionError(f"missing target {source}/{target}")


def openaq_record(facts, sensor):
    return next(record for record in facts["openaq"] if record["sensor"] == sensor)


def modeled_record(facts, target):
    return next(record for record in facts["modeled"] if record["target"] == target)


class FakeResult:
    def __init__(self, value=None, rows=None):
        self.value = value
        self.rows = rows or []

    def scalar_one(self):
        return self.value

    def scalar_one_or_none(self):
        return self.value

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeHealthConnection:
    """Bounded routing fake; records every statement for read-only assertions."""

    def __init__(self, *, revision="0003_response_integrity", installed="public.vn_air_schema_version",
                 size=8 * 1024 * 1024, run_rows=None, fetch_row=None, coverage_row=None,
                 accepted=None, revision_row=None, snapshot_row=None, stale=None, issues=None,
                 fetch_by_target=None):
        self.revision = revision
        self.installed = installed
        self.size = size
        self.run_rows = run_rows if run_rows is not None else [{
            "status": "succeeded", "error_code": None,
            "started_at": AS_OF - timedelta(minutes=8), "finished_at": AS_OF - timedelta(minutes=7),
            "window_start": AS_OF - timedelta(hours=1), "window_end": AS_OF,
        }]
        self.fetch_row = fetch_row if fetch_row is not None else {
            "latest_success_at": AS_OF - timedelta(minutes=15), "successes": 3}
        self.fetch_by_target = fetch_by_target or {}
        self.coverage_row = coverage_row if coverage_row is not None else {
            "accepted_intervals": 24, "latest_accepted_end": AS_OF - timedelta(hours=1)}
        self.accepted = accepted if accepted is not None else AS_OF - timedelta(hours=1)
        self.revision_row = revision_row
        if revision_row is None:
            revision_row = [{"period_end": AS_OF - timedelta(hours=1), "quality_status": "accepted"}]
        self.revision_row = revision_row
        self.snapshot_row = snapshot_row if snapshot_row is not None else [{
            "recorded_at": AS_OF - timedelta(minutes=20), "data_kind": "forecast",
            "retrieved_at": AS_OF - timedelta(minutes=19), "accepted_values": 4}]
        self.stale = stale or []
        self.issues = issues or []
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if "SET TRANSACTION READ ONLY" in sql or "set_config" in sql:
            return FakeResult(None)
        if "to_regclass" in sql:
            return FakeResult(self.installed)
        if "server_version_num" in sql:
            return FakeResult(150017)
        if "FROM public.vn_air_schema_version" in sql:
            return FakeResult(self.revision)
        if "pg_database_size" in sql:
            return FakeResult(self.size)
        if "FROM vn_air.ingestion_runs" in sql and "status = 'running'" in sql:
            return FakeResult(rows=self.stale)
        if "FROM vn_air.ingestion_runs" in sql:
            return FakeResult(rows=self.run_rows)
        if "FROM vn_air.source_responses" in sql:
            target = (parameters or {}).get("target")
            return FakeResult(rows=[self.fetch_by_target.get(target, self.fetch_row)])
        if "SELECT latest.period_end, latest.quality_status" in sql:
            return FakeResult(rows=self.revision_row)
        if "accepted_intervals" in sql:
            return FakeResult(rows=[self.coverage_row])
        if "SELECT max(period_end) AS latest_accepted_end" in sql:
            return FakeResult(self.accepted)
        if "FROM vn_air.model_snapshots" in sql:
            return FakeResult(rows=self.snapshot_row)
        if "FROM vn_air.data_quality_issues" in sql:
            return FakeResult(rows=self.issues)
        raise AssertionError(f"unexpected SQL reached the fake: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeHealthEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposed = True


class HealthAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.config, self.study = reviewed_configs()

    def test_fully_healthy_configured_checks_exit_zero(self):
        document = assess_health(self.config, healthy_facts(self.config, self.study), as_of=AS_OF)
        self.assertEqual((document["status"], document["exit_code"]), ("healthy", HEALTH_EXIT_HEALTHY))
        self.assertEqual(document["findings"], [])

    def test_schema_missing_and_mismatch_are_failures(self):
        for facts, code in (
            (mutate_facts(self.config, self.study, schema={"installed": False, "revision": None,
                                                           "expected": "0003_response_integrity"}),
             "schema_revision_missing"),
            (mutate_facts(self.config, self.study, schema={"installed": True, "revision": "0002_ingestion",
                                                           "expected": "0003_response_integrity"}),
             "schema_revision_mismatch"),
        ):
            with self.subTest(code=code):
                document = assess_health(self.config, facts, as_of=AS_OF)
                self.assertEqual(document["exit_code"], HEALTH_EXIT_FAILED)
                self.assertIn(code, [finding["code"] for finding in document["findings"]])

    def test_database_budget_failure_and_near_budget_degradation(self):
        full = mutate_facts(self.config, self.study, database_bytes=400 * 1024 * 1024)
        document = assess_health(self.config, full, as_of=AS_OF)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_FAILED)
        self.assertIn("database_size_budget_exhausted", [f["code"] for f in document["findings"]])
        near = mutate_facts(self.config, self.study, database_bytes=330 * 1024 * 1024)
        document = assess_health(self.config, near, as_of=AS_OF)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_DEGRADED)
        self.assertIn("database_size_near_budget", [f["code"] for f in document["findings"]])

    def test_run_status_distinguishes_success_partial_failure_and_missing(self):
        def set_latest(status):
            def apply(facts):
                record = target_key(facts, "openaq", "openaq_11357424")
                record["runs"].update({"latest_status": status, "latest_error_code":
                                       "network_error" if status == "failed" else None})
            return apply
        for status, exit_code, code in (
            ("succeeded", HEALTH_EXIT_HEALTHY, None),
            ("partial", HEALTH_EXIT_DEGRADED, "run_partial"),
            ("failed", HEALTH_EXIT_FAILED, "run_failed"),
        ):
            with self.subTest(status=status):
                facts = mutate_facts(self.config, self.study)
                set_latest(status)(facts)
                document = assess_health(self.config, facts, as_of=AS_OF)
                self.assertEqual(document["exit_code"], exit_code)
                if code:
                    self.assertIn(code, [f["code"] for f in document["findings"]])

        def drop_runs(facts):
            record = target_key(facts, "openaq", "openaq_14581375")
            record["runs"] = {"count": 0, "latest_status": None, "latest_error_code": None,
                              "latest_started_at": None, "latest_finished_at": None,
                              "last_success_at": None, "last_partial_at": None,
                              "last_failure_at": None, "latest_age_seconds": None}
        facts = mutate_facts(self.config, self.study)
        drop_runs(facts)
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_FAILED)
        self.assertIn("run_evidence_missing", [f["code"] for f in document["findings"]])

    def test_stale_and_cooldown_indicators(self):
        def stale_running(facts):
            record = target_key(facts, "openaq", "openaq_11357424")
            record["runs"].update({"latest_status": "running", "latest_age_seconds": 3600.0})
        facts = mutate_facts(self.config, self.study)
        stale_running(facts)
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertIn("run_stale", [f["code"] for f in document["findings"]])

        def cooldown(facts):
            record = target_key(facts, "weather", "cmt8")
            record["runs"].update({"latest_error_code": "provider_cooldown"})
        facts = mutate_facts(self.config, self.study)
        cooldown(facts)
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertIn("provider_cooldown_indicator", [f["code"] for f in document["findings"]])
        self.assertEqual(document["exit_code"], HEALTH_EXIT_DEGRADED)

    def test_fetch_freshness_is_separate_from_accepted_data(self):
        facts = mutate_facts(self.config, self.study)
        facts["fetch"] = []
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_FAILED)
        self.assertIn("fetch_evidence_missing", [f["code"] for f in document["findings"]])
        facts = mutate_facts(self.config, self.study)
        facts["fetch"][0]["latest_success_at"] = AS_OF - timedelta(hours=9)
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_DEGRADED)
        self.assertIn("fetch_stale", [f["code"] for f in document["findings"]])

    def test_fetch_freshness_is_target_scoped(self):
        facts = mutate_facts(self.config, self.study)
        facts["fetch"] = [record for record in facts["fetch"]
                           if not (record["source"] == "openaq"
                                   and record["target"] == "openaq_14581375")]
        document = assess_health(self.config, facts, as_of=AS_OF)
        missing = [finding for finding in document["findings"]
                   if finding["code"] == "fetch_evidence_missing"]
        self.assertTrue(any(finding["target"] == "openaq_14581375" for finding in missing))
        self.assertEqual(document["exit_code"], HEALTH_EXIT_FAILED)

    def test_collected_fetch_facts_are_target_scoped_for_modeled_sources(self):
        connection = FakeHealthConnection(fetch_by_target={
            "hanoi": {"latest_success_at": None, "successes": 0},
        })
        document = health_snapshot(self.config, self.study,
                                   engine_factory=lambda: FakeHealthEngine(connection), as_of=AS_OF)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_FAILED)
        hanoi = next(record for record in document["fetch"] if record["target"] == "hanoi")
        self.assertIsNone(hanoi["latest_success_at"])
        self.assertTrue(any(finding["code"] == "fetch_evidence_missing"
                            and finding["source"] == "cams"
                            and finding["target"] == "hanoi"
                            for finding in document["findings"]))

    def test_stale_fetch_and_threshold_override_affect_only_selected_target(self):
        from vn_air.automation import TargetOverrides
        for source, target in (("openaq", "openaq_14581375"), ("weather", "oceanpark")):
            with self.subTest(source=source):
                facts = healthy_facts(self.config, self.study)
                selected = next(row for row in facts["fetch"]
                                if row["source"] == source and row["target"] == target)
                selected["latest_success_at"] = AS_OF - timedelta(hours=4)
                result = assess_health(self.config, facts, as_of=AS_OF)
                stale = [row for row in result["findings"] if row["code"] == "fetch_stale"]
                self.assertEqual([(row["source"], row["target"]) for row in stale], [(source, target)])
                self.assertEqual(result["exit_code"], HEALTH_EXIT_DEGRADED)
                readiness = self.config.readiness.model_copy(update={
                    "overrides": {target: TargetOverrides(fetch_success_age_seconds=18000)}})
                config = self.config.model_copy(update={"readiness": readiness})
                self.assertEqual(assess_health(config, facts, as_of=AS_OF)["exit_code"], HEALTH_EXIT_HEALTHY)

    def test_openaq_coverage_and_latest_revision(self):
        facts = mutate_facts(self.config, self.study)
        openaq_record(facts, "openaq_11357424")["accepted_intervals"] = 12
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertIn("openaq_low_coverage", [f["code"] for f in document["findings"]])

        facts = mutate_facts(self.config, self.study)
        record = openaq_record(facts, "openaq_14581375")
        record["latest_accepted_within_lookback"] = AS_OF - timedelta(hours=20)
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertIn("openaq_period_stale", [f["code"] for f in document["findings"]])

        facts = mutate_facts(self.config, self.study)
        facts["openaq"] = []
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_FAILED)
        self.assertIn("openaq_accepted_evidence_missing", [f["code"] for f in document["findings"]])

        facts = mutate_facts(self.config, self.study)
        record = openaq_record(facts, "openaq_11357424")
        record["latest_revision_status"] = "invalid"
        record["latest_revision_period_end"] = AS_OF - timedelta(minutes=30)
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertIn("openaq_recent_revision_not_accepted", [f["code"] for f in document["findings"]])

    def test_modeled_capture_uses_capture_time_and_requires_accepted_values(self):
        facts = mutate_facts(self.config, self.study)
        modeled_record(facts, "cmt8")["latest_snapshot"].update({
            "recorded_at": AS_OF - timedelta(hours=9), "retrieved_at": AS_OF - timedelta(hours=9)})
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertIn("modeled_capture_stale", [f["code"] for f in document["findings"]])

        facts = mutate_facts(self.config, self.study)
        modeled_record(facts, "hanoi")["latest_snapshot"]["accepted_values"] = 0
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_FAILED)
        self.assertIn("modeled_snapshot_invalid_only", [f["code"] for f in document["findings"]])

        facts = mutate_facts(self.config, self.study)
        facts["modeled"] = []
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_FAILED)
        self.assertIn("modeled_capture_evidence_missing", [f["code"] for f in document["findings"]])

    def test_stale_running_quality_issues_and_backup_severity(self):
        facts = mutate_facts(self.config, self.study)
        facts["stale_running"] = [{"product_id": PRODUCTS["openaq"], "target_sensor_id": "openaq_11357424",
                                   "target_location_id": None, "started_at": AS_OF - timedelta(hours=2)}]
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertIn("stale_running_runs", [f["code"] for f in document["findings"]])

        facts = mutate_facts(self.config, self.study)
        facts["quality_issues"] = [{"issue_code": "coverage_gap", "severity": "error", "open_count": 1}]
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertIn("open_quality_issues", [f["code"] for f in document["findings"]])

        facts = mutate_facts(self.config, self.study)
        stale_backup = {"status": "stale", "age_seconds": 999999.0, "manifests_found": 1,
                        "latest_manifest": "cycle", "checksum_verified": False,
                        "directory": "backups", "note": ""}
        document = assess_health(self.config, facts, as_of=AS_OF, backup_facts=stale_backup)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_DEGRADED)
        self.assertIn("backup_stale", [f["code"] for f in document["findings"]])
        missing_backup = dict(stale_backup, status="missing", age_seconds=None)
        document = assess_health(self.config, facts, as_of=AS_OF, backup_facts=missing_backup)
        self.assertIn("backup_missing", [f["code"] for f in document["findings"]])
        invalid_backup = dict(stale_backup, status="invalid", age_seconds=None)
        document = assess_health(self.config, facts, as_of=AS_OF, backup_facts=invalid_backup)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_FAILED)
        self.assertIn("backup_manifest_invalid", [f["code"] for f in document["findings"]])

    def test_severity_precedence_failed_beats_degraded_beats_healthy(self):
        facts = mutate_facts(self.config, self.study)
        openaq_record(facts, "openaq_11357424")["accepted_intervals"] = 1
        target_key(facts, "openaq", "openaq_14581375")["runs"].update({"latest_status": "failed"})
        document = assess_health(self.config, facts, as_of=AS_OF)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_FAILED)
        codes = {finding["code"] for finding in document["findings"]}
        self.assertIn("openaq_low_coverage", codes)
        self.assertIn("run_failed", codes)
        ranks = [{"failed": 2, "degraded": 1}[f["severity"]] for f in document["findings"]]
        self.assertEqual(ranks, sorted(ranks, reverse=True))

    def test_assessment_is_deterministic(self):
        facts = healthy_facts(self.config, self.study)
        first = assess_health(self.config, facts, as_of=AS_OF)
        second = assess_health(self.config, facts, as_of=AS_OF)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))


class HealthSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.config, self.study = reviewed_configs()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def test_snapshot_collects_read_only_and_assesses(self):
        connection = FakeHealthConnection()
        engine = FakeHealthEngine(connection)
        document = health_snapshot(self.config, self.study, engine_factory=lambda: engine, as_of=AS_OF)
        self.assertEqual(document["exit_code"], HEALTH_EXIT_HEALTHY)
        self.assertTrue(engine.disposed)
        statements = [sql for sql, _ in connection.calls]
        self.assertIn("SET TRANSACTION READ ONLY", statements)
        self.assertTrue(any("set_config" in sql for sql in statements))
        for sql in statements:
            self.assertFalse(any(word in sql.upper().split() for word in ("INSERT", "UPDATE", "DELETE", "DROP")),
                             sql)
        parameters = [params for sql, params in connection.calls if "target_sensor_id" in sql]
        self.assertTrue(parameters)
        self.assertTrue(all(isinstance(params, dict) for params in parameters))
        fetch_parameters = [params for sql, params in connection.calls
                            if "FROM vn_air.source_responses AS sr" in sql]
        self.assertEqual({params["target"] for params in fetch_parameters},
                         {target["target"] for target in configured_health_targets(self.config, self.study)})

    def test_snapshot_reports_failure_for_unavailable_database(self):
        def broken():
            raise ValueError("Set DATABASE_URL explicitly")
        with self.assertRaises(AutomationError) as context:
            health_snapshot(self.config, self.study, engine_factory=broken, as_of=AS_OF)
        self.assertEqual(context.exception.code, "database_url_missing")

    def test_health_command_output_and_exit_codes(self):
        connection = FakeHealthConnection()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = health_command(self.config, self.study,
                                  engine_factory=lambda: FakeHealthEngine(connection), as_of=AS_OF)
        self.assertEqual(code, HEALTH_EXIT_HEALTHY)
        self.assertEqual(json.loads(output.getvalue())["status"], "healthy")
        existing = self.base / "existing.json"
        existing.write_text("{}")
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = health_command(self.config, self.study,
                                  engine_factory=lambda: FakeHealthEngine(FakeHealthConnection()),
                                  as_of=AS_OF, output=existing)
        self.assertEqual(code, HEALTH_EXIT_INVALID)

    def test_health_command_returns_three_for_invalid_configuration(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = automation_command(action="health", automation_config=self.base / "missing.json",
                                      study_config=STUDY_PATH)
        self.assertEqual(code, HEALTH_EXIT_INVALID)
        self.assertIn("automation_config_missing", stderr.getvalue())

    def test_backup_directory_inspection_is_optional_and_light(self):
        connection = FakeHealthConnection()
        engine = FakeHealthEngine(connection)
        plain = health_snapshot(self.config, self.study, engine_factory=lambda: engine, as_of=AS_OF)
        self.assertIsNone(plain["backup"])
        self.assertEqual(plain["exit_code"], HEALTH_EXIT_HEALTHY)
        missing_dir = health_snapshot(self.config, self.study, engine_factory=lambda: FakeHealthEngine(
            FakeHealthConnection()), as_of=AS_OF, backup_dir=self.base / "none")
        self.assertEqual(missing_dir["exit_code"], HEALTH_EXIT_DEGRADED)
        self.assertIn("backup_missing", [f["code"] for f in missing_dir["findings"]])


class FakeRecoveryConnection:
    def __init__(self, *, stale=None, problems=None):
        self.stale = stale or []
        self.problems = problems or []
        self.calls = []

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.calls.append((sql, parameters))
        if "SET TRANSACTION READ ONLY" in sql or "set_config" in sql:
            return FakeResult(None)
        if "to_regclass" in sql:
            return FakeResult("public.vn_air_schema_version")
        if "FROM public.vn_air_schema_version" in sql:
            return FakeResult("0003_response_integrity")
        if "status = 'running'" in sql:
            return FakeResult(rows=self.stale)
        if "status IN ('failed', 'partial')" in sql:
            product = (parameters or {}).get("product")
            rows = [row for row in self.problems if row["product_id"] == product]
            return FakeResult(rows=rows)
        raise AssertionError(f"unexpected SQL reached the fake: {sql}")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class RecoveryGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.config, self.study = reviewed_configs()

    def problem(self, **changes):
        values = {
            "product_id": PRODUCTS["openaq"], "target_sensor_id": "openaq_11357424",
            "target_location_id": None, "status": "failed", "error_code": "provider_cooldown",
            "started_at": AS_OF - timedelta(hours=2), "finished_at": AS_OF - timedelta(hours=1, minutes=50),
            "window_start": AS_OF - timedelta(hours=74), "window_end": AS_OF - timedelta(hours=2),
            "checkpoint_completed": False,
        }
        values.update(changes)
        return values

    def guidance(self, facts):
        return build_recovery_guidance(self.config, self.study, facts, as_of=AS_OF)

    def test_stale_running_guidance_never_marks_failed_or_retries(self):
        facts = {"stale_running": [{"product_id": PRODUCTS["openaq"], "target_sensor_id": "openaq_11357424",
                                    "target_location_id": None,
                                    "started_at": AS_OF - timedelta(hours=2)}],
                 "problems": []}
        document = self.guidance(facts)
        finding = document["findings"][0]
        self.assertEqual(finding["kind"], "stale_running")
        self.assertFalse(finding["retryable"])
        self.assertIn("Suspected stale", finding["guidance"])
        self.assertIsNone(finding["suggested_command"])

    def test_openaq_cooldown_suggests_bounded_backfill(self):
        document = self.guidance({"stale_running": [], "problems": [self.problem()]})
        finding = document["findings"][0]
        self.assertEqual(finding["source"], "openaq")
        self.assertEqual(finding["retry_class"], "cooldown")
        self.assertTrue(finding["retryable"])
        self.assertTrue(finding["operator_confirmation_required"])
        command = finding["suggested_command"]
        self.assertEqual(command[:5], ["vn-air", "ingest", "backfill", "--source", "openaq"])
        start = datetime.fromisoformat(command[command.index("--start") + 1])
        end = datetime.fromisoformat(command[command.index("--end") + 1])
        self.assertLessEqual((end - start).total_seconds(), 72 * 3600 + 1)
        self.assertLessEqual(end, AS_OF.replace(minute=0, second=0, microsecond=0))

    def test_weather_retry_is_poll_only_and_never_backfilled(self):
        problem = self.problem(product_id=PRODUCTS["weather"], target_sensor_id=None,
                               target_location_id="cmt8", error_code="network_error")
        document = self.guidance({"stale_running": [], "problems": [problem]})
        finding = document["findings"][0]
        self.assertEqual(finding["retry_class"], "transient")
        self.assertTrue(finding["poll_only"])
        self.assertFalse(finding["retryable"])
        self.assertIsNone(finding["suggested_command"])
        self.assertIn("historical model", finding["guidance"])

    def test_unknown_error_code_is_not_auto_retryable(self):
        problem = self.problem(error_code="mystery_code")
        document = self.guidance({"stale_running": [], "problems": [problem]})
        finding = document["findings"][0]
        self.assertEqual(finding["error_code"], "unrecognized_child_error")
        self.assertEqual(finding["retry_class"], "not_retryable")
        self.assertFalse(finding["retryable"])
        self.assertIsNone(finding["suggested_command"])

    def test_completed_checkpoint_is_retained_and_confirmation_required(self):
        problem = self.problem(checkpoint_completed=True)
        document = self.guidance({"stale_running": [], "problems": [problem]})
        finding = document["findings"][0]
        self.assertTrue(finding["checkpoint_completed"])
        self.assertIn("completed checkpoint", finding["guidance"])
        self.assertTrue(finding["operator_confirmation_required"])

    def test_no_bounded_window_blocks_a_suggested_command(self):
        problem = self.problem(window_start=None, window_end=None)
        document = self.guidance({"stale_running": [], "problems": [problem]})
        finding = document["findings"][0]
        self.assertFalse(finding["retryable"])
        self.assertIsNone(finding["suggested_command"])
        self.assertIn("bounded window", finding["guidance"])

    def test_recover_command_is_read_only_and_returns_zero(self):
        connection = FakeRecoveryConnection(problems=[self.problem()])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = recover_command(self.config, self.study,
                                   engine_factory=lambda: FakeHealthEngine(connection), as_of=AS_OF)
        self.assertEqual(code, HEALTH_EXIT_HEALTHY)
        document = json.loads(output.getvalue())
        self.assertTrue(document["read_only"])
        self.assertEqual(document["counts"]["failed_or_partial"], 1)
        for sql, _ in connection.calls:
            self.assertNotIn("UPDATE", sql.upper())
            self.assertNotIn("DELETE", sql.upper())
            self.assertNotIn("INSERT", sql.upper())


if __name__ == "__main__":
    unittest.main()
