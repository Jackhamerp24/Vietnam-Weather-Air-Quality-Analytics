"""Phase 7 feature construction on synthetic bundles; no database and no network."""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from vn_air import features as ft
from vn_air.quality import digest

UTC = timezone.utc
T0 = datetime(2026, 6, 8, tzinfo=UTC)
START = T0
END = T0 + timedelta(hours=96)
CUTOFF = END + timedelta(hours=6)
EARLY = T0 - timedelta(hours=2)
WEATHER_SUPPORT = (("temperature_2m", "instant"), ("apparent_temperature", "instant"),
                   ("relative_humidity_2m", "instant"), ("precipitation", "preceding_hour_sum"),
                   ("surface_pressure", "instant"), ("cloud_cover", "instant"),
                   ("shortwave_radiation", "preceding_hour_mean"), ("wind_speed_10m", "instant"),
                   ("wind_direction_10m", "instant"))
WEATHER_UNITS = {"temperature_2m": "degC", "apparent_temperature": "degC",
                 "relative_humidity_2m": "%", "precipitation": "mm",
                 "surface_pressure": "hPa", "cloud_cover": "%",
                 "shortwave_radiation": "W/m2", "wind_speed_10m": "m/s",
                 "wind_direction_10m": "degree"}
VARIABLES = {code: {"canonical_unit": WEATHER_UNITS[code], "temporal_support": support,
                    "domain": "weather", "representation": "weather", "minimum": None,
                    "maximum": None}
             for code, support in WEATHER_SUPPORT}
VARIABLES["pm2_5"] = {"canonical_unit": "ug/m3", "temporal_support": "instant",
                      "domain": "air_quality", "representation": "concentration",
                      "minimum": 0.0, "maximum": None}
VARIABLES["pm10"] = {"canonical_unit": "ug/m3", "temporal_support": "instant",
                      "domain": "air_quality", "representation": "concentration",
                      "minimum": 0.0, "maximum": None}
WEATHER_CODES = sorted(code for code, meta in VARIABLES.items() if meta["domain"] == "weather")
REVIEWED_STATIONS = {"cmt8": (10.78533, 106.67029), "oceanpark": (20.9933, 105.9441)}
REVIEWED_LOCATIONS = [
    {"id": "hcmc", "name": "HCMC", "kind": "city", "parent_id": None,
     "country_code": "VN", "latitude": 10.82302, "longitude": 106.62965,
     "timezone": "Asia/Ho_Chi_Minh", "provider_timezone": "Asia/Ho_Chi_Minh",
     "geonames_id": 1566083},
    {"id": "hanoi", "name": "Hanoi", "kind": "city", "parent_id": None,
     "country_code": "VN", "latitude": 21.0245, "longitude": 105.84117,
     "timezone": "Asia/Ho_Chi_Minh", "provider_timezone": "Asia/Bangkok",
     "geonames_id": 1581130},
    {"id": "cmt8", "name": "CMT8", "kind": "station", "parent_id": "hcmc",
     "country_code": "VN", "latitude": 10.78533, "longitude": 106.67029,
     "timezone": "Asia/Ho_Chi_Minh", "provider_timezone": "Asia/Ho_Chi_Minh",
     "geonames_id": None},
    {"id": "oceanpark", "name": "OceanPark", "kind": "station", "parent_id": "hanoi",
     "country_code": "VN", "latitude": 20.9933, "longitude": 105.9441,
     "timezone": "Asia/Ho_Chi_Minh", "provider_timezone": "Asia/Ho_Chi_Minh",
     "geonames_id": None},
]
REVIEWED_SENSORS = [
    {"id": "openaq_11357424", "location_id": "cmt8", "product_id": "openaq_airgradient_hourly",
     "external_sensor_id": "11357424", "external_location_id": "3276359",
     "variable_code": "pm2_5", "canonical_unit": "ug/m3", "instrument": "Synthetic",
     "is_reference_monitor": False, "licence_url": "https://creativecommons.org/licenses/by/4.0/",
     "licence_valid_from": "2023-07-15", "licence_valid_to": None,
     "attribution": "Synthetic CMT8", "qualification_notes": "Synthetic test sensor"},
    {"id": "openaq_14581375", "location_id": "oceanpark", "product_id": "openaq_airgradient_hourly",
     "external_sensor_id": "14581375", "external_location_id": "6123215",
     "variable_code": "pm2_5", "canonical_unit": "ug/m3", "instrument": "Synthetic",
     "is_reference_monitor": False, "licence_url": "https://creativecommons.org/licenses/by/4.0/",
     "licence_valid_from": "2023-07-15", "licence_valid_to": None,
     "attribution": "Synthetic OceanPark", "qualification_notes": "Synthetic test sensor"},
]
REVIEWED = {"version": 1,
            "products": [
                {"id": "openaq_airgradient_hourly", "provider": "Synthetic OpenAQ",
                 "domain": "air_quality", "data_kind": "measurement",
                 "endpoint": "https://example.com/openaq", "attribution": "Synthetic",
                 "licence_url": "https://creativecommons.org/licenses/by/4.0/", "options": {}},
                {"id": "open_meteo_weather_forecast", "provider": "Synthetic Open-Meteo",
                 "domain": "weather", "data_kind": "forecast",
                 "endpoint": "https://example.com/weather", "attribution": "Synthetic",
                 "licence_url": "https://creativecommons.org/licenses/by/4.0/",
                 "options": {"models": "ecmwf_ifs"}},
                {"id": "open_meteo_era5", "provider": "Synthetic ERA5",
                 "domain": "weather", "data_kind": "reanalysis",
                 "endpoint": "https://example.com/era5", "attribution": "Synthetic",
                 "licence_url": "https://creativecommons.org/licenses/by/4.0/", "options": {}},
                {"id": "open_meteo_cams_global", "provider": "Synthetic CAMS",
                 "domain": "air_quality", "data_kind": "forecast",
                 "endpoint": "https://example.com/cams", "attribution": "Synthetic",
                 "licence_url": "https://creativecommons.org/licenses/by/4.0/", "options": {}},
            ],
            "variables": [{"code": code, **meta} for code, meta in VARIABLES.items()],
            "locations": REVIEWED_LOCATIONS, "sensors": REVIEWED_SENSORS}
LOCATIONS = {row["id"]: dict(row) for row in REVIEWED_LOCATIONS}
SENSORS = {row["id"]: {**row, "name": LOCATIONS[row["location_id"]]["name"],
                       "timezone": LOCATIONS[row["location_id"]]["timezone"]}
           for row in REVIEWED_SENSORS}
FROZEN = {"FROZEN_START": iso(START), "FROZEN_END": iso(END), "FROZEN_CUTOFF": iso(CUTOFF)} if False else None


def iso(at):
    return at.astimezone(UTC).isoformat()


FROZEN_PATCH = {"FROZEN_START": iso(START), "FROZEN_END": iso(END), "FROZEN_CUTOFF": iso(CUTOFF)}


def frozen():
    return patch.object(ft, "FROZEN_START", iso(START)), patch.object(ft, "FROZEN_END", iso(END)), \
        patch.object(ft, "FROZEN_CUTOFF", iso(CUTOFF))


class FrozenContext:
    """Apply the synthetic frozen window around a block."""

    def __init__(self):
        self.patches = [patch.object(ft, key, value) for key, value in FROZEN_PATCH.items()]

    def __enter__(self):
        for item in self.patches:
            item.start()
        return self

    def __exit__(self, *args):
        for item in self.patches:
            item.stop()
        return False


