"""Phase 8 reproducible chronological PM2.5 baselines.

The runner consumes a Phase 7 artifact directory only.  It never opens a
database, never fills missing feature values and never selects a model from the
test period.  Calendar-only diagnostics may be computed when captured data
features are absent, but the artifact remains explicitly limited.
"""

import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


BASELINES_VERSION = "phase8_baselines_v2"
HORIZONS = (6, 24)
SUMMARY_NAME = "phase_7_feature_summary.json"
FEATURES_NAME = "phase_7_features.csv"
TARGETS_NAME = "phase_7_targets.csv"
SUCCESS_NAME = "SUCCESS.json"
OUTPUT_SUMMARY_NAME = "phase_8_baselines_summary.json"
OUTPUT_METRICS_NAME = "phase_8_baseline_metrics.csv"
OUTPUT_PREDICTIONS_NAME = "phase_8_predictions.csv"
OUTPUT_ASSUMPTIONS_NAME = "phase_8_assumptions.md"
OUTPUT_SUCCESS_NAME = "SUCCESS.json"
REQUIRED_FEATURE_FIELDS = ("sensor_id", "location_id", "origin", "horizon_hours",
                           "origin_local_hour", "target_start", "target_end", "split", "purged",
                           "target_available")
REQUIRED_TARGET_FIELDS = ("sensor_id", "location_id", "origin", "horizon_hours",
                          "target_available", "target_pm25", "target_quality",
                          "target_start", "target_end", "target_missing_reason")
WEATHER_META_FIELDS = {"weather_forecast_missing_count", "weather_forecast_reason",
                       "weather_forecast_run_provenance", "weather_forecast_snapshot_id"}
REQUIRED_PHASE7_HASHES = {SUMMARY_NAME, FEATURES_NAME, TARGETS_NAME}
ALLOWED_PHASE7_HASHES = REQUIRED_PHASE7_HASHES | {"phase_7_lineage.csv", "phase_7_assumptions.md"}
BASELINE_SPECS = [
    {"baseline_id": "persistence_last_available", "role": "primary_reference",
     "kind": "feature", "field": "pm25_last_available"},
    {"baseline_id": "persistence_lag_1h", "role": "sensitivity",
     "kind": "feature", "field": "pm25_lag_1h"},
    {"baseline_id": "trailing_mean_24h", "role": "sensitivity",
     "kind": "feature", "field": "pm25_trailing_mean_24h"},
    {"baseline_id": "local_hour_climatology", "role": "diagnostic_calendar",
     "kind": "local_hour_climatology", "field": None},
    {"baseline_id": "weather_augmented_climatology", "role": "diagnostic_weather",
     "kind": "weather_climatology", "field": None},
]


