"""Phase 11 automation preflight, health and recovery against the isolated
PostgreSQL cluster. Read-only checks only; never touches the project database,
providers or network."""

import contextlib
import io
import json
import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

from vn_air.automation import AutomationError, database_preflight, load_automation_config
from vn_air.automation_health import health_command, health_snapshot, recover_command
from vn_air.config import load_config
from vn_air.database.setup import database_engine, migrate


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.environ.get("VN_AIR_TEST_DATABASE_URL"), "Use scripts/test_database.py")
class AutomationDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.url = os.environ["VN_AIR_TEST_DATABASE_URL"]
        engine = database_engine(cls.url)
        if engine.url.database != "vn_air_test" or engine.url.username != "vn_test":
            engine.dispose()
            raise ValueError("Integration tests require the isolated test cluster")
        with engine.begin() as connection:
            migrate(connection)
        engine.dispose()
        cls.config = load_automation_config(ROOT / "configs/automation.json")

    def test_preflight_reports_schema_and_size(self):
        report = database_preflight(self.config, engine_factory=lambda: database_engine(self.url))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["schema_revision"], "0003_response_integrity")
        self.assertGreater(report["database_bytes"], 0)
        self.assertGreaterEqual(report["server_version_num"], 150000)

    def test_preflight_with_bounded_remaining_budget(self):
        report = database_preflight(self.config, engine_factory=lambda: database_engine(self.url),
                                    remaining_seconds=30)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["schema_revision"], "0003_response_integrity")

    def test_preflight_size_budget_stop(self):
        readiness = self.config.readiness.model_copy(update={"max_database_mib": 1})
        config = self.config.model_copy(update={"readiness": readiness})
        with self.assertRaises(AutomationError) as context:
            database_preflight(config, engine_factory=lambda: database_engine(self.url))
        self.assertEqual(context.exception.code, "database_size_budget_exhausted")

    def test_health_uses_the_real_schema_and_fails_missing_evidence(self):
        study = load_config(ROOT / "configs/study.json")
        document = health_snapshot(self.config, study,
                                   engine_factory=lambda: database_engine(self.url),
                                   as_of=datetime.now(timezone.utc))
        self.assertEqual(document["exit_code"], 1)
        codes = {finding["code"] for finding in document["findings"]}
        self.assertIn("run_evidence_missing", codes)
        self.assertIn("fetch_evidence_missing", codes)
        self.assertEqual(document["schema"]["revision"], "0003_response_integrity")

    def test_recover_is_read_only_and_empty_on_an_empty_seeded_database(self):
        study = load_config(ROOT / "configs/study.json")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = recover_command(self.config, study,
                                   engine_factory=lambda: database_engine(self.url),
                                   as_of=datetime.now(timezone.utc))
        self.assertEqual(code, 0)
        document = json.loads(output.getvalue())
        self.assertTrue(document["read_only"])
        self.assertEqual(document["counts"], {"stale_running": 0, "failed_or_partial": 0})
        self.assertEqual(document["findings"], [])

    def test_health_command_exit_code_on_seeded_database(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = health_command(self.config, load_config(ROOT / "configs/study.json"),
                                  engine_factory=lambda: database_engine(self.url),
                                  as_of=datetime.now(timezone.utc))
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