def synthetic_measurements():
    rows, next_id = [], 1000

    def add(sensor, end, value, *, revision=1, quality="accepted", recorded=EARLY, published=None):
        nonlocal next_id
        next_id += 1
        rows.append({"id": next_id, "sensor_id": sensor, "product_id": "openaq_airgradient_hourly",
                     "variable_code": "pm2_5", "canonical_unit": "ug/m3",
                     "period_start": iso(end - timedelta(hours=1)), "period_end": iso(end),
                     "revision": revision, "value": value, "quality_status": quality,
                     "coverage_percent": 100.0, "source_published_at": iso(published) if published else None,
                     "recorded_at": iso(recorded), "response_id": "resp-meas",
                     "retrieved_at": iso(recorded), "purpose": "backfill"})

    for hour in range(1, 97):
        end = T0 + timedelta(hours=hour)
        add("openaq_11357424", end, 10.0 + hour % 5)
        add("openaq_14581375", end, 20.0 + hour % 7)
    add("openaq_11357424", T0 + timedelta(hours=5), 7.0, revision=2, recorded=T0 - timedelta(hours=1))
    add("openaq_11357424", T0 + timedelta(hours=6), None, revision=2, quality="invalid",
        recorded=T0 - timedelta(hours=1))
    add("openaq_11357424", T0 + timedelta(hours=30), 99.0, revision=2, recorded=T0 + timedelta(hours=50))
    add("openaq_14581375", T0 + timedelta(hours=30), 44.0, revision=2, quality="suspect")
    add("openaq_14581375", T0 + timedelta(hours=31), None, revision=2, quality="missing")
    missing_cmt8 = next(r for r in rows if r["sensor_id"] == "openaq_11357424"
                        and r["period_end"] == iso(T0 + timedelta(hours=10)) and r["revision"] == 1)
    rows.remove(missing_cmt8)
    missing_ocean = next(r for r in rows if r["sensor_id"] == "openaq_14581375"
                         and r["period_end"] == iso(T0 + timedelta(hours=20)) and r["revision"] == 1)
    rows.remove(missing_ocean)
    return rows


def synthetic_snapshot(snapshot_id, location, *, recorded, retrieved, initialized, published,
                       provenance, product="open_meteo_weather_forecast", kind="forecast",
                       model_key="ecmwf_ifs", requested=None, purpose="poll"):
    latitude, longitude = requested or REVIEWED_STATIONS[location]
    domain = "air_quality" if product == "open_meteo_cams_global" else "weather"
    return {"id": snapshot_id, "product_id": product, "domain": domain, "data_kind": kind,
            "location_id": location, "response_id": f"resp-{snapshot_id[:8]}", "model_key": model_key,
            "model_version": "v1", "run_initialized_at": iso(initialized) if initialized else None,
            "source_published_at": iso(published) if published else None, "run_provenance": provenance,
            "requested_latitude": latitude, "requested_longitude": longitude,
            "grid_latitude": 10.0, "grid_longitude": 106.0, "recorded_at": iso(recorded),
            "retrieved_at": iso(retrieved), "http_status": 200, "error_code": None,
            "purpose": purpose, "window_start": iso(START), "window_end": iso(END)}


def synthetic_values(snapshot_id, *, offset=0.0, quality="accepted", recorded=EARLY,
                     valid_hours=range(1, 97), specifications=WEATHER_SUPPORT):
    rows, next_id = [], 5000
    for hour in valid_hours:
        valid = T0 + timedelta(hours=hour)
        for code, support in specifications:
            next_id += 1
            rows.append({"id": next_id, "snapshot_id": snapshot_id, "domain": VARIABLES[code]["domain"],
                         "variable_code": code, "canonical_unit": VARIABLES[code]["canonical_unit"],
                         "valid_at": iso(valid),
                         "period_start": iso(valid - timedelta(hours=1)) if support != "instant" else iso(valid),
                         "temporal_support": support, "native_interval_seconds": 3600,
                         "value": None if quality == "missing" else (25.0 + offset + hour % 3
                                                                     if code != "wind_direction_10m" else 90.0),
                         "quality_status": quality, "recorded_at": iso(recorded)})
    return rows


def prestart_measurements():
    rows, next_id = [], 7000
    for offset in range(-72, 1):
        next_id += 1
        end = T0 + timedelta(hours=offset)
        rows.append({"id": next_id, "sensor_id": "openaq_11357424", "product_id": "openaq_airgradient_hourly",
                     "variable_code": "pm2_5", "canonical_unit": "ug/m3",
                     "period_start": iso(end - timedelta(hours=1)), "period_end": iso(end),
                     "revision": 1, "value": 50.0 + offset % 9, "quality_status": "accepted",
                     "coverage_percent": 100.0, "source_published_at": None,
                     "recorded_at": iso(EARLY), "response_id": "resp-meas",
                     "retrieved_at": iso(EARLY), "purpose": "backfill"})
    return rows


def signed_bundle(bundle, reviewed=REVIEWED):
    bundle = json.loads(json.dumps(bundle))
    locations = {row["id"]: row for row in reviewed["locations"]}
    bundle["dataset"]["locations"] = locations
    bundle["dataset"]["variables"] = {
        row["code"]: {key: row.get(key) for key in
                       ("canonical_unit", "domain", "representation", "temporal_support", "minimum", "maximum")}
        for row in reviewed["variables"]
    }
    bundle["dataset"]["sensors"] = {
        row["id"]: {**row, "name": locations[row["location_id"]]["name"],
                    "timezone": locations[row["location_id"]]["timezone"]}
        for row in reviewed["sensors"]
    }
    for row in bundle["dataset"]["measurements"]:
        sensor = bundle["dataset"]["sensors"][row["sensor_id"]]
        row.update(product_id=sensor["product_id"], variable_code=sensor["variable_code"],
                   canonical_unit=sensor["canonical_unit"])
    for row in bundle["dataset"]["model_values"]:
        variable = bundle["dataset"]["variables"].get(row["variable_code"])
        if variable is not None:
            row.update(domain=variable["domain"], canonical_unit=variable["canonical_unit"],
                       temporal_support=variable["temporal_support"])
    bundle["manifest"]["configuration_sha256"] = digest(reviewed)
    return resign(bundle)


def shifted_bundle():
    bundle = json.loads(json.dumps(synthetic_bundle()))
    shift = timedelta(days=30)
    bundle["manifest"]["start"] = iso(START + shift)
    bundle["manifest"]["end"] = iso(END + shift)
    bundle["manifest"]["cutoff"] = iso(CUTOFF + shift)
    return resign(bundle)


def variant_bundle(*, measurements=True, snapshots=True, pm_quality=None, weather_quality=None):
    bundle = json.loads(json.dumps(synthetic_bundle()))
    if not measurements:
        bundle["dataset"]["measurements"] = []
    if not snapshots:
        bundle["dataset"]["snapshots"] = []
        bundle["dataset"]["model_values"] = []
    if pm_quality:
        for row in bundle["dataset"]["measurements"]:
            row["quality_status"] = pm_quality
            if pm_quality in ("missing", "invalid"):
                row["value"] = None
    if weather_quality:
        for row in bundle["dataset"]["model_values"]:
            row["quality_status"] = weather_quality
            if weather_quality in ("missing", "invalid"):
                row["value"] = None
    return resign(bundle)


def resign(bundle):
    """Recompute declared table hashes, counts and the outer bundle digest."""
    dataset = bundle["dataset"]
    bundle["manifest"]["input_sha256"] = {key: digest(dataset[key])
                                          for key in ("measurements", "snapshots", "model_values")}
    bundle["manifest"]["input_counts"] = {key: len(dataset[key])
                                          for key in ("measurements", "snapshots", "model_values")}
    bundle["bundle_sha256"] = digest({k: v for k, v in bundle.items() if k != "bundle_sha256"})
    return bundle


