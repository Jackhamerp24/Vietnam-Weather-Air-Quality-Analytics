"""Phase 9 chronological machine-learning runner.

The runner consumes one Phase 7 captured feature artifact and one Phase 8 v2
reference artifact from disk only.  It never opens a database or a network
connection, never imputes a missing feature, never selects a model on the test
period and never lets a target value enter a design matrix.
"""

import hashlib
import json
import math
import random
import statistics
from datetime import date, timedelta
from pathlib import Path

from vn_air import baselines


ML_VERSION = "phase9_ml_v4"
REVISION = "comparison_hardened"
SUPERSEDED_ARTIFACTS = [
    {"directory": "phase_9_models_2026-09-11_final", "model_version": "phase9_ml_v1",
     "manifest_sha256": "1cd67cda5e2c0a12d85872f0f3c169922bb42e81f6954114358c25fa2d04d758"},
    {"directory": "phase_9_models_2026-09-11_corrected", "model_version": "phase9_ml_v2",
     "manifest_sha256": "f729fe7eee8428c92da1fc3b4becd7f77bc4eb92f7ec5a142ebffaa291256795"},
    {"directory": "phase_9_models_2026-09-12_review_hardened", "model_version": "phase9_ml_v3",
     "manifest_sha256": "c5cc4047766c16108beb0e5f0dc46dd7e9ddb871159d37989e7dd4b5a3df0d82"},
]
CORRECTION_PLAN = "docs/verification/phase_9_integrity_replay_hardening_plan.md"
NUMERICAL_PREDICTION_FAILURES = {"prediction_inverse_overflow", "prediction_inverse_nonfinite"}
REFERENCE_STATUSES = {"predicted", "unavailable"}
REPLAY_STATIC_KEYS = (
    "model_version", "revision", "purpose", "phase7", "phase8_reference",
    "horizons", "feature_sets", "model_families", "target_transforms", "scopes",
    "sensors", "model_definitions", "feature_allowlists", "row_gates",
    "selection_policy", "fit_partitions", "test_selection_used", "metric_scope",
    "transform_policy", "superseded_artifact_identities",
)
PURPOSE = ("Phase 9 chronological machine learning over a Phase 7 captured "
           "feature artifact; descriptive limited diagnostic, not forecast skill")
BASE_SEED = 20260911
HORIZONS = (6, 24)
FEATURE_SETS = ("calendar_only", "history_only", "weather_only", "history_weather")
MODEL_FAMILIES = ("ridge", "bagged_tree")
TARGET_TRANSFORMS = ("log1p", "raw")
SCOPES = ("pooled", "per_sensor")
RIDGE_ALPHAS = (0.1, 1.0, 10.0, 100.0)
RIDGE_FALLBACK_ALPHA = 1.0
TREE_COUNT = 25
TREE_MAX_DEPTH = 4
TREE_MIN_LEAF = 10
TREE_SAMPLE_FRACTION = 0.8
MIN_TRAIN_ROWS = 30
MIN_TRAIN_DATES = 5
MIN_TREE_TRAIN_ROWS = 60
SPLIT_ORDER = ("train", "validation", "test")

EXPECTED_PHASE7_FEATURE_VERSION = "phase7_features_v7"
EXPECTED_PHASE7_MANIFEST_SHA256 = "6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa"
EXPECTED_PHASE8_BASELINE_VERSION = "phase8_baselines_v2"
EXPECTED_PHASE8_MANIFEST_SHA256 = "ec651c4df04cb605f8849c1af96a3aea58f0902370e16ec39b9c48fdee22775e"
EXPECTED_PHASE7_PAYLOAD_SHA256 = {
    "phase_7_assumptions.md": "bb7038c6692d5a7333aa3f01ca927053b99790014db50c3f38d6c0106dcdc06b",
    "phase_7_feature_summary.json": "7fd1bfd725c5bec6df0088adf52af1f6e34f08d7d2244bb95b6172f7896e4d0b",
    "phase_7_features.csv": "2e2829e8cd14444ce4da322dc4f288ebb49baa05dba14423529bea2c866e092c",
    "phase_7_lineage.csv": "621a88c28b2f88f267c3671969cbb4df262a52defd571e3eb689975476056aaa",
    "phase_7_targets.csv": "d3e5198ccba3814259e5c9e8cfe647f481d58481b1bb8d774997e982e0f51073",
}
EXPECTED_PHASE8_PAYLOAD_SHA256 = {
    "phase_8_assumptions.md": "e77111278c3456221480f44a173fab0aa99e8a79f9b4e173a095094ac1588ebc",
    "phase_8_baseline_metrics.csv": "9626e4112689f108afba1256100e3911675bc44712b4072e9d87f267b675ca63",
    "phase_8_baselines_summary.json": "e7dbcd35f7d896b2ec7d3ec38b64ddb43f601efe56d4341d6b091cc8e2c9dc26",
    "phase_8_predictions.csv": "ea9f9f4a8568170e4f36a56059c18784a1260bcd1335c8b52df8856180f5a0bf",
}

PHASE7_SUMMARY_NAME = "phase_7_feature_summary.json"
PHASE7_PREDICTIONS_NAME = "phase_7_features.csv"
PHASE8_SUMMARY_NAME = "phase_8_baselines_summary.json"
PHASE8_PREDICTIONS_NAME = "phase_8_predictions.csv"
PHASE8_METRICS_NAME = "phase_8_baseline_metrics.csv"
PHASE8_ASSUMPTIONS_NAME = "phase_8_assumptions.md"
SUCCESS_NAME = "SUCCESS.json"

OUTPUT_SUMMARY_NAME = "phase_9_model_summary.json"
OUTPUT_METRICS_NAME = "phase_9_metrics.csv"
OUTPUT_PREDICTIONS_NAME = "phase_9_predictions.csv"
OUTPUT_PARAMETERS_NAME = "phase_9_model_parameters.json"
OUTPUT_FEATURES_NAME = "phase_9_feature_manifest.json"
OUTPUT_ASSUMPTIONS_NAME = "phase_9_assumptions.md"
OUTPUT_SUCCESS_NAME = "SUCCESS.json"

PM_HISTORY_COLUMNS = (
    "pm25_lag_1h", "pm25_lag_3h", "pm25_lag_6h", "pm25_lag_12h",
    "pm25_lag_24h", "pm25_lag_48h", "pm25_lag_72h",
    "pm25_last_available", "pm25_last_age_hours",
    "pm25_trailing_count_3h", "pm25_trailing_count_6h",
    "pm25_trailing_count_12h", "pm25_trailing_count_24h",
    "pm25_trailing_mean_3h", "pm25_trailing_mean_6h",
    "pm25_trailing_mean_12h", "pm25_trailing_mean_24h",
    "pm25_trailing_std_24h",
)
WEATHER_COLUMNS = (
    "weather_forecast_apparent_temperature", "weather_forecast_cloud_cover",
    "weather_forecast_precipitation", "weather_forecast_relative_humidity_2m",
    "weather_forecast_shortwave_radiation", "weather_forecast_surface_pressure",
    "weather_forecast_temperature_2m", "weather_forecast_wind_direction_cos",
    "weather_forecast_wind_direction_sin", "weather_forecast_wind_speed_10m",
)
FEATURE_SET_SPECS = {
    "calendar_only": {"history": False, "weather": False},
    "history_only": {"history": True, "weather": False},
    "weather_only": {"history": False, "weather": True},
    "history_weather": {"history": True, "weather": True},
}
FORBIDDEN_EXACT = {
    "lineage_id", "purged", "purge_reason", "split", "feature_version",
    "availability_basis", "availability_assumption", "feature_available_through",
    "pm_available_through", "pm_history_reason", "weather_forecast_reason",
    "weather_forecast_missing_count", "weather_forecast_run_provenance",
    "weather_forecast_snapshot_id", "target_available", "target_quality",
    "target_missing_reason", "target_observation_id", "target_revision",
    "target_recorded_at", "target_retrieved_at", "target_source_published_at",
    "target_start", "target_end", "target_local_date", "target_local_hour",
    "target_local_weekday", "location_id",
}
FORBIDDEN_PREFIXES = ("target_",)
FORBIDDEN_SUFFIXES = ("_recorded_at", "_retrieved_at", "_snapshot_id",
                      "_response_id", "_published_at", "_provenance")
BASELINE_COMPARISONS = (
    ("local_hour_climatology", "diagnostic_calendar"),
    ("persistence_last_available", "primary_reference"),
    ("persistence_lag_1h", "sensitivity"),
    ("trailing_mean_24h", "sensitivity"),
)


class MLError(ValueError):
    """Invalid or unsafe machine-learning input."""


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def forbidden_predictor(name):
    if name.startswith(FORBIDDEN_PREFIXES) or name in FORBIDDEN_EXACT:
        return True
    return name.endswith(FORBIDDEN_SUFFIXES)


def validate_feature_allowlist(columns):
    for column in columns:
        if not isinstance(column, str) or not column:
            raise MLError("Feature allowlist contains an invalid column name")
        if forbidden_predictor(column):
            raise MLError(f"Forbidden predictor column in feature allowlist: {column}")