class BaselineError(ValueError):
    """Invalid or unsafe baseline input."""


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def sha256_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    body = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def read_metadata(path, label):
    """Read an unambiguous JSON object without duplicate keys or NaN tokens."""
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise BaselineError(f"{label} contains duplicate JSON keys")
            result[key] = value
        return result

    def reject_constant(value):
        raise BaselineError(f"{label} contains a non-finite JSON token")

    try:
        result = json.loads(Path(path).read_text(encoding="utf-8"),
                            object_pairs_hook=unique_keys, parse_constant=reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BaselineError(f"{label} is not valid JSON") from error
    if not isinstance(result, dict):
        raise BaselineError(f"{label} must be a JSON object")
    return result


def parse_float(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise BaselineError(f"Invalid numeric value: {value!r}") from None
    return number if math.isfinite(number) else None


def parse_bool(value):
    if value in (True, "True", "true", "1"):
        return True
    if value in (False, "False", "false", "0"):
        return False
    raise BaselineError(f"Invalid boolean value: {value!r}")


def parse_origin(value):
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise BaselineError(f"Invalid UTC origin: {value!r}") from None
    if moment.utcoffset() != timedelta(0):
        raise BaselineError("Origins must be timezone-aware UTC timestamps")
    return moment.astimezone(timezone.utc)


def read_csv(path, required_fields):
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise BaselineError(f"CSV header is missing or duplicated: {path.name}")
            missing = set(required_fields) - set(reader.fieldnames)
            if missing:
                raise BaselineError(f"{path.name} is missing fields: {sorted(missing)}")
            rows = list(reader)
    except OSError as error:
        raise BaselineError(f"Cannot read baseline input: {path.name}") from error
    return rows


def artifact_files(artifact_dir):
    if not artifact_dir.is_dir():
        raise BaselineError("Phase 7 artifact must be an existing directory")
    paths = {name: artifact_dir / name for name in (SUMMARY_NAME, FEATURES_NAME, TARGETS_NAME, SUCCESS_NAME)}
    if any(path.is_symlink() or not path.is_file() for path in paths.values()):
        raise BaselineError("Phase 7 artifact is missing a required summary, feature, target or SUCCESS file")
    return paths


def load_artifact(artifact_dir):
    paths = artifact_files(Path(artifact_dir))
    success = read_metadata(paths[SUCCESS_NAME], "Phase 7 SUCCESS.json")
    summary = read_metadata(paths[SUMMARY_NAME], "Phase 7 summary")
    manifest = summary.get("manifest")
    if not isinstance(manifest, dict):
        raise BaselineError("Phase 7 summary manifest must be a JSON object")
    declared_files = success.get("files_sha256")
    if not isinstance(declared_files, dict):
        raise BaselineError("Phase 7 SUCCESS.json has no file hash manifest")
    if not REQUIRED_PHASE7_HASHES.issubset(declared_files):
        raise BaselineError("Phase 7 SUCCESS.json omits a required baseline input hash")
    if not set(declared_files).issubset(ALLOWED_PHASE7_HASHES):
        raise BaselineError("Phase 7 SUCCESS.json contains an unrecognized artifact path")
    actual_files = {path.name for path in Path(artifact_dir).iterdir()
                    if path.is_file() and path.name != SUCCESS_NAME}
    if set(declared_files) != actual_files:
        raise BaselineError("Phase 7 SUCCESS.json file manifest does not match the artifact directory")
    if success.get("feature_version") != manifest.get("feature_version"):
        raise BaselineError("Phase 7 SUCCESS feature version does not match its summary")
    if success.get("bundle_sha256") != manifest.get("bundle_sha256"):
        raise BaselineError("Phase 7 SUCCESS bundle digest does not match its summary")
    if success.get("availability_basis") != manifest.get("availability_basis"):
        raise BaselineError("Phase 7 SUCCESS availability basis does not match its summary")
    for name, expected in declared_files.items():
        path = Path(artifact_dir) / name
        if (not isinstance(expected, str) or len(expected) != 64
                or any(char not in "0123456789abcdef" for char in expected)
                or path.is_symlink() or not path.is_file() or sha256_file(path) != expected):
            raise BaselineError(f"Phase 7 artifact hash mismatch for {name}")
    if success.get("manifest_sha256") != summary.get("manifest_sha256"):
        raise BaselineError("Phase 7 SUCCESS manifest hash does not match its summary")
    if not isinstance(manifest, dict) or digest(manifest) != summary.get("manifest_sha256"):
        raise BaselineError("Phase 7 summary manifest hash mismatch")
    feature_version = manifest.get("feature_version")
    if not isinstance(feature_version, str) or not feature_version.startswith("phase7_features_"):
        raise BaselineError("Unsupported Phase 7 feature version")
    horizons = manifest.get("horizons")
    if sorted(horizons or []) != list(horizons or []) or list(horizons or []) != list(HORIZONS):
        raise BaselineError("Phase 7 horizons are invalid")
    availability_basis = manifest.get("availability_basis")
    if availability_basis != "captured":
        raise BaselineError("Phase 8 baselines require captured Phase 7 availability")
    split = manifest.get("split") or {}
    try:
        validation_start = parse_origin(split["validation_start"])
        test_start = parse_origin(split["test_start"])
    except (KeyError, BaselineError):
        raise BaselineError("Phase 7 split boundaries are missing or invalid") from None
    if validation_start >= test_start:
        raise BaselineError("Phase 7 split boundaries are not chronological")
    features = read_csv(paths[FEATURES_NAME], REQUIRED_FEATURE_FIELDS)
    targets = read_csv(paths[TARGETS_NAME], REQUIRED_TARGET_FIELDS)
    feature_rows = parse_feature_rows(features)
    target_rows = parse_target_rows(targets)
    feature_keys = {row["key"] for row in feature_rows}
    target_keys = {row["key"] for row in target_rows}
    if feature_keys != target_keys:
        raise BaselineError("Phase 7 feature/target keys are not exactly aligned")
    target_by_key = {row["key"]: row for row in target_rows}
    for row in feature_rows:
        target = target_by_key[row["key"]]
        if row["target_available"] != target["target_available"]:
            raise BaselineError("Phase 7 feature and target availability flags disagree")
        if row["location_id"] != target["location_id"] or row["target_end"] != target["target_end"]:
            raise BaselineError("Phase 7 feature and target identity fields disagree")
        expected_split = "train" if row["origin_dt"] < validation_start else (
            "validation" if row["origin_dt"] < test_start else "test")
        if row["split"] != expected_split:
            raise BaselineError("Phase 7 feature row violates its chronological split boundary")
        expected_purged = ((expected_split == "train" and row["target_end_dt"] > validation_start)
                           or (expected_split == "validation" and row["target_end_dt"] > test_start))
        if row["purged"] != expected_purged:
            raise BaselineError("Phase 7 feature row violates its horizon purge contract")
    expected_rows = (manifest.get("counts") or {}).get("rows")
    if expected_rows is not None and expected_rows != len(feature_rows):
        raise BaselineError("Phase 7 feature row count differs from its manifest")
    return {"directory": Path(artifact_dir), "paths": paths, "summary": summary,
            "manifest": manifest, "features": feature_rows, "targets": target_rows,
            "target_by_key": target_by_key,
            "input_hashes": {name: sha256_file(path) for name, path in paths.items()}}


def parse_feature_rows(rows):
    output, keys = [], set()
    for raw in rows:
        try:
            horizon = int(raw["horizon_hours"])
            hour = int(raw["origin_local_hour"])
            purged = parse_bool(raw["purged"])
            origin = parse_origin(raw["origin"])
            target_start = parse_origin(raw["target_start"])
            target_end = parse_origin(raw["target_end"])
        except (KeyError, TypeError, ValueError):
            raise BaselineError("Malformed Phase 7 feature row") from None
        if horizon not in HORIZONS or not 0 <= hour <= 23 or raw["split"] not in {"train", "validation", "test"}:
            raise BaselineError("Phase 7 feature row has invalid horizon, local hour or split")
        if target_end != origin + timedelta(hours=horizon) or target_start != target_end - timedelta(hours=1):
            raise BaselineError("Phase 7 feature target_end violates origin+horizon")
        if not raw["sensor_id"] or not raw.get("location_id"):
            raise BaselineError("Phase 7 feature row has an empty identity")
        key = (raw["sensor_id"], raw["origin"], horizon)
        if key in keys:
            raise BaselineError("Duplicate Phase 7 feature key")
        keys.add(key)
        values = {field: parse_float(raw.get(field)) for field in raw
                  if field.startswith("pm25_") or (field.startswith("weather_forecast_")
                  and field not in WEATHER_META_FIELDS)}
        output.append({"key": key, "sensor_id": raw["sensor_id"], "location_id": raw.get("location_id", ""),
                       "origin": raw["origin"], "origin_dt": origin, "horizon_hours": horizon,
                       "target_start": raw["target_start"],
                       "target_end": raw["target_end"], "target_end_dt": target_end,
                       "origin_local_hour": hour, "split": raw["split"], "purged": purged,
                       "target_available": parse_bool(raw["target_available"]),
                       "values": values, "raw": raw})
    return output


def parse_target_rows(rows):
    output, keys = [], set()
    for raw in rows:
        try:
            horizon = int(raw["horizon_hours"])
            origin = parse_origin(raw["origin"])
            target_start = parse_origin(raw["target_start"])
            target_end = parse_origin(raw["target_end"])
            available = parse_bool(raw["target_available"])
        except (KeyError, TypeError, ValueError):
            raise BaselineError("Malformed Phase 7 target row") from None
        if horizon not in HORIZONS:
            raise BaselineError("Phase 7 target row has unsupported horizon")
        if target_end != origin + timedelta(hours=horizon) or target_start != target_end - timedelta(hours=1):
            raise BaselineError("Phase 7 target alignment violates the Phase 7 contract")
        if not raw["sensor_id"] or not raw.get("location_id"):
            raise BaselineError("Phase 7 target row has an empty identity")
        key = (raw["sensor_id"], raw["origin"], horizon)
        if key in keys:
            raise BaselineError("Duplicate Phase 7 target key")
        keys.add(key)
        target = parse_float(raw.get("target_pm25"))
        if available and (target is None or target < 0):
            raise BaselineError("Available Phase 7 target must be a finite non-negative value")
        if available and raw.get("target_quality") != "accepted":
            raise BaselineError("Available Phase 7 target must have accepted quality")
        if available and raw.get("target_missing_reason"):
            raise BaselineError("Available Phase 7 target must not have a missing reason")
        if not available and not raw.get("target_missing_reason"):
            raise BaselineError("Unavailable Phase 7 target must have a missing reason")
        if not available and target is not None:
            raise BaselineError("Unavailable Phase 7 target must have a null label")
        output.append({"key": key, "sensor_id": raw["sensor_id"], "location_id": raw.get("location_id", ""),
                       "origin": raw["origin"], "origin_dt": origin, "horizon_hours": horizon,
                       "target_available": available, "target_pm25": target,
                       "target_start": raw["target_start"], "target_end": raw["target_end"],
                       "target_start_dt": target_start, "target_end_dt": target_end, "raw": raw})
    return output


def weather_available(row):
    return any(field.startswith("weather_forecast_") and finite(value)
               and field not in WEATHER_META_FIELDS for field, value in row["values"].items())


def mean_or_none(values):
    return statistics.fmean(values) if values else None


def fit_climatology(rows, horizon, *, weather_indicator=False):
    cells = defaultdict(list)
    for row in rows:
        if row["horizon_hours"] != horizon:
            continue
        if row["split"] != "train" or row["purged"]:
            continue
        target = row["target_pm25"]
        if not row["target_available"] or not finite(target):
            continue
        key = (row["sensor_id"], row["horizon_hours"], row["origin_local_hour"])
        if weather_indicator:
            key += (weather_available(row),)
        cells[key].append(target)
    return {key: mean_or_none(values) for key, values in cells.items()}


def prediction_for(row, spec, climatology, weather_climatology_available):
    if spec["kind"] == "feature":
        value = row["values"].get(spec["field"])
        return value, ("predicted" if finite(value) else "unavailable"), (None if finite(value) else "missing_feature")
    if spec["kind"] == "local_hour_climatology":
        key = (row["sensor_id"], row["horizon_hours"], row["origin_local_hour"])
        value = climatology.get(key)
        return value, ("predicted" if finite(value) else "unavailable"), (None if finite(value) else "no_training_climatology_cell")
    if not weather_climatology_available:
        return None, "unavailable", "no_finite_captured_weather_features"
    key = (row["sensor_id"], row["horizon_hours"], row["origin_local_hour"], weather_available(row))
    value = climatology.get(key)
    return value, ("predicted" if finite(value) else "unavailable"), (None if finite(value) else "no_training_weather_climatology_cell")


def mase_denominator(rows, sensor_id, horizon):
    series = [row for row in rows if row["sensor_id"] == sensor_id and row["horizon_hours"] == horizon
              and row["split"] == "train" and not row["purged"] and row["target_available"] and finite(row["target_pm25"])]
    series.sort(key=lambda row: row["origin_dt"])
    diffs = [abs(current["target_pm25"] - previous["target_pm25"])
             for previous, current in zip(series, series[1:])
             if current["origin_dt"] - previous["origin_dt"] == timedelta(hours=1)]
    denominator = mean_or_none(diffs)
    return denominator


def metric_values(pairs, mase_denominator_value):
    actual = [pair[0] for pair in pairs]
    predicted = [pair[1] for pair in pairs]
    errors = [predicted_value - actual_value for actual_value, predicted_value in pairs]
    absolute = [abs(error) for error in errors]
    smape_terms = [200 * abs(predicted_value - actual_value) / (abs(actual_value) + abs(predicted_value))
                   for actual_value, predicted_value in pairs
                   if abs(actual_value) + abs(predicted_value) > 0]
    mae = statistics.fmean(absolute)
    return {"mae": mae, "rmse": math.sqrt(statistics.fmean(error * error for error in errors)),
            "mean_error": statistics.fmean(errors), "median_absolute_error": statistics.median(absolute),
            "mase_denominator": mase_denominator_value,
            "mase": mae / mase_denominator_value if mase_denominator_value and mase_denominator_value > 0 else None,
            "smape": statistics.fmean(smape_terms) if smape_terms else None}


def compute_baselines(artifact):
    features = artifact["features"]
    target_by_key = artifact["target_by_key"]
    joined = []
    for feature in features:
        target = target_by_key[feature["key"]]
        joined.append({**feature, "target_available": target["target_available"],
                       "target_pm25": target["target_pm25"]})
    weather_fields = [field for row in joined for field in row["values"]
                      if field.startswith("weather_forecast_") and field not in WEATHER_META_FIELDS]
    training_rows = [row for row in joined if row["split"] == "train" and not row["purged"]]
    weather_climatology_available = any(finite(row["values"].get(field))
                                        for row in training_rows for field in weather_fields)
    predictions, metrics = [], []
    for spec in BASELINE_SPECS:
        climatology_by_horizon = {}
        if spec["kind"] == "local_hour_climatology":
            climatology_by_horizon = {horizon: fit_climatology(joined, horizon) for horizon in HORIZONS}
        elif spec["kind"] == "weather_climatology":
            climatology_by_horizon = {horizon: fit_climatology(joined, horizon, weather_indicator=True)
                                      for horizon in HORIZONS}
        baseline_predictions = {}
        for row in joined:
            climatology = climatology_by_horizon.get(row["horizon_hours"], {})
            prediction, status, reason = prediction_for(row, spec, climatology, weather_climatology_available)
            baseline_predictions[row["key"]] = prediction
            predictions.append({"baseline_id": spec["baseline_id"], "baseline_role": spec["role"],
                                "sensor_id": row["sensor_id"], "location_id": row["location_id"],
                                "origin": row["origin"], "horizon_hours": row["horizon_hours"],
                                "split": row["split"], "purged": row["purged"],
                                "target_available": row["target_available"], "target_pm25": row["target_pm25"],
                                "prediction": prediction, "prediction_status": status,
                                "prediction_reason": reason, "feature_version": artifact["manifest"]["feature_version"]})
        groups = [("pooled", None)]
        groups.extend((sensor_id, sensor_id) for sensor_id in sorted({row["sensor_id"] for row in joined}))
        for group_name, sensor_filter in groups:
            for horizon in HORIZONS:
                for split in ("train", "validation", "test"):
                    candidates = [row for row in joined if row["horizon_hours"] == horizon and not row["purged"]
                                 and (sensor_filter is None or row["sensor_id"] == sensor_filter)
                                 and row["split"] == split]
                    if not candidates:
                        continue
                    pairs = [(row["target_pm25"], baseline_predictions[row["key"]]) for row in candidates
                             if row["target_available"] and finite(row["target_pm25"])
                             and finite(baseline_predictions[row["key"]])]
                    target_rows = sum(row["target_available"] and finite(row["target_pm25"]) for row in candidates)
                    predicted_rows = sum(finite(baseline_predictions[row["key"]]) for row in candidates)
                    missing_target_rows = sum(not row["target_available"] or not finite(row["target_pm25"])
                                              for row in candidates)
                    missing_prediction_rows = sum(not finite(baseline_predictions[row["key"]])
                                                  for row in candidates)
                    denominator = mase_denominator(joined, sensor_filter, horizon) if sensor_filter else None
                    if sensor_filter is None:
                        denominators = [mase_denominator(joined, sensor, horizon)
                                        for sensor in sorted({row["sensor_id"] for row in joined})]
                        denominators = [value for value in denominators if value is not None and value > 0]
                        denominator = mean_or_none(denominators)
                    values = metric_values(pairs, denominator) if pairs else {}
                    reason = None
                    if not pairs:
                        reason = "no_eligible_target_prediction_pairs"
                    elif spec["kind"] == "weather_climatology" and not weather_climatology_available:
                        reason = "no_finite_captured_weather_features"
                    group_location = next((row["location_id"] for row in candidates), "") if sensor_filter else "pooled"
                    metrics.append({"baseline_id": spec["baseline_id"], "baseline_role": spec["role"],
                                    "sensor_id": group_name if sensor_filter else "pooled", "location_id": group_location,
                                    "horizon_hours": horizon, "split": split, "candidate_rows": len(candidates),
                                    "target_available_rows": int(target_rows), "predicted_rows": int(predicted_rows),
                                    "missing_target_rows": int(missing_target_rows),
                                    "missing_prediction_rows": int(missing_prediction_rows),
                                    "eligible_rows": len(pairs), "purged_rows_excluded": sum(row["purged"] for row in joined
                                                                                             if row["horizon_hours"] == horizon
                                                                                             and (sensor_filter is None or row["sensor_id"] == sensor_filter)
                                                                                             and row["split"] == split),
                                    "coverage_percent": 100 * len(pairs) / len(candidates),
                                    "metric_status": "available" if pairs else "unavailable",
                                    "metric_scope": "descriptive_only",
                                    "evaluation_type": "in_sample_fit" if split == "train" else "chronological_holdout",
                                    "metric_reason": reason, **values})
    metric_available = any(row["metric_status"] == "available" for row in metrics)
    phase7_missing = artifact["manifest"].get("status_missing_families") or []
    status_reasons = [f"input_phase7_missing_{family}" for family in phase7_missing]
    if not metric_available:
        status_reasons.append("no_eligible_baseline_metrics")
    manifest = {"baseline_version": BASELINES_VERSION,
        "input_feature_version": artifact["manifest"]["feature_version"],
        "input_summary_sha256": sha256_file(artifact["paths"][SUMMARY_NAME]),
        "input_features_sha256": sha256_file(artifact["paths"][FEATURES_NAME]),
        "input_targets_sha256": sha256_file(artifact["paths"][TARGETS_NAME]),
        "input_success_sha256": sha256_file(artifact["paths"][SUCCESS_NAME]),
        "input_manifest_sha256": artifact["summary"]["manifest_sha256"],
        "input_bundle_sha256": artifact["manifest"].get("bundle_sha256"),
        "input_bundle_file_sha256": artifact["manifest"].get("bundle_file_sha256"),
        "implementation_sha256": {
            "baselines.py": sha256_file(Path(__file__)),
            "baselines_output.py": sha256_file(Path(__file__).with_name("baselines_output.py")),
        },
        "availability_basis": artifact["manifest"].get("availability_basis"),
        "horizons": list(HORIZONS), "boundary": artifact["manifest"].get("boundary"),
        "split": artifact["manifest"].get("split"),
        "input_rows": len(joined), "input_target_rows": len(target_by_key),
        "input_phase7_status": artifact["manifest"].get("status"),
        "status": "ok" if not status_reasons else "limited_diagnostic",
        "status_reasons": status_reasons,
        "test_selection_used": False,
        "baseline_definitions": BASELINE_SPECS,
        "selection_policy": "All declared baselines are reported; no baseline is selected using test metrics.",
        "transform_policy": "No imputation, interpolation, forward fill or target-derived feature is permitted.",
        "weather_policy": "Weather-augmented climatology is unavailable unless finite captured weather features exist; no ERA5/CAMS/assumed fallback is used.",
        "metrics": metrics}
    return {"purpose": "Phase 8 reproducible chronological PM2.5 baselines; no operational forecast claim",
            "manifest": manifest, "manifest_sha256": digest(manifest), "predictions": predictions,
            "metrics": metrics,
            "limitations": [
                "Metrics are descriptive baseline diagnostics, not forecast-skill certification.",
                "The Phase 7 captured artifact has no prospectively captured PM/weather feature evidence; feature-based baselines are therefore unavailable.",
                "The local-hour climatology uses training targets and calendar hour only; it is not an operational feature baseline.",
                "Two non-reference sensor sites are not a city average or population estimate.",
                "The final test period is reported but never used for baseline selection or fitting.",
            ]}


def run_baselines(artifact_dir):
    return compute_baselines(load_artifact(Path(artifact_dir)))


def write_csv(path, rows):
    fields = sorted({field for row in rows for field in row})
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: value for key, value in row.items()})