def synthetic_bundle():
    snapshots = [
        synthetic_snapshot("snapA-operational", "cmt8", recorded=T0 - timedelta(hours=2),
                           retrieved=T0 - timedelta(hours=2), initialized=T0 - timedelta(hours=3),
                           published=T0 - timedelta(hours=3), provenance="operational"),
        synthetic_snapshot("snapB-operational", "cmt8", recorded=T0 - timedelta(hours=1),
                           retrieved=T0 - timedelta(hours=1), initialized=T0 - timedelta(hours=1, minutes=30),
                           published=T0 - timedelta(hours=1, minutes=30), provenance="operational"),
        synthetic_snapshot("snapC-late-values", "cmt8", recorded=T0 + timedelta(hours=5),
                           retrieved=T0 + timedelta(hours=5), initialized=T0 + timedelta(hours=5),
                           published=T0 + timedelta(hours=5), provenance="operational"),
        synthetic_snapshot("snapD-oceanpark-unknown", "oceanpark", recorded=T0 - timedelta(hours=2),
                           retrieved=T0 - timedelta(hours=2), initialized=None, published=None,
                           provenance="unknown"),
        synthetic_snapshot("snapE-era5", "cmt8", recorded=T0 - timedelta(hours=2),
                           retrieved=T0 - timedelta(hours=2), initialized=None, published=None,
                           provenance="reanalysis", product="open_meteo_era5", kind="reanalysis"),
        synthetic_snapshot("snapF-cams", "cmt8", recorded=T0 - timedelta(hours=2),
                           retrieved=T0 - timedelta(hours=2), initialized=None, published=None,
                           provenance="reanalysis", product="open_meteo_cams_global", kind="forecast"),
    ]
    values = synthetic_values("snapA-operational", offset=0.0)
    values += synthetic_values("snapB-operational", offset=1.0)
    values += synthetic_values("snapC-late-values", offset=2.0, recorded=T0 + timedelta(hours=30))
    values += synthetic_values("snapD-oceanpark-unknown", offset=3.0, valid_hours=range(1, 40))
    values += synthetic_values("snapE-era5", offset=500.0)
    values += synthetic_values("snapF-cams", offset=800.0, specifications=(("pm10", "instant"),))
    for row in values:
        if row["snapshot_id"] == "snapC-late-values" and row["variable_code"] == "temperature_2m" \
                and row["valid_at"] == iso(T0 + timedelta(hours=50)):
            row["quality_status"], row["value"] = "missing", None
    dataset = {"sensors": SENSORS, "locations": LOCATIONS, "variables": VARIABLES,
               "measurements": synthetic_measurements(),
               "snapshots": snapshots, "model_values": values}
    manifest = {"extract_version": "phase7_extract_v2", "cutoff": iso(CUTOFF), "start": iso(START),
                "end": iso(END), "history_start": iso(START - timedelta(hours=72)), "warmup_hours": 72,
                "configuration_sha256": "0" * 64, "schema_revision": "0003_response_integrity",
                "query_sha256": "0" * 64, "implementation_sha256": {}, "input_sha256": {},
                "input_counts": {"measurements": len(dataset["measurements"]),
                                 "snapshots": len(snapshots), "model_values": len(values)},
                "excluded_modeled_values_by_product": {"open_meteo_cams_global": 864, "open_meteo_era5": 864},
                "policy": {}, "extraction": {"read_only": True}}
    return resign(json.loads(json.dumps({"manifest": manifest, "dataset": dataset}, sort_keys=True)))


def build(bundle, *, horizons=(6, 24), basis="captured", lag=None, reviewed=None,
          require_frozen_boundary=False):
    with FrozenContext():
        return ft.build_features(bundle, "0" * 64, horizons=horizons, availability_basis=basis,
                                 assumed_lag_hours=lag, reviewed=reviewed,
                                 require_frozen_boundary=require_frozen_boundary)


def row_for(result, sensor, origin_offset, horizon):
    origin = T0 + timedelta(hours=origin_offset)
    return next(row for row in result["rows"] if row["sensor_id"] == sensor
                and row["origin"] == iso(origin) and row["horizon_hours"] == horizon)


class RequestValidationTests(unittest.TestCase):
    def test_horizons_must_be_declared_values(self):
        with self.assertRaises(ft.FeatureError):
            ft.validate_request((12,), "captured", None)
        with self.assertRaises(ft.FeatureError):
            ft.validate_request((), "captured", None)

    def test_captured_forbids_lag_and_assumed_requires_it(self):
        with self.assertRaises(ft.FeatureError):
            ft.validate_request((6,), "captured", 6)
        with self.assertRaises(ft.FeatureError):
            ft.validate_request((6,), "assumed", None)
        with self.assertRaises(ft.FeatureError):
            ft.validate_request((6,), "assumed", 0)
        self.assertEqual(ft.validate_request((24, 6), "assumed", 6.0), [6, 24])

    def test_grid_and_split_stop_on_tiny_windows(self):
        with self.assertRaises(ft.FeatureError):
            ft.origin_grid(START, START + timedelta(hours=3), (24,))
        with self.assertRaises(ft.FeatureError):
            ft.split_boundaries([START + timedelta(hours=hour) for hour in range(8)])


class TargetAndContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(synthetic_bundle())

    def test_target_alignment_contract(self):
        for row in self.result["rows"][:60]:
            end, start, origin = (ft.instant(row["target_end"]), ft.instant(row["target_start"]),
                                  ft.instant(row["origin"]))
            self.assertEqual(end - origin, timedelta(hours=row["horizon_hours"]))
            self.assertEqual(end - start, timedelta(hours=1))
            self.assertEqual(origin.timestamp() % 3600, 0)

    def test_targets_are_separate_from_features(self):
        feature_row = self.result["rows"][0]
        self.assertNotIn("target_pm25", feature_row)
        self.assertFalse(any("target_pm25" in key for key in feature_row))
        self.assertTrue(all("target_pm25" in target for target in self.result["targets"]))

    def test_eventual_target_lookup_and_reasons(self):
        targets = {(target["sensor_id"], target["target_end"], target["horizon_hours"]): target
                   for target in self.result["targets"]}
        good = targets[("openaq_11357424", iso(T0 + timedelta(hours=7)), 6)]
        self.assertTrue(good["target_available"])
        self.assertEqual(good["target_pm25"], 10.0 + 7 % 5)
        self.assertEqual(good["target_revision"], 1)
        invalid = targets[("openaq_11357424", iso(T0 + timedelta(hours=6)), 6)]
        self.assertFalse(invalid["target_available"])
        self.assertEqual(invalid["target_missing_reason"], "target_not_accepted_invalid")
        self.assertIsNone(invalid["target_pm25"])
        absent = targets[("openaq_14581375", iso(T0 + timedelta(hours=20)), 6)]
        self.assertEqual(absent["target_missing_reason"], "target_absent")


class RevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(synthetic_bundle())

    def test_latest_revision_wins_before_quality(self):
        row = row_for(self.result, "openaq_11357424", 8, 6)
        self.assertEqual(row["pm25_lag_3h"], 7.0)

    def test_later_invalid_revision_prevents_resurrection(self):
        row = row_for(self.result, "openaq_11357424", 7, 6)
        self.assertIsNone(row["pm25_lag_1h"])
        self.assertEqual(row["pm25_trailing_count_3h"], 2)
        self.assertIsNone(row["pm25_trailing_mean_3h"])

    def test_row_order_cannot_create_a_false_lag(self):
        shuffled = json.loads(json.dumps(synthetic_bundle()))
        shuffled["dataset"]["measurements"] = list(reversed(shuffled["dataset"]["measurements"]))
        shuffled = resign(shuffled)
        self.assertEqual(comparable(build(shuffled)), comparable(self.result))


def comparable(result):
    manifest = {key: value for key, value in result["manifest"].items()
                if key not in ("bundle_sha256", "bundle_file_sha256", "input_manifest_sha256",
                               "input_integrity")}
    rows = [{k: v for k, v in row.items() if k != "input_manifest_sha256"} for row in result["rows"]]
    return digest({"manifest": manifest, "rows": rows, "targets": result["targets"],
                   "lineage": result["lineage"]})


class AvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(synthetic_bundle())

    def test_captured_never_uses_a_later_backfill(self):
        early = row_for(self.result, "openaq_11357424", 42, 6)
        self.assertEqual(early["pm25_lag_12h"], 10.0)
        self.assertEqual(early["pm25_lag_24h"], 10.0 + 18 % 5)
        late = row_for(self.result, "openaq_11357424", 54, 6)
        self.assertEqual(late["pm25_lag_24h"], 99.0)

    def test_captured_forecast_vintage_gate_and_value_level_evidence(self):
        row = row_for(self.result, "openaq_11357424", 0, 6)
        self.assertEqual(row["weather_forecast_snapshot_id"], "snapB-operational")
        gated = row_for(self.result, "openaq_11357424", 7, 6)
        self.assertEqual(gated["weather_forecast_snapshot_id"], "snapC-late-values")
        self.assertIsNone(gated["weather_forecast_temperature_2m"])
        self.assertEqual(gated["weather_forecast_reason"], "values_missing_or_not_accepted")
        opened = row_for(self.result, "openaq_11357424", 40, 6)
        self.assertEqual(opened["weather_forecast_snapshot_id"], "snapC-late-values")
        self.assertIsNotNone(opened["weather_forecast_temperature_2m"])

    def test_assumed_mode_uses_declared_lag_on_event_time(self):
        result = build(synthetic_bundle(), basis="assumed", lag=6)
        self.assertEqual(result["manifest"]["availability_basis"], "assumed")
        self.assertEqual(result["manifest"]["availability_assumption"], 6)
        gated = row_for(result, "openaq_11357424", 11, 6)
        self.assertIsNone(gated["pm25_lag_6h"])
        available = row_for(result, "openaq_11357424", 17, 6)
        self.assertEqual(available["pm25_lag_12h"], 7.0)
        later = row_for(result, "openaq_11357424", 16, 6)
        self.assertIsNone(later["pm25_lag_1h"])
        self.assertEqual(later["pm25_lag_12h"], 10.0 + 4 % 5)
        self.assertGreater(result["manifest"]["counts"]["pm_available_origin_count"], 0)

    def test_assumed_rejects_unknown_initialization(self):
        result = build(synthetic_bundle(), basis="assumed", lag=6)
        self.assertGreater(result["manifest"]["ambiguous_vintage_rejections"], 0)
        row = row_for(result, "openaq_14581375", 30, 6)
        self.assertIsNone(row["weather_forecast_snapshot_id"])

    def test_leakage_guards_stop_future_evidence(self):
        assumed_lineage = {"pm_available_through": iso(T0 + timedelta(hours=10)),
                           "weather_run_initialized_at": None}
        with self.assertRaises(ft.FeatureError):
            ft._check_leakage(assumed_lineage, T0 + timedelta(hours=15), "assumed", 6)
        ft._check_leakage(assumed_lineage, T0 + timedelta(hours=17), "assumed", 6)
        captured_lineage = {"pm_max_recorded_at": iso(T0 + timedelta(hours=10)),
                            "pm_max_retrieved_at": None, "weather_max_recorded_at": None,
                            "weather_max_retrieved_at": None, "weather_run_initialized_at": None,
                            "weather_source_published_at": None}
        with self.assertRaises(ft.FeatureError):
            ft._check_leakage(captured_lineage, T0 + timedelta(hours=10), "captured", None)
        ft._check_leakage(captured_lineage, T0 + timedelta(hours=11), "captured", None)


class SourceSeparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(synthetic_bundle())

    def test_era5_and_cams_never_enter_the_matrix(self):
        for row in self.result["rows"]:
            for key, value in row.items():
                if key.startswith("weather_forecast_") and isinstance(value, float):
                    self.assertNotIn(round(value, 6), (525.0, 526.0, 527.0))
                    self.assertNotIn(round(value, 6), (825.0, 826.0, 827.0))
        self.assertEqual(self.result["manifest"]["counts"]["weather_alignment_rejected"] >= 0, True)

    def test_forecast_lineage_is_retained(self):
        lineage = {item["lineage_id"]: item for item in self.result["lineage"]}
        item = lineage[f"openaq_11357424|{iso(T0 + timedelta(hours=1))}|6"]
        self.assertEqual(item["weather_snapshot_id"], "snapB-operational")
        self.assertEqual(item["weather_run_provenance"], "operational")
        self.assertTrue(json.loads(item["weather_model_value_ids"]))
        self.assertEqual(item["availability_basis"], "captured")


class VintageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(synthetic_bundle())

    def test_one_deterministic_vintage_by_documented_ranking(self):
        self.assertEqual(row_for(self.result, "openaq_11357424", 0, 6)["weather_forecast_snapshot_id"],
                         "snapB-operational")
        self.assertEqual(row_for(self.result, "openaq_11357424", 40, 6)["weather_forecast_snapshot_id"],
                         "snapC-late-values")

    def test_overlapping_vintages_are_never_averaged(self):
        for offset, snapshot, base in ((1, "snapB-operational", 26.0), (40, "snapC-late-values", 27.0)):
            row = row_for(self.result, "openaq_11357424", offset, 6)
            self.assertEqual(row["weather_forecast_snapshot_id"], snapshot)
            values = [value for key, value in row.items() if key.startswith("weather_forecast_")
                      and isinstance(value, float)
                      and key not in ("weather_forecast_wind_direction_sin",
                                      "weather_forecast_wind_direction_cos")]
            self.assertTrue(values)
            for value in values:
                self.assertIn(round(value, 6), (base, base + 1.0, base + 2.0))
                self.assertNotIn(round(value, 6), (base + 0.5, base + 1.5))


class TemporalSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = synthetic_bundle()
        cls.result = build(cls.bundle)

    def test_instant_and_preceding_join_at_the_declared_boundaries(self):
        row = row_for(self.result, "openaq_11357424", 1, 6)
        expected_valid = T0 + timedelta(hours=6)
        expected_end = T0 + timedelta(hours=7)
        instant_value = next(v["value"] for v in self.bundle["dataset"]["model_values"]
                             if v["snapshot_id"] == "snapB-operational" and v["variable_code"] == "temperature_2m"
                             and v["valid_at"] == iso(expected_valid))
        self.assertEqual(row["weather_forecast_temperature_2m"], instant_value)
        preceding_value = next(v["value"] for v in self.bundle["dataset"]["model_values"]
                               if v["snapshot_id"] == "snapB-operational" and v["variable_code"] == "precipitation"
                               and v["valid_at"] == iso(expected_end))
        self.assertEqual(row["weather_forecast_precipitation"], preceding_value)

    def test_wrong_temporal_support_is_rejected(self):
        bundle = json.loads(json.dumps(self.bundle))
        for value in bundle["dataset"]["model_values"]:
            if value["snapshot_id"] == "snapC-late-values" and value["variable_code"] == "temperature_2m" \
                    and value["valid_at"] == iso(T0 + timedelta(hours=51)):
                value["temporal_support"] = "preceding_hour_mean"
        with self.assertRaises(ft.FeatureError):
            build(resign(bundle))

    def test_missing_values_are_reported_not_filled(self):
        row = row_for(self.result, "openaq_11357424", 45, 6)
        self.assertIsNone(row["weather_forecast_temperature_2m"])
        self.assertEqual(row["weather_forecast_reason"], "values_missing_or_not_accepted")
        self.assertGreater(self.result["manifest"]["counts"]["weather_missing_values"], 0)


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(synthetic_bundle())

    def test_exact_lags_do_not_bridge_gaps_and_age_is_exposed(self):
        gap = row_for(self.result, "openaq_11357424", 11, 6)
        self.assertIsNone(gap["pm25_lag_1h"])
        self.assertEqual(gap["pm25_lag_3h"], 10.0 + 8 % 5)
        stale = row_for(self.result, "openaq_11357424", 10, 6)
        self.assertEqual(stale["pm25_last_available"], 10.0 + 9 % 5)
        self.assertAlmostEqual(stale["pm25_last_age_hours"], 1.0)
        self.assertEqual(gap["pm_history_reason"], "ok")

    def test_strict_trailing_windows_require_every_expected_hour(self):
        row = row_for(self.result, "openaq_11357424", 11, 6)
        self.assertEqual(row["pm25_trailing_count_3h"], 2)
        self.assertIsNone(row["pm25_trailing_mean_3h"])
        complete = row_for(self.result, "openaq_11357424", 16, 6)
        self.assertEqual(complete["pm25_trailing_count_3h"], 3)
        self.assertAlmostEqual(complete["pm25_trailing_mean_3h"],
                               (10.0 + 14 % 5 + 10.0 + 15 % 5 + 10.0 + 16 % 5) / 3)

    def test_without_eligible_values_features_stay_null(self):
        trimmed = json.loads(json.dumps(synthetic_bundle()))
        trimmed["dataset"]["measurements"] = [item for item in trimmed["dataset"]["measurements"]
                                              if item["sensor_id"] == "openaq_14581375"]
        trimmed = resign(trimmed)
        result = build(trimmed)
        row = row_for(result, "openaq_11357424", 10, 6)
        self.assertIsNone(row["pm25_last_available"])
        self.assertIsNone(row["pm25_last_age_hours"])
        self.assertEqual(row["pm_history_reason"], "no_eligible_accepted_values")


class WindEncodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(synthetic_bundle())

    def test_sine_cosine_encoding(self):
        row = row_for(self.result, "openaq_11357424", 1, 6)
        self.assertAlmostEqual(row["weather_forecast_wind_direction_sin"], 1.0, places=9)
        self.assertAlmostEqual(row["weather_forecast_wind_direction_cos"], 0.0, places=9)

    def test_raw_direction_is_absent(self):
        self.assertFalse(any("weather_forecast_wind_direction_10m" in row for row in self.result["rows"]))


class IsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(synthetic_bundle())

    def test_sensor_values_do_not_cross_sensors(self):
        cmt8 = row_for(self.result, "openaq_11357424", 16, 6)
        oceanpark = row_for(self.result, "openaq_14581375", 16, 6)
        self.assertNotEqual(cmt8["pm25_lag_1h"], oceanpark["pm25_lag_1h"])
        self.assertNotEqual(cmt8["weather_forecast_temperature_2m"],
                            oceanpark["weather_forecast_temperature_2m"])

    def test_lineage_and_rows_stay_aligned_and_target_free(self):
        self.assertEqual(len(self.result["rows"]), len(self.result["lineage"]))
        for row, item in zip(self.result["rows"], self.result["lineage"]):
            self.assertEqual(row["lineage_id"], item["lineage_id"])
            origin = ft.instant(row["origin"])
            if row["availability_basis"] == "captured":
                stamps = [ft.instant(item[key]) for key in
                          ("pm_max_recorded_at", "pm_max_retrieved_at", "weather_max_recorded_at",
                           "weather_max_retrieved_at", "weather_run_initialized_at",
                           "weather_source_published_at") if item.get(key)]
                self.assertTrue(all(stamp < origin for stamp in stamps))


class SplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(synthetic_bundle())

    def test_shared_boundaries_across_sensors_and_horizons(self):
        manifest = self.result["manifest"]
        self.assertTrue(manifest["split"]["shared_across_sensors_and_horizons"])
        self.assertEqual(ft.instant(manifest["split"]["validation_start"]), T0 + timedelta(hours=43))
        self.assertEqual(ft.instant(manifest["split"]["test_start"]), T0 + timedelta(hours=58))

    def test_horizon_overlap_is_purged_and_test_untouched(self):
        counts = self.result["manifest"]["counts"]
        self.assertGreater(counts["purged_rows"], 0)
        self.assertGreater(counts["purge_reasons"].get("target_reaches_validation", 0), 0)
        long_purged = row_for(self.result, "openaq_11357424", 30, 24)
        self.assertEqual(long_purged["purge_reason"], "target_reaches_validation")
        short_train = row_for(self.result, "openaq_11357424", 30, 6)
        self.assertEqual(short_train["split"], "train")
        self.assertFalse(short_train["purged"])
        validation_purged = row_for(self.result, "openaq_11357424", 45, 24)
        self.assertEqual(validation_purged["purge_reason"], "target_reaches_test")
        for row in self.result["rows"]:
            if row["split"] == "test":
                self.assertFalse(row["purged"])


class DeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = synthetic_bundle()
        cls.result = build(cls.bundle)

    def test_same_inputs_produce_identical_results(self):
        self.assertEqual(digest(build(self.bundle)), digest(self.result))

    def test_tampered_bundle_is_rejected(self):
        tampered = json.loads(json.dumps(self.bundle))
        tampered["dataset"]["measurements"][0]["value"] = 777.0
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            with FrozenContext(), self.assertRaises(ft.FeatureError):
                ft.load_bundle(path)

    def test_existing_output_directory_is_rejected(self):
        from vn_air.features_output import write_outputs
        with TemporaryDirectory() as directory:
            parent = Path(directory)
            first = write_outputs(parent / "out", self.result)
            self.assertEqual(first["file_count"], 6)
            with self.assertRaises(ValueError):
                write_outputs(parent / "out", self.result)




class BoundaryModeTests(unittest.TestCase):
    def test_frozen_flag_accepts_the_frozen_window(self):
        result = build(synthetic_bundle(), require_frozen_boundary=True)
        self.assertEqual(result["manifest"]["boundary"]["mode"], "frozen")
        self.assertTrue(result["manifest"]["boundary"]["frozen_boundary_applied"])

    def test_shifted_window_succeeds_without_the_flag(self):
        result = build(shifted_bundle())
        self.assertEqual(result["manifest"]["boundary"]["mode"], "explicit")
        self.assertFalse(result["manifest"]["boundary"]["frozen_boundary_applied"])
        self.assertEqual(result["manifest"]["origin_start"], iso(START + timedelta(days=30)))

    def test_shifted_window_is_rejected_with_the_flag(self):
        with self.assertRaises(ft.FeatureError):
            build(shifted_bundle(), require_frozen_boundary=True)

    def test_invalid_boundaries_still_stop_the_build(self):
        bundle = shifted_bundle()
        bundle["manifest"]["start"] = iso(START + timedelta(days=30, minutes=30))
        bundle = resign(bundle)
        with self.assertRaises(ValueError):
            build(bundle)

    def test_boundary_mode_is_recorded(self):
        self.assertEqual(build(synthetic_bundle())["manifest"]["boundary"]["mode"], "explicit")


class WarmupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = synthetic_bundle()
        cls.bundle["dataset"]["measurements"] += prestart_measurements()
        cls.bundle = resign(cls.bundle)
        cls.result = build(cls.bundle)

    def test_lag72_populated_at_first_origin(self):
        row = row_for(self.result, "openaq_11357424", 0, 6)
        self.assertEqual(row["pm25_lag_72h"], 50.0 + (-72) % 9)
        self.assertTrue(row["pm_full_lag_coverage"])
        self.assertEqual(self.result["manifest"]["warmup_hours"], 72)
        self.assertEqual(self.result["manifest"]["history_start"], iso(START - timedelta(hours=72)))

    def test_lag72_null_without_warmup_rows(self):
        result = build(synthetic_bundle())
        row = row_for(result, "openaq_11357424", 0, 6)
        self.assertIsNone(row["pm25_lag_72h"])
        self.assertFalse(row["pm_full_lag_coverage"])

    def test_trailing_windows_use_exact_timestamps_at_first_origin(self):
        row = row_for(self.result, "openaq_11357424", 0, 6)
        self.assertEqual(row["pm25_trailing_count_3h"], 3)
        self.assertAlmostEqual(row["pm25_trailing_mean_3h"],
                               (50.0 + (-2) % 9 + 50.0 + (-1) % 9 + 50.0 + 0) / 3)

    def test_first_origin_and_targets_unchanged(self):
        self.assertEqual(self.result["manifest"]["origin_start"], iso(START))
        self.assertTrue(all(ft.instant(target["target_end"]) >= START + timedelta(hours=1)
                            for target in self.result["targets"]))
        self.assertEqual(self.result["manifest"]["warmup_selected_rows_by_sensor"]["openaq_11357424"], 72)


class AssumedForecastValueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = synthetic_bundle()

    def test_assumed_includes_late_recorded_values_by_event_time(self):
        result = build(self.bundle, basis="assumed", lag=2)
        row = row_for(result, "openaq_11357424", 9, 6)
        self.assertEqual(row["weather_forecast_snapshot_id"], "snapC-late-values")
        self.assertEqual(row["weather_forecast_temperature_2m"], 25.0 + 2.0 + 14 % 3)
        self.assertEqual(row["availability_basis"], "assumed")
        lineage = next(item for item in result["lineage"] if item["lineage_id"] == row["lineage_id"])
        records = json.loads(lineage["weather_values"])
        self.assertTrue(records)
        self.assertEqual(records[0]["availability_basis"], "assumed")
        self.assertEqual(records[0]["value_recorded_at"], iso(T0 + timedelta(hours=30)))
        self.assertEqual(records[0]["snapshot_id"], "snapC-late-values")

    def test_captured_excludes_the_same_values(self):
        result = build(self.bundle)
        row = row_for(result, "openaq_11357424", 9, 6)
        self.assertEqual(row["weather_forecast_snapshot_id"], "snapC-late-values")
        self.assertIsNone(row["weather_forecast_temperature_2m"])
        self.assertEqual(row["weather_forecast_reason"], "values_missing_or_not_accepted")

    def test_lineage_carries_required_fields(self):
        result = build(self.bundle, basis="assumed", lag=2)
        lineage = next(item for item in result["lineage"]
                       if item["weather_values"] and item["sensor_id"] == "openaq_11357424")
        record = json.loads(lineage["weather_values"])[0]
        for key in ("feature_names", "value_id", "variable_code", "valid_at", "period_start",
                    "temporal_support", "quality_status", "value_recorded_at", "snapshot_id",
                    "product_id", "data_kind", "model_key", "model_version", "requested_latitude",
                    "requested_longitude", "grid_latitude", "grid_longitude", "response_id",
                    "response_retrieved_at", "snapshot_recorded_at", "run_initialized_at",
                    "source_published_at", "availability_basis"):
            self.assertIn(key, record)
        self.assertNotIn("target_pm25", lineage)


class VintageIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.signed = signed_bundle(synthetic_bundle())
        cls.result = build(cls.signed, reviewed=REVIEWED)

    def test_reviewed_config_validates(self):
        self.assertEqual(self.result["manifest"]["config_validation"]["mode"], "reviewed_config")
        self.assertEqual(self.result["manifest"]["config_validation"]["forecast_model_key"], "ecmwf_ifs")
        self.assertTrue(self.result["manifest"]["config_validation"]["variable_registry_verified"])
        self.assertTrue(self.result["manifest"]["config_validation"]["sensor_registry_verified"])
        self.assertTrue(self.result["manifest"]["config_validation"]["location_registry_verified"])

    def test_wrong_model_key_is_rejected_and_ranking_falls_back(self):
        bundle = json.loads(json.dumps(self.signed))
        for snapshot in bundle["dataset"]["snapshots"]:
            if snapshot["id"] == "snapB-operational":
                snapshot["model_key"] = "gfs_graphql"
        bundle = resign(bundle)
        result = build(bundle, reviewed=REVIEWED)
        self.assertEqual(result["manifest"]["snapshot_rejections"].get("snapB-operational"), "model_key")
        row = row_for(result, "openaq_11357424", 1, 6)
        self.assertEqual(row["weather_forecast_snapshot_id"], "snapA-operational")

    def test_wrong_purpose_is_rejected(self):
        bundle = json.loads(json.dumps(self.signed))
        for snapshot in bundle["dataset"]["snapshots"]:
            if snapshot["id"] == "snapB-operational":
                snapshot["purpose"] = "backfill"
        bundle = resign(bundle)
        result = build(bundle, reviewed=REVIEWED)
        self.assertEqual(result["manifest"]["snapshot_rejections"].get("snapB-operational"), "purpose")

    def test_requested_coordinate_mismatch_is_rejected(self):
        bundle = json.loads(json.dumps(self.signed))
        for snapshot in bundle["dataset"]["snapshots"]:
            if snapshot["id"] == "snapB-operational":
                snapshot["requested_latitude"] = 11.0
        bundle = resign(bundle)
        result = build(bundle, reviewed=REVIEWED)
        self.assertEqual(result["manifest"]["snapshot_rejections"].get("snapB-operational"), "coordinates")

    def test_unconfigured_snapshot_location_is_rejected(self):
        bundle = json.loads(json.dumps(self.signed))
        bundle["dataset"]["snapshots"][0]["location_id"] = "atlantis"
        bundle = resign(bundle)
        result = build(bundle, reviewed=REVIEWED)
        self.assertEqual(result["manifest"]["snapshot_rejections"].get("snapA-operational"), "location")
        self.assertFalse(any(row["weather_forecast_snapshot_id"] == "snapA-operational"
                             for row in result["rows"]))

    def test_city_location_snapshot_is_never_selected(self):
        bundle = json.loads(json.dumps(self.signed))
        bundle["dataset"]["snapshots"].append(
            synthetic_snapshot("snapG-city", "hcmc", recorded=T0 - timedelta(hours=1),
                               retrieved=T0 - timedelta(hours=1), initialized=T0 - timedelta(hours=1),
                               published=T0 - timedelta(hours=1), provenance="operational",
                               requested=(10.5, 106.5)))
        bundle = resign(bundle)
        result = build(bundle, reviewed=REVIEWED)
        self.assertEqual(result["manifest"]["snapshot_rejections"].get("snapG-city"), "location")
        self.assertFalse(any(row["weather_forecast_snapshot_id"] == "snapG-city"
                             for row in result["rows"]))

    def test_config_digest_mismatch_rejects(self):
        with self.assertRaises(ft.FeatureError):
            build(synthetic_bundle(), reviewed=REVIEWED)

    def assert_registry_rejects(self, mutate):
        bundle = json.loads(json.dumps(self.signed))
        mutate(bundle)
        with self.assertRaises(ft.FeatureError):
            build(resign(bundle), reviewed=REVIEWED)

    def test_variable_temporal_support_mutation_is_rejected(self):
        self.assert_registry_rejects(
            lambda bundle: bundle["dataset"]["variables"]["temperature_2m"].update(
                temporal_support="preceding_hour_mean"))

    def test_variable_canonical_unit_mutation_is_rejected(self):
        self.assert_registry_rejects(
            lambda bundle: bundle["dataset"]["variables"]["temperature_2m"].update(
                canonical_unit="wrong"))

    def test_variable_domain_mutation_is_rejected(self):
        self.assert_registry_rejects(
            lambda bundle: bundle["dataset"]["variables"]["temperature_2m"].update(
                domain="air_quality", representation="concentration"))

    def test_added_and_removed_variables_are_rejected(self):
        def add(bundle):
            bundle["dataset"]["variables"]["extra_weather"] = {
                "canonical_unit": "unit", "domain": "weather", "representation": "weather",
                "temporal_support": "instant", "minimum": None, "maximum": None}
        self.assert_registry_rejects(add)

        def remove(bundle):
            del bundle["dataset"]["variables"]["temperature_2m"]
        self.assert_registry_rejects(remove)

    def test_sensor_identity_mutations_are_rejected(self):
        self.assert_registry_rejects(
            lambda bundle: bundle["dataset"]["sensors"]["openaq_11357424"].update(
                product_id="wrong_product"))
        self.assert_registry_rejects(
            lambda bundle: bundle["dataset"]["sensors"]["openaq_11357424"].update(
                location_id="oceanpark"))
        self.assert_registry_rejects(
            lambda bundle: bundle["dataset"]["locations"]["cmt8"].update(latitude=11.0))
        self.assert_registry_rejects(
            lambda bundle: bundle["dataset"]["locations"]["cmt8"].update(timezone="UTC"))

    def test_sensor_derived_metadata_mutations_are_rejected(self):
        self.assert_registry_rejects(
            lambda bundle: bundle["dataset"]["sensors"]["openaq_11357424"].update(
                timezone="UTC"))
        self.assert_registry_rejects(
            lambda bundle: bundle["dataset"]["sensors"]["openaq_11357424"].update(
                name="Tampered station"))

    def test_measurement_and_modeled_value_registry_mismatches_are_rejected(self):
        def measurement(bundle):
            bundle["dataset"]["measurements"][0]["variable_code"] = "pm10"
        self.assert_registry_rejects(measurement)

        def modeled_value(bundle):
            bundle["dataset"]["model_values"][0]["canonical_unit"] = "wrong"
        self.assert_registry_rejects(modeled_value)

        def modeled_domain(bundle):
            bundle["dataset"]["model_values"][0]["domain"] = "air_quality"
        self.assert_registry_rejects(modeled_domain)

    def test_snapshot_identity_mutations_are_rejected(self):
        for field, value in (("product_id", "unknown_product"),
                             ("domain", "air_quality"),
                             ("data_kind", "measurement")):
            self.assert_registry_rejects(
                lambda bundle, field=field, value=value:
                bundle["dataset"]["snapshots"][0].update(**{field: value}))

        def missing_field(bundle):
            bundle["dataset"]["snapshots"][0].pop("domain")
        self.assert_registry_rejects(missing_field)

        def missing_product(bundle):
            bundle["dataset"]["snapshots"][0].pop("product_id")
        self.assert_registry_rejects(missing_product)

        def missing_kind(bundle):
            bundle["dataset"]["snapshots"][0].pop("data_kind")
        self.assert_registry_rejects(missing_kind)

        def mismatched_snapshot_value_domain(bundle):
            bundle["dataset"]["model_values"][0]["domain"] = "air_quality"
        self.assert_registry_rejects(mismatched_snapshot_value_domain)

    def test_registry_embedded_ids_must_match_mapping_keys(self):
        def sensor_key(bundle):
            sensor = bundle["dataset"]["sensors"].pop("openaq_11357424")
            bundle["dataset"]["sensors"]["renamed_sensor"] = sensor
        self.assert_registry_rejects(sensor_key)

        def location_key(bundle):
            location = bundle["dataset"]["locations"].pop("cmt8")
            bundle["dataset"]["locations"]["renamed_location"] = location
        self.assert_registry_rejects(location_key)

    def test_duplicate_modeled_value_key_is_rejected(self):
        def duplicate(bundle):
            bundle["dataset"]["model_values"].append(
                dict(bundle["dataset"]["model_values"][0]))
        self.assert_registry_rejects(duplicate)

    def test_snapshot_city_or_unknown_location_is_rejected(self):
        bundle = json.loads(json.dumps(self.signed))
        bundle["dataset"]["snapshots"][0]["location_id"] = "unknown_station"
        result = build(resign(bundle), reviewed=REVIEWED)
        self.assertEqual(result["manifest"]["snapshot_rejections"].get("snapA-operational"), "location")

        bundle = json.loads(json.dumps(self.signed))
        bundle["dataset"]["snapshots"][0].pop("location_id")
        result = build(resign(bundle), reviewed=REVIEWED)
        self.assertEqual(result["manifest"]["snapshot_rejections"].get("snapA-operational"), "location")

        bundle = json.loads(json.dumps(self.signed))
        bundle["dataset"]["snapshots"][0]["location_id"] = "hcmc"
        result = build(resign(bundle), reviewed=REVIEWED)
        self.assertEqual(result["manifest"]["snapshot_rejections"].get("snapA-operational"), "location")


class TargetQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(synthetic_bundle())

    def target(self, sensor, end_offset, horizon=6):
        targets = {(item["sensor_id"], item["target_end"]): item for item in self.result["targets"]}
        return targets[(sensor, iso(T0 + timedelta(hours=end_offset)))]

    def test_suspect_target_has_null_label(self):
        target = self.target("openaq_14581375", 30)
        self.assertFalse(target["target_available"])
        self.assertIsNone(target["target_pm25"])
        self.assertEqual(target["target_missing_reason"], "target_not_accepted_suspect")
        self.assertEqual(target["target_revision"], 2)
        self.assertEqual(target["target_quality"], "suspect")

    def test_missing_target_has_null_label(self):
        target = self.target("openaq_14581375", 31)
        self.assertFalse(target["target_available"])
        self.assertIsNone(target["target_pm25"])
        self.assertEqual(target["target_missing_reason"], "target_not_accepted_missing")

    def test_older_accepted_target_is_not_resurrected(self):
        suspect = self.target("openaq_14581375", 30)
        self.assertIsNotNone(suspect["target_observation_id"])
        self.assertNotEqual(suspect["target_observation_id"],
                            self.target("openaq_14581375", 29)["target_observation_id"])


class TemporalPeriodStartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = build(synthetic_bundle())

    def test_wrong_period_start_with_correct_support_is_rejected(self):
        bundle = json.loads(json.dumps(synthetic_bundle()))
        for value in bundle["dataset"]["model_values"]:
            if value["snapshot_id"] == "snapC-late-values" and value["variable_code"] == "temperature_2m" \
                    and value["valid_at"] == iso(T0 + timedelta(hours=60)):
                value["period_start"] = iso(T0 + timedelta(hours=59))
        result = build(resign(bundle))
        row = row_for(result, "openaq_11357424", 55, 6)
        self.assertIsNone(row["weather_forecast_temperature_2m"])
        self.assertEqual(row["weather_forecast_reason"], "alignment_mismatch")
        self.assertGreater(result["manifest"]["counts"]["weather_alignment_rejected"], 0)


class StatusTruthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bundle = synthetic_bundle()
        bundle["dataset"]["measurements"] += prestart_measurements()
        cls.warm = resign(bundle)

    def test_both_families_available(self):
        result = build(self.warm)
        self.assertEqual(result["manifest"]["status"], "ok")
        self.assertEqual(result["manifest"]["status_missing_families"], [])
        self.assertGreater(result["manifest"]["counts"]["rows_with_complete_data_feature_set"], 0)

    def test_pm_only_is_limited(self):
        result = build(variant_bundle(snapshots=False))
        self.assertEqual(result["manifest"]["status"], "limited_diagnostic")
        self.assertEqual(result["manifest"]["status_missing_families"], ["forecast_weather"])
        self.assertGreater(result["manifest"]["counts"]["pm_available_origin_count"], 0)
        self.assertEqual(result["manifest"]["counts"]["weather_available_origin_count"], 0)
        self.assertGreater(result["manifest"]["counts"]["rows_with_any_data_feature"], 0)
        self.assertEqual(result["manifest"]["counts"]["rows_with_complete_data_feature_set"], 0)

    def test_weather_only_is_limited(self):
        result = build(variant_bundle(measurements=False))
        self.assertEqual(result["manifest"]["status"], "limited_diagnostic")
        self.assertEqual(result["manifest"]["status_missing_families"], ["pm_history"])
        self.assertGreater(result["manifest"]["counts"]["weather_available_origin_count"], 0)
        self.assertEqual(result["manifest"]["counts"]["pm_available_origin_count"], 0)

    def test_neither_family_is_limited(self):
        result = build(variant_bundle(measurements=False, snapshots=False))
        self.assertEqual(result["manifest"]["status"], "limited_diagnostic")
        self.assertEqual(result["manifest"]["status_missing_families"],
                         ["pm_history", "forecast_weather"])
        self.assertEqual(result["manifest"]["counts"]["rows_with_any_data_feature"], 0)


