"""Offline tests for the Phase 9 chronological machine-learning runner."""

import csv
import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from vn_air import baselines, ml


ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
START = datetime(2026, 6, 8, tzinfo=UTC)
VAL_START = START + timedelta(hours=120)
TEST_START = START + timedelta(hours=144)
SENSORS = (("sensor_a", "loc_a"), ("sensor_b", "loc_b"))


def iso(moment):
    return moment.isoformat()


def write_rows(path, rows):
    fields = sorted({field for row in rows for field in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_phase7(root, *, history=True, weather=True, origins=168, extra_columns=None,
                feature_mutation=None, target_mutation=None, extra_payloads=None):
    root.mkdir()
    features, targets = [], []
    for sensor_index, (sensor_id, location_id) in enumerate(SENSORS):
        for offset in range(origins):
            origin = START + timedelta(hours=offset)
            local = origin + timedelta(hours=7)
            for horizon in (6, 24):
                target_end = origin + timedelta(hours=horizon)
                split = "train" if origin < VAL_START else (
                    "validation" if origin < TEST_START else "test")
                purged = ((split == "train" and target_end > VAL_START)
                          or (split == "validation" and target_end > TEST_START))
                absent = offset % 19 == 7
                feature = {
                    "sensor_id": sensor_id, "location_id": location_id,
                    "origin": iso(origin), "origin_local_date": local.date().isoformat(),
                    "origin_local_hour": local.hour, "origin_local_weekday": local.weekday(),
                    "horizon_hours": horizon,
                    "target_start": iso(target_end - timedelta(hours=1)),
                    "target_end": iso(target_end), "split": split, "purged": str(purged),
                    "target_available": str(not absent),
                    "pm_history_reason": "ok" if history else "no_eligible_accepted_values",
                    "weather_forecast_reason": "ok" if weather else "no_eligible_vintage",
                }
                for index, column in enumerate(ml.PM_HISTORY_COLUMNS):
                    feature[column] = "" if not history else str(
                        5.0 + sensor_index + (offset % 11) + index * 0.25)
                for index, column in enumerate(ml.WEATHER_COLUMNS):
                    feature[column] = "" if not weather else str(
                        20.0 + sensor_index + (offset % 5) + index * 0.5)
                if extra_columns:
                    feature.update(extra_columns)
                if feature_mutation:
                    feature_mutation(feature)
                target = {
                    "sensor_id": sensor_id, "location_id": location_id,
                    "origin": iso(origin), "horizon_hours": horizon,
                    "target_available": str(not absent),
                    "target_pm25": "" if absent else str(10.0 + (offset % 9) + sensor_index),
                    "target_quality": "accepted" if not absent else "",
                    "target_start": feature["target_start"], "target_end": feature["target_end"],
                    "target_missing_reason": "target_absent" if absent else "",
                }
                if target_mutation:
                    target_mutation(target)
                features.append(feature)
                targets.append(target)
    write_rows(root / "phase_7_features.csv", features)
    write_rows(root / "phase_7_targets.csv", targets)
    missing = []
    if not history:
        missing.append("pm_history")
    if not weather:
        missing.append("forecast_weather")
    manifest = {
        "feature_version": "phase7_features_v7", "horizons": [6, 24],
        "availability_basis": "captured", "bundle_sha256": "b" * 64,
        "bundle_file_sha256": "f" * 64, "boundary": {"mode": "explicit"},
        "split": {"validation_start": iso(VAL_START), "test_start": iso(TEST_START)},
        "counts": {"rows": len(features)}, "status": "ok" if not missing else "limited_diagnostic",
        "status_missing_families": missing,
        "prospective_collection_period_required": bool(missing),
    }
    summary = {"purpose": "synthetic Phase 7 artifact", "manifest": manifest,
               "manifest_sha256": baselines.digest(manifest)}
    payload_names = [summary_name := "phase_7_feature_summary.json",
                     "phase_7_features.csv", "phase_7_targets.csv"]
    for name, content in (extra_payloads or {}).items():
        (root / name).write_text(content, encoding="utf-8")
        payload_names.append(name)
    write_summary_bundle(root, summary, summary_name, manifest, "phase7_features_v7",
                         payload_names)
    return root


def write_summary_bundle(root, summary, summary_name, manifest, version_key, payload_names):
    (root / summary_name).write_text(
        json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
             for name in payload_names}
    success = {"feature_version": version_key, "manifest_sha256": summary["manifest_sha256"],
               "bundle_sha256": manifest["bundle_sha256"], "availability_basis": "captured",
               "files_sha256": files}
    (root / "SUCCESS.json").write_text(json.dumps(success, sort_keys=True, indent=2) + "\n",
                                       encoding="utf-8")


def make_phase8_reference(root, phase7_dir, extra_payloads=None):
    root.mkdir()
    with (phase7_dir / "phase_7_features.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    baseline_roles = {
        "persistence_last_available": "primary_reference",
        "persistence_lag_1h": "sensitivity",
        "trailing_mean_24h": "sensitivity",
        "local_hour_climatology": "diagnostic_calendar",
        "weather_augmented_climatology": "diagnostic_weather",
    }
    predicted_baselines = {"local_hour_climatology", "persistence_last_available",
                           "weather_augmented_climatology"}
    predictions = []
    for raw in rows:
        for baseline_id, role in baseline_roles.items():
            predicted = baseline_id in predicted_baselines
            predictions.append({
                "baseline_id": baseline_id, "baseline_role": role,
                "feature_version": "phase7_features_v7",
                "horizon_hours": raw["horizon_hours"], "location_id": raw["location_id"],
                "origin": raw["origin"],
                "prediction": str(10.0 + int(raw["origin_local_hour"]) % 5) if predicted else "",
                "prediction_reason": "" if predicted else "baseline_unavailable",
                "prediction_status": "predicted" if predicted else "unavailable",
                "purged": raw["purged"], "sensor_id": raw["sensor_id"], "split": raw["split"],
                "target_available": raw["target_available"], "target_pm25": "",
            })
    write_rows(root / "phase_8_predictions.csv", predictions)
    manifest = {"baseline_version": "phase8_baselines_v2", "feature_version": "phase7_features_v7",
                "status": "limited_diagnostic", "availability_basis": "captured",
                "horizons": [6, 24],
                "baseline_definitions": [{"baseline_id": baseline_id, "role": role}
                                         for baseline_id, role in baseline_roles.items()],
                "split": {"validation_start": iso(VAL_START), "test_start": iso(TEST_START)}}
    summary = {"purpose": "synthetic Phase 8 reference", "manifest": manifest,
               "manifest_sha256": baselines.digest(manifest)}
    (root / "phase_8_baselines_summary.json").write_text(
        json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    payload_names = ["phase_8_baselines_summary.json", "phase_8_predictions.csv"]
    for name, content in (extra_payloads or {}).items():
        (root / name).write_text(content, encoding="utf-8")
        payload_names.append(name)
    files = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
             for name in payload_names}
    success = {"baseline_version": "phase8_baselines_v2",
               "manifest_sha256": summary["manifest_sha256"], "files_sha256": files}
    (root / "SUCCESS.json").write_text(json.dumps(success, sort_keys=True, indent=2) + "\n",
                                       encoding="utf-8")
    return root


def resign(root):
    success = json.loads((root / "SUCCESS.json").read_text())
    success["files_sha256"] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                               for name in success["files_sha256"]}
    (root / "SUCCESS.json").write_text(json.dumps(success, sort_keys=True, indent=2) + "\n",
                                       encoding="utf-8")


def mutate_predictions(root, mutate):
    path = root / "phase_8_predictions.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows, fields = list(reader), reader.fieldnames
    mutate(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    resign(root)


def first_row(rows, baseline_id):
    return next(row for row in rows if row["baseline_id"] == baseline_id)


def mutate_value(path, column, transform):
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows, fields = list(reader), reader.fieldnames
    row = next(item for item in rows if item.get(column) not in (None, ""))
    row[column] = transform(row[column])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def compute_instance(artifact, *, feature_set="calendar_only", family="ridge",
                     transform="raw", scope="pooled", sensor="sensor_a", horizon=6):
    location = next(row["location_id"] for row in artifact["rows"]
                    if row["sensor_id"] == sensor) if scope == "per_sensor" else "pooled"
    identity = {"model_family": family, "feature_set": feature_set,
                "target_transform": transform, "scope": scope,
                "sensor_id": sensor if scope == "per_sensor" else "pooled",
                "location_id": location,
                "horizon_hours": horizon}
    group_rows = [row for row in artifact["rows"] if row["horizon_hours"] == horizon
                  and (scope == "pooled" or row["sensor_id"] == sensor)]
    group_sensors = artifact["sensors"] if scope == "pooled" else [sensor]
    return ml.compute_instance(identity, group_rows, feature_set, family, transform, scope,
                               group_sensors, artifact["sensors"], artifact["rows"],
                               ml.identity_key(identity))


def model_row(x, y, *, hour=0, weekday=0, sensor="sensor_a"):
    return {"origin_local_hour": hour, "origin_local_weekday": weekday, "sensor_id": sensor,
            "values": {"x": x}, "day_index": 0, "target_pm25": y}


def reduced_scope():
    return (
        mock.patch.object(ml, "FEATURE_SETS", ("calendar_only",)),
        mock.patch.object(ml, "TREE_COUNT", 3),
    )


def run_reduced(root, reference_root, output_a, output_b):
    artifact = ml.load_phase7(root)
    reference = ml.load_baseline_reference(reference_root)
    with reduced_scope()[0], reduced_scope()[1]:
        result = ml.compute_ml(artifact, reference)
        ml.write_outputs(output_a, result)
        ml.replay_ml(root, reference_root, output_a / ml.OUTPUT_SUMMARY_NAME, output_b,
                     expected_identities=False)
    return result


class Phase9Tests(unittest.TestCase):
    def test_phase7_hash_manifest_is_mandatory_and_tamper_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            success = json.loads((root / "SUCCESS.json").read_text())
            del success["files_sha256"]["phase_7_features.csv"]
            (root / "SUCCESS.json").write_text(json.dumps(success), encoding="utf-8")
            with self.assertRaises(baselines.BaselineError):
                ml.load_phase7(root)
            root2 = make_phase7(Path(directory) / "phase7b")
            path = root2 / "phase_7_features.csv"
            path.write_text(path.read_text().replace("sensor_a", "sensor_x", 1), encoding="utf-8")
            with self.assertRaises(baselines.BaselineError):
                ml.load_phase7(root2)

    def test_frozen_identity_and_reference_identity_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            with self.assertRaises(ml.MLError):
                ml.run_ml(root, reference, expected_identities=True)
            with self.assertRaises(ml.MLError):
                ml.load_baseline_reference(reference, expected_manifest="0" * 64)

    def test_key_misalignment_and_injected_target_columns_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            with (root / "phase_7_targets.csv").open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            write_rows(root / "phase_7_targets.csv", rows[:-1])
            with self.assertRaises(baselines.BaselineError):
                ml.load_phase7(root)
            with self.assertRaises(ml.MLError):
                ml.validate_feature_allowlist(["pm25_lag_1h", "target_pm25", "lineage_id"])
            with self.assertRaises(ml.MLError):
                ml.validate_feature_allowlist(["weather_forecast_snapshot_id"])

    def test_non_allowlisted_source_columns_never_enter_design(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7",
                               extra_columns={"cams_pm25": "1.0", "era5_temperature_2m": "2.0"})
            artifact = ml.load_phase7(root)
            columns = ml.feature_columns("history_weather", artifact["sensors"], "pooled")[1]
            self.assertNotIn("cams_pm25", columns)
            self.assertNotIn("era5_temperature_2m", columns)

    def test_assumed_availability_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            summary = json.loads((root / "phase_7_feature_summary.json").read_text())
            summary["manifest"]["availability_basis"] = "assumed"
            summary["manifest_sha256"] = baselines.digest(summary["manifest"])
            (root / "phase_7_feature_summary.json").write_text(
                json.dumps(summary, sort_keys=True, separators=(",", ":")), encoding="utf-8")
            success = json.loads((root / "SUCCESS.json").read_text())
            success["availability_basis"] = "assumed"
            success["manifest_sha256"] = summary["manifest_sha256"]
            success["files_sha256"]["phase_7_feature_summary.json"] = hashlib.sha256(
                (root / "phase_7_feature_summary.json").read_bytes()).hexdigest()
            (root / "SUCCESS.json").write_text(json.dumps(success), encoding="utf-8")
            with self.assertRaises(baselines.BaselineError):
                ml.load_phase7(root)

    def test_purged_rows_are_excluded_from_partitions_and_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7"))
            _, coverage = ml.partition_rows(
                [row for row in artifact["rows"] if row["horizon_hours"] == 6], "calendar_only")
            for split in ml.SPLIT_ORDER:
                eligible_keys = {row["key"] for row in coverage[split]["eligible"]}
                purged_keys = {row["key"] for row in artifact["rows"]
                               if row["horizon_hours"] == 6 and row["split"] == split
                               and row["purged"]}
                self.assertFalse(eligible_keys & purged_keys)
            instance = compute_instance(artifact)
            self.assertGreater(instance["metrics"][0]["purged_rows_excluded"], 0)

    def test_test_mutation_changes_only_test_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7"))
            before = compute_instance(artifact, family="ridge")
            for row in artifact["rows"]:
                if (row["split"] == "test" and row["horizon_hours"] == 6 and not row["purged"]
                        and row["target_available"] and row["target_pm25"] is not None):
                    row["target_pm25"] += 100.0
            after = compute_instance(artifact, family="ridge")
            self.assertEqual(before["parameters"]["selection_fit"]["coefficients"],
                             after["parameters"]["selection_fit"]["coefficients"])
            self.assertEqual(before["parameters"]["final_fit"]["coefficients"],
                             after["parameters"]["final_fit"]["coefficients"])
            before_test = next(row for row in before["metrics"] if row["split"] == "test")
            after_test = next(row for row in after["metrics"] if row["split"] == "test")
            self.assertNotEqual(before_test["mae"], after_test["mae"])

    def test_validation_mutation_preserves_train_transformations(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7"))
            before = compute_instance(artifact, family="ridge")
            for row in artifact["rows"]:
                if row["split"] == "validation" and row["horizon_hours"] == 6:
                    row["day_index"] += 3
            after = compute_instance(artifact, family="ridge")
            self.assertEqual(before["parameters"]["selection_fit"]["means"],
                             after["parameters"]["selection_fit"]["means"])
            self.assertEqual(before["parameters"]["selection_fit"]["scales"],
                             after["parameters"]["selection_fit"]["scales"])
            self.assertNotEqual(before["parameters"]["final_fit"]["means"],
                                after["parameters"]["final_fit"]["means"])

    def test_train_plus_validation_refit_excludes_test_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7"))
            before = compute_instance(artifact, family="bagged_tree")
            for row in artifact["rows"]:
                if row["split"] == "test":
                    row["target_pm25"] = (row["target_pm25"] or 0.0) + 50.0
                    row["values"] = {name: (value or 0.0) + 50.0
                                     for name, value in row["values"].items()}
            after = compute_instance(artifact, family="bagged_tree")
            self.assertEqual(before["parameters"]["final_fit"]["trees"],
                             after["parameters"]["final_fit"]["trees"])
            before_test = next(row for row in before["metrics"] if row["split"] == "test")
            after_test = next(row for row in after["metrics"] if row["split"] == "test")
            self.assertNotEqual(before_test["mae"], after_test["mae"])

    def test_per_sensor_models_do_not_consume_other_sensor(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7"))
            before = compute_instance(artifact, scope="per_sensor", sensor="sensor_a",
                                      family="ridge")
            for row in artifact["rows"]:
                if row["sensor_id"] == "sensor_b":
                    row["target_pm25"] = (row["target_pm25"] or 0.0) + 100.0
                    row["day_index"] += 5
            after = compute_instance(artifact, scope="per_sensor", sensor="sensor_a",
                                     family="ridge")
            self.assertEqual(before["parameters"]["selection_fit"]["coefficients"],
                             after["parameters"]["selection_fit"]["coefficients"])
            self.assertTrue(all(row["sensor_id"] == "sensor_a" for row in before["predictions"]))

    def test_standardization_means_come_from_fit_partition_only(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7"))
            instance = compute_instance(artifact, family="ridge")
            train_rows = [row for row in artifact["rows"]
                          if row["horizon_hours"] == 6 and row["split"] == "train"
                          and not row["purged"] and row["target_available"]]
            expected = sum(row["day_index"] for row in train_rows) / len(train_rows)
            measured = instance["parameters"]["selection_fit"]["means"]["day_index"]
            self.assertAlmostEqual(float(measured), expected, places=6)

    def test_ridge_recovers_exact_coefficients(self):
        matrix = [[1.0, 2.0], [1.0, 3.0], [1.0, 4.0]]
        coefficients = ml.solve_ridge(matrix, [5.0, 7.0, 9.0], 0.0)
        self.assertAlmostEqual(coefficients[0], 1.0)
        self.assertAlmostEqual(coefficients[1], 2.0)

    def test_ridge_rejects_nonfinite_and_rank_deficient_matrices(self):
        with self.assertRaises(ml.MLError):
            ml.solve_ridge([[1.0, float("nan")], [1.0, 2.0]], [1.0, 2.0], 0.1)
        with self.assertRaises(ml.MLError):
            ml.solve_ridge([[1.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1.0, 2.0, 2.0]],
                           [1.0, 2.0, 3.0], 0.0)

    def test_alpha_selection_uses_validation_rmse_and_tie_break(self):
        context = {"categorical": [], "continuous": ["x"], "transform": "raw"}
        flat_train = [model_row(float(index), 0.0) for index in range(6)]
        flat_validation = [model_row(float(index), 0.0) for index in range(6, 10)]
        alpha, status, detail = ml.select_alpha(flat_train, flat_validation, context)
        self.assertEqual(status, "validation_selected")
        self.assertEqual(alpha, min(ml.RIDGE_ALPHAS))
        self.assertEqual(len(detail["candidates"]), len(ml.RIDGE_ALPHAS))
        linear_train = [model_row(float(index), 2.0 * index + 1.0) for index in range(12)]
        linear_validation = [model_row(float(index), 2.0 * index + 1.0) for index in range(12, 18)]
        alpha, _, detail = ml.select_alpha(linear_train, linear_validation, context)
        chosen = min(detail["candidates"],
                     key=lambda item: (item["validation_rmse"], item["alpha"]))
        self.assertEqual(alpha, chosen["alpha"])
        fallback, status, _ = ml.select_alpha(linear_train, [], context)
        self.assertEqual((fallback, status), (ml.RIDGE_FALLBACK_ALPHA, "validation_unavailable"))

    def test_target_transforms_are_deterministic_and_nonnegative(self):
        self.assertEqual(ml.transform_target(0.0, "log1p"), 0.0)
        self.assertEqual(ml.transform_target(3.0, "raw"), 3.0)
        self.assertEqual(ml.inverse_transform(-100.0, "log1p"), 0.0)
        self.assertEqual(ml.inverse_transform(-2.0, "raw"), 0.0)
        self.assertAlmostEqual(ml.inverse_transform(ml.transform_target(9.0, "log1p"), "log1p"), 9.0)

    def test_tree_training_is_deterministic_and_seed_bound(self):
        rows = [{"origin_local_hour": index % 24, "origin_local_weekday": index % 7,
                 "sensor_id": "sensor_a", "values": {}, "day_index": float(index % 5),
                 "target_pm25": float(index % 7)} for index in range(40)]
        first = ml.fit_trees(rows, [], ["day_index"], "raw", "digest-one")
        second = ml.fit_trees(rows, [], ["day_index"], "raw", "digest-one")
        third = ml.fit_trees(rows, [], ["day_index"], "raw", "digest-two")
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        self.assertNotEqual(first["trees"][0]["seed"], third["trees"][0]["seed"])

    def test_tree_min_leaf_policy_returns_leaf_for_tiny_samples(self):
        rows = [{"origin_local_hour": index % 24, "origin_local_weekday": index % 7,
                 "sensor_id": "sensor_a", "values": {}, "day_index": float(index),
                 "target_pm25": float(index)} for index in range(15)]
        model = ml.fit_trees(rows, [], ["day_index"], "raw", "digest")
        self.assertTrue(all("leaf" in tree["tree"] for tree in model["trees"]))
        self.assertEqual(model["min_leaf"], ml.TREE_MIN_LEAF)

    def test_complete_case_gates_preserve_missing_rows_and_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7",
                                                  history=False, weather=False))
            for feature_set, reason in (("history_only", "missing_pm_history_features"),
                                        ("weather_only", "missing_captured_weather_features")):
                instance = compute_instance(artifact, feature_set=feature_set)
                self.assertEqual(instance["model_status"], "unavailable")
                self.assertIn("insufficient_training_rows", instance["model_reasons"])
                coverage = instance["feature_spec"]["coverage"]["train"]
                if feature_set == "history_only":
                    self.assertGreater(coverage["incomplete_history_rows"], 0)
                else:
                    self.assertGreater(coverage["incomplete_weather_rows"], 0)
                self.assertTrue(all("mae" not in row for row in instance["metrics"]))

    def test_smape_zero_safe_and_undefined_r2_reasons(self):
        values = ml.metric_values([(5.0, 5.0), (5.0, 4.0)], None)
        self.assertAlmostEqual(values["smape"], (0.0 + 200.0 / 9.0) / 2.0)
        self.assertIsNone(values["r2"])
        self.assertEqual(values["r2_reason"], "undefined_zero_target_variance")
        zero = ml.metric_values([(0.0, 0.0)], None)
        self.assertIsNone(zero["smape"])
        single = ml.metric_values([(1.0, 1.0)], 2.0)
        self.assertEqual(single["r2_reason"], "insufficient_pairs")

    def test_mase_uses_training_one_hour_denominator(self):
        rows = [{"sensor_id": "sensor_a", "horizon_hours": 6,
                 "origin_dt": START + timedelta(hours=index), "split": "train",
                 "purged": False, "target_available": True, "target_pm25": value}
                for index, value in enumerate([1.0, 2.0, 4.0, 7.0, 11.0])]
        denominator = ml.group_denominator(rows, "sensor_a", ["sensor_a"], 6)
        assert denominator is not None
        self.assertAlmostEqual(denominator, 2.5)
        values = ml.metric_values([(1.0, 1.0), (3.0, 1.0)], denominator)
        mase = values["mase"]
        assert mase is not None
        self.assertAlmostEqual(mase, 1.0 / 2.5)

    def test_paired_comparisons_require_matching_keys_and_compute_deltas(self):
        identity = {"model_family": "ridge", "feature_set": "calendar_only",
                    "target_transform": "raw", "scope": "pooled", "sensor_id": "pooled",
                    "location_id": "pooled", "horizon_hours": 6}
        record = ml.comparison_record(
            identity, "test", "ml_vs_baseline", "local_hour_climatology", "diagnostic_calendar",
            {"a": 11.0, "b": 12.0}, {"a": 10.0, "b": 10.0}, {"a": 10.0, "b": 15.0},
            fit_partition="train_plus_validation", fit_key_digest="digest",
            reference_fit_partition="train", reference_fit_key_digest="digest",
            reference_finite_rows=2)
        self.assertEqual(record["comparison_status"], "paired")
        self.assertEqual(record["paired_rows"], 2)
        self.assertAlmostEqual(record["mae_delta"], 1.5 - 2.5)
        self.assertAlmostEqual(record["rmse_delta"],
                               (2.5 ** 0.5) - (12.5 ** 0.5))
        self.assertEqual(record["fit_partition"], "train_plus_validation")
        self.assertEqual(record["reference_fit_partition"], "train")
        self.assertEqual(record["history_status"], "training_history_mismatch")
        self.assertEqual(record["metric_scope"], "descriptive_only")
        self.assertIn("paired_key_digest", record)
        unmatched = ml.comparison_record(
            identity, "test", "ml_vs_baseline", "local_hour_climatology", "diagnostic_calendar",
            {"a": 11.0}, {"a": 10.0}, {"z": 10.0},
            fit_partition="train_plus_validation", fit_key_digest="digest",
            reference_fit_partition="train", reference_fit_key_digest="digest",
            reference_finite_rows=1)
        self.assertEqual(unmatched["comparison_status"], "not_paired")
        self.assertEqual(unmatched["comparison_reason"], "no_shared_finite_prediction_keys")
        self.assertEqual(unmatched["history_status"], "not_paired")
        self.assertIsNone(unmatched["paired_key_digest"])
        self.assertEqual(unmatched["location_id"], "pooled")

    def test_limited_fixture_has_no_fabricated_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7",
                                                  history=False, weather=False))
            instance = compute_instance(artifact, feature_set="history_weather",
                                        family="bagged_tree")
            self.assertEqual(instance["model_status"], "unavailable")
            self.assertTrue(all(row["metric_status"] == "unavailable"
                                for row in instance["metrics"]))
            self.assertTrue(all(row["metric_reason"] for row in instance["metrics"]))
            self.assertEqual(instance["predictions"], [])
            statuses = {row["model_reason"] for row in instance["metrics"]}
            self.assertTrue(any("insufficient_training_rows" in value for value in statuses))

    def test_prospective_fixture_trains_every_feature_set(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7"))
            for feature_set in ml.FEATURE_SETS:
                for family in ml.MODEL_FAMILIES:
                    instance = compute_instance(artifact, feature_set=feature_set,
                                                family=family)
                    self.assertEqual(instance["model_status"], "available",
                                     f"{feature_set}/{family}")
                    test_metric = next(row for row in instance["metrics"]
                                       if row["split"] == "test")
                    self.assertEqual(test_metric["metric_status"], "available")
                    self.assertIn("mae", test_metric)

    def test_output_refuses_overwrite_and_missing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7"))
            reference = make_phase8_reference(Path(directory) / "phase8",
                                              Path(directory) / "phase7")
            with reduced_scope()[0], reduced_scope()[1]:
                result = ml.compute_ml(artifact, ml.load_baseline_reference(reference))
                target = Path(directory) / "out"
                ml.write_outputs(target, result)
                with self.assertRaises(ml.MLError):
                    ml.write_outputs(target, result)
                with self.assertRaises(ml.MLError):
                    ml.write_outputs(Path(directory) / "missing" / "out", result)

    def test_read_summary_rejects_duplicate_keys_and_unexpected_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            path.write_text('{"purpose": "a", "purpose": "b", "model_version": "x",'
                            ' "manifest": {}, "manifest_sha256": "c"}', encoding="utf-8")
            with self.assertRaises(baselines.BaselineError):
                ml.read_summary(path)
            path.write_text(json.dumps({"purpose": ml.PURPOSE, "model_version": ml.ML_VERSION,
                                        "manifest": {}, "manifest_sha256": baselines.digest({}),
                                        "extra": 1}), encoding="utf-8")
            with self.assertRaises(ml.MLError):
                ml.read_summary(path)

    def test_function_level_run_and_replay_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            output_a = Path(directory) / "out_a"
            output_b = Path(directory) / "out_b"
            run_reduced(root, reference, output_a, output_b)
            names = sorted(path.name for path in output_a.iterdir())
            self.assertEqual(len(names), 7)
            for name in names:
                self.assertEqual((output_a / name).read_bytes(), (output_b / name).read_bytes(),
                                 name)
            summary = json.loads((output_a / ml.OUTPUT_SUMMARY_NAME).read_text())
            self.assertEqual(baselines.digest(summary["manifest"]), summary["manifest_sha256"])

    def test_relocating_equivalent_inputs_keeps_output_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            copied = Path(directory) / "copy"
            shutil.copytree(root, copied / "phase7")
            shutil.copytree(reference, copied / "phase8")
            with reduced_scope()[0], reduced_scope()[1]:
                first = ml.compute_ml(ml.load_phase7(root),
                                      ml.load_baseline_reference(reference))
                second = ml.compute_ml(ml.load_phase7(copied / "phase7"),
                                       ml.load_baseline_reference(copied / "phase8"))
                self.assertEqual(first["manifest"], second["manifest"])
                output_a = Path(directory) / "a"
                output_b = Path(directory) / "b"
                ml.write_outputs(output_a, first)
                ml.write_outputs(output_b, second)
            for name in sorted(path.name for path in output_a.iterdir()):
                self.assertEqual((output_a / name).read_bytes(), (output_b / name).read_bytes())

    def test_tampered_summary_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            output_a = Path(directory) / "out_a"
            output_b = Path(directory) / "out_b"
            run_reduced(root, reference, output_a, output_b)
            summary = json.loads((output_a / ml.OUTPUT_SUMMARY_NAME).read_text())
            summary["manifest"]["counts"]["metric_cells"] += 1
            unsigned = Path(directory) / "unsigned.json"
            unsigned.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(ml.MLError):
                ml.replay_ml(root, reference, unsigned, Path(directory) / "replay_u",
                             expected_identities=False)
            summary["manifest_sha256"] = baselines.digest(summary["manifest"])
            resigned = Path(directory) / "resigned.json"
            resigned.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(ml.MLError):
                ml.replay_ml(root, reference, resigned, Path(directory) / "replay_r",
                             expected_identities=False)

    def test_success_hashes_all_output_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            output = Path(directory) / "out"
            run_reduced(root, reference, output, Path(directory) / "out_b")
            success = json.loads((output / "SUCCESS.json").read_text())
            expected = {"phase_9_model_summary.json", "phase_9_metrics.csv",
                        "phase_9_predictions.csv", "phase_9_model_parameters.json",
                        "phase_9_feature_manifest.json", "phase_9_assumptions.md"}
            self.assertEqual(set(success["files_sha256"]), expected)
            for name, digest in success["files_sha256"].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
            summary = json.loads((output / "phase_9_model_summary.json").read_text())
            self.assertEqual(success["manifest_sha256"], summary["manifest_sha256"])

    def test_module_cli_rejects_unexpected_frozen_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
            for command in (["-m", "vn_air.ml"], ["-m", "vn_air.cli", "ml"]):
                completed = subprocess.run(
                    [str(ROOT / ".venv" / "bin" / "python"), "-B", *command, "run",
                     "--artifact", str(root), "--baseline-artifact", str(reference),
                     "--output-dir", str(Path(directory) / "cli_out")],
                    cwd=ROOT, env=environment, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 1, completed.stderr)
                self.assertIn("identity", (completed.stdout + completed.stderr).lower())

    def test_frozen_payload_maps_match_authoritative_artifacts(self):
        phase7 = ROOT / "docs/verification/phase_7_features_2026-09-10_structural_hardened"
        reference = ROOT / "docs/verification/phase_8_baselines_2026-09-11_v2_verified"
        artifact = ml.load_phase7(
            phase7, expected_manifest=ml.EXPECTED_PHASE7_MANIFEST_SHA256,
            expected_payloads=ml.EXPECTED_PHASE7_PAYLOAD_SHA256)
        self.assertEqual(artifact["payload_sha256"], ml.EXPECTED_PHASE7_PAYLOAD_SHA256)
        loaded = ml.load_baseline_reference(
            reference, expected_manifest=ml.EXPECTED_PHASE8_MANIFEST_SHA256,
            expected_payloads=ml.EXPECTED_PHASE8_PAYLOAD_SHA256)
        self.assertEqual(loaded["payload_sha256"], ml.EXPECTED_PHASE8_PAYLOAD_SHA256)

    def test_resigned_phase7_payload_tamper_stops(self):
        def bump(path, column):
            mutate_value(path, column, lambda value: str(float(value) + 1.0))

        cases = {
            "features": ("phase_7_features.csv", lambda root: bump(root / "phase_7_features.csv",
                                                                   "pm25_lag_1h")),
            "targets": ("phase_7_targets.csv", lambda root: bump(root / "phase_7_targets.csv",
                                                                 "target_pm25")),
            "lineage": ("phase_7_lineage.csv", lambda root: (
                root / "phase_7_lineage.csv").write_text(
                    (root / "phase_7_lineage.csv").read_text() + "tampered\n", encoding="utf-8")),
        }
        for label, (name, mutate) in cases.items():
            with tempfile.TemporaryDirectory() as directory, self.subTest(label):
                extra = {"phase_7_lineage.csv": "lineage\n"} if name == "phase_7_lineage.csv" else None
                root = make_phase7(Path(directory) / "phase7", extra_payloads=extra)
                manifest = json.loads((root / "phase_7_feature_summary.json").read_text())["manifest_sha256"]
                expected = ml.payload_map(root)
                ml.load_phase7(root, expected_manifest=manifest, expected_payloads=expected)
                mutate(root)
                resign(root)
                with self.assertRaises(ml.MLError):
                    ml.load_phase7(root, expected_manifest=manifest, expected_payloads=expected)

    def test_resigned_phase8_payload_tamper_stops(self):
        cases = {
            "predictions": lambda root: mutate_value(root / "phase_8_predictions.csv", "prediction",
                                                     lambda value: str(float(value) + 1.0)),
            "metrics": lambda root: (root / "phase_8_baseline_metrics.csv").write_text(
                "tampered\n", encoding="utf-8"),
            "assumptions": lambda root: (root / "phase_8_assumptions.md").write_text(
                "tampered\n", encoding="utf-8"),
        }
        for label, mutate in cases.items():
            with tempfile.TemporaryDirectory() as directory, self.subTest(label):
                root = make_phase7(Path(directory) / "phase7")
                reference = make_phase8_reference(
                    Path(directory) / "phase8", root,
                    extra_payloads={"phase_8_baseline_metrics.csv": "metrics\n",
                                    "phase_8_assumptions.md": "assumptions\n"})
                manifest = json.loads(
                    (reference / "phase_8_baselines_summary.json").read_text())["manifest_sha256"]
                expected = ml.payload_map(reference)
                ml.load_baseline_reference(reference, expected_manifest=manifest,
                                           expected_payloads=expected)
                mutate(reference)
                resign(reference)
                with self.assertRaises(ml.MLError):
                    ml.load_baseline_reference(reference, expected_manifest=manifest,
                                               expected_payloads=expected)

    def test_resigned_tamper_never_starts_fitting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            phase7_manifest = json.loads(
                (root / "phase_7_feature_summary.json").read_text())["manifest_sha256"]
            reference_manifest = json.loads(
                (reference / "phase_8_baselines_summary.json").read_text())["manifest_sha256"]
            expected7 = ml.payload_map(root)
            expected8 = ml.payload_map(reference)
            mutate_value(root / "phase_7_features.csv", "pm25_lag_1h",
                         lambda value: str(float(value) + 1.0))
            resign(root)
            with mock.patch.object(ml, "EXPECTED_PHASE7_MANIFEST_SHA256", phase7_manifest), \
                    mock.patch.object(ml, "EXPECTED_PHASE7_PAYLOAD_SHA256", expected7), \
                    mock.patch.object(ml, "EXPECTED_PHASE8_MANIFEST_SHA256", reference_manifest), \
                    mock.patch.object(ml, "EXPECTED_PHASE8_PAYLOAD_SHA256", expected8), \
                    mock.patch.object(ml, "compute_ml",
                                      side_effect=AssertionError("fitting started")):
                with self.assertRaises(ml.MLError):
                    ml.run_ml(root, reference, expected_identities=True)

    def test_payload_rename_or_extra_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7",
                               extra_payloads={"phase_7_lineage.csv": "lineage\n"})
            manifest = json.loads(
                (root / "phase_7_feature_summary.json").read_text())["manifest_sha256"]
            expected = ml.payload_map(root)
            renamed = dict(expected)
            renamed["phase_7_features_renamed.csv"] = renamed.pop("phase_7_features.csv")
            with self.assertRaises(ml.MLError):
                ml.load_phase7(root, expected_manifest=manifest, expected_payloads=renamed)
            without_lineage = {name: value for name, value in expected.items()
                               if name != "phase_7_lineage.csv"}
            with self.assertRaises(ml.MLError):
                ml.load_phase7(root, expected_manifest=manifest,
                               expected_payloads=without_lineage)

    def test_no_overwrite_preflight_before_computation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            existing = Path(directory) / "existing"
            existing.mkdir()
            with mock.patch.object(ml, "compute_ml",
                                   side_effect=AssertionError("fitting started")):
                with self.assertRaises(ml.MLError):
                    ml.run_ml(root, reference, expected_identities=False, output_dir=existing)
                with self.assertRaises(ml.MLError):
                    ml.replay_ml(root, reference, Path(directory) / "absent.json", existing,
                                 expected_identities=False)
            with self.assertRaises(ml.MLError):
                ml.run_ml(root, reference, expected_identities=False,
                          output_dir=Path(directory) / "missing" / "out")

    def test_cli_preflight_rejects_existing_output_without_partial_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            existing = Path(directory) / "existing"
            existing.mkdir()
            sentinel = existing / "sentinel.txt"
            sentinel.write_text("keep\n", encoding="utf-8")
            environment = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
            commands = (
                ["-m", "vn_air.ml", "run", "--artifact", str(root),
                 "--baseline-artifact", str(reference), "--output-dir", str(existing)],
                ["-m", "vn_air.ml", "replay", "--artifact", str(root),
                 "--baseline-artifact", str(reference), "--summary", str(existing / "none.json"),
                 "--output-dir", str(existing)],
                ["-m", "vn_air.cli", "ml", "run", "--artifact", str(root),
                 "--baseline-artifact", str(reference), "--output-dir", str(existing)],
            )
            for command in commands:
                completed = subprocess.run(
                    [str(ROOT / ".venv" / "bin" / "python"), "-B", *command],
                    cwd=ROOT, env=environment, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 1, completed.stderr)
                self.assertIn("must be new", completed.stdout + completed.stderr)
            self.assertEqual([path.name for path in existing.iterdir()], ["sentinel.txt"])

    def test_log1p_inverse_has_no_undeclared_clamp(self):
        self.assertAlmostEqual(ml.inverse_transform(ml.transform_target(9.0, "log1p"), "log1p"), 9.0)
        self.assertEqual(ml.inverse_transform(-100.0, "log1p"), 0.0)
        self.assertEqual(ml.inverse_transform(50.0, "log1p"), math.expm1(50.0))
        with self.assertRaises(ml.MLError) as captured:
            ml.inverse_transform(1000.0, "log1p")
        self.assertIn("overflow", str(captured.exception))
        with self.assertRaises(ml.MLError):
            ml.inverse_transform(float("nan"), "raw")

    def test_overflowing_model_cell_is_unavailable_with_reason(self):
        identity = {"model_family": "ridge", "feature_set": "calendar_only",
                    "target_transform": "log1p", "scope": "pooled", "sensor_id": "pooled",
                    "location_id": "pooled", "horizon_hours": 6}
        coverage = {split: {"candidate_rows": 1, "purged_rows_excluded": 0,
                            "unavailable_target_rows": 0, "incomplete_feature_rows": 0,
                            "incomplete_history_rows": 0, "incomplete_weather_rows": 0}
                    for split in ml.SPLIT_ORDER}
        row = {"key": ("sensor", "origin", 6), "sensor_id": "sensor", "location_id": "loc",
               "origin": "origin", "purged": False, "target_available": True,
               "target_quality": "accepted", "target_pm25": 1.0}
        model = {"family": "ridge", "transform": "log1p", "categorical": [], "continuous": [],
                 "means": {}, "scales": {}, "coefficients": [1000.0],
                 "coefficient_names": ["intercept"], "columns": 1, "training_rows": 1}
        metrics, predictions, _ = ml.score_instance(identity, [row], [], [], coverage, None,
                                                     model, model)
        train = next(item for item in metrics if item["split"] == "train")
        self.assertEqual(train["metric_status"], "unavailable")
        self.assertEqual(train["metric_reason"], "prediction_inverse_overflow")
        self.assertEqual(predictions, [])

    def test_reference_row_alignment_is_enforced(self):
        def set_split(rows):
            row = first_row(rows, "local_hour_climatology")
            row["split"] = "test" if row["split"] != "test" else "train"

        mutations = {
            "unknown_sensor": lambda rows: first_row(rows, "local_hour_climatology").update(
                sensor_id="sensor_x"),
            "location": lambda rows: first_row(rows, "local_hour_climatology").update(
                location_id="loc_x"),
            "split": set_split,
            "purged": lambda rows: first_row(rows, "local_hour_climatology").update(
                purged="False" if first_row(rows, "local_hour_climatology")["purged"] == "True"
                else "True"),
            "availability": lambda rows: first_row(rows, "local_hour_climatology").update(
                target_available="False"
                if first_row(rows, "local_hour_climatology")["target_available"] == "True"
                else "True"),
            "predicted_without_value": lambda rows: first_row(
                rows, "local_hour_climatology").update(prediction=""),
            "unavailable_with_value": lambda rows: first_row(
                rows, "persistence_lag_1h").update(prediction="1.0"),
            "unknown_status": lambda rows: first_row(
                rows, "persistence_lag_1h").update(prediction_status="made_up"),
            "missing_reason": lambda rows: first_row(
                rows, "persistence_lag_1h").update(prediction_reason=""),
            "predicted_with_reason": lambda rows: first_row(
                rows, "local_hour_climatology").update(prediction_reason="why"),
            "wrong_role": lambda rows: first_row(
                rows, "local_hour_climatology").update(baseline_role="made_up"),
            "unknown_baseline": lambda rows: first_row(rows, "local_hour_climatology").update(
                baseline_id="made_up"),
            "missing_baseline": lambda rows: rows.__setitem__(
                slice(None), [row for row in rows
                              if row["baseline_id"] != "weather_augmented_climatology"]),
        }
        for label, mutate in mutations.items():
            with tempfile.TemporaryDirectory() as directory, self.subTest(label):
                root = make_phase7(Path(directory) / "phase7")
                reference = make_phase8_reference(Path(directory) / "phase8", root)
                artifact = ml.load_phase7(root)
                loaded = ml.load_baseline_reference(reference)
                ml.validate_reference_rows(artifact, loaded)
                mutate_predictions(reference, mutate)
                loaded = ml.load_baseline_reference(reference)
                with self.assertRaises(ml.MLError):
                    ml.validate_reference_rows(artifact, loaded)

    def test_fixed_payload_preflight_happens_before_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            manifest = json.loads(
                (root / "phase_7_feature_summary.json").read_text())["manifest_sha256"]
            expected = ml.payload_map(root)
            mutate_value(root / "phase_7_features.csv", "pm25_lag_1h",
                         lambda value: str(float(value) + 1.0))
            resign(root)
            with mock.patch.object(baselines, "read_csv", wraps=baselines.read_csv) as spy:
                with self.assertRaises(ml.MLError):
                    ml.load_phase7(root, expected_manifest=manifest, expected_payloads=expected)
                self.assertEqual(spy.call_count, 0)

    def test_replay_rejects_type_confused_resigned_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            output_a = Path(directory) / "out_a"
            output_b = Path(directory) / "out_b"
            run_reduced(root, reference, output_a, output_b)
            cases = (
                ("bool_int", lambda manifest: manifest.update(test_selection_used=0)),
                ("int_float", lambda manifest: manifest["row_gates"].update(min_train_rows=30.0)),
            )
            for label, mutate in cases:
                with self.subTest(label):
                    summary = json.loads((output_a / ml.OUTPUT_SUMMARY_NAME).read_text())
                    mutate(summary["manifest"])
                    summary["manifest_sha256"] = baselines.digest(summary["manifest"])
                    tampered = Path(directory) / f"summary_{label}.json"
                    tampered.write_text(json.dumps(summary), encoding="utf-8")
                    replay_dir = Path(directory) / f"replay_{label}"
                    with reduced_scope()[0], reduced_scope()[1]:
                        with self.assertRaises(ml.MLError):
                            ml.replay_ml(root, reference, tampered, replay_dir,
                                         expected_identities=False)
                    self.assertFalse(replay_dir.exists())

    def test_replay_requires_complete_static_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            output_a = Path(directory) / "out_a"
            run_reduced(root, reference, output_a, Path(directory) / "out_b")
            summary = json.loads((output_a / ml.OUTPUT_SUMMARY_NAME).read_text())
            del summary["manifest"]["model_definitions"]
            summary["manifest_sha256"] = baselines.digest(summary["manifest"])
            tampered = Path(directory) / "summary_missing.json"
            tampered.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(ml.MLError):
                ml.replay_ml(root, reference, tampered, Path(directory) / "replay_missing",
                             expected_identities=False)

    def test_alpha_selection_skips_single_failing_candidate(self):
        context = ml.alpha_fit([], ["x"], "raw")
        train = [model_row(float(index), 2.0 * index + 1.0) for index in range(6)]
        validation = [model_row(7.0, 15.0)]
        real = ml.predict_ridge
        calls = {"count": 0}

        def flaky(model, rows):
            calls["count"] += 1
            if calls["count"] == 1:
                raise ml.MLError("prediction_inverse_overflow")
            return real(model, rows)

        with mock.patch.object(ml, "predict_ridge", side_effect=flaky):
            alpha, status, detail = ml.select_alpha(train, validation, context)
        self.assertEqual(status, "validation_selected")
        self.assertIsNotNone(alpha)
        self.assertEqual(detail["candidates"][0]["status"], "unavailable")
        self.assertEqual(detail["candidates"][0]["failure_reason"], "prediction_inverse_overflow")

    def test_alpha_selection_all_candidates_failing_returns_unavailable(self):
        context = ml.alpha_fit([], ["x"], "log1p")
        train = [model_row(float(index), math.expm1(float(index))) for index in range(6)]
        validation = [model_row(1e9, 1.0)]
        alpha, status, detail = ml.select_alpha(train, validation, context)
        self.assertIsNone(alpha)
        self.assertEqual(status, "validation_prediction_failed")
        self.assertTrue(all(item["validation_rmse"] is None for item in detail["candidates"]))
        self.assertTrue(all(item["failure_reason"] is not None for item in detail["candidates"]))

    def test_validation_overflow_marks_instance_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7"))
            rows = [row for row in artifact["rows"] if row["horizon_hours"] == 6]
            for row in rows:
                if row["split"] == "train" and not row["purged"]:
                    for column in ml.PM_HISTORY_COLUMNS:
                        row["values"][column] = float(row["day_index"])
                    row["target_pm25"] = math.expm1(float(row["day_index"]) + 1.0)
            validation = [row for row in rows
                          if row["split"] == "validation" and not row["purged"]]
            self.assertTrue(validation)
            for column in ml.PM_HISTORY_COLUMNS:
                validation[0]["values"][column] = 1e6
            validation[0]["target_pm25"] = 1.0
            instance = compute_instance(artifact, feature_set="history_only", family="ridge",
                                        transform="log1p")
            self.assertEqual(instance["model_status"], "unavailable")
            self.assertIn("validation_prediction_failed", instance["model_reasons"])
            self.assertTrue(all(row["metric_status"] == "unavailable"
                                for row in instance["metrics"]))

    def test_structural_prediction_error_is_not_masked(self):
        identity = {"model_family": "ridge", "feature_set": "calendar_only",
                    "target_transform": "raw", "scope": "pooled", "sensor_id": "pooled",
                    "location_id": "pooled", "horizon_hours": 6}
        coverage = {split: {"candidate_rows": 1, "purged_rows_excluded": 0,
                            "unavailable_target_rows": 0, "incomplete_feature_rows": 0,
                            "incomplete_history_rows": 0, "incomplete_weather_rows": 0}
                    for split in ml.SPLIT_ORDER}
        row = {"key": ("sensor", "origin", 6), "sensor_id": "sensor", "location_id": "loc",
               "origin": "origin", "purged": False, "target_available": True,
               "target_quality": "accepted", "target_pm25": 1.0}
        model = {"family": "ridge", "transform": "raw", "categorical": [], "continuous": [],
                 "means": {}, "scales": {}, "coefficients": [1.0],
                 "coefficient_names": ["intercept"], "columns": 1, "training_rows": 1}
        with mock.patch.object(ml, "predict_model",
                               side_effect=ml.MLError("design_matrix_malformed")):
            with self.assertRaises(ml.MLError) as captured:
                ml.score_instance(identity, [row], [], [], coverage, None, model, model)
        self.assertEqual(str(captured.exception), "design_matrix_malformed")

    def test_authoritative_sensor_location_mapping(self):
        artifact = ml.load_phase7(
            ROOT / "docs/verification/phase_7_features_2026-09-10_structural_hardened")
        self.assertEqual(ml.sensor_location_map(artifact),
                         {"openaq_11357424": "cmt8", "openaq_14581375": "oceanpark"})

    def test_per_sensor_identity_uses_reviewed_location(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7"))
            for sensor, location in (("sensor_a", "loc_a"), ("sensor_b", "loc_b")):
                instance = compute_instance(artifact, scope="per_sensor", sensor=sensor)
                self.assertEqual(instance["identity"]["location_id"], location)
                self.assertEqual(instance["parameters"]["identity"]["location_id"], location)
                self.assertTrue(all(row["location_id"] == location
                                    for row in instance["metrics"]))
                self.assertTrue(all(row["location_id"] == location
                                    for row in instance["predictions"]))

    def test_conflicting_sensor_location_mapping_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = ml.load_phase7(make_phase7(Path(directory) / "phase7"))
            artifact["rows"][0]["location_id"] = "conflict"
            with self.assertRaises(ml.MLError):
                ml.sensor_location_map(artifact)

    def test_comparison_records_include_fit_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = make_phase7(Path(directory) / "phase7")
            reference = make_phase8_reference(Path(directory) / "phase8", root)
            artifact = ml.load_phase7(root)
            with mock.patch.object(ml, "FEATURE_SETS", ("calendar_only", "history_only")), \
                    mock.patch.object(ml, "TREE_COUNT", 3):
                result = ml.compute_ml(artifact, ml.load_baseline_reference(reference))
            comparisons = result["manifest"]["comparisons"]
            self.assertTrue(comparisons)
            schema = ("location_id", "fit_partition", "fit_key_digest",
                      "reference_fit_partition", "reference_fit_key_digest",
                      "reference_fit_status", "reference_fit_reason",
                      "counterpart_fit_partition", "counterpart_fit_key_digest",
                      "model_finite_rows", "reference_finite_rows", "paired_rows",
                      "paired_key_digest", "history_status", "metric_scope")
            for record in comparisons:
                self.assertIn(record["fit_partition"], {"train", "train_plus_validation"})
                self.assertEqual(record["fit_partition"], ml.fit_partition_for(record["split"]))
                self.assertEqual(record["metric_scope"], "descriptive_only")
                for field in schema:
                    self.assertIn(field, record)
                if record["scope"] == "per_sensor":
                    self.assertIn(record["location_id"], {"loc_a", "loc_b"})
                else:
                    self.assertEqual(record["location_id"], "pooled")
                if record["comparison_status"] != "paired":
                    self.assertIsNone(record["paired_key_digest"])
                self.assertLessEqual(record["paired_rows"],
                                     min(record["model_finite_rows"],
                                         record["reference_finite_rows"]))
            paired = [record for record in comparisons if record["comparison_status"] == "paired"
                      and record["reference_baseline"] == "local_hour_climatology"]
            self.assertTrue(paired)
            for record in paired:
                self.assertEqual(record["reference_fit_partition"], "train")
                self.assertEqual(record["reference_fit_status"], "fitted")
                self.assertIsNotNone(record["reference_fit_key_digest"])
                self.assertIn("paired_key_digest", record)
                if record["split"] == "test":
                    self.assertEqual(record["history_status"], "training_history_mismatch")
                else:
                    self.assertEqual(record["history_status"], "matched")
            direct = [record for record in comparisons
                      if record["reference_baseline"] == "persistence_last_available"
                      and record["comparison_status"] == "paired"]
            self.assertTrue(direct)
            self.assertTrue(all(record["history_status"] == "not_applicable"
                                and record["reference_fit_key_digest"] is None
                                for record in direct))
            artifact = ml.load_phase7(root)
            direct_digest, direct_status, _ = ml.reference_fit_info(
                artifact, "persistence_last_available", 6, ["sensor_a"],
                {"local_hour_climatology"})
            self.assertEqual((direct_digest, direct_status), (None, "not_applicable"))
            unknown_digest, unknown_status, unknown_reason = ml.reference_fit_info(
                artifact, "weather_augmented_climatology", 6, ["sensor_a"],
                {"local_hour_climatology"})
            self.assertEqual((unknown_digest, unknown_status),
                             (None, "unknown"))
            self.assertIsNotNone(unknown_reason)
            fitted_digest, fitted_status, _ = ml.reference_fit_info(
                artifact, "local_hour_climatology", 6, ["sensor_a"],
                {"local_hour_climatology"})
            self.assertIsNotNone(fitted_digest)
            self.assertEqual(fitted_status, "fitted")
            ablations = [record for record in comparisons
                         if record["comparison_kind"].startswith("ablation")
                         and record["comparison_status"] == "paired"]
            self.assertTrue(ablations)
            for record in ablations:
                self.assertEqual(record["counterpart_fit_partition"], record["fit_partition"])
                self.assertIsNotNone(record["counterpart_fit_key_digest"])
                self.assertEqual(record["reference_fit_key_digest"],
                                 record["counterpart_fit_key_digest"])
                self.assertEqual(record["history_status"], "matched")

    def _comparison_fixture(self, directory, *, null_row=False, feature_sets=None):
        root = make_phase7(Path(directory) / "phase7")
        artifact = ml.load_phase7(root)
        if null_row:
            row = next(item for item in artifact["rows"]
                       if item["horizon_hours"] == 6 and item["split"] == "train"
                       and item["sensor_id"] == "sensor_a" and not item["purged"]
                       and item["target_available"])
            row["values"]["pm25_lag_1h"] = None
        reference = make_phase8_reference(Path(directory) / "phase8", root)
        with mock.patch.object(ml, "FEATURE_SETS", feature_sets), \
                mock.patch.object(ml, "TREE_COUNT", 3):
            result = ml.compute_ml(artifact, ml.load_baseline_reference(reference))
        return artifact, result

    def test_reference_counts_are_sensor_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact, result = self._comparison_fixture(
                directory, null_row=True, feature_sets=("history_only",))
            eligible = {(row["sensor_id"], row["origin"]) for row in artifact["rows"]
                        if row["horizon_hours"] == 6 and row["split"] == "train"
                        and not row["purged"] and row["target_available"]
                        and baselines.finite(row["target_pm25"])}
            incomplete = {(row["sensor_id"], row["origin"]) for row in artifact["rows"]
                          if row["horizon_hours"] == 6 and row["split"] == "train"
                          and not row["purged"]
                          and not baselines.finite(row["values"].get("pm25_lag_1h"))}
            model_eligible = eligible - incomplete
            comparisons = result["manifest"]["comparisons"]
            per_sensor = next(record for record in comparisons
                              if record["feature_set"] == "history_only"
                              and record["split"] == "train"
                              and record["sensor_id"] == "sensor_a"
                              and record["reference_baseline"] == "local_hour_climatology")
            expected_model = {key for key in model_eligible if key[0] == "sensor_a"}
            expected_reference = {key for key in eligible if key[0] == "sensor_a"}
            self.assertEqual(per_sensor["model_finite_rows"], len(expected_model))
            self.assertEqual(per_sensor["reference_finite_rows"], len(expected_reference))
            self.assertEqual(per_sensor["paired_rows"],
                             len(expected_model & expected_reference))
            pooled = next(record for record in comparisons
                          if record["feature_set"] == "history_only"
                          and record["split"] == "train"
                          and record["sensor_id"] == "pooled"
                          and record["reference_baseline"] == "local_hour_climatology")
            self.assertEqual(pooled["model_finite_rows"], len(model_eligible))
            self.assertEqual(pooled["reference_finite_rows"], len(eligible))

    def test_fit_history_uses_fit_key_digests(self):
        with tempfile.TemporaryDirectory() as directory:
            _, result = self._comparison_fixture(
                directory, null_row=True,
                feature_sets=("calendar_only", "history_only"))
            ablation = next(record for record in result["manifest"]["comparisons"]
                            if record["comparison_kind"] == "ablation_history"
                            and record["model_family"] == "ridge"
                            and record["target_transform"] == "raw"
                            and record["split"] == "train"
                            and record["sensor_id"] == "sensor_a"
                            and record["comparison_status"] == "paired")
            self.assertEqual(ablation["fit_partition"], "train")
            self.assertEqual(ablation["history_status"], "training_history_mismatch")
            self.assertNotEqual(ablation["fit_key_digest"],
                                ablation["counterpart_fit_key_digest"])
            self.assertEqual(ablation["reference_fit_key_digest"],
                             ablation["counterpart_fit_key_digest"])
            root = make_phase7(Path(directory) / "phase7b")
            reference = make_phase8_reference(Path(directory) / "phase8b", root)
            artifact = ml.load_phase7(root)
            with mock.patch.object(ml, "FEATURE_SETS", ("calendar_only", "history_only")), \
                    mock.patch.object(ml, "TREE_COUNT", 3):
                matched_result = ml.compute_ml(artifact, ml.load_baseline_reference(reference))
            matched = next(record for record in matched_result["manifest"]["comparisons"]
                           if record["comparison_kind"] == "ablation_history"
                           and record["model_family"] == "ridge"
                           and record["target_transform"] == "raw"
                           and record["split"] == "train"
                           and record["sensor_id"] == "sensor_a"
                           and record["comparison_status"] == "paired")
            self.assertEqual(matched["history_status"], "matched")
            self.assertEqual(matched["fit_key_digest"], matched["counterpart_fit_key_digest"])


if __name__ == "__main__":
    unittest.main()