def require_new_output_dir(output_dir):
    output_dir = Path(output_dir)
    if output_dir.exists() or not output_dir.parent.is_dir():
        raise MLError("Phase 9 output directory must be new and its parent must exist")


def payload_map(root):
    root = Path(root)
    if not root.is_dir():
        raise MLError("Artifact directory does not exist")
    result = {}
    for path in sorted(root.iterdir()):
        if path.name == SUCCESS_NAME or not path.is_file():
            continue
        if path.is_symlink():
            raise MLError("Artifact payload contains a symlink")
        result[path.name] = baselines.sha256_file(path)
    return result


def verify_payload_map(root, expected, label):
    actual = payload_map(root)
    if set(actual) != set(expected):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        raise MLError(f"{label} payload file set does not match the frozen identity "
                      f"(missing={missing}, extra={extra})")
    for name, expected_hash in expected.items():
        if actual[name] != expected_hash:
            raise MLError(f"{label} payload hash does not match the frozen identity for {name}")
    return actual


def load_phase7(artifact_dir, *, expected_manifest=None, expected_payloads=None):
    observed_payloads = None
    if expected_payloads is not None:
        observed_payloads = verify_payload_map(artifact_dir, expected_payloads, "Phase 7")
    artifact = baselines.load_artifact(Path(artifact_dir))
    summary = artifact["summary"]
    manifest = artifact["manifest"]
    if expected_manifest is not None and summary.get("manifest_sha256") != expected_manifest:
        raise MLError("Phase 7 artifact manifest identity does not match the frozen identity")
    if observed_payloads is None:
        observed_payloads = payload_map(artifact_dir)
    if manifest.get("feature_version") != EXPECTED_PHASE7_FEATURE_VERSION:
        raise MLError("Phase 9 requires the phase7_features_v7 feature version")
    rows = []
    for feature in artifact["features"]:
        target = artifact["target_by_key"][feature["key"]]
        raw = feature["raw"]
        try:
            weekday = int(raw["origin_local_weekday"])
            local_date = date.fromisoformat(raw["origin_local_date"])
        except (KeyError, TypeError, ValueError):
            raise MLError("Phase 7 feature row has invalid local calendar fields") from None
        expected_date = (feature["origin_dt"] + timedelta(hours=7)).date()
        if not 0 <= weekday <= 6 or local_date != expected_date or weekday != expected_date.weekday():
            raise MLError("Phase 7 local calendar fields disagree with the UTC origin")
        row = dict(feature)
        row["target_pm25"] = target["target_pm25"]
        row["target_quality"] = target["raw"].get("target_quality", "")
        row["origin_local_weekday"] = weekday
        row["origin_local_date"] = local_date
        rows.append(row)
    rows.sort(key=lambda row: (row["origin_dt"], row["sensor_id"], row["horizon_hours"], row["origin"]))
    earliest = min(row["origin_local_date"] for row in rows)
    for row in rows:
        row["day_index"] = (row["origin_local_date"] - earliest).days
    artifact = dict(artifact)
    artifact["rows"] = rows
    artifact["sensors"] = sorted({row["sensor_id"] for row in rows})
    artifact["payload_sha256"] = observed_payloads
    artifact["expected_payload_sha256"] = (dict(expected_payloads)
                                           if expected_payloads is not None else None)
    return artifact


def load_baseline_reference(artifact_dir, *, expected_manifest=None, expected_payloads=None):
    root = Path(artifact_dir)
    if not root.is_dir():
        raise MLError("Phase 8 reference artifact must be an existing directory")
    paths = {name: root / name for name in (PHASE8_SUMMARY_NAME, PHASE8_PREDICTIONS_NAME, SUCCESS_NAME)}
    if any(path.is_symlink() or not path.is_file() for path in paths.values()):
        raise MLError("Phase 8 reference artifact is missing a required summary, prediction or SUCCESS file")
    success = baselines.read_metadata(paths[SUCCESS_NAME], "Phase 8 SUCCESS.json")
    summary = baselines.read_metadata(paths[PHASE8_SUMMARY_NAME], "Phase 8 summary")
    manifest = summary.get("manifest")
    if not isinstance(manifest, dict):
        raise MLError("Phase 8 reference manifest must be a JSON object")
    if manifest.get("baseline_version") != EXPECTED_PHASE8_BASELINE_VERSION:
        raise MLError("Phase 9 requires the phase8_baselines_v2 reference version")
    definitions = manifest.get("baseline_definitions")
    if not isinstance(definitions, list) or not definitions:
        raise MLError("Phase 8 reference manifest has no baseline definitions")
    baseline_roles = {}
    for entry in definitions:
        if (not isinstance(entry, dict) or not isinstance(entry.get("baseline_id"), str)
                or not isinstance(entry.get("role"), str)):
            raise MLError("Phase 8 reference baseline definition is malformed")
        if entry["baseline_id"] in baseline_roles:
            raise MLError("Phase 8 reference baseline definitions contain duplicates")
        baseline_roles[entry["baseline_id"]] = entry["role"]
    if set(baseline_roles) != {spec["baseline_id"] for spec in baselines.BASELINE_SPECS}:
        raise MLError("Phase 8 reference baseline definitions do not match the declared series")
    if expected_manifest is not None and summary.get("manifest_sha256") != expected_manifest:
        raise MLError("Phase 8 reference manifest identity does not match the frozen identity")
    if baselines.digest(manifest) != summary.get("manifest_sha256"):
        raise MLError("Phase 8 reference manifest hash mismatch")
    declared = success.get("files_sha256")
    if not isinstance(declared, dict) or not {PHASE8_SUMMARY_NAME, PHASE8_PREDICTIONS_NAME}.issubset(declared):
        raise MLError("Phase 8 SUCCESS.json omits a required reference hash")
    allowed = {PHASE8_SUMMARY_NAME, PHASE8_PREDICTIONS_NAME, PHASE8_METRICS_NAME, PHASE8_ASSUMPTIONS_NAME}
    if not set(declared).issubset(allowed):
        raise MLError("Phase 8 SUCCESS.json contains an unrecognized artifact path")
    actual = {path.name for path in root.iterdir() if path.is_file() and path.name != SUCCESS_NAME}
    if set(declared) != actual:
        raise MLError("Phase 8 SUCCESS.json file manifest does not match the artifact directory")
    if success.get("manifest_sha256") != summary.get("manifest_sha256"):
        raise MLError("Phase 8 SUCCESS manifest hash does not match its summary")
    if success.get("baseline_version") != manifest.get("baseline_version"):
        raise MLError("Phase 8 SUCCESS baseline version does not match its summary")
    for name, expected in declared.items():
        path = root / name
        if (not isinstance(expected, str) or len(expected) != 64
                or any(char not in "0123456789abcdef" for char in expected)
                or path.is_symlink() or not path.is_file()
                or baselines.sha256_file(path) != expected):
            raise MLError(f"Phase 8 reference hash mismatch for {name}")
    observed_payloads = (verify_payload_map(artifact_dir, expected_payloads, "Phase 8 reference")
                         if expected_payloads is not None else payload_map(artifact_dir))
    required_fields = ("baseline_id", "baseline_role", "sensor_id", "origin", "horizon_hours",
                       "location_id", "prediction", "prediction_status", "prediction_reason",
                       "split", "purged", "target_available", "target_pm25")
    predictions = {}
    try:
        with paths[PHASE8_PREDICTIONS_NAME].open("r", encoding="utf-8", newline="") as handle:
            reader = json_load_csv(handle, required_fields)
            for raw in reader:
                horizon = int(raw["horizon_hours"])
                if horizon not in HORIZONS:
                    raise MLError("Phase 8 reference prediction row has an unsupported horizon")
                key = (raw["baseline_id"], raw["sensor_id"], raw["origin"], horizon)
                if key in predictions:
                    raise MLError("Duplicate Phase 8 reference prediction key")
                reason = raw["prediction_reason"].strip()
                predictions[key] = {
                    "prediction": baselines.parse_float(raw.get("prediction")),
                    "status": raw["prediction_status"], "role": raw["baseline_role"],
                    "reason": reason or None, "split": raw["split"],
                    "location_id": raw["location_id"], "purged": baselines.parse_bool(raw["purged"]),
                    "target_available": baselines.parse_bool(raw["target_available"])}
    except OSError as error:
        raise MLError("Cannot read the Phase 8 reference predictions") from error
    return {"directory": root, "summary": summary, "manifest": manifest,
            "predictions": predictions, "baseline_roles": baseline_roles,
            "payload_sha256": observed_payloads,
            "expected_payload_sha256": (dict(expected_payloads)
                                        if expected_payloads is not None else None),
            "input_hashes": {name: baselines.sha256_file(root / name) for name in declared}}


def json_load_csv(handle, required_fields):
    import csv
    reader = csv.DictReader(handle)
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise MLError("Reference CSV header is missing or duplicated")
    missing = set(required_fields) - set(reader.fieldnames)
    if missing:
        raise MLError(f"Reference CSV is missing fields: {sorted(missing)}")
    return list(reader)


