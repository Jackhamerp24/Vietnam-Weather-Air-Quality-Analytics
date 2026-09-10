"""Phase 7: availability-aware, leakage-safe feature construction.

Pure and deterministic. No model training, no prediction insertion, no
operational forecast claim. Targets stay physically separate from features.
"""

import hashlib
import json
import math
import statistics
from bisect import bisect_right, insort
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from vn_air.quality import digest, finite, validate_window

FEATURES_VERSION = "phase7_features_v7"
HORIZONS = (6, 24)
PM_LAG_HOURS = (1, 3, 6, 12, 24, 48, 72)
TRAILING_HOURS = (3, 6, 12, 24)
WARMUP_HOURS = max(max(PM_LAG_HOURS), max(TRAILING_HOURS))
FORECAST_PRODUCT = "open_meteo_weather_forecast"
FORECAST_DATA_KIND = "forecast"
FORECAST_PURPOSE = "poll"
SCHEMA_REVISION = "0003_response_integrity"
FROZEN_CUTOFF = "2026-09-06T20:59:00.669630Z"
FROZEN_START = "2026-06-08T00:00:00Z"
FROZEN_END = "2026-09-06T00:00:00Z"
REQUIRED_MANIFEST_KEYS = {"extract_version", "cutoff", "start", "end", "configuration_sha256",
                          "schema_revision", "query_sha256", "implementation_sha256", "input_sha256",
                          "input_counts", "policy"}
SUPPORT_CLASSES = {"instant", "preceding_hour_mean", "preceding_hour_sum"}
ALLOWED_AVAILABILITY = ("captured", "assumed")
DOMAINS = {"weather", "air_quality"}
COORDINATE_TOLERANCE = 1e-6
MAX_BUNDLE_BYTES = 120_000_000
HOUR = timedelta(hours=1)
MIN_TIME = datetime.min.replace(tzinfo=timezone.utc)
SPLIT_FRACTIONS = {"train": 0.6, "validation": 0.2, "test": 0.2}
FEATURE_POLICY = {
    "captured": "A source value is eligible at origin o only when every applicable evidence timestamp (response retrieved_at, row recorded_at, snapshot recorded_at, modeled-value recorded_at, run_initialized_at and source_published_at when present) is strictly before o, the response is a retained successful response, and the row is not withheld. Conservative captured-timestamp policy: the schema has no exact transaction commit time, so this is not proof of as-issued provider availability when run_provenance is unknown.",
    "assumed": "Declared lag scenario only; retrospective sensitivity/mechanics output, never an operational backtest. Measured observations use event time period_end with period_end + lag < origin. Forecast snapshots use run_initialized_at + lag < origin, are rejected as ambiguous when run_initialized_at is unknown, and their modeled values may carry later backfill storage timestamps because the snapshot event time governs availability.",
    "fallback": "Never silently fall back from captured to assumed.",
    "backfill_warning": "The Phase 3 historical backfill was retrieved after the historical period; its retrieved_at is not historical availability.",
}
SOURCE_POLICY = {
    "target_and_pm_history": "Measured OpenAQ PM2.5 (latest eligible revision before quality filtering; accepted rows for the primary track).",
    "captured_weather": "Open-Meteo forecast snapshots only; product, domain, data kind, purpose, model key, location, requested coordinates and response success are validated; one deterministic vintage per location/origin; snapshots are never averaged.",
    "excluded_from_captured_matrix": "ERA5 reanalysis (retrospective context only) and CAMS modeled air quality (separate benchmark stream).",
    "no_substitution": "Missing measured PM2.5 is never replaced with CAMS or any model output.",
}
TARGET_CONTRACT = {
    "target_end": "origin + horizon hours",
    "target_start": "target_end - 1 hour",
    "target_row": "measured hourly interval [target_start, target_end), represented by the observation with period_end = target_end",
    "target_lookup": "eventual quality-qualified record at the extraction cutoff, for evaluation only; never a feature input",
    "unaccepted_targets": "target_available = false and target_pm25 = null with an explicit reason; identity, quality and source timestamps remain for audit",
    "storage": "target values are written to phase_7_targets.csv only",
}
STATUS_POLICY = {
    "ok": "Both required data families (accepted PM history and eligible forecast weather) have available evidence at at least one origin.",
    "limited_diagnostic": "At least one required family has zero available origins; the reason map names the missing families.",
    "note": "Available-origin counts equal captured-origin counts when the availability basis is captured. Calendar-only rows are not operational evidence.",
}


class FeatureError(ValueError):
    pass


def sig(value, digits=12):
    return None if value is None else float(f"{value:.{digits}g}")


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value


def iso(at):
    return None if at is None else at.astimezone(timezone.utc).isoformat()


