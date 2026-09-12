#!/usr/bin/env python3
"""Build public Phase 10 JSON from pinned, frozen Phase 5--9 artifacts.

Standard library only: no application/model imports, fitting, database, network,
environment loading or source-data writes. Existing destinations are never
replaced. The shared Phase 10 contract defines the public field allowlists.
"""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat


SCHEMA_VERSION = "phase10_dashboard_v1"
OUTPUT_NAME = "dashboard.json"
PHASE5 = Path("docs/verification/phase_5_eda_2026-09-07_final")
PHASE6 = Path("docs/verification/phase_6_statistics_2026-09-09_corrected")
PHASE7 = Path("docs/verification/phase_7_features_2026-09-10_structural_hardened")
PHASE8 = Path("docs/verification/phase_8_baselines_2026-09-11_v2_verified")
PHASE9 = Path("docs/verification/phase_9_models_2026-09-12_comparison_hardened")

# File-byte digests of SUCCESS.json, NOT their embedded manifest identities.
# Altering a payload and re-signing its manifest cannot change this trust root.
EXPECTED_SUCCESS = {
    PHASE5: "e32a3ae84bf236504c4b183e277beccbc9682f4811f2e5c8956975f9ac3c4e89",
    PHASE6: "017a901cb68a58f06e7fbc68e81bc17d76b4db675fe0032109907ec38a3bb4f3",
    PHASE7: "a7ea4cb56d378766ca83561d9e290bec3703ac161b88f69d4200ff155fbd2297",
    PHASE8: "d178890fa503752e03ee09cd2d9633d1bcfc76af9d8f3365a02d63e5d06da336",
    PHASE9: "68bdad7e7cc244bde48899b9fbb9934fbba8604aa9c11634d78a705945bcadad",
}
# The sole reviewed exception is a non-consumed documentation file. Keep all
# four coordinates explicit: repository-relative directory, filename, declared
# digest and observed digest, under the unchanged Phase 5 SUCCESS trust root.
PHASE5_README_DECLARED = "f6e76ba8011e6657c3894124639c7789806a17db9097dc4b82a5921f24d625cd"
PHASE5_README_OBSERVED = "f5de669c0c37f0f3d4e9fd7a02c0c4c21540f233397f34fbbb234082d0e68988"
PHASE5_README_REASON = (
    "Reviewed pre-existing documentation-only mismatch: the committed README ends in LF; "
    "one additional trailing LF would match its declared hash. The file is hashed but "
    "not consumed, normalized or rewritten. All displayed data are strictly verified; "
    "the complete Phase 5 artifact is not fully verified."
)
EXPECTED_IDENTITY = {
    PHASE5: "92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63",
    PHASE6: "71f7b17bff4bd43a406d235bbc585a268ec56b07f2554cc2b19939b5b5dcf918",
    PHASE7: "6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa",
    PHASE8: "ec651c4df04cb605f8849c1af96a3aea58f0902370e16ec39b9c48fdee22775e",
    PHASE9: "378f2e7f34476fe885ce6ec9827b7a48c346706f36b548fbc8db78ce94d8a770",
}
SUMMARIES = {
    PHASE5: "eda_bundle.json",
    PHASE6: "phase_6_statistics_summary.json",
    PHASE7: "phase_7_feature_summary.json",
    PHASE8: "phase_8_baselines_summary.json",
    PHASE9: "phase_9_model_summary.json",
}
VERSIONS = {
    PHASE5: ("eda_version", "phase5_eda_v1"),
    PHASE6: ("stats_version", "phase6_statistics_v2"),
    PHASE7: ("feature_version", "phase7_features_v7"),
    PHASE8: ("baseline_version", "phase8_baselines_v2"),
    PHASE9: ("model_version", "phase9_ml_v4"),
}
PHASE_LABELS = {
    PHASE5: "Frozen EDA", PHASE6: "Pre-registered statistics",
    PHASE7: "Availability-aware features", PHASE8: "Chronological baselines",
    PHASE9: "Chronological ML",
}
START = "2026-06-08T00:00:00Z"
END = "2026-09-06T00:00:00Z"
CUTOFF = "2026-09-06T20:59:00.669630Z"
VIETNAM = timezone(timedelta(hours=7))
SENSORS = {
    "openaq_11357424": ("CMT8", "cmt8", "Ho Chi Minh City"),
    "openaq_14581375": ("OceanPark", "oceanpark", "Hanoi urban area"),
}
# Literal metadata from the reviewed registry; additionally reconciled to the
# authenticated Phase 5 bundle, without reading another configuration file.
WEATHER = {
    "apparent_temperature": ("Apparent temperature", "degC", "instant"),
    "cloud_cover": ("Cloud cover", "%", "instant"),
    "precipitation": ("Precipitation", "mm", "preceding_hour_sum"),
    "relative_humidity_2m": ("Relative humidity", "%", "instant"),
    "shortwave_radiation": ("Shortwave radiation", "W/m2", "preceding_hour_mean"),
    "surface_pressure": ("Surface pressure", "hPa", "instant"),
    "temperature_2m": ("Temperature", "degC", "instant"),
    "wind_direction_10m": ("Wind direction", "degree", "instant"),
    "wind_speed_10m": ("Wind speed", "m/s", "instant"),
}
PHASE5_CSV = (
    "daily.csv", "diurnal.csv", "weather_associations.csv",
    "cams_modeled_pm25.csv", "hourly_pm25_weather_grid.csv",
)
HOURLY_FIELDS = (
    "sensor_id", "period_start", "period_end", "local_date", "local_hour",
    "pm25", "quality",
)
DAILY_FIELDS = (
    "sensor_id", "local_date", "accepted_hours", "expected_hours",
    "full_local_day", "coverage_percent", "qualified_mean", "mean",
)
STATS_FIELDS = (
    "fit_id", "hypothesis", "exposure", "estimate", "ci_low", "ci_high",
    "p_value_adjusted", "inference", "scale", "scope", "role", "weather_case",
    "block_days", "n", "formula", "adjustment", "estimand", "standardization",
    "coverage", "nonempty_independent_blocks", "eligible_independent_blocks",
    "exclude_extreme",
)
SCORES = ("mae", "rmse", "mase", "smape", "mase_denominator",
          "mean_error", "median_absolute_error")