def feature_complete(row, feature_set):
    spec = FEATURE_SET_SPECS[feature_set]
    reasons = []
    if spec["history"] and not all(baselines.finite(row["values"].get(column))
                                   for column in PM_HISTORY_COLUMNS):
        reasons.append("missing_pm_history_features")
    if spec["weather"]:
        weather_ok = row["raw"].get("weather_forecast_reason") == "ok"
        if not weather_ok or not all(baselines.finite(row["values"].get(column))
                                     for column in WEATHER_COLUMNS):
            reasons.append("missing_captured_weather_features")
    return not reasons, ";".join(reasons)


def feature_columns(feature_set, sensors, scope):
    if feature_set not in FEATURE_SET_SPECS or scope not in SCOPES:
        raise MLError("Unknown feature set or scope")
    categorical = [f"local_hour_{hour:02d}" for hour in range(24)]
    categorical += [f"weekday_{weekday}" for weekday in range(7)]
    if scope == "pooled":
        categorical += [f"sensor_{sensor}" for sensor in sensors]
    continuous = ["day_index"]
    if FEATURE_SET_SPECS[feature_set]["history"]:
        continuous += list(PM_HISTORY_COLUMNS)
    if FEATURE_SET_SPECS[feature_set]["weather"]:
        continuous += list(WEATHER_COLUMNS)
    validate_feature_allowlist(categorical + continuous)
    return categorical, continuous


def encoded_categoricals(row, categorical):
    values = []
    for name in categorical:
        if name.startswith("local_hour_"):
            values.append(1.0 if row["origin_local_hour"] == int(name[11:]) else 0.0)
        elif name.startswith("weekday_"):
            values.append(1.0 if row["origin_local_weekday"] == int(name[8:]) else 0.0)
        elif name.startswith("sensor_"):
            values.append(1.0 if row["sensor_id"] == name[7:] else 0.0)
        else:
            raise MLError(f"Unknown categorical column: {name}")
    return values


def continuous_value(row, name):
    if name == "day_index":
        return float(row["day_index"])
    return row["values"].get(name)


def partition_rows(group_rows, feature_set):
    rows_by_split = {split: [] for split in SPLIT_ORDER}
    for row in group_rows:
        rows_by_split[row["split"]].append(row)
    coverage = {}
    for split in SPLIT_ORDER:
        rows = rows_by_split[split]
        purged = [row for row in rows if row["purged"]]
        active = [row for row in rows if not row["purged"]]
        unavailable_target = [row for row in active
                              if not row["target_available"] or not baselines.finite(row["target_pm25"])]
        eligible, incomplete = [], []
        for row in active:
            complete, reason = feature_complete(row, feature_set)
            if complete:
                eligible.append(row)
            else:
                incomplete.append((row, reason))
        eligible_final = [row for row in eligible
                          if row["target_available"] and baselines.finite(row["target_pm25"])]
        coverage[split] = {
            "candidate_rows": len(rows),
            "purged_rows_excluded": len(purged),
            "unavailable_target_rows": len(unavailable_target),
            "incomplete_feature_rows": len(incomplete),
            "incomplete_history_rows": sum(1 for _, reason in incomplete
                                           if "missing_pm_history_features" in reason),
            "incomplete_weather_rows": sum(1 for _, reason in incomplete
                                           if "missing_captured_weather_features" in reason),
            "eligible_rows": len(eligible_final),
            "distinct_origins": len({row["origin"] for row in eligible_final}),
            "distinct_dates": len({row["origin_local_date"] for row in eligible_final}),
            "eligible_keys": [row["key"] for row in eligible_final],
            "eligible": eligible_final,
        }
    return rows_by_split, coverage


def transform_target(value, transform):
    if transform == "log1p":
        return math.log1p(value)
    if transform == "raw":
        return value
    raise MLError(f"Unknown target transform: {transform}")


def inverse_transform(value, transform):
    if not math.isfinite(value):
        raise MLError("prediction_inverse_nonfinite")
    if transform == "log1p":
        try:
            result = math.expm1(value)
        except OverflowError:
            raise MLError("prediction_inverse_overflow") from None
    elif transform == "raw":
        result = value
    else:
        raise MLError(f"Unknown target transform: {transform}")
    if not math.isfinite(result):
        raise MLError("prediction_inverse_overflow")
    return max(0.0, result)


def standardize_continuous(fit_rows, continuous):
    means, scales, kept, dropped = {}, {}, [], []
    for name in continuous:
        values = [continuous_value(row, name) for row in fit_rows]
        if any(not baselines.finite(value) for value in values):
            raise MLError(f"Non-finite feature value in the fit partition: {name}")
        mean = statistics.fmean(values)
        scale = math.sqrt(statistics.fmean((value - mean) ** 2 for value in values))
        if scale <= 1e-12:
            dropped.append(name)
        else:
            means[name] = mean
            scales[name] = scale
            kept.append(name)
    return means, scales, kept, dropped


def keep_categoricals(fit_rows, categorical):
    kept, dropped = [], []
    size = len(fit_rows)
    for name in categorical:
        ones = sum(encoded_categoricals(row, [name])[0] for row in fit_rows)
        if 0 < ones < size:
            kept.append(name)
        else:
            dropped.append(name)
    return kept, dropped


def design_matrix(rows, categorical, continuous, means, scales):
    matrix = []
    for row in rows:
        vector = [1.0]
        vector.extend(encoded_categoricals(row, categorical))
        for name in continuous:
            vector.append((continuous_value(row, name) - means[name]) / scales[name])
        matrix.append(vector)
    return matrix


def solve_ridge(matrix, target, alpha):
    n = len(matrix)
    if n == 0:
        raise MLError("Cannot fit a model without training rows")
    columns = len(matrix[0])
    if columns == 0 or any(len(row) != columns for row in matrix):
        raise MLError("Design matrix is malformed")
    if len(target) != n:
        raise MLError("Design matrix and target lengths differ")
    for row in matrix:
        if any(not baselines.finite(value) for value in row):
            raise MLError("Design matrix contains a non-finite value")
    if any(not baselines.finite(value) for value in target):
        raise MLError("Target vector contains a non-finite value")
    gram = [[0.0] * columns for _ in range(columns)]
    rhs = [0.0] * columns
    for row, value in zip(matrix, target):
        for i in range(columns):
            rhs[i] += row[i] * value
            for j in range(i, columns):
                gram[i][j] += row[i] * row[j]
    for i in range(columns):
        for j in range(i):
            gram[i][j] = gram[j][i]
    for index in range(1, columns):
        gram[index][index] += alpha
    return solve_linear(gram, rhs)


def solve_linear(matrix, rhs):
    n = len(matrix)
    if n == 0 or len(rhs) != n or any(len(row) != n for row in matrix):
        raise MLError("Linear system is malformed")
    augmented = [[float(matrix[i][j]) for j in range(n)] + [float(rhs[i])] for i in range(n)]
    if any(not baselines.finite(value) for row in augmented for value in row):
        raise MLError("Linear system contains a non-finite value")
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise MLError("Design matrix is rank deficient or unusable")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        pivot_value = augmented[column][column]
        for row in range(column + 1, n):
            factor = augmented[row][column] / pivot_value
            if factor:
                for position in range(column, n + 1):
                    augmented[row][position] -= factor * augmented[column][position]
    solution = [0.0] * n
    for row in range(n - 1, -1, -1):
        total = augmented[row][n]
        for column in range(row + 1, n):
            total -= augmented[row][column] * solution[column]
        solution[row] = total / augmented[row][row]
    if any(not baselines.finite(value) for value in solution):
        raise MLError("Linear solver produced a non-finite coefficient")
    return solution


def fit_ridge(rows, alpha, categorical, continuous, transform):
    means, scales, kept_continuous, dropped_continuous = standardize_continuous(rows, continuous)
    kept_categorical, dropped_categorical = keep_categoricals(rows, categorical)
    matrix = design_matrix(rows, kept_categorical, kept_continuous, means, scales)
    target = [transform_target(row["target_pm25"], transform) for row in rows]
    coefficients = solve_ridge(matrix, target, alpha)
    return {"family": "ridge", "alpha": alpha, "transform": transform,
            "categorical": kept_categorical, "continuous": kept_continuous,
            "means": means, "scales": scales,
            "dropped_categorical": dropped_categorical,
            "dropped_continuous": dropped_continuous,
            "coefficient_names": ["intercept"] + kept_categorical + kept_continuous,
            "coefficients": coefficients,
            "columns": len(coefficients),
            "training_rows": len(rows)}