def check_bundle_structure(bundle):
    if not isinstance(bundle, dict):
        raise FeatureError("Feature bundle must be a JSON object")
    bundle = dict(bundle)
    manifest = bundle.get("manifest") or {}
    if not isinstance(manifest, dict):
        raise FeatureError("Feature bundle manifest must be a JSON object")
    missing = REQUIRED_MANIFEST_KEYS - set(manifest)
    if missing:
        raise FeatureError(f"Feature bundle manifest is missing required keys: {sorted(missing)}")
    dataset = bundle.get("dataset") or {}
    if not isinstance(dataset, dict):
        raise FeatureError("Feature bundle dataset must be a JSON object")
    for key in ("sensors", "locations", "variables", "measurements", "snapshots", "model_values"):
        if key not in dataset:
            raise FeatureError(f"Feature bundle dataset is missing '{key}'")
    for key in ("sensors", "locations", "variables"):
        if not isinstance(dataset[key], dict):
            raise FeatureError(f"Feature bundle dataset '{key}' must be a mapping")
    for key in ("measurements", "snapshots", "model_values"):
        if not isinstance(dataset[key], list) or any(not isinstance(row, dict) for row in dataset[key]):
            raise FeatureError(f"Feature bundle table '{key}' must contain only JSON objects")
    if manifest["schema_revision"] != SCHEMA_REVISION:
        raise FeatureError("Feature extraction requires schema revision 0003_response_integrity")
    input_counts = manifest.get("input_counts")
    if not isinstance(input_counts, dict):
        raise FeatureError("Feature bundle input_counts must be a mapping")
    declared_hashes = manifest.get("input_sha256")
    if not isinstance(declared_hashes, dict) or set(declared_hashes) != {"measurements", "snapshots", "model_values"}:
        raise FeatureError("Feature bundle must declare exactly the measurements, snapshots and model_values table hashes")
    for key in ("measurements", "snapshots", "model_values"):
        if not isinstance(input_counts.get(key), int) or input_counts[key] < 0:
            raise FeatureError(f"Feature bundle input count is invalid for {key}")
        if not isinstance(declared_hashes[key], str) or len(declared_hashes[key]) != 64:
            raise FeatureError(f"Feature bundle input hash is invalid for {key}")
        if len(dataset[key]) != input_counts[key]:
            raise FeatureError(f"Feature bundle input count mismatch for {key}")
        if digest(dataset[key]) != declared_hashes[key]:
            raise FeatureError(f"Feature bundle input table hash mismatch for {key}")
    variable_fields = ("canonical_unit", "domain", "representation", "temporal_support")
    for key, meta in dataset["variables"].items():
        if not isinstance(meta, dict) or any(field not in meta for field in variable_fields):
            raise FeatureError(f"Variable registry entry is malformed for {key}")
    for key, meta in dataset["locations"].items():
        if not isinstance(meta, dict) or meta.get("id") != key:
            raise FeatureError(f"Location registry key mismatch for {key}")
        if any(field not in meta for field in ("id", "name", "kind", "latitude", "longitude", "timezone")):
            raise FeatureError(f"Location registry entry is malformed for {key}")
    for key, meta in dataset["sensors"].items():
        if not isinstance(meta, dict) or meta.get("id") != key:
            raise FeatureError(f"Sensor registry key mismatch for {key}")
        if any(field not in meta for field in ("id", "location_id", "product_id", "variable_code",
                                               "canonical_unit", "name", "timezone")):
            raise FeatureError(f"Sensor registry entry is malformed for {key}")
    for code, meta in dataset["variables"].items():
        if meta.get("domain") not in DOMAINS or meta.get("representation") not in {"weather", "concentration", "index"} \
                or meta.get("temporal_support") not in SUPPORT_CLASSES or not meta.get("canonical_unit"):
            raise FeatureError(f"Invalid variable schema in bundle for {code}")
    valid_data_kinds = {"measurement", "reanalysis", "forecast"}
    measurement_fields = ("id", "sensor_id", "product_id", "variable_code", "canonical_unit",
                          "period_start", "period_end", "revision", "value", "quality_status",
                          "source_published_at", "recorded_at", "retrieved_at", "response_id")
    for row in dataset["measurements"]:
        if any(field not in row for field in measurement_fields):
            raise FeatureError("Measurement is missing required fields")
    snapshot_fields = ("id", "product_id", "domain", "data_kind", "response_id", "recorded_at",
                       "retrieved_at", "http_status", "error_code", "purpose", "model_key",
                       "run_initialized_at", "source_published_at", "run_provenance",
                       "requested_latitude", "requested_longitude", "grid_latitude", "grid_longitude",
                       "window_start", "window_end")
    for row in dataset["snapshots"]:
        if any(field not in row for field in snapshot_fields):
            raise FeatureError("Snapshot is missing required fields")
        if not isinstance(row, dict) or any(not row.get(field) for field in ("id", "product_id", "domain", "data_kind")):
            raise FeatureError("Snapshot is missing required identity fields")
        if row["domain"] not in DOMAINS or row["data_kind"] not in valid_data_kinds:
            raise FeatureError(f"Invalid snapshot identity for {row['id']}")
    value_fields = ("id", "snapshot_id", "variable_code", "canonical_unit", "domain", "valid_at",
                    "period_start", "temporal_support", "value", "quality_status", "recorded_at")
    for row in dataset["model_values"]:
        if any(field not in row for field in value_fields):
            raise FeatureError("Modeled value is missing required fields")
    snapshot_ids = {row.get("id") for row in dataset["snapshots"]}
    if None in snapshot_ids:
        raise FeatureError("Snapshot identifiers cannot be null")
    if len(snapshot_ids) != len(dataset["snapshots"]):
        raise FeatureError("Duplicate snapshot identifiers in bundle")
    unknown = {row.get("snapshot_id") for row in dataset["model_values"]} - snapshot_ids
    if unknown:
        raise FeatureError("Modeled values reference absent snapshots")
    unknown_sensors = {row.get("sensor_id") for row in dataset["measurements"]} - set(dataset["sensors"])
    if unknown_sensors:
        raise FeatureError("Measurements reference unconfigured sensors")
    unknown_locations = {row.get("location_id") for row in dataset["sensors"].values()} - set(dataset["locations"])
    if unknown_locations:
        raise FeatureError("Sensors reference unconfigured locations")
    try:
        value_keys = [(row.get("snapshot_id"), row.get("variable_code"), instant(row.get("valid_at")))
                  for row in dataset["model_values"]]
    except (TypeError, ValueError, AttributeError):
        raise FeatureError("Modeled value timestamp is invalid") from None
    if len(value_keys) != len(set(value_keys)):
        raise FeatureError("Duplicate modeled-value keys in bundle")
    for sensor_id, sensor in dataset["sensors"].items():
        if sensor.get("location_id") not in dataset["locations"]:
            raise FeatureError(f"Sensor {sensor_id} references an unknown location")
        if sensor.get("variable_code") not in dataset["variables"]:
            raise FeatureError(f"Sensor {sensor_id} references an unknown variable")
        variable = dataset["variables"][sensor["variable_code"]]
        if sensor.get("canonical_unit") != variable.get("canonical_unit"):
            raise FeatureError(f"Sensor {sensor_id} uses a mismatched canonical unit")
    for row in dataset["measurements"]:
        sensor = dataset["sensors"].get(row.get("sensor_id"))
        if sensor is None:
            raise FeatureError("Measurement references an unknown sensor")
        for field in ("product_id", "variable_code", "canonical_unit"):
            if row.get(field) != sensor.get(field):
                raise FeatureError(f"Measurement identity mismatch for {row.get('sensor_id')}: {field}")
    snapshots_by_id = {row["id"]: row for row in dataset["snapshots"]}
    for row in dataset["model_values"]:
        variable = dataset["variables"].get(row.get("variable_code"))
        if variable is None:
            raise FeatureError("Modeled value references an unknown variable")
        snapshot = snapshots_by_id.get(row.get("snapshot_id"))
        if snapshot is None:
            raise FeatureError("Modeled value references absent snapshot")
        for field in ("canonical_unit", "domain", "temporal_support"):
            if row.get(field) != variable.get(field):
                raise FeatureError(f"Modeled-value registry mismatch: {field}")
        if row.get("domain") != snapshot.get("domain"):
            raise FeatureError("Modeled-value domain differs from snapshot domain")
    return bundle