def assumptions_markdown(result):
    manifest = result["manifest"]
    lines = ["# Phase 8 Baselines: Assumptions and Limitations", "",
             "Reproducible chronological baseline diagnostics generated from a Phase 7 artifact.",
             "No database access, no imputation and no operational forecast claim.", "",
             "## Input and boundary", "",
             f"- Phase 7 feature version: `{manifest['input_feature_version']}`",
             f"- Input summary SHA-256: `{manifest['input_summary_sha256']}`",
             f"- Input features SHA-256: `{manifest['input_features_sha256']}`",
             f"- Input targets SHA-256: `{manifest['input_targets_sha256']}`",
             f"- Availability basis: `{manifest['availability_basis']}`; horizons: `{manifest['horizons']}`",
             f"- Phase 8 status: `{manifest['status']}`; reasons: `{json.dumps(manifest['status_reasons'])}`",
             f"- Test metrics are reported but `test_selection_used = {manifest['test_selection_used']}`.", "",
             "## Baselines", "",
             "- `persistence_last_available` uses only Phase 7 `pm25_last_available`.",
             "- `persistence_lag_1h` uses only the exact Phase 7 `pm25_lag_1h` feature.",
             "- `trailing_mean_24h` requires the strict complete Phase 7 24-hour window.",
             "- `local_hour_climatology` is fit by sensor and Vietnam local hour on non-purged training targets only.",
             "- `weather_augmented_climatology` is a diagnostic training climatology stratified by a finite captured-weather availability indicator; it is unavailable when no finite captured weather feature exists.", "",
             "## Metrics", "",
             "Metrics are computed only when the target is accepted/finite, the prediction is finite and the row is not purged.",
             "MASE uses the non-purged training one-hour naive denominator without bridging time gaps. sMAPE skips zero denominators and is null if all denominators are zero.", "",
             "## Limitations", ""]
    lines.extend(f"- {item}" for item in result["limitations"])
    return "\n".join(lines) + "\n"