def fit_trees(rows, categorical, continuous, transform, digest):
    feature_names = list(categorical) + list(continuous)
    matrix = []
    for row in rows:
        vector = encoded_categoricals(row, categorical)
        vector.extend(continuous_value(row, name) for name in continuous)
        matrix.append(tuple(vector))
    target = [transform_target(row["target_pm25"], transform) for row in rows]
    trees = []
    feature_counts = [0] * len(feature_names)
    for index in range(TREE_COUNT):
        rng = random.Random(seed_for(digest, index))
        size = max(1, int(len(matrix) * TREE_SAMPLE_FRACTION))
        sample = [rng.randrange(len(matrix)) for _ in range(size)]
        sampled = [matrix[position] for position in sample]
        sampled_target = [target[position] for position in sample]
        order = [sorted(range(size), key=lambda position: (sampled[position][feature], position))
                 for feature in range(len(feature_names))]
        tree = grow_tree(sampled, sampled_target, order, list(range(size)), 0, feature_counts)
        trees.append({"seed": seed_for(digest, index), "sample_size": size, "tree": tree})
    return {"family": "bagged_tree", "transform": transform,
            "categorical": list(categorical), "continuous": list(continuous),
            "feature_names": feature_names, "trees": trees,
            "tree_count": len(trees), "max_depth": TREE_MAX_DEPTH,
            "min_leaf": TREE_MIN_LEAF, "sample_fraction": TREE_SAMPLE_FRACTION,
            "feature_split_counts": {name: feature_counts[index]
                                     for index, name in enumerate(feature_names)
                                     if feature_counts[index]},
            "training_rows": len(rows)}


def seed_for(digest, index):
    body = f"{BASE_SEED}:{digest}:{index}"
    return int(sha256_text(body)[:16], 16)


def grow_tree(matrix, target, order, positions, depth, feature_counts):
    total_n = len(positions)
    total_y = sum(target[position] for position in positions)
    if depth >= TREE_MAX_DEPTH or total_n < 2 * TREE_MIN_LEAF:
        return {"leaf": total_y / total_n}
    total_y2 = sum(target[position] * target[position] for position in positions)
    in_node = [False] * len(matrix)
    for position in positions:
        in_node[position] = True
    best = None
    sample_size = len(matrix)
    for feature in range(len(matrix[0])):
        left_n = 0
        left_y = 0.0
        left_y2 = 0.0
        cursor = 0
        current_order = order[feature]
        while cursor < sample_size:
            value = matrix[current_order[cursor]][feature]
            while cursor < sample_size and matrix[current_order[cursor]][feature] == value:
                position = current_order[cursor]
                if in_node[position]:
                    left_n += 1
                    left_y += target[position]
                    left_y2 += target[position] * target[position]
                cursor += 1
            if 0 < left_n < total_n and left_n >= TREE_MIN_LEAF and total_n - left_n >= TREE_MIN_LEAF:
                right_n = total_n - left_n
                right_y = total_y - left_y
                right_y2 = total_y2 - left_y2
                sse = (left_y2 - left_y * left_y / left_n) + (right_y2 - right_y * right_y / right_n)
                if best is None or sse < best[0]:
                    best = (sse, feature, value, left_n)
    if best is None:
        return {"leaf": total_y / total_n}
    _, feature, threshold, _ = best
    left_positions = [position for position in positions if matrix[position][feature] <= threshold]
    right_positions = [position for position in positions if matrix[position][feature] > threshold]
    feature_counts[feature] += 1
    return {"feature": feature, "threshold": threshold,
            "left": grow_tree(matrix, target, order, left_positions, depth + 1, feature_counts),
            "right": grow_tree(matrix, target, order, right_positions, depth + 1, feature_counts)}


def tree_predict(tree, vector):
    node = tree
    while "feature" in node:
        node = node["left"] if vector[node["feature"]] <= node["threshold"] else node["right"]
    return node["leaf"]


def predict_ridge(model, rows):
    matrix = design_matrix(rows, model["categorical"], model["continuous"],
                           model["means"], model["scales"])
    predictions = []
    for vector in matrix:
        value = sum(coefficient * item for coefficient, item in zip(model["coefficients"], vector))
        predictions.append(inverse_transform(value, model["transform"]))
    return predictions


def predict_trees(model, rows):
    predictions = []
    for row in rows:
        vector = encoded_categoricals(row, model["categorical"])
        vector.extend(continuous_value(row, name) for name in model["continuous"])
        total = statistics.fmean(tree_predict(tree["tree"], vector) for tree in model["trees"])
        predictions.append(inverse_transform(total, model["transform"]))
    return predictions


def predict_model(model, rows):
    if model["family"] == "ridge":
        return predict_ridge(model, rows)
    return predict_trees(model, rows)


def r2_value(pairs):
    if len(pairs) < 2:
        return None, "insufficient_pairs"
    actual = [value for value, _ in pairs]
    mean = statistics.fmean(actual)
    total = sum((value - mean) ** 2 for value in actual)
    if total <= 0:
        return None, "undefined_zero_target_variance"
    residual = sum((prediction - value) ** 2 for value, prediction in pairs)
    return 1 - residual / total, None


def metric_values(pairs, denominator):
    values = baselines.metric_values(pairs, denominator) if pairs else {}
    r2, r2_reason = r2_value(pairs)
    values["r2"] = r2
    values["r2_reason"] = r2_reason
    return values


def identity_key(identity):
    body = "|".join(f"{name}={identity[name]}" for name in sorted(identity))
    return sha256_text(body)


def group_denominator(feature_rows, group_name, sensors, horizon):
    if group_name != "pooled":
        return baselines.mase_denominator(feature_rows, group_name, horizon)
    values = [baselines.mase_denominator(feature_rows, sensor, horizon) for sensor in sensors]
    valid = [value for value in values if value is not None and value > 0]
    return statistics.fmean(valid) if valid else None


def metric_row(identity, split, coverage, pairs, denominator, *, fit_partition,
               evaluation_type, model_status, model_reason, metric_status, metric_reason):
    row = dict(identity)
    row.update({
        "split": split,
        "fit_partition": fit_partition,
        "evaluation_type": evaluation_type,
        "candidate_rows": coverage["candidate_rows"],
        "purged_rows_excluded": coverage["purged_rows_excluded"],
        "unavailable_target_rows": coverage["unavailable_target_rows"],
        "incomplete_feature_rows": coverage["incomplete_feature_rows"],
        "incomplete_history_rows": coverage["incomplete_history_rows"],
        "incomplete_weather_rows": coverage["incomplete_weather_rows"],
        "eligible_rows": len(pairs),
        "coverage_percent": (100 * len(pairs) / coverage["candidate_rows"]
                             if coverage["candidate_rows"] else 0.0),
        "model_status": model_status,
        "model_reason": model_reason,
        "metric_status": metric_status,
        "metric_reason": metric_reason,
        "metric_scope": "descriptive_only",
    })
    row.update(metric_values(pairs, denominator))
    return row


def compute_instance(identity, group_rows, feature_set, family, transform, scope,
                     group_sensors, sensors, all_rows, digest):
    categorical, continuous = feature_columns(feature_set, group_sensors, scope)
    _, coverage = partition_rows(group_rows, feature_set)
    train = coverage["train"]["eligible"]
    validation = coverage["validation"]["eligible"]
    test = coverage["test"]["eligible"]
    model_reasons = []
    if len(train) < MIN_TRAIN_ROWS:
        model_reasons.append("insufficient_training_rows")
    if coverage["train"]["distinct_dates"] < MIN_TRAIN_DATES:
        model_reasons.append("insufficient_training_dates")
    if family == "bagged_tree" and len(train) < MIN_TREE_TRAIN_ROWS:
        model_reasons.append("insufficient_tree_training_rows")
    denominator = group_denominator(all_rows, identity["sensor_id"], sensors,
                                    identity["horizon_hours"])
    if model_reasons:
        return unavailable_instance(identity, coverage, denominator, categorical, continuous,
                                    model_reasons)
    if family == "ridge":
        alpha, selection_status, selection_detail = select_alpha(
            train, validation, alpha_fit(categorical, continuous, transform))
        if alpha is None:
            return unavailable_instance(identity, coverage, denominator, categorical,
                                        continuous, [selection_status], selection_detail)
        selection_model = fit_ridge(train, alpha, categorical, continuous, transform)
        final_model = fit_ridge(train + validation, alpha, categorical, continuous, transform)
        selection_parameters = ridge_parameters(selection_model)
        final_parameters = ridge_parameters(final_model)
        selection_parameters["selection_status"] = selection_status
        selection_parameters["selection_detail"] = selection_detail
    else:
        selection_model = fit_trees(train, categorical, continuous, transform, digest)
        final_model = fit_trees(train + validation, categorical, continuous, transform, digest)
        selection_parameters = tree_parameters(selection_model)
        final_parameters = tree_parameters(final_model)
    metrics, predictions, prediction_map = score_instance(
        identity, train, validation, test, coverage, denominator,
        selection_model, final_model)
    parameters = {"identity": identity, "model_status": "available",
                  "feature_columns": {"categorical": categorical, "continuous": continuous},
                  "selection_fit": selection_parameters, "final_fit": final_parameters,
                  "coverage": strip_coverage(coverage),
                  "training_key_digest": {
                      "selection": key_digest(train),
                      "final": key_digest(train + validation)}}
    feature_spec = {"identity": identity, "categorical_columns": categorical,
                    "continuous_columns": continuous,
                    "dropped_columns": sorted(set(selection_parameters.get("dropped_categorical", []))
                                              | set(selection_parameters.get("dropped_continuous", []))),
                    "coverage": strip_coverage(coverage),
                    "model_status": "available", "model_reasons": []}
    return {"identity": identity, "model_status": "available", "model_reasons": [],
            "metrics": metrics, "predictions": predictions, "prediction_map": prediction_map,
            "parameters": parameters, "feature_spec": feature_spec}


