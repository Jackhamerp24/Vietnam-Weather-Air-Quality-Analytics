"""Synthetic schema fixtures only, isolated PostgreSQL, no provider requests."""

import hashlib
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from vn_air.config import load_config
from vn_air.database.setup import database_engine, migrate, seed_reference_data


ROOT = Path(__file__).resolve().parents[2]
T = datetime(2026, 6, 9, tzinfo=timezone.utc)


@unittest.skipUnless(os.environ.get("VN_AIR_TEST_DATABASE_URL"), "Use scripts/test_database.py")
class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ["VN_AIR_TEST_DATABASE_URL"]
        cls.engine = database_engine(url)
        if cls.engine.url.database != "vn_air_test" or cls.engine.url.username != "vn_test":
            raise ValueError("Integration tests require the isolated test cluster")
        cls.config = load_config(ROOT / "configs/study.json")
        with cls.engine.begin() as connection:
            migrate(connection)
            seed_reference_data(connection, cls.config)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()

    def tearDown(self):
        self.transaction.rollback()
        self.connection.close()

    def insert(self, table, **values):
        if table == "ingestion_runs":
            values.setdefault("configuration_sha256", self.connection.execute(text("SELECT sha256 FROM vn_air.reference_configs ORDER BY recorded_at LIMIT 1")).scalar_one())
            values.setdefault("pipeline_version", "synthetic_schema_test")
        columns = ", ".join(values)
        binds = ", ".join(f":{key}" for key in values)
        return self.connection.execute(text(f"INSERT INTO vn_air.{table} ({columns}) VALUES ({binds}) RETURNING id"), values).scalar_one()

    def response(self, product="openaq_airgradient_hourly", retrieved=T, status=200):
        run_id = self.insert("ingestion_runs", id=uuid4(), product_id=product, purpose="backfill", started_at=retrieved - timedelta(minutes=1))
        return self.insert("source_responses", id=uuid4(), run_id=run_id, product_id=product,
                           requested_at=retrieved - timedelta(seconds=1), retrieved_at=retrieved,
                           request_parameters="{}", http_status=status, body=b'{"synthetic_test": true}')

    def observation(self, **changes):
        values = dict(sensor_id="openaq_11357424", product_id="openaq_airgradient_hourly",
                      variable_code="pm2_5", canonical_unit="ug/m3", period_start=T - timedelta(hours=2),
                      period_end=T - timedelta(hours=1), revision=1, response_id=self.response(),
                      value=20.0, quality_status="accepted", latitude=10.78533, longitude=106.67029,
                      source_metadata="{}", recorded_at=T)
        values.update(changes)
        return self.insert("air_quality_observations", **values)

    def snapshot(self, product="open_meteo_weather_forecast", **changes):
        kind = "reanalysis" if product == "open_meteo_era5" else "forecast"
        values = dict(id=uuid4(), product_id=product, domain="weather", data_kind=kind,
                      location_id="cmt8", response_id=self.response(product), model_key="ecmwf_ifs",
                      run_provenance="reanalysis" if kind == "reanalysis" else "unknown",
                      requested_latitude=10.78533, requested_longitude=106.67029,
                      grid_latitude=10.8, grid_longitude=106.7, recorded_at=T)
        values.update(changes)
        return self.insert("model_snapshots", **values)

    def modeled(self, snapshot, **changes):
        values = dict(snapshot_id=snapshot, domain="weather", variable_code="temperature_2m",
                      canonical_unit="degC", valid_at=T + timedelta(hours=6), period_start=T + timedelta(hours=6),
                      temporal_support="instant", value=27.0, quality_status="accepted", recorded_at=T)
        values.update(changes)
        return self.insert("modeled_values", **values)

    def assert_rejected(self, operation, state="23514"):
        with self.assertRaises(DBAPIError) as caught:
            with self.connection.begin_nested():
                operation()
        self.assertEqual(caught.exception.orig.sqlstate, state)

    def test_seed_is_idempotent_and_metadata_only(self):
        counts = seed_reference_data(self.connection, self.config)
        self.assertEqual(sum(counts.values()), 0)
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM vn_air.locations")).scalar_one(), 5)
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM vn_air.sensors")).scalar_one(), 2)
        for table in ("air_quality_observations", "modeled_values", "model_predictions", "ingestion_runs"):
            self.assertEqual(self.connection.execute(text(f"SELECT count(*) FROM vn_air.{table}")).scalar_one(), 0)

    def test_conflicting_seed_rolls_back(self):
        config = self.config.model_copy(deep=True)
        config.locations[0].latitude = 22.0
        with self.assertRaisesRegex(ValueError, "Reference conflict"):
            with self.connection.begin_nested():
                seed_reference_data(self.connection, config)
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM vn_air.reference_configs")).scalar_one(), 1)

    def test_duplicate_period_rejected_and_revision_preserved(self):
        self.observation()
        self.assert_rejected(lambda: self.observation(), "23505")
        self.observation(revision=2, value=25.0, recorded_at=T + timedelta(seconds=1))
        self.observation(revision=3, value=20.0, recorded_at=T + timedelta(seconds=2))
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM vn_air.air_quality_observations")).scalar_one(), 3)
        latest = self.connection.execute(text("SELECT revision, value FROM vn_air.latest_air_quality")).one()
        self.assertEqual(latest, (3, 20.0))

    def test_revision_chain_and_chronology(self):
        self.assert_rejected(lambda: self.observation(revision=2), "23503")
        self.observation(recorded_at=T + timedelta(seconds=10))
        self.assert_rejected(lambda: self.observation(revision=2, recorded_at=T + timedelta(seconds=5)))

    def test_missing_revision_does_not_resurrect_old_value(self):
        self.observation()
        self.observation(revision=2, value=None, quality_status="missing")
        self.assertIsNone(self.connection.execute(text("SELECT value FROM vn_air.latest_air_quality")).scalar_one())

    def test_invalid_revision_can_invalidate_prior_value(self):
        self.observation()
        self.observation(revision=2, value=None, quality_status="invalid")
        self.assertEqual(self.connection.execute(text("SELECT value, quality_status FROM vn_air.latest_air_quality")).one(), (None, "invalid"))

    def test_asof_query_excludes_late_revision(self):
        self.observation()
        self.observation(revision=2, value=99.0, response_id=self.response(retrieved=T + timedelta(days=1)), recorded_at=T + timedelta(days=1))
        row = self.connection.execute(text("""
            SELECT o.value FROM vn_air.air_quality_observations o
            JOIN vn_air.source_responses r ON r.id=o.response_id
            WHERE o.recorded_at <= :origin AND r.retrieved_at <= :origin AND o.period_end <= :origin
            ORDER BY o.revision DESC LIMIT 1
        """), {"origin": T + timedelta(hours=1)}).scalar_one()
        self.assertEqual(row, 20.0)

    def test_measurement_values_timestamps_and_units(self):
        for changes in (
            {"value": -1}, {"value": float("nan")}, {"value": float("inf")},
            {"latitude": 91}, {"value": None}, {"quality_status": "missing"},
            {"period_end": T}, {"recorded_at": T - timedelta(seconds=1)},
            {"coverage_percent": 101}, {"source_published_at": T + timedelta(hours=1)},
            {"response_id": self.response(status=500)},
        ):
            with self.subTest(changes=changes):
                self.assert_rejected(lambda: self.observation(**changes))
        self.assert_rejected(lambda: self.observation(canonical_unit="USAQI"), "23503")

    def test_extreme_valid_concentration_is_not_deleted(self):
        self.observation(value=900.0, quality_status="suspect")
        self.assertEqual(self.connection.execute(text("SELECT value FROM vn_air.latest_air_quality")).scalar_one(), 900.0)

    def test_incomplete_hour_and_licence_interval_rejected(self):
        self.assert_rejected(lambda: self.observation(period_start=T, period_end=T + timedelta(hours=1)))
        self.assert_rejected(lambda: self.observation(period_start=datetime(2020, 1, 1, tzinfo=timezone.utc), period_end=datetime(2020, 1, 1, 1, tzinfo=timezone.utc)))

    def test_wrong_product_and_sensor_identity(self):
        self.assert_rejected(lambda: self.observation(product_id="open_meteo_cams_global", response_id=self.response("open_meteo_cams_global")), "23503")
        self.assert_rejected(lambda: self.observation(sensor_id="not_a_sensor"), "23503")

    def test_source_body_hash_and_quarantine(self):
        response = self.response()
        stored = self.connection.execute(text("SELECT body_sha256 FROM vn_air.source_responses WHERE id=:id"), {"id": response}).scalar_one()
        self.assertEqual(stored, hashlib.sha256(b'{"synthetic_test": true}').hexdigest())
        self.insert("quarantined_records", response_id=response, record_locator="results/0", reason_code="unexpected_unit", details='{"raw_unit":"invalid"}')
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM vn_air.quarantined_records")).scalar_one(), 1)

    def test_raw_and_reference_rows_are_append_only(self):
        self.observation()
        for table in ("source_responses", "air_quality_observations", "sensors", "locations", "reference_configs"):
            with self.subTest(table=table):
                self.assert_rejected(lambda: self.connection.execute(text(f"DELETE FROM vn_air.{table}")))

    def test_distinct_forecast_vintages_same_valid_time(self):
        first, second = self.snapshot(), self.snapshot()
        self.modeled(first)
        self.modeled(second, value=28.0)
        self.assert_rejected(lambda: self.modeled(first), "23505")
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM vn_air.weather_observations")).scalar_one(), 2)

    def test_measured_vs_modeled_and_variable_domain(self):
        snapshot = self.snapshot("open_meteo_cams_global", domain="air_quality")
        self.modeled(snapshot, domain="air_quality", variable_code="pm2_5", canonical_unit="ug/m3")
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM vn_air.modeled_air_quality")).scalar_one(), 1)
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM vn_air.air_quality_observations")).scalar_one(), 0)
        self.assert_rejected(lambda: self.modeled(snapshot), "23503")

    def test_weather_physical_bounds_and_interval_semantics(self):
        snapshot = self.snapshot()
        self.assert_rejected(lambda: self.modeled(snapshot, variable_code="relative_humidity_2m", canonical_unit="%", value=101))
        self.assert_rejected(lambda: self.modeled(snapshot, variable_code="precipitation", canonical_unit="mm", temporal_support="preceding_hour_sum"))
        self.modeled(snapshot, variable_code="precipitation", canonical_unit="mm", temporal_support="preceding_hour_sum", period_start=T + timedelta(hours=5))

    def test_reanalysis_and_run_provenance(self):
        snapshot = self.snapshot("open_meteo_era5", model_key="era5")
        self.assert_rejected(lambda: self.modeled(snapshot))
        self.assert_rejected(lambda: self.snapshot(run_provenance="operational"))
        self.assert_rejected(lambda: self.snapshot(run_initialized_at=T + timedelta(hours=1)))

    def test_timestamp_offset_is_normalized_to_utc(self):
        self.observation(period_start="2026-06-09T05:00:00+07:00", period_end="2026-06-09T06:00:00+07:00")
        stored = self.connection.execute(text("SELECT period_end FROM vn_air.latest_air_quality")).scalar_one()
        self.assertEqual(stored, T - timedelta(hours=1))
        self.assertEqual(stored.utcoffset(), timedelta(0))

    def test_responses_reject_cross_product_provenance_and_secret_parameters(self):
        run = self.insert("ingestion_runs", id=uuid4(), product_id="openaq_airgradient_hourly", purpose="poll")
        parameters = dict(id=uuid4(), run_id=run, product_id="openaq_airgradient_hourly",
                          requested_at=T, retrieved_at=T, request_parameters='{"apikey":"synthetic-not-secret"}', http_status=200, body=b'{}')
        self.assert_rejected(lambda: self.insert("source_responses", **parameters))
        self.assert_rejected(lambda: self.insert("source_responses", **(parameters | {"request_parameters": "{}", "product_id": "open_meteo_cams_global"})), "23503")

    def test_retrospective_prediction_cannot_be_misrepresented_as_operational(self):
        model = self.insert("model_runs", id=uuid4(), model_name="synthetic_backtest", model_version="test", horizon_hours=6,
                            training_started_at=T - timedelta(days=90), training_cutoff=T - timedelta(days=1),
                            fitted_at=T + timedelta(days=1), feature_version="test", code_revision="synthetic",
                            data_manifest_sha256="b" * 64, parameters="{}")
        values = dict(model_run_id=model, sensor_id="openaq_11357424", horizon_hours=6, forecast_origin=T,
                      target_start=T + timedelta(hours=5), target_end=T + timedelta(hours=6),
                      generated_at=T + timedelta(days=1), feature_available_through=T, predicted_pm2_5=20.0)
        self.assert_rejected(lambda: self.insert("model_predictions", **values, prediction_kind="operational"))
        self.insert("model_predictions", **values, prediction_kind="retrospective")

    def test_assumed_historical_availability_is_explicit(self):
        model = self.insert("model_runs", id=uuid4(), model_name="synthetic_lag_study", model_version="test", horizon_hours=6,
                            training_started_at=T - timedelta(days=90), training_cutoff=T - timedelta(days=1),
                            fitted_at=T, feature_version="test", code_revision="synthetic",
                            data_manifest_sha256="c" * 64, parameters="{}")
        values = dict(model_run_id=model, sensor_id="openaq_11357424", horizon_hours=6, forecast_origin=T,
                      target_start=T + timedelta(hours=5), target_end=T + timedelta(hours=6), generated_at=T,
                      availability_basis="assumed", availability_assumption="Synthetic one-hour lag scenario; historical availability unknown",
                      feature_available_through=None, predicted_pm2_5=20.0)
        self.assert_rejected(lambda: self.insert("model_predictions", **values, prediction_kind="operational"))
        self.insert("model_predictions", **values, prediction_kind="retrospective")

    def test_quality_issues_and_failed_run_require_explanation(self):
        self.assert_rejected(lambda: self.insert("ingestion_runs", id=uuid4(), product_id="openaq_airgradient_hourly", purpose="poll", status="failed", started_at=T, finished_at=T))
        run = self.insert("ingestion_runs", id=uuid4(), product_id="openaq_airgradient_hourly", purpose="poll", started_at=T)
        self.insert("data_quality_issues", run_id=run, sensor_id="openaq_14581375", window_start=T, window_end=T + timedelta(hours=119), issue_code="missing_hours", severity="warning", details='{"synthetic_test":true}')

    def test_prediction_horizon_training_and_uncertainty_contract(self):
        model = self.insert("model_runs", id=uuid4(), model_name="synthetic_baseline", model_version="test1", horizon_hours=6,
                            training_started_at=T - timedelta(days=90), training_cutoff=T - timedelta(days=1),
                            fitted_at=T - timedelta(hours=1), feature_version="test", code_revision="synthetic",
                            data_manifest_sha256="a" * 64, parameters="{}")
        values = dict(model_run_id=model, sensor_id="openaq_11357424", horizon_hours=6, forecast_origin=T,
                      target_start=T + timedelta(hours=5), target_end=T + timedelta(hours=6),
                      prediction_kind="operational", generated_at=T, feature_available_through=T, predicted_pm2_5=20.0)
        for changes in ({"horizon_hours": 24}, {"feature_available_through": T + timedelta(hours=1)},
                        {"lower_bound": 5.0}, {"forecast_origin": T - timedelta(days=2)},
                        {"generated_at": T + timedelta(days=1)}, {"predicted_pm2_5": -1}):
            with self.subTest(changes=changes):
                self.assert_rejected(lambda: self.insert("model_predictions", **(values | changes)))
        self.insert("model_predictions", **values)

    def test_z_migration_downgrade_upgrade_and_noop(self):
        migrate(self.connection)
        migrate(self.connection, "base", downgrade=True)
        self.assertIsNone(self.connection.execute(text("SELECT to_regnamespace('vn_air')")).scalar_one())
        migrate(self.connection)
        self.assertEqual(seed_reference_data(self.connection, self.config)["sensors"], 2)

    def test_failed_migration_rolls_back_and_preserves_existing_state(self):
        with self.assertRaises(DBAPIError):
            with self.connection.begin_nested():
                migrate(self.connection, "base", downgrade=True)
                self.connection.execute(text("CREATE SCHEMA vn_air"))
                migrate(self.connection)
        self.assertEqual(self.connection.execute(text("SELECT count(*) FROM vn_air.sensors")).scalar_one(), 2)
        self.assertEqual(self.connection.execute(text("SELECT version_num FROM public.vn_air_schema_version")).scalar_one(), "0003_response_integrity")

    def test_withheld_or_empty_success_cannot_support_observations(self):
        run = self.insert("ingestion_runs", id=uuid4(), product_id="openaq_airgradient_hourly", purpose="poll")
        values = dict(id=uuid4(), run_id=run, product_id="openaq_airgradient_hourly", requested_at=T,
                      retrieved_at=T, request_parameters="{}", http_status=200, body=None)
        self.assert_rejected(lambda: self.insert("source_responses", **values))
        response = self.insert("source_responses", **values, error_code="credential_echo")
        self.assert_rejected(lambda: self.observation(response_id=response))