def bundle_file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_bundle(path):
    if path.stat().st_size > MAX_BUNDLE_BYTES:
        raise FeatureError("Oversize feature input bundle")
    bundle = json.loads(path.read_text(encoding="utf-8"))
    if bundle.get("bundle_sha256") != digest({k: v for k, v in bundle.items() if k != "bundle_sha256"}):
        raise FeatureError("Feature input bundle integrity mismatch")
    return check_bundle_structure(bundle)


def validate_reviewed(reviewed, bundle):
    """Verify the complete reviewed registry against the input bundle."""
    manifest = bundle["manifest"]
    if digest(reviewed) != manifest["configuration_sha256"]:
        raise FeatureError("Reviewed configuration digest differs from the input bundle record")
    dataset = bundle["dataset"]
    reviewed_products = {row["id"]: row for row in reviewed["products"]}
    for snapshot in dataset["snapshots"]:
        product = reviewed_products.get(snapshot.get("product_id"))
        if product is None:
            raise FeatureError(f"Snapshot references an unknown reviewed product: {snapshot.get('product_id')}")
        if snapshot.get("domain") != product.get("domain") or snapshot.get("data_kind") != product.get("data_kind"):
            raise FeatureError(f"Snapshot product identity differs for {snapshot.get('id')}")
    reviewed_variables = {row["code"]: row for row in reviewed["variables"]}
    bundle_variables = dataset["variables"]
    if set(reviewed_variables) != set(bundle_variables):
        raise FeatureError("Bundle variables differ from the reviewed configuration")
    variable_fields = ("canonical_unit", "domain", "representation", "temporal_support", "minimum", "maximum")
    for code in reviewed_variables:
        if any(bundle_variables[code].get(field) != reviewed_variables[code].get(field)
               for field in variable_fields):
            raise FeatureError(f"Bundle variable registry differs for {code}")

    reviewed_locations = {row["id"]: row for row in reviewed["locations"]}
    bundle_locations = dataset["locations"]
    if set(reviewed_locations) != set(bundle_locations):
        raise FeatureError("Bundle locations differ from the reviewed configuration")
    location_fields = ("name", "kind", "parent_id", "country_code", "latitude", "longitude", "timezone",
                       "provider_timezone", "geonames_id")
    for location_id in reviewed_locations:
        if any(bundle_locations[location_id].get(field) != reviewed_locations[location_id].get(field)
               for field in location_fields):
            raise FeatureError(f"Bundle location registry differs for {location_id}")

    reviewed_sensors = {row["id"]: row for row in reviewed["sensors"]}
    bundle_sensors = dataset["sensors"]
    if set(reviewed_sensors) != set(bundle_sensors):
        raise FeatureError("Bundle sensors differ from the reviewed configuration")
    sensor_fields = ("location_id", "product_id", "external_sensor_id", "external_location_id",
                     "variable_code", "canonical_unit", "instrument", "is_reference_monitor",
                     "licence_url", "licence_valid_from", "licence_valid_to", "attribution",
                     "qualification_notes")
    for sensor_id in reviewed_sensors:
        if any(bundle_sensors[sensor_id].get(field) != reviewed_sensors[sensor_id].get(field)
               for field in sensor_fields):
            raise FeatureError(f"Bundle sensor registry differs for {sensor_id}")
        location_id = reviewed_sensors[sensor_id]["location_id"]
        reviewed_location = reviewed_locations[location_id]
        if reviewed_location["kind"] != "station":
            raise FeatureError(f"Reviewed sensor {sensor_id} does not reference a station")
        if bundle_sensors[sensor_id].get("name") != reviewed_location["name"]:
            raise FeatureError(f"Bundle sensor derived name differs for {sensor_id}")
        if bundle_sensors[sensor_id].get("timezone") != reviewed_location["timezone"]:
            raise FeatureError(f"Bundle sensor derived timezone differs for {sensor_id}")

    forecast = next((row for row in reviewed["products"] if row["id"] == FORECAST_PRODUCT), None)
    if forecast is None or not forecast.get("options", {}).get("models"):
        raise FeatureError("Reviewed configuration lacks the forecast model key")
    return forecast["options"]["models"]


def validate_request(horizons, availability_basis, assumed_lag_hours):
    if not horizons or any(h not in HORIZONS for h in horizons):
        raise FeatureError(f"Horizons must be a non-empty subset of {HORIZONS}")
    if availability_basis not in ALLOWED_AVAILABILITY:
        raise FeatureError("availability must be captured or assumed")
    if availability_basis == "captured":
        if assumed_lag_hours is not None:
            raise FeatureError("--assumed-lag-hours is forbidden for captured availability")
    elif assumed_lag_hours is None or assumed_lag_hours <= 0:
        raise FeatureError("assumed availability requires a positive --assumed-lag-hours")
    return sorted(horizons)


def selection_key(row):
    """Deterministic latest-revision order: revision, then freshest evidence, then stable id."""
    return (row["revision"], instant(row["recorded_at"]), instant(row["retrieved_at"]), str(row["id"]))