def alpha_fit(categorical, continuous, transform):
    return {"categorical": categorical, "continuous": continuous, "transform": transform}


def fit_partition_for(split):
    return "train_plus_validation" if split == "test" else "train"


def evaluation_type_for(split):
    return {"train": "in_sample_fit", "validation": "tuning_diagnostic",
            "test": "final_refit_holdout"}[split]


def select_alpha(train, validation, _context):
    if not validation:
        return RIDGE_FALLBACK_ALPHA, "validation_unavailable", {"candidates": []}
    candidates = []
    for alpha in RIDGE_ALPHAS:
        model = fit_ridge(train, alpha, _context["categorical"], _context["continuous"],
                          _context["transform"])
        try:
            pairs = [(row["target_pm25"], prediction)
                     for row, prediction in zip(validation, predict_ridge(model, validation))]
            rmse = baselines.metric_values(pairs, None)["rmse"]
            candidates.append({"alpha": alpha, "validation_rmse": rmse,
                               "status": "ok", "failure_reason": None})
        except MLError as error:
            if str(error) not in NUMERICAL_PREDICTION_FAILURES:
                raise
            candidates.append({"alpha": alpha, "validation_rmse": None,
                               "status": "unavailable", "failure_reason": str(error)})
    successful = [item for item in candidates if item["validation_rmse"] is not None]
    if not successful:
        return None, "validation_prediction_failed", {"candidates": candidates}
    best = min(successful, key=lambda item: (item["validation_rmse"], item["alpha"]))
    return best["alpha"], "validation_selected", {"candidates": candidates}


def unavailable_instance(identity, coverage, denominator, categorical, continuous,
                         model_reasons, detail=None):
    reason = ";".join(model_reasons)
    metrics = []
    for split in SPLIT_ORDER:
        metrics.append(metric_row(identity, split, coverage[split], [], denominator,
                                  fit_partition=fit_partition_for(split),
                                  evaluation_type=evaluation_type_for(split),
                                  model_status="unavailable", model_reason=reason,
                                  metric_status="unavailable", metric_reason=reason))
    parameters = {"identity": identity, "model_status": "unavailable",
                  "model_reasons": model_reasons,
                  "feature_columns": {"categorical": categorical, "continuous": continuous},
                  "coverage": strip_coverage(coverage)}
    if detail is not None:
        parameters["selection_detail"] = detail
    feature_spec = {"identity": identity, "categorical_columns": categorical,
                    "continuous_columns": continuous,
                    "coverage": strip_coverage(coverage),
                    "model_status": "unavailable", "model_reasons": model_reasons}
    return {"identity": identity, "model_status": "unavailable", "model_reasons": model_reasons,
            "metrics": metrics, "predictions": [], "prediction_map": {},
            "parameters": parameters, "feature_spec": feature_spec}


def ridge_parameters(model):
    return {"family": "ridge", "alpha": model["alpha"], "transform": model["transform"],
            "means": model["means"], "scales": model["scales"],
            "dropped_categorical": model["dropped_categorical"],
            "dropped_continuous": model["dropped_continuous"],
            "coefficient_names": model["coefficient_names"],
            "coefficients": model["coefficients"], "columns": model["columns"],
            "training_rows": model["training_rows"]}


def tree_parameters(model):
    return {"family": "bagged_tree", "transform": model["transform"],
            "tree_count": model["tree_count"], "max_depth": model["max_depth"],
            "min_leaf": model["min_leaf"], "sample_fraction": model["sample_fraction"],
            "feature_names": model["feature_names"],
            "feature_split_counts": model["feature_split_counts"],
            "trees": model["trees"], "training_rows": model["training_rows"]}


def key_digest(rows):
    body = "\n".join("|".join(str(part) for part in row["key"]) for row in rows)
    return sha256_text(body)


def strip_coverage(coverage):
    return {split: {name: value for name, value in coverage[split].items()
                    if name not in {"eligible", "eligible_keys"}}
            for split in SPLIT_ORDER}


def score_instance(identity, train, validation, test, coverage, denominator,
                   selection_model, final_model):
    metrics, predictions, prediction_map = [], [], {}
    splits = (
        ("train", train, selection_model),
        ("validation", validation, selection_model),
        ("test", test, final_model),
    )
    for split, rows, model in splits:
        fit_partition = fit_partition_for(split)
        evaluation_type = evaluation_type_for(split)
        if rows:
            try:
                values = predict_model(model, rows)
                pairs = [(row["target_pm25"], prediction)
                         for row, prediction in zip(rows, values)]
                status, reason = "available", None
            except MLError as error:
                if str(error) not in NUMERICAL_PREDICTION_FAILURES:
                    raise
                values, pairs = [], []
                status, reason = "unavailable", str(error)
        else:
            values, pairs = [], []
            status, reason = "unavailable", "no_eligible_rows"
        metrics.append(metric_row(identity, split, coverage[split], pairs, denominator,
                                  fit_partition=fit_partition, evaluation_type=evaluation_type,
                                  model_status="available", model_reason=None,
                                  metric_status=status, metric_reason=reason))
        prediction_map[split] = {}
        for row, prediction in zip(rows, values):
            prediction_map[split][(row["sensor_id"], row["origin"])] = (prediction, row["target_pm25"])
            predictions.append(dict(identity, split=split, fit_partition=fit_partition,
                                    sensor_id=row["sensor_id"], location_id=row["location_id"],
                                    origin=row["origin"], purged=row["purged"],
                                    target_available=row["target_available"],
                                    target_quality=row["target_quality"],
                                    target_pm25=row["target_pm25"],
                                    prediction=prediction, prediction_status="predicted",
                                    prediction_reason=None))
    return metrics, predictions, prediction_map


def sensor_location_map(artifact):
    mapping = {}
    for row in artifact["rows"]:
        existing = mapping.get(row["sensor_id"])
        if existing is None:
            mapping[row["sensor_id"]] = row["location_id"]
        elif existing != row["location_id"]:
            raise MLError(f"Conflicting location mapping for sensor {row['sensor_id']}")
    if not mapping:
        raise MLError("Phase 7 artifact has no sensor rows")
    return mapping


def model_instances(artifact):
    rows = artifact["rows"]
    sensors = artifact["sensors"]
    locations = sensor_location_map(artifact)
    instances = []
    for horizon in HORIZONS:
        horizon_rows = [row for row in rows if row["horizon_hours"] == horizon]
        for feature_set in FEATURE_SETS:
            for family in MODEL_FAMILIES:
                for transform in TARGET_TRANSFORMS:
                    for scope in SCOPES:
                        if scope == "pooled":
                            groups = [("pooled", horizon_rows, sensors, "pooled")]
                        else:
                            groups = [(sensor, [row for row in horizon_rows if row["sensor_id"] == sensor],
                                       [sensor], locations[sensor]) for sensor in sensors]
                        for group_name, group_rows, group_sensors, location in groups:
                            identity = {"model_family": family, "feature_set": feature_set,
                                        "target_transform": transform, "scope": scope,
                                        "sensor_id": group_name, "location_id": location,
                                        "horizon_hours": horizon}
                            digest = identity_key(identity)
                            instances.append(compute_instance(
                                identity, group_rows, feature_set, family, transform, scope,
                                group_sensors, sensors, artifact["rows"], digest))
    return instances


def split_maps(instance, split):
    predictions = {key: value[0] for key, value in
                   instance["prediction_map"].get(split, {}).items()}
    targets = {key: value[1] for key, value in
               instance["prediction_map"].get(split, {}).items()}
    return predictions, targets


def instance_fit_info(instance, split):
    fit_partition = fit_partition_for(split)
    digests = instance["parameters"]["training_key_digest"]
    return fit_partition, digests["final" if fit_partition == "train_plus_validation"
                                  else "selection"]


def baseline_kind(baseline_id):
    for spec in baselines.BASELINE_SPECS:
        if spec["baseline_id"] == baseline_id:
            return spec["kind"]
    return None


def reference_fit_info(artifact, baseline_id, horizon, sensors, predicted_baselines):
    kind = baseline_kind(baseline_id)
    if kind == "feature":
        return None, "not_applicable", "direct_feature_reference"
    if kind == "weather_climatology":
        return None, "unknown", "reference_fit_membership_unavailable"
    if kind != "local_hour_climatology" or baseline_id not in predicted_baselines:
        return None, "unknown", "reference_fit_unavailable"
    rows = [row for row in artifact["rows"]
            if row["horizon_hours"] == horizon and row["sensor_id"] in sensors
            and row["split"] == "train" and not row["purged"]
            and row["target_available"] and baselines.finite(row["target_pm25"])]
    return key_digest(rows), "fitted", None


