"""Phase 11 real synthetic backup/restore drill against the isolated cluster.

Builds a complete synthetic project dataset in a dedicated database, creates a
real project-scoped pg_dump archive, verifies it by checksum/listing and by a
real restore into a fresh private socket-only cluster, and checks health and
recovery projections against the synthetic state. Never touches Supabase, the
project database, providers or network. No credential is read or printed.
"""

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

from vn_air.automation import load_automation_config
from vn_air.automation_backup import (
    BACKUP_MANIFEST_NAME,
    create_backup,
    verify_backup_directory,
)
from vn_air.automation_health import health_command, recover_command, health_snapshot
from vn_air.config import load_config
from vn_air.database.setup import database_engine, migrate, seed_reference_data


ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_DATABASE = "vn_air_phase11_synth"
OPENAQ_PRODUCT = "openaq_airgradient_hourly"
WEATHER_PRODUCT = "open_meteo_weather_forecast"
CAMS_PRODUCT = "open_meteo_cams_global"
SENSOR_COORDINATES = {
    "openaq_11357424": (10.78533, 106.67029),
    "openaq_14581375": (20.9933, 105.9441),
}
STATION_COORDINATES = {"cmt8": (10.78533, 106.67029), "oceanpark": (20.9933, 105.9441)}
CITY_COORDINATES = {"hanoi": (21.0245, 105.84117), "hcmc": (10.82302, 106.62965),
                    "da_nang": (16.06778, 108.22083)}