def prepare_measurements(rows, availability_basis, assumed_lag_hours):
    """Group measurement rows per sensor with a monotone eligibility key."""
    grouped = {}
    for row in rows:
        if availability_basis == "captured":
            eligibility = max(instant(row["recorded_at"]), instant(row["retrieved_at"]),
                              instant(row["source_published_at"]) if row.get("source_published_at") else MIN_TIME)
        else:
            eligibility = instant(row["period_end"]) + timedelta(hours=assumed_lag_hours)
        prepared = dict(row, period_end=instant(row["period_end"]), _elig=eligibility)
        grouped.setdefault(row["sensor_id"], []).append(prepared)
    for sensor_rows in grouped.values():
        sensor_rows.sort(key=lambda r: (r["_elig"], r["period_end"], selection_key(r)))
    return grouped


def snapshot_rejections(rows, reviewed=None):
    """Forecast snapshots excluded by source/vintage identity checks; never selected."""
    rejected, accepted = {}, []
    expected_model = None
    stations = {}
    if reviewed is not None:
        forecast = next((row for row in reviewed["products"] if row["id"] == FORECAST_PRODUCT), None)
        expected_model = forecast.get("options", {}).get("models") if forecast else None
        stations = {row["id"]: (row["latitude"], row["longitude"]) for row in reviewed["locations"]
                    if row.get("kind") == "station"}
    for row in rows:
        if row.get("product_id") != FORECAST_PRODUCT or row.get("data_kind") != FORECAST_DATA_KIND:
            continue
        reason = None
        if row.get("domain") != "weather":
            reason = "domain"
        elif row.get("purpose") != FORECAST_PURPOSE:
            reason = "purpose"
        elif reviewed is not None and (expected_model is None or row.get("model_key") != expected_model):
            reason = "model_key"
        elif not row.get("location_id"):
            reason = "location"
        elif reviewed is not None and row.get("location_id") not in stations:
            reason = "location"
        elif reviewed is not None and row.get("location_id") in stations:
            latitude, longitude = stations[row["location_id"]]
            requested_latitude, requested_longitude = row.get("requested_latitude"), row.get("requested_longitude")
            if requested_latitude is None or requested_longitude is None \
                    or abs(requested_latitude - latitude) > COORDINATE_TOLERANCE \
                    or abs(requested_longitude - longitude) > COORDINATE_TOLERANCE:
                reason = "coordinates"
        if row.get("http_status") != 200 or row.get("error_code"):
            reason = reason or "unsuccessful_response"
        if reason:
            rejected[row["id"]] = reason
        else:
            accepted.append(row)
    return accepted, rejected


def prepare_snapshots(rows, availability_basis, assumed_lag_hours, reviewed=None):
    """Eligible forecast snapshots per location with eligibility keys and identity checks."""
    accepted, rejected = snapshot_rejections(rows, reviewed)
    grouped = {}
    for row in accepted:
        prepared = dict(row)
        if availability_basis == "captured":
            prepared["_elig"] = max(instant(prepared["recorded_at"]), instant(prepared["retrieved_at"]),
                                    instant(prepared["run_initialized_at"]) if prepared.get("run_initialized_at") else MIN_TIME,
                                    instant(prepared["source_published_at"]) if prepared.get("source_published_at") else MIN_TIME)
            prepared["ambiguous"] = False
        else:
            initialized = instant(prepared["run_initialized_at"]) if prepared.get("run_initialized_at") else None
            prepared["_elig"] = None if initialized is None else initialized + timedelta(hours=assumed_lag_hours)
            prepared["ambiguous"] = initialized is None
        grouped.setdefault(row["location_id"], []).append(prepared)
    for location_rows in grouped.values():
        location_rows.sort(key=lambda r: (r["_elig"] is None, r["_elig"] or MIN_TIME, str(r["id"])))
    return grouped, rejected


def vintage_rank(snapshot):
    return (instant(snapshot["run_initialized_at"]) if snapshot.get("run_initialized_at") else MIN_TIME,
            instant(snapshot["source_published_at"]) if snapshot.get("source_published_at") else MIN_TIME,
            instant(snapshot["retrieved_at"]), instant(snapshot["recorded_at"]), str(snapshot["id"]))


def origin_grid(start, end, horizons):
    last_origin = end - max(horizons) * HOUR
    if last_origin < start:
        raise FeatureError("insufficient_time_window: origin range cannot support the requested horizons")
    origins = []
    at = start
    while at <= last_origin:
        origins.append(at)
        at += HOUR
    return origins


def split_boundaries(origins):
    count = len(origins)
    if count < 10:
        raise FeatureError("insufficient_time_window: origin range cannot support train/validation/test splits")
    train_end_index = count * 6 // 10
    validation_end_index = count * 8 // 10
    if train_end_index == 0 or validation_end_index <= train_end_index or validation_end_index >= count:
        raise FeatureError("insufficient_time_window: split fractions produce an empty period")
    return origins[train_end_index], origins[validation_end_index]


def local_parts(at):
    local = at.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
    return local.date().isoformat(), local.hour, local.weekday()


def period_start_ok(row, support):
    period_start, valid_at = instant(row["period_start"]), instant(row["valid_at"])
    if support == "instant":
        return period_start == valid_at
    if support in ("preceding_hour_mean", "preceding_hour_sum"):
        return period_start == valid_at - HOUR
    return False


def pm_feature_set(accepted, periods, origin):
    features, used_ids = {}, set()
    for lag in PM_LAG_HOURS:
        row = accepted.get(origin - lag * HOUR)
        features[f"pm25_lag_{lag}h"] = row["value"] if row else None
        if row:
            used_ids.add(row["id"])
    last = None
    for index in range(bisect_right(periods, origin) - 1, -1, -1):
        if periods[index] in accepted:
            last = periods[index]
            break
    features["pm25_last_available"] = accepted[last]["value"] if last else None
    features["pm25_last_age_hours"] = (origin - last).total_seconds() / 3600 if last else None
    if last:
        used_ids.add(accepted[last]["id"])
    for window in TRAILING_HOURS:
        low = bisect_right(periods, origin - window * HOUR)
        high = bisect_right(periods, origin)
        members = [when for when in periods[low:high] if when in accepted]
        values = [accepted[when]["value"] for when in members]
        for when in members:
            used_ids.add(accepted[when]["id"])
        features[f"pm25_trailing_count_{window}h"] = len(values)
        complete = len(values) == window
        features[f"pm25_trailing_mean_{window}h"] = statistics.fmean(values) if complete else None
        if window == 24:
            features["pm25_trailing_std_24h"] = statistics.stdev(values) if complete else None
    full_lag_coverage = all(features[f"pm25_lag_{lag}h"] is not None for lag in PM_LAG_HOURS)
    return features, used_ids, full_lag_coverage