def build_comparisons(instances, reference_predictions, artifact):
    by_identity = {}
    for instance in instances:
        identity = instance["identity"]
        by_identity[(identity["feature_set"], identity["model_family"], identity["target_transform"],
                     identity["scope"], identity["horizon_hours"], identity["sensor_id"])] = instance
    eligible = {(row["sensor_id"], row["origin"], row["horizon_hours"])
                for row in artifact["rows"]
                if not row["purged"] and row["target_available"]
                and baselines.finite(row["target_pm25"])}
    predicted_baselines = {baseline_id for (baseline_id, _, _, _), entry
                           in reference_predictions.items()
                           if entry["status"] == "predicted"
                           and baselines.finite(entry["prediction"])}
    reference_index = {}
    for (baseline_id, sensor, origin, horizon), entry in reference_predictions.items():
        if entry["status"] != "predicted" or not baselines.finite(entry["prediction"]):
            continue
        if (sensor, origin, horizon) not in eligible:
            continue
        bucket = reference_index.setdefault(
            (baseline_id, entry["split"], horizon, sensor), {})
        bucket[(sensor, origin)] = entry["prediction"]
    comparisons = []
    for instance in instances:
        if instance["model_status"] != "available":
            continue
        identity = instance["identity"]
        scope_sensors = ([identity["sensor_id"]] if identity["scope"] == "per_sensor"
                         else list(artifact["sensors"]))
        for split in SPLIT_ORDER:
            ml_predictions, ml_targets = split_maps(instance, split)
            fit_partition, fit_key_digest = instance_fit_info(instance, split)
            for baseline_id, role in BASELINE_COMPARISONS:
                reference = {}
                for sensor in scope_sensors:
                    reference.update(reference_index.get(
                        (baseline_id, split, identity["horizon_hours"], sensor), {}))
                ref_digest, ref_status, ref_reason = reference_fit_info(
                    artifact, baseline_id, identity["horizon_hours"], scope_sensors,
                    predicted_baselines)
                comparisons.append(comparison_record(
                    identity, split, "ml_vs_baseline", baseline_id, role,
                    ml_predictions, ml_targets, reference,
                    fit_partition=fit_partition, fit_key_digest=fit_key_digest,
                    reference_fit_partition=("train" if ref_status == "fitted" else None),
                    reference_fit_key_digest=ref_digest,
                    reference_fit_status=ref_status, reference_fit_reason=ref_reason,
                    reference_finite_rows=len(reference)))
        counterpart = None
        kind, label = None, None
        if identity["feature_set"] == "calendar_only":
            counterpart = by_identity.get(("history_only", identity["model_family"],
                                           identity["target_transform"], identity["scope"],
                                           identity["horizon_hours"], identity["sensor_id"]))
            kind, label = "ablation_history", "history_only"
        elif identity["feature_set"] == "history_only":
            counterpart = by_identity.get(("history_weather", identity["model_family"],
                                           identity["target_transform"], identity["scope"],
                                           identity["horizon_hours"], identity["sensor_id"]))
            kind, label = "ablation_weather", "history_weather"
        if counterpart is not None:
            available = counterpart["model_status"] == "available"
            for split in SPLIT_ORDER:
                ml_predictions, ml_targets = split_maps(instance, split)
                fit_partition, fit_key_digest = instance_fit_info(instance, split)
                if available:
                    other, _ = split_maps(counterpart, split)
                    counterpart_partition, counterpart_digest = instance_fit_info(counterpart,
                                                                                  split)
                    counterpart_status = "fitted"
                else:
                    other = {}
                    counterpart_partition, counterpart_digest = None, None
                    counterpart_status = "not_paired"
                comparisons.append(comparison_record(
                    identity, split, kind, label, "ablation",
                    ml_predictions, ml_targets, other,
                    fit_partition=fit_partition, fit_key_digest=fit_key_digest,
                    reference_fit_partition=counterpart_partition,
                    reference_fit_key_digest=counterpart_digest,
                    reference_fit_status=counterpart_status,
                    reference_fit_reason=(None if available
                                          else "counterpart_model_unavailable"),
                    reference_finite_rows=len(other),
                    counterpart_fit_partition=counterpart_partition,
                    counterpart_fit_key_digest=counterpart_digest,
                    counterpart_reason=None if available else "counterpart_model_unavailable"))
    return comparisons


def paired_key_digest(keys):
    payload = []
    for key in sorted(keys):
        if isinstance(key, (tuple, list)):
            payload.append([str(part) for part in key])
        else:
            payload.append(str(key))
    return baselines.digest(payload)


def comparison_record(identity, split, kind, reference_id, reference_role, model_predictions,
                      model_targets, reference, *, fit_partition, fit_key_digest,
                      reference_fit_partition=None, reference_fit_key_digest=None,
                      reference_fit_status="fitted", reference_fit_reason=None,
                      reference_finite_rows=0,
                      counterpart_fit_partition=None, counterpart_fit_key_digest=None,
                      counterpart_reason=None):
    shared = sorted(key for key in model_predictions
                    if key in reference and key in model_targets
                    and baselines.finite(reference[key]) and baselines.finite(model_targets[key]))
    if counterpart_reason is not None or not shared:
        history_status = "not_paired"
    elif reference_fit_status == "not_applicable":
        history_status = "not_applicable"
    elif reference_fit_status != "fitted" or reference_fit_key_digest is None:
        history_status = "unknown"
    elif (reference_fit_partition != fit_partition
          or reference_fit_key_digest != fit_key_digest):
        history_status = "training_history_mismatch"
    else:
        history_status = "matched"
    record = {name: identity[name] for name in ("model_family", "feature_set", "target_transform",
                                                "scope", "sensor_id", "location_id",
                                                "horizon_hours")}
    record.update({"split": split, "comparison_kind": kind,
                   "reference_baseline": reference_id, "reference_role": reference_role,
                   "comparison_status": "not_paired",
                   "fit_partition": fit_partition, "fit_key_digest": fit_key_digest,
                   "reference_fit_partition": reference_fit_partition,
                   "reference_fit_key_digest": reference_fit_key_digest,
                   "reference_fit_status": reference_fit_status,
                   "reference_fit_reason": reference_fit_reason,
                   "counterpart_fit_partition": counterpart_fit_partition,
                   "counterpart_fit_key_digest": counterpart_fit_key_digest,
                   "model_finite_rows": len(model_predictions),
                   "reference_finite_rows": reference_finite_rows,
                   "paired_rows": 0, "paired_key_digest": None,
                   "history_status": history_status,
                   "metric_scope": "descriptive_only"})
    if not shared:
        record["comparison_reason"] = (counterpart_reason
                                       or "no_shared_finite_prediction_keys")
        return record
    if len(shared) > min(len(model_predictions), reference_finite_rows):
        raise MLError("Comparison pairing exceeds a side's finite-row count")
    model_errors = [model_predictions[key] - model_targets[key] for key in shared]
    reference_errors = [reference[key] - model_targets[key] for key in shared]
    model_mae = statistics.fmean(abs(value) for value in model_errors)
    reference_mae = statistics.fmean(abs(value) for value in reference_errors)
    model_rmse = math.sqrt(statistics.fmean(value * value for value in model_errors))
    reference_rmse = math.sqrt(statistics.fmean(value * value for value in reference_errors))
    record.update({"comparison_status": "paired", "paired_rows": len(shared),
                   "paired_key_digest": paired_key_digest(shared),
                   "model_mae": model_mae, "reference_mae": reference_mae,
                   "mae_delta": model_mae - reference_mae,
                   "model_rmse": model_rmse, "reference_rmse": reference_rmse,
                   "rmse_delta": model_rmse - reference_rmse,
                   "comparison_reason": None})
    return record


