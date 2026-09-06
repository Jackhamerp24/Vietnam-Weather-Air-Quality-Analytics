"""Synthetic HTTP responses through the real ingestion path and isolated SQL."""

import contextlib
import io
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingestion_fixtures import aq_row, licence_payload, location_payload, meteo_payload
from vn_air.config import load_config
from vn_air.database.setup import database_engine, migrate, seed_reference_data
from vn_air.ingestion import PIPELINE_VERSION, IngestionError
from vn_air.ingestion.pipeline import Ingestor, LOCK_ID, fingerprint, insert_many


ROOT = Path(__file__).resolve().parents[2]
T = datetime(2026, 6, 8, tzinfo=timezone.utc)


@unittest.skipUnless(os.environ.get("VN_AIR_TEST_DATABASE_URL"), "Use scripts/test_database.py")
class IngestionDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = database_engine(os.environ["VN_AIR_TEST_DATABASE_URL"])
        if cls.engine.url.database != "vn_air_test" or cls.engine.url.username != "vn_test":
            raise ValueError("Requires isolated test cluster")
        cls.config = load_config(ROOT / "configs/study.json")
        cls.sensor = cls.config.sensors[0]
        cls.location = next(row for row in cls.config.locations if row.id == cls.sensor.location_id)
        with cls.engine.begin() as connection:
            migrate(connection)
            seed_reference_data(connection, cls.config)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def tearDown(self):
        with self.engine.begin() as connection:
            # Fixtures belong to this disposable cluster, never a configured DB.
            connection.execute(text("TRUNCATE vn_air.ingestion_checkpoints, vn_air.data_quality_issues, vn_air.quarantined_records, vn_air.modeled_values, vn_air.model_snapshots, vn_air.air_quality_observations, vn_air.source_responses, vn_air.ingestion_runs"))

    def scalar(self, sql):
        with self.engine.connect() as connection:
            return connection.execute(text(sql)).scalar_one()

    def handler(self, rows=None, fail=None, metadata=None):
        def respond(request):
            if "/licenses/" in request.url.path:
                return httpx.Response(200, json=licence_payload())
            if "/locations/" in request.url.path:
                return httpx.Response(200, json=metadata or location_payload(self.sensor, self.location))
            if fail:
                return fail(request)
            return httpx.Response(200, json={"meta": {"page": int(request.url.params["page"])}, "results": rows or []})
        return respond

    def run_aq(self, rows=None, *, handler=None, resume=False, max_requests=20):
        worker = Ingestor(self.engine, self.config, key="synthetic_secret", transport=httpx.MockTransport(handler or self.handler(rows)), sleep=lambda s: None, max_requests=max_requests)
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                result = worker.run("openaq", T, T + timedelta(days=1), target_ids=[self.sensor.id], resume=resume)
            self.assertNotIn("synthetic_secret", output.getvalue())
            return result
        finally:
            worker.close()

    def test_insert_repeat_revision_revert_and_invalid_marker(self):
        first = self.run_aq([aq_row(T)])
        self.assertEqual(first[0]["inserted"], 1)
        second = self.run_aq([aq_row(T)])
        self.assertEqual((second[0]["inserted"], second[0]["unchanged"]), (0, 1))
        self.run_aq([aq_row(T, 25)])
        self.run_aq([aq_row(T, 10)])
        self.run_aq([aq_row(T, -999)])
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.air_quality_observations"), 4)
        self.assertEqual(self.scalar("SELECT quality_status FROM vn_air.latest_air_quality"), "invalid")
        self.assertEqual(self.scalar("SELECT max(revision) FROM vn_air.air_quality_observations"), 4)

    def test_duplicate_and_conflicting_duplicates(self):
        self.run_aq([aq_row(T), aq_row(T)])
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.air_quality_observations"), 1)
        self.run_aq([aq_row(T), aq_row(T, 21)])
        self.assertEqual(self.scalar("SELECT quality_status FROM vn_air.latest_air_quality"), "invalid")
        self.assertGreater(self.scalar("SELECT count(*) FROM vn_air.quarantined_records"), 0)

    def test_resume_skips_http_and_preserves_completed_data(self):
        self.run_aq([aq_row(T)])
        def never(request):
            self.fail("Completed checkpoint must avoid API request")
        result = self.run_aq(handler=never, resume=True)
        self.assertEqual(result[0]["status"], "skipped")
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.ingestion_runs"), 1)

    def test_failed_refresh_invalidates_old_checkpoint(self):
        self.run_aq([aq_row(T)])
        self.run_aq([aq_row(T, -999)])
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.ingestion_checkpoints"), 0)
        result = self.run_aq([aq_row(T)], resume=True)
        self.assertEqual(result[0]["inserted"], 1)

    def test_dropped_session_is_not_reconnected_under_lost_lock(self):
        original = Ingestor.before_attempt
        def lose_session(worker, group):
            worker.connection.invalidate()
            original(worker, group)
        with patch.object(Ingestor, "before_attempt", lose_session):
            with self.assertRaisesRegex(IngestionError, "database_session_lost"):
                self.run_aq([aq_row(T)])
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.source_responses"), 0)
        self.run_aq([aq_row(T)])
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.ingestion_runs WHERE error_code='worker_interrupted'"), 1)

    def test_read_only_ingestion_report(self):
        from vn_air.ingestion.report import ingestion_report
        self.run_aq([aq_row(T)])
        report = ingestion_report(self.engine)
        self.assertEqual(report["measurements"][0]["distinct_hours"], 1)
        self.assertEqual(report["predictions"][0]["predictions"], 0)

    def test_provider_cooldown_survives_restart(self):
        with self.assertRaisesRegex(IngestionError, "provider_cooldown"):
            self.run_aq(handler=self.handler(fail=lambda request: httpx.Response(429, headers={"Retry-After": "3600"}, json={})))
        requests = self.scalar("SELECT count(*) FROM vn_air.source_responses")
        with self.assertRaisesRegex(IngestionError, "provider_cooldown"):
            self.run_aq([aq_row(T)])
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.source_responses"), requests)

    def test_model_missing_field_is_partial_without_checkpoint(self):
        variables = [v for v in self.config.variables if v.domain == "weather"]
        payload = meteo_payload(self.location, variables, T)
        del payload["hourly"]["apparent_temperature"]
        worker = Ingestor(self.engine, self.config, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)), sleep=lambda s: None)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                result = worker.run("era5", T, T + timedelta(days=1), target_ids=[self.location.id])
            self.assertEqual(result[0]["status"], "partial")
            self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.ingestion_checkpoints"), 0)
            self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.modeled_values WHERE quality_status='missing'"), 24)
        finally:
            worker.close()

    def test_missing_hours_not_invented(self):
        self.run_aq([aq_row(T), aq_row(T + timedelta(hours=23))])
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.air_quality_observations"), 2)
        self.assertEqual(self.scalar("SELECT (details->>'missing_hours')::int FROM vn_air.data_quality_issues WHERE issue_code='missing_hours'"), 22)

    def test_401_and_retry_attempts_persist(self):
        with self.assertRaisesRegex(IngestionError, "http_401"):
            self.run_aq(handler=self.handler(fail=lambda request: httpx.Response(401, json={})))
        self.assertEqual(self.scalar("SELECT status FROM vn_air.ingestion_runs"), "failed")
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.source_responses WHERE http_status=401"), 1)
        calls = []
        def transient(request):
            calls.append(1)
            return httpx.Response(503, json={}) if len(calls) == 1 else httpx.Response(200, json={"meta": {"page": 1}, "results": [aq_row(T)]})
        self.run_aq(handler=self.handler(fail=transient))
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.source_responses WHERE http_status=503"), 1)

    def test_secret_response_withheld(self):
        with self.assertRaisesRegex(IngestionError, "credential_echo"):
            self.run_aq(handler=self.handler(fail=lambda request: httpx.Response(200, json={"echo": "synthetic_secret"})))
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.source_responses WHERE error_code='credential_echo' AND body IS NULL"), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.air_quality_observations"), 0)

    def test_malformed_json_quarantined(self):
        with self.assertRaisesRegex(IngestionError, "invalid_json"):
            self.run_aq(handler=self.handler(fail=lambda request: httpx.Response(200, content=b'not json')))
        self.assertEqual(self.scalar("SELECT reason_code FROM vn_air.quarantined_records"), "invalid_json")
        self.assertEqual(self.scalar("SELECT status FROM vn_air.ingestion_runs"), "failed")

    def test_database_failure_retains_raw_evidence_and_can_replay(self):
        original = insert_many
        def fail(connection, table, rows):
            if table == "air_quality_observations":
                raise RuntimeError("synthetic database failure")
            return original(connection, table, rows)
        with patch("vn_air.ingestion.pipeline.insert_many", side_effect=fail):
            with self.assertRaisesRegex(IngestionError, "internal_or_database_error"):
                self.run_aq([aq_row(T)])
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.source_responses"), 3)
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.air_quality_observations"), 0)
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.ingestion_checkpoints"), 0)
        self.run_aq([aq_row(T)], resume=True)
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.air_quality_observations"), 1)

    def test_metadata_drift_blocks_measurements(self):
        metadata = location_payload(self.sensor, self.location)
        metadata["results"][0]["isMonitor"] = True
        with self.assertRaisesRegex(IngestionError, "instrument_metadata_changed"):
            self.run_aq(handler=self.handler(metadata=metadata))
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.air_quality_observations"), 0)

    def test_budget_exhaustion_is_not_silent(self):
        with self.assertRaisesRegex(IngestionError, "request_budget_exhausted"):
            self.run_aq([aq_row(T)], max_requests=1)
        self.assertEqual(self.scalar("SELECT status FROM vn_air.ingestion_runs"), "failed")

    def test_concurrent_worker_rejected(self):
        with self.engine.connect() as connection:
            connection.execute(text("SELECT pg_advisory_lock(:lock)"), {"lock": LOCK_ID})
            try:
                with self.assertRaisesRegex(IngestionError, "ingestion_already_running"):
                    self.run_aq([aq_row(T)])
            finally:
                connection.execute(text("SELECT pg_advisory_unlock(:lock)"), {"lock": LOCK_ID})
                connection.commit()

    def test_orphaned_run_recovered_only_after_lock(self):
        run = uuid4()
        with self.engine.begin() as connection:
            insert_many(connection, "ingestion_runs", [dict(id=run, product_id=self.sensor.product_id,
                        configuration_sha256=fingerprint(self.config.model_dump(mode="json")), pipeline_version=PIPELINE_VERSION, purpose="backfill")])
        self.run_aq([aq_row(T)])
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.ingestion_runs WHERE error_code='worker_interrupted'"), 1)

    def test_model_exact_repeat_and_changed_capture(self):
        variables = [v for v in self.config.variables if v.domain == "weather"]
        payload = meteo_payload(self.location, variables, T)
        def run():
            worker = Ingestor(self.engine, self.config, transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)), sleep=lambda s: None)
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    return worker.run("era5", T, T + timedelta(days=1), target_ids=[self.location.id])
            finally:
                worker.close()
        self.assertEqual(run()[0]["inserted"], 216)
        payload["generationtime_ms"] = 123
        self.assertEqual(run()[0]["unchanged"], 216)
        payload["hourly"]["temperature_2m"][0] = 25
        self.assertEqual(run()[0]["inserted"], 216)
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.model_snapshots"), 2)
        self.assertEqual(self.scalar("SELECT count(*) FROM vn_air.air_quality_observations"), 0)

    def test_rls_and_search_path_hardening(self):
        self.assertEqual(self.scalar("SELECT count(*) FROM pg_tables WHERE schemaname='vn_air' AND NOT rowsecurity"), 0)
        self.assertTrue(self.scalar("SELECT relrowsecurity FROM pg_class WHERE oid='public.vn_air_schema_version'::regclass"))
        self.assertIn("search_path=pg_catalog", self.scalar("SELECT proconfig FROM pg_proc WHERE oid='vn_air.reject_mutation()'::regprocedure"))
        with self.engine.begin() as connection:
            connection.execute(text("CREATE ROLE synthetic_reader NOLOGIN"))
            connection.execute(text("GRANT USAGE ON SCHEMA vn_air TO synthetic_reader"))
            connection.execute(text("GRANT SELECT ON vn_air.sensors TO synthetic_reader"))
            connection.execute(text("SET LOCAL ROLE synthetic_reader"))
            self.assertEqual(connection.execute(text("SELECT count(*) FROM vn_air.sensors")).scalar_one(), 0)
            connection.execute(text("RESET ROLE"))
            connection.execute(text("REVOKE ALL ON vn_air.sensors FROM synthetic_reader"))
            connection.execute(text("REVOKE ALL ON SCHEMA vn_air FROM synthetic_reader"))
            connection.execute(text("DROP ROLE synthetic_reader"))