def weather_feature_set(values_index, variables, weather_codes, target_start, target_end):
    features, used, counters = {}, {}, {"missing": 0, "alignment": 0}
    for code in weather_codes:
        support = variables[code]["temporal_support"]
        valid_at = target_start if support == "instant" else target_end
        row = values_index.get((code, valid_at))
        name = f"weather_forecast_{code}"
        if row is None:
            features[name] = None
            counters["missing"] += 1
            continue
        if row["temporal_support"] != support or not period_start_ok(row, support):
            features[name] = None
            counters["alignment"] += 1
            continue
        used[code] = row
        if row["quality_status"] != "accepted" or not finite(row["value"]):
            features[name] = None
            counters["missing"] += 1
        else:
            features[name] = row["value"]
    return features, used, counters


def wind_components(weather_features):
    direction = weather_features.pop("weather_forecast_wind_direction_10m", None)
    if direction is None:
        weather_features["weather_forecast_wind_direction_sin"] = None
        weather_features["weather_forecast_wind_direction_cos"] = None
    else:
        radians = math.radians(direction)
        weather_features["weather_forecast_wind_direction_sin"] = math.sin(radians)
        weather_features["weather_forecast_wind_direction_cos"] = math.cos(radians)


def value_lineage(code, row, snapshot, availability_basis):
    names = (["weather_forecast_wind_direction_sin", "weather_forecast_wind_direction_cos"]
             if code == "wind_direction_10m" else [f"weather_forecast_{code}"])
    return {"feature_names": names, "value_id": row["id"], "variable_code": code,
            "valid_at": iso(instant(row["valid_at"])), "period_start": iso(instant(row["period_start"])),
            "temporal_support": row["temporal_support"], "quality_status": row["quality_status"],
            "value_recorded_at": iso(instant(row["recorded_at"])), "snapshot_id": snapshot["id"],
            "product_id": snapshot["product_id"], "data_kind": snapshot["data_kind"],
            "model_key": snapshot.get("model_key"), "model_version": snapshot.get("model_version"),
            "requested_latitude": snapshot.get("requested_latitude"),
            "requested_longitude": snapshot.get("requested_longitude"),
            "grid_latitude": snapshot.get("grid_latitude"), "grid_longitude": snapshot.get("grid_longitude"),
            "response_id": snapshot["response_id"],
            "response_retrieved_at": iso(instant(snapshot["retrieved_at"])),
            "snapshot_recorded_at": iso(instant(snapshot["recorded_at"])),
            "run_initialized_at": iso(instant(snapshot["run_initialized_at"])) if snapshot.get("run_initialized_at") else None,
            "source_published_at": iso(instant(snapshot["source_published_at"])) if snapshot.get("source_published_at") else None,
            "availability_basis": availability_basis}