def validate_reference_rows(artifact, reference):
    allowed_baselines = {spec["baseline_id"] for spec in baselines.BASELINE_SPECS}
    feature_by_key = {row["key"]: row for row in artifact["rows"]}
    required = {(baseline_id, row["key"][0], row["key"][1], row["key"][2])
                for baseline_id in allowed_baselines for row in artifact["rows"]}
    actual = set(reference["predictions"])
    if actual != required:
        missing = len(required - actual)
        extra = len(actual - required)
        raise MLError("Phase 8 reference prediction keys do not align with the "
                      f"Phase 7 artifact (missing={missing}, extra={extra})")
    for (baseline_id, sensor_id, origin, horizon), entry in reference["predictions"].items():
        if baseline_id not in allowed_baselines:
            raise MLError("Phase 8 reference row uses an undeclared baseline")
        if reference["baseline_roles"].get(baseline_id) != entry["role"]:
            raise MLError("Phase 8 reference baseline role does not match its declaration")
        key = (sensor_id, origin, horizon)
        feature = feature_by_key.get(key)
        target = artifact["target_by_key"].get(key)
        if feature is None or target is None:
            raise MLError("Phase 8 reference row has no matching Phase 7 key")
        if entry["location_id"] != feature["location_id"]:
            raise MLError("Phase 8 reference location identity does not match Phase 7")
        if entry["split"] != feature["split"] or entry["purged"] != feature["purged"]:
            raise MLError("Phase 8 reference split or purge identity does not match Phase 7")
        if (entry["target_available"] != feature["target_available"]
                or entry["target_available"] != target["target_available"]):
            raise MLError("Phase 8 reference target availability does not match Phase 7")
        if entry["status"] not in REFERENCE_STATUSES:
            raise MLError("Phase 8 reference row has an unknown prediction status")
        if entry["status"] == "predicted":
            if not baselines.finite(entry["prediction"]):
                raise MLError("Phase 8 reference predicted row lacks a finite prediction")
            if entry["reason"]:
                raise MLError("Phase 8 reference predicted row carries an unavailable reason")
        else:
            if entry["prediction"] is not None:
                raise MLError("Phase 8 reference unavailable row carries a prediction")
            if not entry["reason"]:
                raise MLError("Phase 8 reference unavailable row lacks a reason")


def static_manifest(artifact, reference):
    missing = artifact["manifest"].get("status_missing_families") or []
    return {
        "model_version": ML_VERSION,
        "revision": REVISION,
        "superseded_artifact_identities": SUPERSEDED_ARTIFACTS,
        "correction_plan": CORRECTION_PLAN,
        "purpose": PURPOSE,
        "phase7": {
            "feature_version": artifact["manifest"]["feature_version"],
            "manifest_sha256": artifact["summary"]["manifest_sha256"],
            "summary_sha256": baselines.sha256_file(artifact["paths"][PHASE7_SUMMARY_NAME]),
            "features_sha256": baselines.sha256_file(artifact["paths"][PHASE7_PREDICTIONS_NAME]),
            "targets_sha256": baselines.sha256_file(artifact["paths"]["phase_7_targets.csv"]),
            "success_sha256": baselines.sha256_file(artifact["paths"][SUCCESS_NAME]),
            "observed_payload_sha256": artifact["payload_sha256"],
            "expected_payload_sha256": artifact["expected_payload_sha256"],
            "payload_map_sha256": baselines.digest(artifact["payload_sha256"]),
            "bundle_sha256": artifact["manifest"].get("bundle_sha256"),
            "bundle_file_sha256": artifact["manifest"].get("bundle_file_sha256"),
            "availability_basis": artifact["manifest"].get("availability_basis"),
            "boundary": artifact["manifest"].get("boundary"),
            "horizons": list(HORIZONS),
            "split": artifact["manifest"].get("split"),
            "status": artifact["manifest"].get("status"),
            "status_missing_families": list(missing),
            "counts": artifact["manifest"].get("counts"),
        },
        "phase8_reference": {
            "baseline_version": reference["manifest"]["baseline_version"],
            "manifest_sha256": reference["summary"]["manifest_sha256"],
            "summary_sha256": baselines.sha256_file(reference["directory"] / PHASE8_SUMMARY_NAME),
            "predictions_sha256": baselines.sha256_file(reference["directory"] / PHASE8_PREDICTIONS_NAME),
            "success_sha256": baselines.sha256_file(reference["directory"] / SUCCESS_NAME),
            "observed_payload_sha256": reference["payload_sha256"],
            "expected_payload_sha256": reference["expected_payload_sha256"],
            "payload_map_sha256": baselines.digest(reference["payload_sha256"]),
        },
        "horizons": list(HORIZONS),
        "feature_sets": list(FEATURE_SETS),
        "model_families": list(MODEL_FAMILIES),
        "target_transforms": list(TARGET_TRANSFORMS),
        "scopes": list(SCOPES),
        "sensors": list(artifact["sensors"]),
        "model_definitions": {
            "ridge": {"alphas": list(RIDGE_ALPHAS), "fallback_alpha": RIDGE_FALLBACK_ALPHA,
                      "intercept_regularized": False,
                      "continuous_standardization": "train_partition_only"},
            "bagged_tree": {"tree_count": TREE_COUNT, "max_depth": TREE_MAX_DEPTH,
                            "min_leaf": TREE_MIN_LEAF,
                            "sample_fraction": TREE_SAMPLE_FRACTION, "base_seed": BASE_SEED,
                            "seed_policy": "sha256(base_seed:spec_digest:tree_index)"},
        },
        "feature_allowlists": {feature_set: {
            "categorical": feature_columns(feature_set, artifact["sensors"], "pooled")[0],
            "continuous": feature_columns(feature_set, artifact["sensors"], "pooled")[1]}
            for feature_set in FEATURE_SETS},
        "row_gates": {"min_train_rows": MIN_TRAIN_ROWS, "min_train_dates": MIN_TRAIN_DATES,
                      "min_tree_train_rows": MIN_TREE_TRAIN_ROWS},
        "selection_policy": ("Ridge alpha is selected by validation RMSE on the PM2.5 scale "
                             "with a smaller-alpha tie-break; every declared specification is "
                             "reported and no model, feature set or transform is selected on test."),
        "fit_partitions": {"selection": "train", "final": "train_plus_validation",
                           "test_used_for_selection": False},
        "test_selection_used": False,
        "metric_scope": "descriptive_only",
        "transform_policy": ("Continuous features are standardized on the declared fit partition "
                             "only; no imputation, interpolation, forward fill or target-derived feature."),
        "implementation_sha256": {
            "ml.py": baselines.sha256_file(Path(__file__)),
            "ml_output.py": baselines.sha256_file(Path(__file__).with_name("ml_output.py")),
        },
    }


def replay_projection(manifest):
    projection = {}
    for key in REPLAY_STATIC_KEYS:
        if key not in manifest:
            raise MLError(f"Phase 9 summary manifest is missing the replay-bound field {key}")
        projection[key] = manifest[key]
    return projection


def compute_ml(artifact, reference):
    validate_reference_rows(artifact, reference)
    instances = model_instances(artifact)
    metrics = [row for instance in instances for row in instance["metrics"]]
    predictions = [row for instance in instances for row in instance["predictions"]]
    metrics.sort(key=lambda row: (row["horizon_hours"], row["feature_set"], row["model_family"],
                                  row["target_transform"], row["scope"], row["sensor_id"],
                                  SPLIT_ORDER.index(row["split"])))
    predictions.sort(key=lambda row: (row["horizon_hours"], row["feature_set"], row["model_family"],
                                      row["target_transform"], row["scope"], row["sensor_id"],
                                      SPLIT_ORDER.index(row["split"]), row["origin"]))
    comparisons = build_comparisons(instances, reference["predictions"], artifact)
    parameter_fits = [instance["parameters"] for instance in instances]
    feature_specs = [instance["feature_spec"] for instance in instances]
    available = [instance for instance in instances if instance["model_status"] == "available"]
    unavailable = [instance for instance in instances if instance["model_status"] != "available"]
    metric_available = sum(1 for row in metrics if row["metric_status"] == "available")
    metric_unavailable = len(metrics) - metric_available
    status_reasons = []
    missing = artifact["manifest"].get("status_missing_families") or []
    if "pm_history" in missing:
        status_reasons.append("phase7_pm_history_unavailable")
    if "forecast_weather" in missing:
        status_reasons.append("phase7_forecast_weather_unavailable")
    if metric_unavailable:
        status_reasons.append("model_cells_unavailable")
    manifest = static_manifest(artifact, reference)
    manifest.update({
        "counts": {
            "model_instances": len(instances),
            "trained_instances": len(available),
            "unavailable_instances": len(unavailable),
            "metric_cells": len(metrics),
            "available_metric_cells": metric_available,
            "unavailable_metric_cells": metric_unavailable,
            "prediction_rows": len(predictions),
            "comparison_records": len(comparisons),
        },
        "status": "ok" if not status_reasons else "limited_diagnostic",
        "status_reasons": status_reasons,
        "prospective_collection_period_required": bool(
            artifact["manifest"].get("prospective_collection_period_required")
            or artifact["manifest"].get("status_missing_families")),
        "metrics": metrics,
        "comparisons": comparisons,
        "limitations": [
            "All metrics are descriptive diagnostics, not forecast-skill certification.",
            "The frozen Phase 7 captured artifact has no prospectively captured PM/weather features, so history and weather models are unavailable.",
            "The calendar diagnostic uses local calendar fields and training targets only; it is not an operational forecast.",
            "Pooled results are a descriptive combination of two non-reference sensor sites, not a city average.",
            "The final test period is scored once by a train-plus-validation refit and never used for selection.",
        ],
    })
    return {"purpose": PURPOSE, "model_version": ML_VERSION, "manifest": manifest,
            "manifest_sha256": baselines.digest(manifest), "metrics": metrics,
            "predictions": predictions,
            "parameters": {"model_version": ML_VERSION,
                           "phase7_feature_version": artifact["manifest"]["feature_version"],
                           "fits": parameter_fits},
            "feature_manifest": {"model_version": ML_VERSION,
                                 "phase7_feature_version": artifact["manifest"]["feature_version"],
                                 "train_only_transform_policy": "fit partition means/scales only",
                                 "row_gates": {"min_train_rows": MIN_TRAIN_ROWS,
                                               "min_train_dates": MIN_TRAIN_DATES,
                                               "min_tree_train_rows": MIN_TREE_TRAIN_ROWS},
                                 "source_policy": ("only captured Phase 7 feature columns in the "
                                                   "declared allowlist; ERA5, CAMS, assumed mode, targets "
                                                   "and lineage fields excluded"),
                                 "allowlists": {feature_set: {
                                     "categorical": feature_columns(feature_set, artifact["sensors"], "pooled")[0],
                                     "continuous": feature_columns(feature_set, artifact["sensors"], "pooled")[1]}
                                     for feature_set in FEATURE_SETS},
                                 "specs": feature_specs}}


