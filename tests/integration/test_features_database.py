"""Phase 7 extractor against the isolated PostgreSQL cluster; no writes and no provider traffic."""

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vn_air.config import load_config
from vn_air.database.setup import database_engine, migrate, seed_reference_data
from vn_air.features_store import MAX_ROWS_PER_TABLE, extract_features

ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
T0 = datetime(2026, 6, 8, tzinfo=UTC)
START = T0
END = T0 + timedelta(hours=48)
CUTOFF = END + timedelta(hours=2)
EARLY = T0 - timedelta(hours=2)
CONFIG_PATH = ROOT / "configs/study.json"


def _sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def count_scalar(engine, sql):
    with engine.connect() as connection:
        return connection.execute(text(sql)).scalar_one()


@unittest.skipUnless(os.environ.get("VN_AIR_TEST_DATABASE_URL"), "Use scripts/test_database.py")
class FeatureExtractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = database_engine(os.environ["VN_AIR_TEST_DATABASE_URL"])
        if cls.engine.url.database != "vn_air_test" or cls.engine.url.username != "vn_test":
            raise ValueError("Requires isolated test cluster")
        cls.config = load_config(CONFIG_PATH)
        with cls.engine.begin() as connection:
            migrate(connection)
            seed_reference_data(connection, cls.config)
        cls.insert_fixtures()

    @classmethod
    def tearDownClass(cls):
        with cls.engine.begin() as connection:
            # Fixtures belong to this disposable cluster, never a configured DB.
            connection.execute(text(
                "TRUNCATE vn_air.ingestion_checkpoints, vn_air.data_quality_issues,"
                " vn_air.quarantined_records, vn_air.modeled_values, vn_air.model_snapshots,"
                " vn_air.air_quality_observations, vn_air.source_responses, vn_air.ingestion_runs"))
        cls.engine.dispose()

    @classmethod
    def config_sha(cls):
        from vn_air.quality import digest
        return digest(cls.config.model_dump(mode="json"))

    @classmethod
    def cutoff_now(cls):
        """A cutoff after the seeded reference rows but before the live transaction."""
        return datetime.now(UTC)

    @classmethod
    def insert_fixtures(cls):
        location = next(row for row in cls.config.locations if row.id == "cmt8")
        with cls.engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO vn_air.ingestion_runs (id, product_id, configuration_sha256, pipeline_version,
                    purpose, status, started_at, finished_at, window_start, window_end)
                VALUES ('11111111-1111-1111-1111-111111111111', 'openaq_airgradient_hourly', :config, 'test',
                        'poll', 'succeeded', :started, :started, :window_start, :window_end),
                       ('22222222-2222-2222-2222-222222222222', 'open_meteo_weather_forecast', :config, 'test',
                        'poll', 'succeeded', :started, :started, :window_start, :window_end),
                       ('33333333-3333-3333-3333-333333333333', 'open_meteo_era5', :config, 'test', 'backfill',
                        'succeeded', :started, :started, :window_start, :window_end)
            """), {"config": cls.config_sha(), "started": EARLY, "window_start": START, "window_end": END})
            connection.execute(text("""
                INSERT INTO vn_air.source_responses (id, run_id, product_id, requested_at, retrieved_at,
                    request_parameters, http_status, media_type, body)
                VALUES ('aaaa1111-1111-1111-1111-111111111111', '11111111-1111-1111-1111-111111111111',
                        'openaq_airgradient_hourly', :measured_requested, :measured_retrieved, '{}', 200,
                        'application/json', '{}'::bytea),
                       ('aaaa4444-4444-4444-4444-444444444444', '11111111-1111-1111-1111-111111111111',
                        'openaq_airgradient_hourly', :measured_requested2, :measured_retrieved2, '{}', 200,
                        'application/json', '{}'::bytea),
                       ('aaaa2222-2222-2222-2222-222222222222', '22222222-2222-2222-2222-222222222222',
                        'open_meteo_weather_forecast', :at, :at, '{}', 200, 'application/json', '{}'::bytea),
                       ('aaaa3333-3333-3333-3333-333333333333', '33333333-3333-3333-3333-333333333333',
                        'open_meteo_era5', :era5_requested, :era5_retrieved, '{}', 200,
                        'application/json', '{}'::bytea)
            """), {"at": EARLY, "era5_requested": T0 + timedelta(hours=2),
                   "era5_retrieved": T0 + timedelta(hours=2),
                   "measured_requested": START + timedelta(hours=48),
                   "measured_retrieved": START + timedelta(hours=49),
                   "measured_requested2": START + timedelta(hours=48),
                   "measured_retrieved2": START + timedelta(hours=49) + timedelta(minutes=1)})
            connection.execute(text("""
                INSERT INTO vn_air.air_quality_observations (sensor_id, product_id, variable_code,
                    canonical_unit, period_start, period_end, revision, response_id, value,
                    quality_status, source_flags, coverage_percent, latitude, longitude,
                    source_metadata, recorded_at)
                VALUES ('openaq_11357424', 'openaq_airgradient_hourly', 'pm2_5', 'ug/m3',
                            :period_start, :period_end, 1, 'aaaa1111-1111-1111-1111-111111111111',
                            9.5, 'accepted', '{}', 100.0, :lat, :lon, '{}', :recorded)
            """), {"period_start": START - timedelta(hours=1), "period_end": START,
                   "lat": location.latitude, "lon": location.longitude,
                   "recorded": START + timedelta(hours=49)})
            for revision, value, quality in ((1, 12.5, "accepted"), (2, None, "invalid")):
                connection.execute(text("""
                    INSERT INTO vn_air.air_quality_observations (sensor_id, product_id, variable_code,
                        canonical_unit, period_start, period_end, revision, response_id, value,
                        quality_status, source_flags, coverage_percent, latitude, longitude,
                        source_metadata, recorded_at)
                    VALUES ('openaq_11357424', 'openaq_airgradient_hourly', 'pm2_5', 'ug/m3',
                            :period_start, :period_end, :revision, :response_id,
                            :value, :quality, '{}', 100.0, :lat, :lon, '{}', :recorded)
                """), {"period_start": START, "period_end": START + timedelta(hours=1),
                       "response_id": "aaaa1111-1111-1111-1111-111111111111" if revision == 1
                                      else "aaaa4444-4444-4444-4444-444444444444",
                       "revision": revision, "value": value, "quality": quality,
                       "lat": location.latitude, "lon": location.longitude,
                       "recorded": START + timedelta(hours=49)
                                   + (timedelta(minutes=1) if revision == 2 else timedelta(0))})
            connection.execute(text("""
                INSERT INTO vn_air.model_snapshots (id, product_id, domain, data_kind, location_id,
                    response_id, model_key, run_initialized_at, source_published_at, run_provenance,
                    requested_latitude, requested_longitude, grid_latitude, grid_longitude, recorded_at)
                VALUES ('bbbb2222-2222-2222-2222-222222222222', 'open_meteo_weather_forecast', 'weather',
                        'forecast', 'cmt8', 'aaaa2222-2222-2222-2222-222222222222', 'best_match',
                        :initialized, :initialized, 'unknown', :lat, :lon, :lat, :lon, :recorded),
                       ('bbbb3333-3333-3333-3333-333333333333', 'open_meteo_era5', 'weather',
                        'reanalysis', 'cmt8', 'aaaa3333-3333-3333-3333-333333333333', 'era5',
                        NULL, NULL, 'reanalysis', :lat, :lon, :lat, :lon, :era5_recorded)
            """), {"initialized": EARLY, "lat": location.latitude, "lon": location.longitude,
                   "recorded": EARLY, "era5_recorded": T0 + timedelta(hours=2)})
            for code, support, unit in (("temperature_2m", "instant", "degC"),
                                        ("precipitation", "preceding_hour_sum", "mm")):
                valid = START + timedelta(hours=1)
                connection.execute(text("""
                    INSERT INTO vn_air.modeled_values (snapshot_id, domain, variable_code, canonical_unit,
                        valid_at, period_start, temporal_support, native_interval_seconds, value,
                        quality_status, source_flags, recorded_at)
                    VALUES ('bbbb2222-2222-2222-2222-222222222222', 'weather', :code, :unit,
                            :valid, :period_start, :support, 3600, :value, 'accepted', '{}', :recorded),
                           ('bbbb3333-3333-3333-3333-333333333333', 'weather', :code, :unit,
                            :valid, :period_start, :support, 3600, :value, 'accepted', '{}', :era5_recorded)
                """), {"code": code, "unit": unit, "valid": valid, "era5_recorded": T0 + timedelta(hours=2),
                       "period_start": valid if support == "instant" else valid - timedelta(hours=1),
                       "support": support, "value": 21.5, "recorded": EARLY})

    def extract(self):
        return extract_features(self.engine, self.config, cutoff=self.cutoff_now(), start=START, end=END)

    def test_extract_is_read_only_and_complete(self):
        before = count_scalar(self.engine, "SELECT count(*) FROM vn_air.air_quality_observations")
        bundle = self.extract()
        after = count_scalar(self.engine, "SELECT count(*) FROM vn_air.air_quality_observations")
        self.assertEqual(before, after)
        self.assertEqual(bundle["manifest"]["input_counts"]["measurements"], 3)
        self.assertEqual(len(bundle["dataset"]["measurements"]), 3)
        self.assertEqual(bundle["manifest"]["history_start"], (START - timedelta(hours=72)).isoformat())
        self.assertEqual(bundle["manifest"]["warmup_hours"], 72)
        warmup = [row for row in bundle["dataset"]["measurements"]
                  if row["period_end"] == START.isoformat()]
        self.assertEqual(len(warmup), 1)
        revisions = sorted(row["revision"] for row in bundle["dataset"]["measurements"]
                           if row["period_end"] == (START + timedelta(hours=1)).isoformat())
        self.assertEqual(revisions, [1, 2])
        self.assertEqual(bundle["manifest"]["schema_revision"], "0003_response_integrity")
        self.assertTrue(bundle["dataset"]["model_values"])
        era5_values = [row for row in bundle["dataset"]["model_values"]
                       if row["snapshot_id"] == "bbbb3333-3333-3333-3333-333333333333"]
        self.assertEqual(era5_values, [])
        self.assertEqual(bundle["manifest"]["excluded_modeled_values_by_product"]["open_meteo_era5"], 2)

    def test_as_of_revisions_are_extracted_before_quality_filtering(self):
        bundle = self.extract()
        hour_rows = [row for row in bundle["dataset"]["measurements"]
                     if row["period_end"] == (START + timedelta(hours=1)).isoformat()]
        by_revision = {row["revision"]: row for row in hour_rows}
        self.assertEqual(by_revision[1]["quality_status"], "accepted")
        self.assertEqual(by_revision[2]["quality_status"], "invalid")
        self.assertEqual(by_revision[2]["value"], None)

    def test_builder_accepts_extracted_bundle_with_reviewed_config(self):
        from vn_air.features import build_features, bundle_file_sha256
        from pathlib import Path as _Path
        import tempfile
        reviewed = self.config.model_dump(mode="json")
        with tempfile.TemporaryDirectory() as directory:
            path = _Path(directory) / "bundle.json"
            bundle = self.extract()
            path.write_text(json.dumps(bundle, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            result = build_features(bundle, _sha(path), horizons=(6, 24), availability_basis="captured",
                                    reviewed=reviewed)
        self.assertEqual(result["manifest"]["status"], "limited_diagnostic")
        self.assertEqual(result["manifest"]["config_validation"]["mode"], "reviewed_config")
        changed = dict(reviewed)
        changed["locations"] = [dict(row, latitude=row["latitude"] + 1.0)
                                if row["kind"] == "station" else row for row in reviewed["locations"]]
        with self.assertRaises(ValueError):
            build_features(bundle, "0" * 64, horizons=(6, 24), availability_basis="captured",
                           reviewed=changed)

    def test_read_only_transaction_rejects_writes(self):
        with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            with connection.begin():
                connection.execute(text("SET TRANSACTION READ ONLY"))
                with self.assertRaises(Exception):
                    connection.execute(text(
                        "INSERT INTO vn_air.data_quality_issues (issue_code, severity, detected_at) "
                        "VALUES ('synthetic', 'info', :at)"), {"at": EARLY})

    def test_configuration_boundary(self):
        import tempfile
        document = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        document["locations"][0]["name"] = "Renamed"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "changed.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(ValueError):
                extract_features(self.engine, load_config(path), cutoff=self.cutoff_now(),
                                 start=START, end=END)

    def test_row_budget_stops_oversize_extracts(self):
        with patch.object(__import__("vn_air.features_store", fromlist=["MAX_ROWS_PER_TABLE"]),
                          "MAX_ROWS_PER_TABLE", 1):
            with self.assertRaises(ValueError):
                self.extract()

    def test_schema_revision_boundary(self):
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM public.vn_air_schema_version"))
        try:
            with self.assertRaises(ValueError):
                self.extract()
        finally:
            with self.engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO public.vn_air_schema_version (version_num) "
                    "VALUES ('0003_response_integrity') ON CONFLICT DO NOTHING"))


if __name__ == "__main__":
    unittest.main()