def build_features(bundle, bundle_file_sha256, *, horizons, availability_basis, assumed_lag_hours=None,
                   feature_version=FEATURES_VERSION, reviewed=None, require_frozen_boundary=False):
    bundle = check_bundle_structure(bundle)
    horizons = validate_request(horizons, availability_basis, assumed_lag_hours)
    lag_hours = float(assumed_lag_hours) if assumed_lag_hours is not None else 0.0
    if require_frozen_boundary:
        require_frozen_boundary_apply(bundle)
    manifest_in = bundle["manifest"]
    dataset = bundle["dataset"]
    start, end, cutoff = (instant(manifest_in[key]) for key in ("start", "end", "cutoff"))
    validate_window(cutoff, start, end)
    forecast_model_key = None
    if reviewed is not None:
        forecast_model_key = validate_reviewed(reviewed, bundle)
    sensors = dataset["sensors"]
    if not sensors:
        raise FeatureError("Bundle contains no sensors")
    if len({meta["timezone"] for meta in sensors.values()}) != 1:
        raise FeatureError("All sensors must share one local timezone for calendar features")
    variables = dataset["variables"]
    weather_codes = sorted(code for code, meta in variables.items() if meta["domain"] == "weather")
    if not weather_codes:
        raise FeatureError("Bundle contains no weather variables")
    measurements = prepare_measurements(dataset["measurements"], availability_basis, assumed_lag_hours)
    snapshots, snapshot_rejection_reasons = prepare_snapshots(dataset["snapshots"], availability_basis,
                                                              assumed_lag_hours, reviewed)
    values_by_snapshot = {}
    for row in dataset["model_values"]:
        values_by_snapshot.setdefault(row["snapshot_id"], {})[(row["variable_code"], instant(row["valid_at"]))] = dict(
            row, valid_at=instant(row["valid_at"]), period_start=instant(row["period_start"]))
    final_revision = {}
    for row in dataset["measurements"]:
        key = (row["sensor_id"], instant(row["period_end"]))
        current = final_revision.get(key)
        if current is None or selection_key(row) > selection_key(current):
            final_revision[key] = dict(row, period_end=instant(row["period_end"]))
    origins = origin_grid(start, end, horizons)
    validation_start, test_start = split_boundaries(origins)
    sensor_state = {sensor_id: {"rows": measurements.get(sensor_id, []), "series": {}, "periods": [],
                                "pointer": 0} for sensor_id in sensors}
    locations = {meta["location_id"] for meta in sensors.values()}
    location_state = {location: {"rows": snapshots.get(location, []), "eligible": [], "pointer": 0}
                      for location in locations}
    rows, targets, lineage = [], [], []
    counts = {"rows": 0, "purged_rows": 0, "split": {"train": 0, "validation": 0, "test": 0},
              "purge_reasons": {}, "target_available": 0, "target_reasons": {}, "pm_reasons": {},
              "weather_reasons": {}, "weather_alignment_rejected": 0, "weather_missing_values": 0,
              "pm_available_origin_count": 0, "weather_available_origin_count": 0,
              "rows_with_any_data_feature": 0, "rows_with_complete_data_feature_set": 0,
              "rows_with_full_lag_coverage": 0}
    history_start = start - WARMUP_HOURS * HOUR
    for origin in origins:
        origin_parts = local_parts(origin)
        pm_by_sensor = {}
        for sensor_id, state in sensor_state.items():
            while state["pointer"] < len(state["rows"]) and state["rows"][state["pointer"]]["_elig"] < origin:
                item = state["rows"][state["pointer"]]
                state["pointer"] += 1
                current = state["series"].get(item["period_end"])
                if current is None:
                    insort(state["periods"], item["period_end"])
                if current is None or selection_key(item) > selection_key(current):
                    state["series"][item["period_end"]] = item
            accepted = {when: item for when, item in state["series"].items()
                        if item["quality_status"] == "accepted" and finite(item["value"])}
            features, used_ids, full_lag = pm_feature_set(accepted, state["periods"], origin)
            available_through = max(accepted) if accepted else None
            reason = "ok" if accepted else "no_eligible_accepted_values"
            counts["pm_reasons"][reason] = counts["pm_reasons"].get(reason, 0) + 1
            if accepted:
                counts["pm_available_origin_count"] += 1
            if availability_basis == "captured":
                measured_evidence = max((max(instant(item["recorded_at"]), instant(item["retrieved_at"]),
                                             instant(item["source_published_at"]) if item.get("source_published_at") else MIN_TIME)
                                         for item in state["series"].values()), default=None)
                assumed_horizon = None
            else:
                measured_evidence = None
                assumed_horizon = (available_through + timedelta(hours=lag_hours)
                                   if available_through else None)
            pm_by_sensor[sensor_id] = {"features": features, "used_ids": used_ids, "accepted": len(accepted),
                                       "series": len(state["series"]), "through": available_through,
                                       "reason": reason, "evidence": measured_evidence,
                                       "assumed_horizon": assumed_horizon, "full_lag": full_lag}
        weather_by_location = {}
        for location, state in location_state.items():
            while state["pointer"] < len(state["rows"]) and state["rows"][state["pointer"]]["_elig"] is not None \
                    and state["rows"][state["pointer"]]["_elig"] < origin:
                item = state["rows"][state["pointer"]]
                state["pointer"] += 1
                state["eligible"].append(item)
            snapshot = max(state["eligible"], key=vintage_rank) if state["eligible"] else None
            if snapshot:
                snapshot_values = values_by_snapshot.get(snapshot["id"], {})
                if availability_basis == "captured":
                    usable_values = {key: row for key, row in snapshot_values.items()
                                     if instant(row["recorded_at"]) < origin}
                else:
                    usable_values = dict(snapshot_values)
                snapshot_evidence = max(instant(snapshot["recorded_at"]), instant(snapshot["retrieved_at"]),
                                        instant(snapshot["run_initialized_at"]) if snapshot.get("run_initialized_at") else MIN_TIME,
                                        instant(snapshot["source_published_at"]) if snapshot.get("source_published_at") else MIN_TIME)
                assumed_event = (instant(snapshot["run_initialized_at"]) + timedelta(hours=lag_hours)
                                 if availability_basis == "assumed" and snapshot.get("run_initialized_at") else None)
            else:
                usable_values, snapshot_evidence, assumed_event = {}, None, None
            weather_by_location[location] = {"snapshot": snapshot, "values": usable_values,
                                             "evidence": snapshot_evidence, "assumed_event": assumed_event}
        weather_usable_locations = set()
        for sensor_id in sorted(sensors):
            meta = sensors[sensor_id]
            pm = pm_by_sensor[sensor_id]
            weather = weather_by_location[meta["location_id"]]
            snapshot = weather["snapshot"]
            for horizon in horizons:
                target_end = origin + horizon * HOUR
                target_start = target_end - HOUR
                target_parts = local_parts(target_end)
                final = final_revision.get((sensor_id, target_end))
                if final is None:
                    target_available, target_reason = False, "target_absent"
                elif final["quality_status"] != "accepted" or not finite(final["value"]):
                    target_available, target_reason = False, f"target_not_accepted_{final['quality_status']}"
                else:
                    target_available, target_reason = True, "ok"
                counts["target_reasons"][target_reason] = counts["target_reasons"].get(target_reason, 0) + 1
                counts["target_available"] += target_available
                if origin < validation_start:
                    split = "train"
                elif origin < test_start:
                    split = "validation"
                else:
                    split = "test"
                purged, purge_reason = False, ""
                if split == "train" and target_end > validation_start:
                    purged, purge_reason = True, "target_reaches_validation"
                elif split == "validation" and target_end > test_start:
                    purged, purge_reason = True, "target_reaches_test"
                counts["split"][split] += 1
                counts["purged_rows"] += purged
                if purge_reason:
                    counts["purge_reasons"][purge_reason] = counts["purge_reasons"].get(purge_reason, 0) + 1
                weather_features, used_values, weather_counters = weather_feature_set(
                    weather["values"], variables, weather_codes, target_start, target_end)
                wind_components(weather_features)
                counts["weather_missing_values"] += weather_counters["missing"]
                counts["weather_alignment_rejected"] += weather_counters["alignment"]
                if any(value is not None for value in weather_features.values()):
                    weather_usable_locations.add(meta["location_id"])
                if snapshot is None:
                    weather_reason = "no_eligible_vintage"
                elif weather_counters["alignment"]:
                    weather_reason = "alignment_mismatch"
                elif weather_counters["missing"]:
                    weather_reason = "values_missing_or_not_accepted"
                else:
                    weather_reason = "ok"
                counts["weather_reasons"][weather_reason] = counts["weather_reasons"].get(weather_reason, 0) + 1
                value_records = [value_lineage(code, row, snapshot, availability_basis)
                                 for code, row in sorted(used_values.items())] if snapshot else []
                weather_max_value_recorded = max((instant(row["recorded_at"]) for row in used_values.values()),
                                                 default=None)
                if availability_basis == "captured":
                    evidence_times = [pm["evidence"], weather["evidence"], weather_max_value_recorded]
                    feature_available_through = max((t for t in evidence_times if t is not None), default=None)
                else:
                    event_times = [pm["assumed_horizon"], weather["assumed_event"]]
                    feature_available_through = max((t for t in event_times if t is not None), default=None)
                lineage_id = f"{sensor_id}|{iso(origin)}|{horizon}"
                lineage_row = {"lineage_id": lineage_id, "sensor_id": sensor_id, "location_id": meta["location_id"],
                    "origin": iso(origin), "horizon_hours": horizon, "target_start": iso(target_start),
                    "target_end": iso(target_end), "availability_basis": availability_basis,
                    "availability_assumption": assumed_lag_hours if availability_basis == "assumed" else None,
                    "pm_observation_ids": json.dumps(sorted(pm["used_ids"]), separators=(",", ":")),
                    "pm_accepted_rows": pm["accepted"], "pm_asof_rows": pm["series"],
                    "pm_available_through": iso(pm["through"]),
                    "pm_max_recorded_at": iso(max((instant(item["recorded_at"])
                        for item in sensor_state[sensor_id]["series"].values()), default=None)) if pm["series"] else None,
                    "pm_max_retrieved_at": iso(max((instant(item["retrieved_at"])
                        for item in sensor_state[sensor_id]["series"].values()), default=None)) if pm["series"] else None,
                    "weather_snapshot_id": snapshot["id"] if snapshot else None,
                    "weather_response_id": snapshot["response_id"] if snapshot else None,
                    "weather_run_provenance": snapshot["run_provenance"] if snapshot else None,
                    "weather_model_key": snapshot.get("model_key") if snapshot else None,
                    "weather_model_version": snapshot.get("model_version") if snapshot else None,
                    "weather_model_value_ids": json.dumps(sorted(row["id"] for row in used_values.values()),
                                                          separators=(",", ":")),
                    "weather_values": json.dumps(value_records, sort_keys=True, separators=(",", ":")),
                    "weather_max_value_recorded_at": iso(weather_max_value_recorded),
                    "weather_max_recorded_at": iso(instant(snapshot["recorded_at"])) if snapshot else None,
                    "weather_max_retrieved_at": iso(instant(snapshot["retrieved_at"])) if snapshot else None,
                    "weather_run_initialized_at": iso(instant(snapshot["run_initialized_at"])) if snapshot and snapshot.get("run_initialized_at") else None,
                    "weather_source_published_at": iso(instant(snapshot["source_published_at"])) if snapshot and snapshot.get("source_published_at") else None}
                lineage.append(lineage_row)
                has_any = any(value is not None for key, value in pm["features"].items()
                              if "trailing_count" not in key) \
                    or any(value is not None for value in weather_features.values())
                complete = (pm["reason"] == "ok" and weather_reason == "ok"
                            and weather_counters["missing"] == 0 and pm["full_lag"]
                            and all(weather_features[f"weather_forecast_{code}"] is not None
                                    for code in weather_codes if code != "wind_direction_10m")
                            and weather_features["weather_forecast_wind_direction_sin"] is not None)
                counts["rows_with_any_data_feature"] += has_any
                counts["rows_with_complete_data_feature_set"] += complete
                counts["rows_with_full_lag_coverage"] += pm["full_lag"]
                rows.append({"sensor_id": sensor_id, "location_id": meta["location_id"], "origin": iso(origin),
                    "horizon_hours": horizon, "target_start": iso(target_start), "target_end": iso(target_end),
                    "origin_local_date": origin_parts[0], "origin_local_hour": origin_parts[1],
                    "origin_local_weekday": origin_parts[2], "target_local_date": target_parts[0],
                    "target_local_hour": target_parts[1], "target_local_weekday": target_parts[2],
                    **pm["features"], **weather_features,
                    "pm_asof_rows": pm["series"], "pm_history_reason": pm["reason"],
                    "pm_available_through": iso(pm["through"]), "pm_full_lag_coverage": pm["full_lag"],
                    "weather_forecast_reason": weather_reason,
                    "weather_forecast_snapshot_id": snapshot["id"] if snapshot else None,
                    "weather_forecast_run_provenance": snapshot["run_provenance"] if snapshot else None,
                    "weather_forecast_missing_count": weather_counters["missing"],
                    "availability_basis": availability_basis,
                    "availability_assumption": assumed_lag_hours if availability_basis == "assumed" else None,
                    "feature_available_through": iso(feature_available_through),
                    "feature_version": feature_version, "input_manifest_sha256": digest(manifest_in),
                    "lineage_id": lineage_id, "split": split, "purged": purged, "purge_reason": purge_reason,
                    "target_available": target_available,
                    "target_quality": final["quality_status"] if final else None,
                    "target_observation_id": final["id"] if final else None,
                    "target_revision": final["revision"] if final else None,
                    "target_missing_reason": target_reason})
                targets.append({"sensor_id": sensor_id, "location_id": meta["location_id"], "origin": iso(origin),
                    "horizon_hours": horizon, "target_start": iso(target_start), "target_end": iso(target_end),
                    "target_available": target_available,
                    "target_pm25": final["value"] if final and target_available else None,
                    "target_quality": final["quality_status"] if final else None,
                    "target_observation_id": final["id"] if final else None,
                    "target_revision": final["revision"] if final else None,
                    "target_recorded_at": final["recorded_at"] if final else None,
                    "target_retrieved_at": final["retrieved_at"] if final else None,
                    "target_source_published_at": final.get("source_published_at") if final else None,
                    "target_missing_reason": None if target_available else target_reason})
                counts["rows"] += 1
                _check_leakage(lineage_row, origin, availability_basis, assumed_lag_hours)
        counts["weather_available_origin_count"] += len(weather_usable_locations)
    last_origin = origins[-1]
    never_eligible_measurements = sum(1 for sensor_rows in measurements.values()
                                      for row in sensor_rows if row["_elig"] >= last_origin)
    never_eligible_snapshots = sum(1 for location_rows in snapshots.values() for row in location_rows
                                   if row["_elig"] is None or row["_elig"] >= last_origin)
    ambiguous_vintages = sum(1 for location_rows in snapshots.values() for row in location_rows if row["ambiguous"])
    warmup_rows_by_sensor = {sensor_id: sum(1 for key, row in final_revision.items()
                                            if key[0] == sensor_id and key[1] < start)
                             for sensor_id in sensors}
    missing_families = []
    if counts["pm_available_origin_count"] == 0:
        missing_families.append("pm_history")
    if counts["weather_available_origin_count"] == 0:
        missing_families.append("forecast_weather")
    status = "ok" if not missing_families else "limited_diagnostic"
    manifest = {"feature_version": feature_version, "cutoff": iso(cutoff), "start": iso(start), "end": iso(end),
        "bundle_sha256": bundle["bundle_sha256"], "bundle_file_sha256": bundle_file_sha256,
        "input_manifest_sha256": digest(manifest_in), "schema_revision": manifest_in["schema_revision"],
        "input_integrity": {"verified": True, **{f"{key}_sha256": digest(dataset[key])
            for key in ("measurements", "snapshots", "model_values")}},
        "configuration_sha256": manifest_in["configuration_sha256"], "extract_query_sha256": manifest_in["query_sha256"],
        "boundary": {"mode": "frozen" if require_frozen_boundary else "explicit",
                     "frozen_boundary_applied": bool(require_frozen_boundary),
                     "frozen_values": {"cutoff": FROZEN_CUTOFF, "start": FROZEN_START, "end": FROZEN_END}},
        "history_start": iso(history_start), "warmup_hours": WARMUP_HOURS,
        "warmup_selected_rows_by_sensor": warmup_rows_by_sensor,
        "config_validation": {"mode": "reviewed_config" if reviewed is not None else "none",
                              "reviewed_sha256": digest(reviewed) if reviewed is not None else None,
                              "forecast_model_key": forecast_model_key,
                              "variable_registry_verified": reviewed is not None,
                              "sensor_registry_verified": reviewed is not None,
                              "location_registry_verified": reviewed is not None},
        "availability_basis": availability_basis,
        "availability_assumption": assumed_lag_hours if availability_basis == "assumed" else None,
        "availability_policy": FEATURE_POLICY, "source_policy": SOURCE_POLICY, "target_contract": TARGET_CONTRACT,
        "status_policy": STATUS_POLICY,
        "horizons": horizons, "origin_start": iso(origins[0]), "origin_end": iso(origins[-1]),
        "origin_count": len(origins),
        "split": {"validation_start": iso(validation_start), "test_start": iso(test_start),
                  "fractions": SPLIT_FRACTIONS, "shared_across_sensors_and_horizons": True},
        "weather_variables": weather_codes,
        "snapshot_rejections": snapshot_rejection_reasons,
        "catalog": {"pm_lag_hours": list(PM_LAG_HOURS), "trailing_hours": list(TRAILING_HOURS),
                    "weather_prefix": "weather_forecast_", "wind_direction": "sin/cos components only",
                    "trailing_means": "strict: null unless every expected hourly observation is accepted",
                    "trailing_std": "sample standard deviation over the strict 24h window",
                    "warmup": "full 72h lag/trailing catalog is attempted at every origin; missing warm-up rows stay null with coverage flags"},
        "status": status, "status_missing_families": missing_families,
        "prospective_collection_period_required": status == "limited_diagnostic",
        "future_evidence_rejections": 0,
        "measurement_rows_never_eligible": never_eligible_measurements,
        "forecast_snapshots_never_eligible": never_eligible_snapshots,
        "ambiguous_vintage_rejections": ambiguous_vintages, "counts": counts,
        "implementation_sha256": {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                                  for name in ("features.py", "features_output.py")},
        "limitations": LIMITATIONS}
    return {"feature_version": feature_version, "availability_basis": availability_basis,
            "availability_assumption": assumed_lag_hours if availability_basis == "assumed" else None,
            "manifest": manifest, "manifest_sha256": digest(manifest),
            "rows": rows, "targets": targets, "lineage": lineage}