def load_inputs(artifact_dir, baseline_dir, *, expected_identities=True):
    artifact = load_phase7(
        artifact_dir,
        expected_manifest=EXPECTED_PHASE7_MANIFEST_SHA256 if expected_identities else None,
        expected_payloads=EXPECTED_PHASE7_PAYLOAD_SHA256 if expected_identities else None)
    reference = load_baseline_reference(
        baseline_dir,
        expected_manifest=EXPECTED_PHASE8_MANIFEST_SHA256 if expected_identities else None,
        expected_payloads=EXPECTED_PHASE8_PAYLOAD_SHA256 if expected_identities else None)
    return artifact, reference


def run_ml(artifact_dir, baseline_dir, *, expected_identities=True, output_dir=None):
    if output_dir is not None:
        require_new_output_dir(output_dir)
    artifact, reference = load_inputs(artifact_dir, baseline_dir,
                                      expected_identities=expected_identities)
    return compute_ml(artifact, reference)


def read_summary(path):
    summary = baselines.read_metadata(path, "Phase 9 summary")
    expected = {"purpose", "model_version", "manifest", "manifest_sha256"}
    if set(summary) != expected:
        raise MLError("Phase 9 summary has unexpected top-level fields")
    if summary.get("model_version") != ML_VERSION or summary.get("purpose") != PURPOSE:
        raise MLError("Phase 9 summary implementation identity does not match")
    manifest = summary.get("manifest")
    if not isinstance(manifest, dict) or baselines.digest(manifest) != summary.get("manifest_sha256"):
        raise MLError("Phase 9 summary manifest digest does not match")
    return summary


PREDICTION_FIELDS = ("model_family", "feature_set", "target_transform", "scope", "sensor_id",
                     "location_id", "origin", "horizon_hours", "split", "fit_partition",
                     "purged", "target_available", "target_quality", "target_pm25",
                     "prediction", "prediction_status", "prediction_reason")
METRIC_FIELDS = ("model_family", "feature_set", "target_transform", "scope", "sensor_id",
                 "location_id", "horizon_hours", "split", "fit_partition", "evaluation_type",
                 "candidate_rows", "purged_rows_excluded", "unavailable_target_rows",
                 "incomplete_feature_rows", "incomplete_history_rows", "incomplete_weather_rows",
                 "eligible_rows", "coverage_percent", "model_status", "model_reason",
                 "metric_status", "metric_reason", "metric_scope")


def write_table(path, rows, required_fields):
    if rows:
        baselines.write_csv(path, rows)
        return
    import csv
    with path.open("x", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=list(required_fields), lineterminator="\n").writeheader()


def write_outputs(output_dir, result):
    output_dir = Path(output_dir)
    if output_dir.exists() or not output_dir.parent.is_dir():
        raise MLError("Phase 9 output directory must be new and its parent must exist")
    output_dir.mkdir(mode=0o700)
    summary = {"purpose": result["purpose"], "model_version": result["model_version"],
               "manifest": result["manifest"], "manifest_sha256": result["manifest_sha256"]}
    with (output_dir / OUTPUT_SUMMARY_NAME).open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, sort_keys=True, ensure_ascii=True, allow_nan=False,
                  separators=(",", ":"))
        handle.write("\n")
    write_table(output_dir / OUTPUT_METRICS_NAME, result["metrics"], METRIC_FIELDS)
    write_table(output_dir / OUTPUT_PREDICTIONS_NAME, result["predictions"], PREDICTION_FIELDS)
    for name, payload in ((OUTPUT_PARAMETERS_NAME, result["parameters"]),
                          (OUTPUT_FEATURES_NAME, result["feature_manifest"])):
        with (output_dir / name).open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":"))
            handle.write("\n")
    with (output_dir / OUTPUT_ASSUMPTIONS_NAME).open("x", encoding="utf-8") as handle:
        handle.write(assumptions_markdown(result))
    files = {path.name: baselines.sha256_file(path) for path in sorted(output_dir.iterdir())}
    with (output_dir / OUTPUT_SUCCESS_NAME).open("x", encoding="utf-8") as handle:
        json.dump({"model_version": ML_VERSION, "manifest_sha256": result["manifest_sha256"],
                   "files_sha256": files}, handle, sort_keys=True, indent=2)
        handle.write("\n")
    return {"output_dir": str(output_dir), "manifest_sha256": result["manifest_sha256"],
            "file_count": len(files) + 1}


def replay_ml(artifact_dir, baseline_dir, summary_path, output_dir, *, expected_identities=True):
    require_new_output_dir(output_dir)
    previous = read_summary(summary_path)
    prior_manifest = previous["manifest"]
    prior_digest = previous["manifest_sha256"]
    artifact, reference = load_inputs(artifact_dir, baseline_dir,
                                      expected_identities=expected_identities)
    if baselines.digest(replay_projection(prior_manifest)) != baselines.digest(
            replay_projection(static_manifest(artifact, reference))):
        raise MLError("Phase 9 summary-bound replay mismatch: static replay contract differs")
    result = compute_ml(artifact, reference)
    if result["manifest"] != prior_manifest:
        raise MLError("Phase 9 summary-bound replay mismatch: recomputed manifest differs")
    if result["manifest_sha256"] != prior_digest:
        raise MLError("Phase 9 summary-bound replay mismatch: manifest digest differs")
    return write_outputs(output_dir, result)


def assumptions_markdown(result):
    manifest = result["manifest"]
    lines = [
        "# Phase 9 Machine Learning: Assumptions and Limitations",
        "",
        "Deterministic, database-free chronological ML diagnostics over one Phase 7 captured",
        "feature artifact with a Phase 8 v2 reference comparison. No operational forecast claim.",
        "",
        "## Inputs and boundary",
        "",
        f"- Model version: `{manifest['model_version']}`",
        f"- Phase 7 feature version: `{manifest['phase7']['feature_version']}`",
        f"- Phase 7 manifest SHA-256: `{manifest['phase7']['manifest_sha256']}`",
        f"- Phase 8 reference: `{manifest['phase8_reference']['baseline_version']}` "
        f"(`{manifest['phase8_reference']['manifest_sha256']}`)",
        f"- Availability basis: `{manifest['phase7']['availability_basis']}`; horizons: `{manifest['horizons']}`",
        f"- Status: `{manifest['status']}`; reasons: `{json.dumps(manifest['status_reasons'])}`",
        f"- Test used for selection: `{manifest['test_selection_used']}`",
        "",
        "## Models and features",
        "",
        "- Ridge with an unregularized intercept and train-partition-only standardization;",
        "- 25 shallow bagged trees (depth 4, minimum leaf 10, 80% bootstrap) with SHA-256 seeds;",
        "- Feature sets: calendar-only, history-only, weather-only and history+weather;",
        "- Target transforms: log1p (primary) and raw (sensitivity), both with a non-negative reporting bound.",
        "",
        "## Rules",
        "",
        "- Only finite, accepted, non-purged targets are scored; no imputation of missing features;",
        "- Every declared specification is reported; no model, feature set or transform is selected on test;",
        "- Final test scoring uses a train-plus-validation refit after validation-only alpha selection;",
        "- Predictions are descriptive and must not be presented as forecast skill.",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in result["manifest"]["limitations"])
    return "\n".join(lines) + "\n"


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="vn-air-ml")
    actions = parser.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run")
    run.add_argument("--artifact", type=Path, required=True)
    run.add_argument("--baseline-artifact", type=Path, required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    replay = actions.add_parser("replay")
    replay.add_argument("--artifact", type=Path, required=True)
    replay.add_argument("--baseline-artifact", type=Path, required=True)
    replay.add_argument("--summary", type=Path, required=True)
    replay.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "run":
            result = run_ml(args.artifact, args.baseline_artifact, output_dir=args.output_dir)
            print(json.dumps(write_outputs(args.output_dir, result), sort_keys=True))
        else:
            print(json.dumps(replay_ml(args.artifact, args.baseline_artifact, args.summary,
                                       args.output_dir), sort_keys=True))
        return 0
    except (MLError, baselines.BaselineError, OSError) as error:
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