@unittest.skipUnless(os.environ.get("VN_AIR_TEST_DATABASE_URL"), "Use scripts/test_database.py")
class AutomationBackupDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_url = os.environ["VN_AIR_TEST_DATABASE_URL"]
        parsed = make_url(cls.base_url)
        admin = database_engine(cls.base_url)
        if parsed.database != "vn_air_test" or parsed.username != "vn_test":
            admin.dispose()
            raise ValueError("Integration tests require the isolated test cluster")
        with admin.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS {SYNTHETIC_DATABASE} WITH (FORCE)"))
            connection.execute(text(f"CREATE DATABASE {SYNTHETIC_DATABASE}"))
        admin.dispose()
        cls.url = parsed.set(database=SYNTHETIC_DATABASE).render_as_string(hide_password=False)
        cls.engine = database_engine(cls.url)
        cls.study = load_config(ROOT / "configs/study.json")
        cls.config = load_automation_config(ROOT / "configs/automation.json")
        cls.as_of = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        with cls.engine.begin() as connection:
            migrate(connection)
            seed_reference_data(connection, cls.study)
        cls.run_ids = {}
        cls._insert_synthetic_project_data()
        with cls.engine.begin() as connection:
            connection.execute(text("CREATE SCHEMA unrelated"))
            connection.execute(text("CREATE TABLE unrelated.secret(id integer)"))

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    @classmethod
    def _insert(cls, table, **values):
        columns = ", ".join(values)
        bindings = ", ".join(f":{key}" for key in values)
        with cls.engine.begin() as connection:
            return connection.execute(
                text(f"INSERT INTO vn_air.{table} ({columns}) VALUES ({bindings}) RETURNING id"),
                values).scalar_one()

    @classmethod
    def _reference_sha(cls):
        with cls.engine.begin() as connection:
            return connection.execute(text(
                "SELECT sha256 FROM vn_air.reference_configs ORDER BY recorded_at LIMIT 1")).scalar_one()

    @classmethod
    def _run(cls, product, *, target_sensor=None, target_location=None, status="succeeded",
             error_code=None, started_at=None, finished_at=None, window_start=None, window_end=None):
        started = started_at or cls.as_of - timedelta(minutes=3)
        finished = finished_at or cls.as_of - timedelta(minutes=2)
        run_id = cls._insert(
            "ingestion_runs", id=str(uuid.uuid4()), product_id=product, purpose="poll",
            configuration_sha256=cls._reference_sha(), pipeline_version="phase11_synthetic",
            status=status, started_at=started, finished_at=finished, error_code=error_code,
            target_sensor_id=target_sensor, target_location_id=target_location,
            window_start=window_start, window_end=window_end,
            inserted_count=24 if status == "succeeded" else 0, unchanged_count=0, quarantined_count=0)
        cls.run_ids.setdefault((product, target_sensor, target_location), run_id)
        return run_id

    @classmethod
    def _response(cls, run_id, product, *, provider_group, retrieved, body):
        return cls._insert(
            "source_responses", id=str(uuid.uuid4()), run_id=run_id, product_id=product,
            requested_at=retrieved - timedelta(seconds=1), retrieved_at=retrieved,
            request_parameters="{}", http_status=200, media_type="application/json",
            body=body, provider_group=provider_group, request_path="/synthetic", attempt=1,
            elapsed_ms=12)

    @classmethod
    def _insert_synthetic_project_data(cls):
        for sensor in SENSOR_COORDINATES:
            run = cls._run(OPENAQ_PRODUCT, target_sensor=sensor, window_start=cls.as_of - timedelta(hours=24),
                           window_end=cls.as_of)
            response = cls._response(run, OPENAQ_PRODUCT, provider_group="openaq", retrieved=cls.as_of,
                                     body=b'{"synthetic":"openaq_measurement"}')
            latitude, longitude = SENSOR_COORDINATES[sensor]
            for hour in range(24):
                period_end = cls.as_of - timedelta(hours=hour)
                cls._insert(
                    "air_quality_observations", sensor_id=sensor, product_id=OPENAQ_PRODUCT,
                    variable_code="pm2_5", canonical_unit="ug/m3",
                    period_start=period_end - timedelta(hours=1), period_end=period_end,
                    revision=1, response_id=response, value=10.0 + hour, quality_status="accepted",
                    latitude=latitude, longitude=longitude, source_metadata="{}", recorded_at=cls.as_of)
            later = cls.as_of + timedelta(seconds=1)
            revision_response = cls._response(run, OPENAQ_PRODUCT, provider_group="openaq", retrieved=later,
                                              body=b'{"synthetic":"openaq_revision"}')
            cls._insert(
                "air_quality_observations", sensor_id=sensor, product_id=OPENAQ_PRODUCT,
                variable_code="pm2_5", canonical_unit="ug/m3", period_start=cls.as_of - timedelta(hours=1),
                period_end=cls.as_of, revision=2, response_id=revision_response, value=12.5,
                quality_status="accepted", latitude=latitude, longitude=longitude,
                source_metadata="{}", recorded_at=later)
        for location in STATION_COORDINATES:
            run = cls._run(WEATHER_PRODUCT, target_location=location,
                           window_start=cls.as_of, window_end=cls.as_of + timedelta(days=3))
            response = cls._response(run, WEATHER_PRODUCT, provider_group="open_meteo", retrieved=cls.as_of,
                                     body=b'{"synthetic":"open_meteo_forecast"}')
            latitude, longitude = STATION_COORDINATES[location]
            snapshot = cls._insert(
                "model_snapshots", id=str(uuid.uuid4()), product_id=WEATHER_PRODUCT, domain="weather",
                data_kind="forecast", location_id=location, response_id=response, model_key="ecmwf_ifs",
                run_provenance="unknown", requested_latitude=latitude, requested_longitude=longitude,
                grid_latitude=latitude, grid_longitude=longitude, recorded_at=cls.as_of)
            valid_at = cls.as_of + timedelta(hours=3)
            for code, unit, value in (("temperature_2m", "degC", 30.0),
                                      ("relative_humidity_2m", "%", 70.0),
                                      ("wind_speed_10m", "m/s", 3.0)):
                cls._insert(
                    "modeled_values", snapshot_id=snapshot, domain="weather", variable_code=code,
                    canonical_unit=unit, valid_at=valid_at, period_start=valid_at,
                    temporal_support="instant", value=value, quality_status="accepted",
                    recorded_at=cls.as_of)
        for location in CITY_COORDINATES:
            run = cls._run(CAMS_PRODUCT, target_location=location,
                           window_start=cls.as_of, window_end=cls.as_of + timedelta(days=3))
            response = cls._response(run, CAMS_PRODUCT, provider_group="open_meteo", retrieved=cls.as_of,
                                     body=b'{"synthetic":"open_meteo_cams"}')
            latitude, longitude = CITY_COORDINATES[location]
            snapshot = cls._insert(
                "model_snapshots", id=str(uuid.uuid4()), product_id=CAMS_PRODUCT, domain="air_quality",
                data_kind="forecast", location_id=location, response_id=response, model_key="cams_global",
                run_provenance="unknown", requested_latitude=latitude, requested_longitude=longitude,
                grid_latitude=latitude, grid_longitude=longitude, recorded_at=cls.as_of)
            valid_at = cls.as_of + timedelta(hours=3)
            cls._insert(
                "modeled_values", snapshot_id=snapshot, domain="air_quality", variable_code="pm2_5",
                canonical_unit="ug/m3", valid_at=valid_at, period_start=valid_at,
                temporal_support="instant", value=15.0, quality_status="accepted", recorded_at=cls.as_of)
        cls._insert("ingestion_checkpoints",
                    id=hashlib.sha256(b"synthetic-checkpoint").hexdigest(),
                    run_id=cls.run_ids[(OPENAQ_PRODUCT, "openaq_11357424", None)])
        cls._insert("data_quality_issues", run_id=cls.run_ids[(OPENAQ_PRODUCT, "openaq_14581375", None)],
                    sensor_id="openaq_14581375", issue_code="synthetic_note", severity="info",
                    details='{"synthetic":true}')
        cls._insert("quarantined_records",
                    response_id=cls._response(
                        cls.run_ids[(OPENAQ_PRODUCT, "openaq_14581375", None)], OPENAQ_PRODUCT,
                        provider_group="openaq", retrieved=cls.as_of, body=b'{"synthetic":"quarantine"}'),
                    record_locator="results/0", reason_code="synthetic_note", details='{}')

    def test_01_health_reports_synthetic_dataset_healthy(self):
        document = health_snapshot(self.config, self.study,
                                   engine_factory=lambda: database_engine(self.url), as_of=self.as_of)
        self.assertEqual(document["exit_code"], 0, json.dumps(document["findings"], indent=2))
        self.assertEqual(document["status"], "healthy")
        for target in document["targets"]:
            self.assertEqual(target["runs"]["latest_status"], "succeeded")
        self.assertTrue(all(record["accepted_intervals"] == 24 for record in document["openaq"]))
        self.assertTrue(all(record["latest_snapshot"]["accepted_values"] > 0
                            for record in document["modeled"]))

    def test_05_receipts_respect_target_identity_and_upper_cutoff(self):
        cutoff = self.as_of - timedelta(minutes=10)
        for product, sensor, location, provider in (
                (OPENAQ_PRODUCT, "openaq_11357424", "cmt8", "openaq"),
                (WEATHER_PRODUCT, None, "cmt8", "open_meteo")):
            run = self._run(product, target_sensor=sensor, target_location=location,
                            started_at=cutoff - timedelta(minutes=3),
                            finished_at=cutoff - timedelta(minutes=1),
                            window_start=cutoff.replace(minute=0) - timedelta(hours=24),
                            window_end=cutoff.replace(minute=0))
            self._response(run, product, provider_group=provider,
                           retrieved=cutoff - timedelta(minutes=2), body=b'{"synthetic":"target_only"}')
        report = health_snapshot(self.config, self.study, engine_factory=lambda: database_engine(self.url),
                                 as_of=cutoff)
        receipts = {(row["source"], row["target"]): row for row in report["fetch"]}
        for identity in (("openaq", "openaq_11357424"), ("weather", "cmt8")):
            self.assertEqual(receipts[identity]["successes"], 1)
        for identity in (("openaq", "openaq_14581375"), ("weather", "oceanpark")):
            self.assertEqual(receipts[identity]["successes"], 0)
            self.assertIsNone(receipts[identity]["latest_success_at"])
        sensor = next(row for row in report["targets"] if row["target"] == "openaq_11357424")
        self.assertEqual(sensor["runs"]["count"], 1)  # Real OpenAQ runs have both sensor and location IDs.

    def test_02_backup_and_real_restore_drill_verifies_synthetic_content(self):
        environment = dict(os.environ)
        environment["DATABASE_URL"] = self.url
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        output = Path(temporary.name) / "backup"
        result = create_backup(self.config, self.study, output_dir=output, environ=environment)
        self.assertEqual(result["status"], "backup_created")
        manifest = json.loads((output / BACKUP_MANIFEST_NAME).read_text(encoding="utf-8"))
        probe = manifest["content_probe"]
        self.assertEqual(probe["source_products"], 4)
        self.assertEqual(probe["variables"], 16)
        self.assertEqual(probe["locations"], 5)
        self.assertEqual(probe["sensors"], 2)
        self.assertEqual(probe["air_quality_max_revision"], 2)
        self.assertEqual(probe["air_quality_intervals"], 48)
        self.assertEqual(probe["source_response_body_hashes"], 5)
        self.assertEqual(probe["ingestion_checkpoints"], 1)
        self.assertEqual(probe["data_quality_issues"], 1)
        self.assertEqual(manifest["database"]["schema_revision"], "0003_response_integrity")

        verification = verify_backup_directory(output, restore_drill=True, config=self.config,
                                               study=self.study, environ=environment)
        self.assertEqual(verification["status"], "restore_verified")
        self.assertTrue(verification["checksum_verified"])
        self.assertTrue(verification["listing_verified"])
        self.assertTrue(verification["restore_verified"])
        evidence = verification["restore_evidence"]
        self.assertEqual(evidence["schema_revision"], "0003_response_integrity")
        self.assertEqual(evidence["content_probe"], probe)
        self.assertEqual(evidence["reference_counts"],
                         {"source_products": 4, "variables": 16, "locations": 5, "sensors": 2})
        self.assertTrue(evidence["unrelated_schemas_absent"])
        self.assertTrue(evidence["project_public_relations_only"])
        self.assertTrue(all(evidence["constraint_probes"].values()))
        self.assertEqual(evidence["view_row_counts"],
                         {"latest_air_quality": 48, "weather_observations": 6, "modeled_air_quality": 3})

    def test_03_health_degrades_and_recovery_guides_after_synthetic_failures(self):
        failed_at = self.as_of - timedelta(seconds=30)
        self._run(OPENAQ_PRODUCT, target_sensor="openaq_11357424", status="failed",
                  error_code="provider_cooldown", started_at=failed_at,
                  finished_at=failed_at + timedelta(seconds=1),
                  window_start=self.as_of - timedelta(hours=74), window_end=self.as_of - timedelta(hours=2))
        weather_failed = self.as_of - timedelta(seconds=20)
        self._run(WEATHER_PRODUCT, target_location="cmt8", status="failed", error_code="network_error",
                  started_at=weather_failed, finished_at=weather_failed + timedelta(seconds=1),
                  window_start=self.as_of - timedelta(hours=6), window_end=self.as_of)
        document = health_snapshot(self.config, self.study,
                                   engine_factory=lambda: database_engine(self.url), as_of=self.as_of)
        self.assertEqual(document["exit_code"], 1)
        codes = {finding["code"] for finding in document["findings"]}
        self.assertIn("run_failed", codes)

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = recover_command(self.config, self.study,
                                   engine_factory=lambda: database_engine(self.url), as_of=self.as_of)
        self.assertEqual(code, 0)
        guidance = json.loads(output.getvalue())
        openaq = next(finding for finding in guidance["findings"] if finding["source"] == "openaq")
        self.assertTrue(openaq["retryable"])
        self.assertTrue(openaq["operator_confirmation_required"])
        command = openaq["suggested_command"]
        start = datetime.fromisoformat(command[command.index("--start") + 1])
        end = datetime.fromisoformat(command[command.index("--end") + 1])
        self.assertLessEqual((end - start).total_seconds(), 72 * 3600 + 1)
        self.assertLessEqual(end, self.as_of)
        weather = next(finding for finding in guidance["findings"] if finding["source"] == "weather")
        self.assertTrue(weather["poll_only"])
        self.assertIsNone(weather["suggested_command"])

    def test_04_cli_failure_exit_codes_do_not_touch_live_services(self):
        import subprocess
        import sys

        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ROOT / "src")
        environment["DATABASE_URL"] = self.url
        missing_switch = subprocess.run(
            [sys.executable, "-B", "-m", "vn_air.cli", "automation", "backup",
             "--output-dir", str(Path(tempfile.mkdtemp()) / "never")],
            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=60)
        self.assertEqual(missing_switch.returncode, 3)
        self.assertIn("automation_execute_required", missing_switch.stderr)

        bad_database = dict(environment)
        bad_database["DATABASE_URL"] = make_url(self.url).set(
            database="vn_air_phase11_missing").render_as_string(hide_password=False)
        missing_db = subprocess.run(
                [sys.executable, "-B", "-m", "vn_air.cli", "automation", "health"],
                cwd=ROOT, env=bad_database, capture_output=True, text=True, timeout=120)
        self.assertEqual(missing_db.returncode, 1)
        self.assertIn("database_unavailable", missing_db.stderr)


if __name__ == "__main__":
    unittest.main()