def require_frozen_boundary_apply(bundle):
    manifest = bundle["manifest"]
    for key, frozen in (("cutoff", FROZEN_CUTOFF), ("start", FROZEN_START), ("end", FROZEN_END)):
        if instant(manifest[key]) != instant(frozen):
            raise FeatureError(f"Feature bundle {key} differs from the frozen Phase 7 boundary")


def _check_leakage(lineage_row, origin, availability_basis, assumed_lag_hours):
    if availability_basis == "captured":
        stamps = [instant(lineage_row[key]) for key in
                  ("pm_max_recorded_at", "pm_max_retrieved_at", "weather_max_recorded_at",
                   "weather_max_retrieved_at", "weather_max_value_recorded_at",
                   "weather_run_initialized_at", "weather_source_published_at") if lineage_row.get(key)]
        if any(stamp >= origin for stamp in stamps):
            raise FeatureError("Future evidence in feature lineage; refusing to emit the row")
    else:
        if lineage_row.get("pm_available_through") is not None \
                and instant(lineage_row["pm_available_through"]) + timedelta(hours=assumed_lag_hours) >= origin:
            raise FeatureError("Assumed-lag violation for measured history; refusing to emit the row")
        if lineage_row.get("weather_run_initialized_at") is not None \
                and instant(lineage_row["weather_run_initialized_at"]) + timedelta(hours=assumed_lag_hours) >= origin:
            raise FeatureError("Assumed-lag violation for forecast vintage; refusing to emit the row")


LIMITATIONS = [
    "Feature availability uses evidence timestamps; the schema has no exact transaction commit time, so captured eligibility is a conservative policy, not proof of as-issued provider availability.",
    "The Phase 3 historical backfill was retrieved after the historical period; captured mode therefore yields a limited diagnostic artifact until a prospective collection period exists.",
    "ERA5 reanalysis and CAMS modeled air quality are excluded from the captured measured-target feature matrix.",
    "Targets are evaluation labels stored separately; they never enter feature lineage, and unaccepted target values are stored as null labels with explicit reasons.",
    "Assumed-mode rows and lineage records carry later backfill storage timestamps by design; they are declared scenarios, never operational evidence.",
    "No model is trained here; no forecast-skill, causal, city-wide or operational claim is supported.",
]