BASELINE_FIELDS = (
    "baseline_id", "baseline_role", "candidate_rows", "coverage_percent",
    "eligible_rows", "evaluation_type", "horizon_hours", "location_id",
    "metric_reason", "metric_scope", "metric_status", "missing_prediction_rows",
    "missing_target_rows", "predicted_rows", "purged_rows_excluded", "sensor_id",
    "split", "target_available_rows",
) + SCORES
ML_FIELDS = (
    "candidate_rows", "coverage_percent", "eligible_rows", "evaluation_type",
    "feature_set", "fit_partition", "horizon_hours", "incomplete_feature_rows",
    "incomplete_history_rows", "incomplete_weather_rows", "location_id",
    "metric_reason", "metric_scope", "metric_status", "model_family",
    "model_reason", "model_status", "purged_rows_excluded", "r2", "r2_reason",
    "scope", "sensor_id", "split", "target_transform", "unavailable_target_rows",
) + SCORES
COMPARISON_FIELDS = (
    "comparison_kind", "comparison_reason", "comparison_status",
    "counterpart_fit_key_digest", "counterpart_fit_partition", "feature_set",
    "fit_key_digest", "fit_partition", "history_status", "horizon_hours",
    "location_id", "metric_scope", "model_family", "model_finite_rows",
    "paired_key_digest", "paired_rows", "reference_baseline", "reference_finite_rows",
    "reference_fit_key_digest", "reference_fit_partition", "reference_fit_reason",
    "reference_fit_status", "reference_role", "scope", "sensor_id", "split",
    "target_transform", "mae_delta", "rmse_delta", "model_mae", "model_rmse",
    "reference_mae", "reference_rmse",
)
COMPARISON_SCORES = (
    "mae_delta", "rmse_delta", "model_mae", "model_rmse", "reference_mae", "reference_rmse",
)


class DashboardBuildError(ValueError):
    """An input failed the frozen trust boundary or output contract."""


def require(condition, message):
    if not condition:
        raise DashboardBuildError(message)


def fields(value, required, label):
    require(type(value) is dict, f"{label} must be an object")
    require(set(required) <= set(value), f"{label} is missing required fields")
    return value


def rows(value, label):
    require(type(value) is list, f"{label} must be an array")
    require(all(type(row) is dict for row in value), f"{label} contains a non-object")
    return value


def validate_finite(value):
    """Also reject exponent overflow such as 1e999, not just NaN literals."""
    if type(value) is float:
        require(math.isfinite(value), "Non-finite numeric value")
    elif type(value) is dict:
        for child in value.values():
            validate_finite(child)
    elif type(value) is list:
        for child in value:
            validate_finite(child)