def write_outputs(output_dir, result):
    output_dir = Path(output_dir)
    if output_dir.exists() or not output_dir.parent.is_dir():
        raise BaselineError("Phase 8 output directory must be new and its parent must exist")
    output_dir.mkdir(mode=0o700)
    summary = {"purpose": result["purpose"], "manifest": result["manifest"],
               "manifest_sha256": result["manifest_sha256"]}
    with (output_dir / OUTPUT_SUMMARY_NAME).open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        handle.write("\n")
    write_csv(output_dir / OUTPUT_METRICS_NAME, result["metrics"])
    write_csv(output_dir / OUTPUT_PREDICTIONS_NAME, result["predictions"])
    with (output_dir / OUTPUT_ASSUMPTIONS_NAME).open("x", encoding="utf-8") as handle:
        handle.write(assumptions_markdown(result))
    files = {path.name: sha256_file(path) for path in sorted(output_dir.iterdir())}
    with (output_dir / OUTPUT_SUCCESS_NAME).open("x", encoding="utf-8") as handle:
        json.dump({"baseline_version": BASELINES_VERSION, "manifest_sha256": result["manifest_sha256"],
                   "files_sha256": files}, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return {"output_dir": str(output_dir), "manifest_sha256": result["manifest_sha256"],
            "file_count": len(files) + 1}


def replay_baselines(artifact_dir, summary_path, output_dir):
    if Path(output_dir).exists() or not Path(output_dir).parent.is_dir():
        raise BaselineError("Phase 8 output directory must be new and its parent must exist")
    previous = read_metadata(summary_path, "Phase 8 summary")
    if set(previous) != {"purpose", "manifest", "manifest_sha256"}:
        raise BaselineError("Phase 8 summary fields do not match the replay contract")
    expected = previous.get("manifest")
    if not isinstance(expected, dict) or previous.get("manifest_sha256") != digest(expected):
        raise BaselineError("Phase 8 summary manifest hash mismatch")
    result = run_baselines(artifact_dir)
    if result["manifest_sha256"] != previous["manifest_sha256"] or result["manifest"] != expected:
        raise BaselineError("Phase 8 summary-bound replay mismatch for manifest")
    if previous.get("purpose") != result["purpose"]:
        raise BaselineError("Phase 8 summary-bound replay mismatch for purpose")
    return write_outputs(output_dir, result)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="vn-air-baselines")
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run")
    run.add_argument("--artifact", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    replay = actions.add_parser("replay")
    replay.add_argument("--artifact", type=Path, required=True)
    replay.add_argument("--summary", type=Path, required=True)
    replay.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_baselines(args.artifact) if args.action == "run" else replay_baselines(args.artifact, args.summary, args.output_dir)
        if args.action == "run":
            result = write_outputs(args.output_dir, result)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (BaselineError, OSError) as error:
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