class StructuralBoundaryTests(unittest.TestCase):
    def test_missing_manifest_key_is_rejected(self):
        bundle = synthetic_bundle()
        del bundle["manifest"]["input_counts"]
        bundle["bundle_sha256"] = digest({k: v for k, v in bundle.items() if k != "bundle_sha256"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps(bundle), encoding="utf-8")
            with FrozenContext(), self.assertRaises(ft.FeatureError):
                ft.load_bundle(path)

    def test_value_referencing_absent_snapshot_is_rejected(self):
        bundle = synthetic_bundle()
        bundle["dataset"]["model_values"][0]["snapshot_id"] = "absent-snapshot"
        bundle["bundle_sha256"] = digest({k: v for k, v in bundle.items() if k != "bundle_sha256"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps(bundle), encoding="utf-8")
            with FrozenContext(), self.assertRaises(ft.FeatureError):
                ft.load_bundle(path)

    def assert_malformed_rejected(self, mutate):
        bundle = synthetic_bundle()
        mutate(bundle)
        if not isinstance(bundle.get("dataset"), dict):
            with self.assertRaises(ft.FeatureError):
                ft.check_bundle_structure(bundle)
            return
        bundle = resign(bundle)
        with self.assertRaises(ft.FeatureError):
            ft.build_features(bundle, "0" * 64, horizons=(6,), availability_basis="captured")

    def test_malformed_rows_and_registries_raise_feature_error(self):
        for field in ("id", "valid_at", "period_start"):
            self.assert_malformed_rejected(
                lambda bundle, field=field: bundle["dataset"]["model_values"][0].pop(field))
        self.assert_malformed_rejected(
            lambda bundle: bundle["dataset"]["measurements"][0].pop("period_end"))
        self.assert_malformed_rejected(
            lambda bundle: bundle["dataset"]["variables"].update(temperature_2m=[]))
        self.assert_malformed_rejected(
            lambda bundle: bundle["dataset"]["model_values"].__setitem__(0, []))
        self.assert_malformed_rejected(lambda bundle: bundle.update(dataset=[]))

    def test_value_level_captured_leakage_guard(self):
        lineage = {"pm_max_recorded_at": None, "pm_max_retrieved_at": None,
                   "weather_max_recorded_at": None, "weather_max_retrieved_at": None,
                   "weather_max_value_recorded_at": iso(T0 + timedelta(hours=5)),
                   "weather_run_initialized_at": None, "weather_source_published_at": None}
        with self.assertRaises(ft.FeatureError):
            ft._check_leakage(lineage, T0 + timedelta(hours=5), "captured", None)
        ft._check_leakage(lineage, T0 + timedelta(hours=6), "captured", None)


class ReplayBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from vn_air.config import load_config
        cls.reviewed = load_config(Path("configs/study.json")).model_dump(mode="json")
        cls.workdir = TemporaryDirectory()
        cls.root = Path(cls.workdir.name)
        cls.bundle_path = cls.root / "bundle.json"
        bundle = signed_bundle(synthetic_bundle(), cls.reviewed)
        cls.bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
        cls.out = cls.root / "build"
        run_cli("features", "build", "--bundle", str(cls.bundle_path), "--config", "configs/study.json",
                "--output-dir", str(cls.out), "--horizons", "6", "24", "--availability", "captured")

    @classmethod
    def tearDownClass(cls):
        cls.workdir.cleanup()

    def summary(self):
        return self.out / "phase_7_feature_summary.json"

    def replay(self, *extra, bundle=None):
        self.counter = getattr(self, "counter", 0) + 1
        target = self.root / f"replay{self.counter}"
        code = run_cli("features", "replay", "--bundle", str(bundle or self.bundle_path),
                       "--config", "configs/study.json", "--output-dir", str(target),
                       "--summary", str(self.summary()), *extra)
        return target, code

    def test_summary_bound_replay_is_byte_identical(self):
        target, code = self.replay()
        self.assertEqual(code, 0)
        for name in ("phase_7_feature_summary.json", "phase_7_features.csv", "phase_7_targets.csv",
                     "phase_7_lineage.csv", "phase_7_assumptions.md"):
            self.assertEqual((self.out / name).read_bytes(), (target / name).read_bytes(), name)

    def test_different_bundle_is_rejected(self):
        other = self.root / "other.json"
        tampered = json.loads(self.bundle_path.read_text(encoding="utf-8"))
        tampered["dataset"]["measurements"][0]["value"] = 424.0
        tampered["bundle_sha256"] = digest({k: v for k, v in tampered.items() if k != "bundle_sha256"})
        other.write_text(json.dumps(tampered), encoding="utf-8")
        target, code = self.replay(bundle=other)
        self.assertEqual(code, 1)

    def test_same_content_different_file_bytes_is_rejected(self):
        rewritten = self.root / "rewritten.json"
        rewritten.write_text(json.dumps(json.loads(self.bundle_path.read_text(encoding="utf-8")),
                                separators=(",", ":")))
        target, code = self.replay(bundle=rewritten)
        self.assertEqual(code, 1)

    def test_changed_horizons_are_rejected(self):
        target, code = self.replay("--horizons", "6")
        self.assertEqual(code, 1)

    def test_changed_availability_is_rejected(self):
        target, code = self.replay("--availability", "assumed", "--assumed-lag-hours", "6")
        self.assertEqual(code, 1)


def run_cli(*args):
    from vn_air import cli
    argv = sys.argv
    sys.argv = ["vn-air", *args]
    try:
        return cli.main()
    finally:
        sys.argv = argv




class FinalFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = synthetic_bundle()

    def test_invalid_only_pm_rows_are_not_available(self):
        result = build(variant_bundle(pm_quality="invalid"))
        counts = result["manifest"]["counts"]
        self.assertEqual(counts["pm_available_origin_count"], 0)
        self.assertGreater(counts["weather_available_origin_count"], 0)
        self.assertEqual(result["manifest"]["status"], "limited_diagnostic")
        self.assertEqual(result["manifest"]["status_missing_families"], ["pm_history"])

    def test_missing_only_weather_values_are_not_available(self):
        result = build(variant_bundle(weather_quality="missing"))
        counts = result["manifest"]["counts"]
        self.assertEqual(counts["weather_available_origin_count"], 0)
        self.assertGreater(counts["pm_available_origin_count"], 0)
        self.assertEqual(result["manifest"]["status"], "limited_diagnostic")
        self.assertEqual(result["manifest"]["status_missing_families"], ["forecast_weather"])

    def test_pm_only_usable_evidence_reports_forecast_missing(self):
        result = build(variant_bundle(snapshots=False))
        self.assertEqual(result["manifest"]["status_missing_families"], ["forecast_weather"])
        self.assertGreater(result["manifest"]["counts"]["pm_available_origin_count"], 0)

    def test_weather_only_usable_evidence_reports_pm_missing(self):
        result = build(variant_bundle(measurements=False))
        self.assertEqual(result["manifest"]["status_missing_families"], ["pm_history"])
        self.assertGreater(result["manifest"]["counts"]["weather_available_origin_count"], 0)

    def test_both_usable_families_are_ok(self):
        result = build(synthetic_bundle())
        self.assertEqual(result["manifest"]["status"], "ok")
        self.assertEqual(result["manifest"]["status_missing_families"], [])

    def test_partial_weather_evidence_counts_without_complete_rows(self):
        bundle = json.loads(json.dumps(self.bundle))
        kept = 0
        for row in bundle["dataset"]["model_values"]:
            if row["snapshot_id"] == "snapB-operational":
                if row["variable_code"] == "temperature_2m" and row["valid_at"] == iso(T0 + timedelta(hours=6)):
                    kept += 1
                    continue
                row["quality_status"] = "missing"
                row["value"] = None
        self.assertEqual(kept, 1)
        result = build(resign(bundle))
        counts = result["manifest"]["counts"]
        self.assertGreater(counts["weather_available_origin_count"], 0)
        self.assertEqual(counts["rows_with_complete_data_feature_set"], 0)

    def test_resigned_altered_table_is_rejected(self):
        tampered = json.loads(json.dumps(self.bundle))
        tampered["dataset"]["measurements"][0]["value"] = 424.0
        tampered["bundle_sha256"] = digest({k: v for k, v in tampered.items() if k != "bundle_sha256"})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            with FrozenContext(), self.assertRaises(ft.FeatureError):
                ft.load_bundle(path)

    def test_non_operational_availability_bases_are_rejected(self):
        with self.assertRaises(ft.FeatureError):
            ft.validate_request((6,), "fallback", None)
        with self.assertRaises(ft.FeatureError):
            ft.validate_request((6,), "captured_lag6", None)

    def test_status_is_deterministic_under_row_reordering(self):
        shuffled = json.loads(json.dumps(self.bundle))
        shuffled["dataset"]["measurements"] = list(reversed(shuffled["dataset"]["measurements"]))
        shuffled = resign(shuffled)
        first, second = build(self.bundle), build(shuffled)
        self.assertEqual(first["manifest"]["status"], second["manifest"]["status"])
        self.assertEqual(first["manifest"]["status_missing_families"],
                         second["manifest"]["status_missing_families"])
        self.assertEqual(first["manifest"]["counts"]["pm_available_origin_count"],
                         second["manifest"]["counts"]["pm_available_origin_count"])
        self.assertEqual(first["manifest"]["counts"]["weather_available_origin_count"],
                         second["manifest"]["counts"]["weather_available_origin_count"])
        self.assertEqual(comparable(first), comparable(second))

    def test_input_integrity_is_recorded(self):
        result = build(self.bundle)
        integrity = result["manifest"]["input_integrity"]
        self.assertTrue(integrity["verified"])
        for key in ("measurements", "snapshots", "model_values"):
            self.assertEqual(integrity[f"{key}_sha256"], digest(self.bundle["dataset"][key]))


if __name__ == "__main__":
    unittest.main()