def canonical(value):
    validate_finite(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError) as error:
        raise DashboardBuildError("Invalid canonical JSON value") from error


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def strict_json(data):
    """Parse verified bytes, rejecting ambiguous or non-finite JSON."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def bad_constant(_value):
        raise DashboardBuildError("Non-finite JSON token")

    try:
        value = json.loads(data, object_pairs_hook=unique, parse_constant=bad_constant)
        validate_finite(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise DashboardBuildError("Malformed JSON") from error


def number(value):
    if value is None or value == "":
        return None
    require(type(value) in (str, int, float), "Invalid numeric type")
    try:
        result = float(value)
    except (ValueError, OverflowError) as error:
        raise DashboardBuildError("Invalid numeric value") from error
    require(math.isfinite(result), "Non-finite numeric value")
    return result


def integer(value):
    require(type(value) in (str, int), "Invalid integer type")
    require(re.fullmatch(r"[0-9]+", str(value)) is not None, "Invalid count")
    return int(value)


def boolean(value):
    require(value in ("True", "False"), "Invalid CSV boolean")
    return value == "True"


def safe_name(name):
    # Artifact files are flat. Reject URI/drive paths, encoded traversal,
    # dotfiles (including .env), separators, controls and SUCCESS self-reference.
    require(type(name) is str and
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) is not None and
            name != "SUCCESS.json", "Unsafe payload path")


def sha_text(value):
    require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
            "Invalid SHA-256")


def checked_directory(path):
    """Reject symlink components, including artifact/output parent directories."""
    path = Path(path).absolute()
    for part in (path, *path.parents):
        require(not part.is_symlink(), "Symlink directory is not permitted")
    require(path.is_dir(), "Missing directory")
    return path


def read_regular(path):
    # O_NONBLOCK avoids blocking on special files; O_NOFOLLOW protects the leaf
    # if it is replaced between the path check and open.
    require(not path.is_symlink(), "Symlink input is not permitted")
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), "Input is not a regular file")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            return handle.read()
    except OSError as error:
        raise DashboardBuildError("Missing or unreadable artifact file") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def verify_artifact(root, expected_success, required_files=(), *, repo_root=None):
    """Hash every declared file; retain verified selected bytes for parsing.

    The bytes passed to parsers are the same bytes that were authenticated.
    No payload path is used before the entire manifest path/hash map is checked.
    """
    root = checked_directory(root)
    repo_root = checked_directory(repo_root if repo_root is not None else
                                  Path(__file__).resolve().parents[1])
    sha_text(expected_success)
    success_bytes = read_regular(root / "SUCCESS.json")
    require(hashlib.sha256(success_bytes).hexdigest() == expected_success,
            "Pinned SUCCESS.json hash mismatch")
    success = fields(strict_json(success_bytes), ("files_sha256",), "SUCCESS")
    declared = success["files_sha256"]
    require(type(declared) is dict and declared, "Missing payload hash map")
    for name, expected in declared.items():
        safe_name(name)
        sha_text(expected)
    require(set(required_files) <= set(declared), "Required payload is not declared")
    try:
        entries = list(root.iterdir())
    except OSError as error:
        raise DashboardBuildError("Unreadable artifact directory") from error
    require({entry.name for entry in entries} == set(declared) | {"SUCCESS.json"},
            "Artifact payload set mismatch")
    selected, verified, exceptions = {}, {}, []
    for name in sorted(declared):
        content = read_regular(root / name)
        observed = hashlib.sha256(content).hexdigest()
        if root == repo_root / PHASE5 and name == "README.md":
            # This branch deliberately precedes normal equality: even a changed
            # README whose bytes match the old declaration is a different state
            # from the exact reviewed exception and must fail closed.
            require(expected_success ==
                    "e32a3ae84bf236504c4b183e277beccbc9682f4811f2e5c8956975f9ac3c4e89"
                    and declared[name] == PHASE5_README_DECLARED
                    and observed == PHASE5_README_OBSERVED,
                    "Phase 5 README does not match the exact reviewed exception")
            require(name not in required_files, "Excepted README must never be consumed")
            exceptions.append({"file": name, "declared_sha256": declared[name],
                               "observed_sha256": observed, "reason": PHASE5_README_REASON})
            continue
        require(observed == declared[name], "Declared payload hash mismatch")
        verified[name] = observed
        if name in required_files or name.endswith(".json"):
            selected[name] = content
    return success, selected, {"files_sha256": verified, "integrity_exceptions": exceptions}


def parse_summary(rel, success, content):
    summary = fields(strict_json(content), ("manifest",), "Phase summary")
    manifest = fields(summary["manifest"], (VERSIONS[rel][0],), "Phase manifest")
    version_key, expected_version = VERSIONS[rel]
    require(manifest[version_key] == expected_version, "Unexpected phase version")
    identity_key = "bundle_sha256" if rel == PHASE5 else "manifest_sha256"
    fields(success, (identity_key,), "SUCCESS")
    fields(summary, (identity_key,), "Phase summary")
    actual = (digest({key: value for key, value in summary.items() if key != identity_key})
              if rel == PHASE5 else digest(manifest))
    require(actual == summary[identity_key] == success[identity_key] == EXPECTED_IDENTITY[rel],
            "Canonical phase identity mismatch")
    if rel != PHASE5:
        require(success.get(version_key) == expected_version, "SUCCESS version mismatch")
    if rel == PHASE9:
        require(summary.get(version_key) == expected_version and
                manifest.get("revision") == "comparison_hardened", "Phase 9 revision mismatch")
    return summary


def read_csv(data, required):
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8"), newline=""), strict=True)
        names = reader.fieldnames
        require(names and all(names) and len(names) == len(set(names)), "Invalid CSV header")
        require(set(required) <= set(names), "Missing required CSV column")
        result = list(reader)
        require(all(None not in row and None not in row.values() for row in result),
                "Malformed CSV row")
        return result
    except (UnicodeError, csv.Error) as error:
        raise DashboardBuildError("Malformed CSV") from error


def timestamp(value):
    require(type(value) is str, "Timestamp must be text")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DashboardBuildError("Malformed timestamp") from error
    require(result.utcoffset() == timedelta(0), "Timestamp must be UTC")
    return result


def select(row, allowed, optional=()):
    fields(row, set(allowed) - set(optional), "Public source record")
    return {key: row.get(key) for key in allowed}


def sensor_identity(sensor_id, location=None, pooled=False):
    if pooled and sensor_id == "pooled":
        require(location in (None, "pooled"), "Pooled identity mismatch")
    else:
        require(sensor_id in SENSORS, "Unknown measured sensor")
        if location is not None:
            require(location == SENSORS[sensor_id][1], "Sensor/location mismatch")


def measured_data(bundle, csvs):
    dataset = fields(bundle.get("dataset"), ("sensors", "rows", "weather_variables",
                                            "cams_modeled_pm25"), "Phase 5 dataset")
    registry = fields(dataset["sensors"], SENSORS, "Sensor registry")
    require(set(registry) == set(SENSORS), "Unexpected sensor registry")
    sensors = []
    for sensor_id, (name, location, region) in SENSORS.items():
        meta = fields(registry[sensor_id], ("name", "location_id", "attribution", "licence_url"),
                      "Sensor metadata")
        require(meta["name"] == name and meta["location_id"] == location,
                "Reviewed sensor metadata mismatch")
        require(type(meta["attribution"]) is str and meta["attribution"] and
                meta["licence_url"] == "https://creativecommons.org/licenses/by/4.0/",
                "Missing reviewed attribution/licence")
        sensors.append({"id": sensor_id, "name": name, "location_id": location, "region": region,
                        "attribution": meta["attribution"], "licence_url": meta["licence_url"]})
    weather_registry = fields(dataset["weather_variables"], WEATHER, "Weather registry")
    require(set(weather_registry) == set(WEATHER), "Unexpected weather registry")
    weather_variables = []
    for code, (label, unit, support) in WEATHER.items():
        require(weather_registry[code] == {"unit": unit, "temporal_support": support},
                "Weather unit/support mismatch")
        weather_variables.append({"code": code, "label": label, "unit": unit,
                                  "temporal_support": support, "source": "ERA5_reanalysis"})
    hourly = []
    seen = set()
    for row in rows(dataset["rows"], "Hourly grid"):
        item = select(row, HOURLY_FIELDS)
        sensor_identity(row["sensor_id"], row.get("location_id"))
        start, end = timestamp(row["period_start"]), timestamp(row["period_end"])
        local = start.astimezone(VIETNAM)
        require(timestamp(START) <= start < timestamp(END) and end - start == timedelta(hours=1)
                and start.minute == start.second == start.microsecond == 0,
                "Invalid measured interval")
        require(row["local_date"] == local.date().isoformat() and
                type(row["local_hour"]) is int and row["local_hour"] == local.hour,
                "Vietnam-local measured interval mismatch")
        key = (row["sensor_id"], row["period_start"])
        require(key not in seen, "Duplicate measured interval")
        seen.add(key)
        value = number(row["pm25"])
        require((row["quality"] == "accepted" and value is not None and value >= 0) or
                (row["quality"] in {"absent", "missing", "invalid", "suspect"} and value is None),
                "Measured value/quality mismatch")
        item["pm25"] = value
        weather = fields(row.get("weather"), WEATHER, "Hourly weather")
        require(set(weather) == set(WEATHER), "Unexpected hourly weather")
        item["weather"], item["weather_quality"] = {}, {}
        for code in WEATHER:
            source = fields(weather[code], ("quality", "value"), "Weather value")
            value = number(source["value"])
            require((source["quality"] == "accepted" and value is not None) or
                    (source["quality"] in {"absent", "missing", "invalid", "suspect"} and value is None),
                    "Weather value/quality mismatch")
            item["weather"][code] = value
            item["weather_quality"][code] = source["quality"]
        hourly.append(item)
    require(len(hourly) == 4320 and Counter(row["sensor_id"] for row in hourly) ==
            Counter({sensor: 2160 for sensor in SENSORS}), "Frozen hourly count mismatch")
    require(Counter(row["quality"] for row in hourly) ==
            Counter({"accepted": 4191, "absent": 129}), "Frozen quality counts mismatch")

    # Cross-check the independent hourly CSV, retaining only its safe fields.
    csv_hourly = read_csv(csvs["hourly_pm25_weather_grid.csv"], HOURLY_FIELDS)
    require(len(csv_hourly) == len(hourly), "Hourly CSV count mismatch")
    for source, item in zip(csv_hourly, hourly):
        for key in HOURLY_FIELDS:
            actual = (number(source[key]) if key == "pm25" else
                      integer(source[key]) if key == "local_hour" else source[key])
            require(actual == item[key], "Hourly CSV/bundle mismatch")

    daily = []
    groups = defaultdict(list)
    for item in hourly:
        groups[(item["sensor_id"], item["local_date"])].append(item)
    seen_daily = set()
    for source in read_csv(csvs["daily.csv"], DAILY_FIELDS):
        item = select(source, DAILY_FIELDS)
        sensor_identity(item["sensor_id"])
        key = (item["sensor_id"], item["local_date"])
        require(key in groups and key not in seen_daily, "Duplicate or unknown daily key")
        seen_daily.add(key)
        for field in ("accepted_hours", "expected_hours"):
            item[field] = integer(item[field])
        for field in ("mean", "qualified_mean", "coverage_percent"):
            item[field] = number(item[field])
        item["full_local_day"] = boolean(item["full_local_day"])
        group = groups[key]
        accepted = sum(row["pm25"] is not None for row in group)
        require(item["expected_hours"] == len(group) and item["accepted_hours"] == accepted and
                item["full_local_day"] == (len(group) == 24), "Daily coverage mismatch")
        require(math.isclose(item["coverage_percent"], accepted / len(group) * 100,
                             rel_tol=1e-12, abs_tol=1e-12),
                "Daily coverage percent mismatch")
        qualified = item["full_local_day"] and accepted >= 18
        require(item["qualified_mean"] == (item["mean"] if qualified else None),
                "Daily qualification mismatch")
        require((item["mean"] is None) == (accepted == 0), "Daily missingness mismatch")
        daily.append(item)
    require(seen_daily == set(groups) and len(daily) == 182, "Daily grid incomplete")

    diurnal = []
    for source in read_csv(csvs["diurnal.csv"], ("sensor_id", "local_hour", "n", "mean")):
        sensor_identity(source["sensor_id"])
        diurnal.append({"sensor_id": source["sensor_id"], "local_hour": integer(source["local_hour"]),
                        "n": integer(source["n"]), "mean": number(source["mean"])})
    require(len(diurnal) == 48 and {(row["sensor_id"], row["local_hour"]) for row in diurnal} ==
            {(sensor, hour) for sensor in SENSORS for hour in range(24)}, "Diurnal grid mismatch")

    associations = []
    for source in read_csv(csvs["weather_associations.csv"], ("sensor_id", "variable", "n", "pearson_r")):
        sensor_identity(source["sensor_id"])
        require(source["variable"] in set(WEATHER) - {"wind_direction_10m"},
                "Unexpected Pearson variable")
        associations.append({"sensor_id": source["sensor_id"], "variable": source["variable"],
                             "n": integer(source["n"]), "pearson_r": number(source["pearson_r"])})
    require(len(associations) == 16, "Association count mismatch")
    return sensors, weather_variables, hourly, daily, diurnal, associations


def aggregate_cams(source_rows):
    """Observed modeled values only, grouped independently by location/date.

    A group containing only nulls is retained with n=0 and mean=null. Genuine
    zeros count as observations. No measured target or source_value fallback.
    """
    groups = defaultdict(list)
    for source in source_rows:
        fields(source, ("location_id", "local_date", "value", "quality"), "CAMS row")
        require(source["location_id"] in {"hanoi", "hcmc", "da_nang"}, "Unknown CAMS location")
        key = (source["location_id"], source["local_date"])
        group = groups[key]
        value = number(source["value"])
        require(source["quality"] in {"accepted", "absent", "missing", "invalid", "suspect"},
                "Unknown CAMS quality")
        require(source["quality"] == "accepted" or value is None, "CAMS value/quality mismatch")
        if value is not None:
            group.append(value)
    return [{"location_id": location, "local_date": date, "n": len(values),
             "mean": math.fsum(values) / len(values) if values else None}
            for (location, date), values in sorted(groups.items())]


def select_statistics(summary):
    result = []
    optional = {"ci_low", "ci_high", "p_value_adjusted", "adjustment"}
    for source in rows(summary.get("results"), "Statistics results"):
        item = select(source, STATS_FIELDS, optional)
        fields(item["standardization"], ("day_center",), "Statistics standardization")
        require(set(item["standardization"]) <= {"day_center", "exposure_mean", "exposure_sd"},
                "Unsafe statistics standardization")
        coverage_keys = {"absent_hours", "accepted_hours", "coverage_percent", "eligible_hours",
                         "expected_hours", "extreme_flagged_hours", "weather_complete_hours"}
        require(type(item["coverage"]) is dict and set(item["coverage"]) == coverage_keys,
                "Unsafe statistics coverage")
        require(item["inference"] in {"inferential", "exploratory", "descriptive_only"},
                "Unknown inference label")
        if item["inference"] == "inferential":
            require(number(item["p_value_adjusted"]) is not None and
                    item["adjustment"] in {"Holm over the two primary hypotheses",
                                          "Benjamini-Hochberg over the five declared secondary exposures"},
                    "Inferential result lacks reviewed adjustment")
        require(type(item["exclude_extreme"]) is bool, "Invalid extreme-value indicator")
        result.append(item)
    require(len(result) == 31, "Statistics result count mismatch")
    return result


def select_metrics(manifest, allowed, expected_count):
    result = []
    for source in rows(manifest.get("metrics"), "Metrics"):
        item = select(source, allowed, SCORES)
        sensor_identity(item["sensor_id"], item["location_id"], pooled=True)
        require(item["metric_scope"] == "descriptive_only", "Metric inference is not permitted")
        require(item["metric_status"] in {"available", "unavailable"}, "Unknown metric status")
        require(item["horizon_hours"] in (6, 24) and item["split"] in {"train", "validation", "test"},
                "Invalid metric horizon/split")
        if item["metric_status"] == "unavailable":
            require(item["metric_reason"] and all(item[field] is None for field in SCORES),
                    "Unavailable metric has no reason or has scores")
        else:
            require(item["metric_reason"] is None and
                    all(number(item[field]) is not None for field in ("mae", "rmse")),
                    "Available metric is missing scores")
        result.append(item)
    require(len(result) == expected_count, "Metric count mismatch")
    return result


def select_comparisons(manifest):
    result = []
    for source in rows(manifest.get("comparisons"), "Comparisons"):
        item = select(source, COMPARISON_FIELDS, COMPARISON_SCORES)
        sensor_identity(item["sensor_id"], item["location_id"], pooled=True)
        require(item["metric_scope"] == "descriptive_only", "Comparison inference is not permitted")
        require(item["history_status"] in {"not_paired", "not_applicable", "unknown",
                                          "training_history_mismatch", "matched"},
                "Unknown comparison history status")
        require(item["comparison_status"] in {"paired", "not_paired"}, "Unknown comparison status")
        if item["comparison_status"] == "not_paired":
            require(item["paired_rows"] == 0 and item["comparison_reason"] and
                    all(item[field] is None for field in COMPARISON_SCORES),
                    "Unpaired comparison has scores or lacks reason")
        result.append(item)
    require(len(result) == 360, "Comparison count mismatch")
    return result


def validate_chain(summaries, successes):
    """Bind summaries to their independently authenticated upstream artifacts."""
    p5, p6, p7, p8, p9 = (summaries[rel]["manifest"] for rel in SUMMARIES)
    for manifest in (p5, p6, p7):
        for field, expected in (("start", START), ("end", END), ("cutoff", CUTOFF)):
            require(timestamp(manifest.get(field)) == timestamp(expected), "Frozen boundary mismatch")
    require(p6.get("phase5_bundle_sha256") == EXPECTED_IDENTITY[PHASE5] and
            p6.get("phase5_bundle_file_sha256") == successes[PHASE5]["files_sha256"][SUMMARIES[PHASE5]]
            and p6.get("phase5_manifest_sha256") == digest(p5), "Phase 6 input binding mismatch")
    require(successes[PHASE7].get("bundle_sha256") == p7.get("bundle_sha256") and
            successes[PHASE7].get("availability_basis") == p7.get("availability_basis") == "captured",
            "Phase 7 availability/bundle mismatch")
    require(p7.get("prospective_collection_period_required") is True and
            p7.get("status_missing_families") == ["pm_history", "forecast_weather"],
            "Phase 7 diagnostic contract mismatch")
    for manifest in (p7, p8, p9):
        require(manifest.get("status") == "limited_diagnostic" and manifest.get("horizons") == [6, 24],
                "Diagnostic status/horizons mismatch")
    require(p8.get("input_success_sha256") == EXPECTED_SUCCESS[PHASE7] and
            p8.get("input_manifest_sha256") == EXPECTED_IDENTITY[PHASE7] and
            p8.get("input_summary_sha256") == successes[PHASE7]["files_sha256"][SUMMARIES[PHASE7]] and
            p8.get("input_feature_version") == p7["feature_version"] and
            p8.get("availability_basis") == "captured", "Phase 8 input binding mismatch")
    reference7 = fields(p9.get("phase7"), ("manifest_sha256", "split", "counts"), "Phase 9 Phase 7")
    reference8 = fields(p9.get("phase8_reference"), ("manifest_sha256",), "Phase 9 Phase 8")
    for rel, reference in ((PHASE7, reference7), (PHASE8, reference8)):
        require(reference.get("manifest_sha256") == EXPECTED_IDENTITY[rel] and
                reference.get("success_sha256") == EXPECTED_SUCCESS[rel] and
                reference.get("observed_payload_sha256") == successes[rel]["files_sha256"] and
                reference.get("expected_payload_sha256") == successes[rel]["files_sha256"],
                "Phase 9 upstream payload binding mismatch")
    require(digest(p7["split"]) == digest(p8["split"]) == digest(reference7["split"]) and
            digest(p7["counts"]) == digest(reference7["counts"]), "Phase 7 summary binding mismatch")
    require(p9.get("prospective_collection_period_required") is True and
            p9.get("test_selection_used") is False and p8.get("test_selection_used") is False,
            "Diagnostic selection contract mismatch")


def build_payload(repo_root):
    """Authenticate all artifacts and return only the reviewed public contract."""
    repo_root = checked_directory(repo_root)
    successes, contents, verifications = {}, {}, {}
    for rel, summary_name in SUMMARIES.items():
        required = (summary_name, *PHASE5_CSV) if rel == PHASE5 else (summary_name,)
        successes[rel], contents[rel], verifications[rel] = verify_artifact(
            repo_root / rel, EXPECTED_SUCCESS[rel], required, repo_root=repo_root)
    # Every phase is authenticated before any selected data is parsed.
    for selected in contents.values():
        for name, content in selected.items():
            if name.endswith(".json"):
                strict_json(content)
    summaries = {rel: parse_summary(rel, successes[rel], contents[rel][name])
                 for rel, name in SUMMARIES.items()}
    validate_chain(summaries, successes)
    bundle = summaries[PHASE5]
    sensors, weather_variables, hourly, daily, diurnal, associations = measured_data(
        bundle, contents[PHASE5])
    cams_rows = read_csv(contents[PHASE5]["cams_modeled_pm25.csv"],
                         ("location_id", "local_date", "quality", "valid_at", "value"))
    require(len(cams_rows) == 6480, "Frozen CAMS row count mismatch")
    bundled_cams = rows(bundle["dataset"]["cams_modeled_pm25"], "CAMS bundle")
    require(len(cams_rows) == len(bundled_cams), "CAMS bundle/CSV count mismatch")
    for source, bundled in zip(cams_rows, bundled_cams):
        for key in ("location_id", "local_date", "quality", "valid_at", "value"):
            actual = number(source[key]) if key == "value" else source[key]
            require(actual == bundled.get(key), "CAMS bundle/CSV mismatch")
        require(source["local_date"] == timestamp(source["valid_at"]).astimezone(VIETNAM).date().isoformat(),
                "CAMS local date mismatch")
    cams_daily = aggregate_cams(cams_rows)
    require(len(cams_daily) == 273, "CAMS daily count mismatch")
    p6, p7, p8, p9 = (summaries[rel]["manifest"] for rel in (PHASE6, PHASE7, PHASE8, PHASE9))
    statistics_results = select_statistics(summaries[PHASE6])
    baseline_metrics = select_metrics(p8, BASELINE_FIELDS, 90)
    ml_metrics = select_metrics(p9, ML_FIELDS, 288)
    comparisons = select_comparisons(p9)
    require(sum(row["metric_status"] == "available" for row in baseline_metrics) == 18,
            "Frozen baseline availability count mismatch")
    require(p9["counts"]["metric_cells"] == len(ml_metrics) and
            p9["counts"]["available_metric_cells"] ==
            sum(row["metric_status"] == "available" for row in ml_metrics) == 72 and
            p9["counts"]["comparison_records"] == len(comparisons), "Frozen ML count mismatch")
    limitations = [
        "Two non-reference sensor sites over one 90-day window, not city averages or population exposure.",
        "Missing measured hours remain null; no interpolation or replacement with modeled values.",
        "Hourly and qualified daily PM2.5 are ug/m3; CAMS daily means are separate modeled ug/m3 context.",
        "Diurnal profiles and Pearson associations are exploratory full-window summaries, unaffected by date filters.",
        "Phase 6 estimates are fixed-window sensor-level associations; only Holm/BH-adjusted results are inferential.",
        "Captured PM/history and forecast-weather features are unavailable in the frozen historical window; a prospective collection period is required.",
        "Baseline and ML scores are fixed-window descriptive calendar diagnostics, not forecast skill, causal findings, health advice or operational readiness.",
        "Pooled diagnostic results combine two sensor sites descriptively; test comparisons may have different model/reference fitting histories.",
    ]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "meta": {
            "title": "Vietnam Air Observatory", "status": "limited_diagnostic",
            "window": {
                "start_utc": START, "end_utc": END, "cutoff_utc": CUTOFF,
                "local_start": timestamp(START).astimezone(VIETNAM).isoformat(),
                "local_end": timestamp(END).astimezone(VIETNAM).isoformat(),
                "timezone": "Asia/Ho_Chi_Minh",
            },
            "daily_policy": bundle["manifest"]["policy"]["daily_mean"],
            "limitations": limitations,
            "integrity_notes": [
                f"{rel.as_posix()}/{exception['file']}: {exception['reason']}"
                for rel in SUMMARIES for exception in verifications[rel]["integrity_exceptions"]
            ],
            "source_policy": (
                "OpenAQ/AirGradient measured PM2.5 (ug/m3) is the target, not a city mean. "
                "Open-Meteo/ERA5 is retrospective weather context: instantaneous variables align "
                "to PM interval start; preceding-hour precipitation sums and radiation means "
                "align to interval end. CAMS via Open-Meteo is separate modeled PM2.5 context; "
                "Da Nang is modeled-only. Provider forecasts are not ground truth and ERA5/CAMS "
                "never replace measured values or captured forecast features."
            ),
        },
        "sensors": sensors, "hourly": hourly, "weather_variables": weather_variables,
        "daily": daily, "diurnal": diurnal, "weather_associations": associations,
        "cams_daily": cams_daily,
        "statistics": {"version": p6["stats_version"], "results": statistics_results,
                       "limitations": summaries[PHASE6]["limitations"]},
        "features": {"version": p7["feature_version"], "status": p7["status"],
                     "missing_families": p7["status_missing_families"], "counts": p7["counts"],
                     "prospective_collection_period_required": True, "split": p7["split"]},
        "baselines": {"version": p8["baseline_version"], "status": p8["status"],
                      "metrics": baseline_metrics, "split": p8["split"]},
        "ml": {"version": p9["model_version"], "status": p9["status"], "counts": p9["counts"],
               "metrics": ml_metrics, "comparisons": comparisons, "split": p7["split"]},
        "provenance": [
            {"phase": phase, "label": PHASE_LABELS[rel], "directory": rel.as_posix(),
             "identity": EXPECTED_IDENTITY[rel], **verifications[rel]}
            for phase, rel in zip(range(5, 10), SUMMARIES)
        ],
    }
    payload["bundle_sha256"] = digest(payload)
    return payload


def preflight_output(output):
    output = Path(output).absolute()
    require(not output.is_symlink() and not output.exists(), "Dashboard output must be new")
    checked_directory(output.parent)
    return output


def write_bundle(output, payload):
    """Exclusive create; validate serialization and digest before opening."""
    output = preflight_output(output)
    fields(payload, ("schema_version", "bundle_sha256"), "Dashboard payload")
    require(payload["schema_version"] == SCHEMA_VERSION and payload["bundle_sha256"] ==
            digest({key: value for key, value in payload.items() if key != "bundle_sha256"}),
            "Dashboard bundle identity mismatch")
    encoded = canonical(payload) + b"\n"
    try:
        with output.open("xb") as handle:
            handle.write(encoded)
    except OSError as error:
        raise DashboardBuildError("Cannot exclusively create dashboard output") from error
    return {"output": str(output), "bundle_sha256": payload["bundle_sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    output = args.output or args.repo_root / "dashboard/data/dashboard.json"
    try:
        preflight_output(output)  # Must precede even the first input read.
        payload = build_payload(args.repo_root)
        print(json.dumps(write_bundle(output, payload), sort_keys=True))
        return 0
    except (DashboardBuildError, OSError):
        # No raw source values, paths or exceptions are printed.
        print("Dashboard build rejected: invalid input integrity/schema or unavailable new output.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
