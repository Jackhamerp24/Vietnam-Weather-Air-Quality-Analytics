"""Offline tests for Phase 8 chronological baselines."""

import csv
import copy
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from vn_air.baselines import (
    BASELINES_VERSION,
    BaselineError,
    compute_baselines,
    digest,
    load_artifact,
    replay_baselines,
    run_baselines,
    write_outputs,
)


UTC = timezone.utc
START = datetime(2026, 6, 8, tzinfo=UTC)
VALIDATION = START + timedelta(hours=48)
TEST = START + timedelta(hours=72)
SENSORS = (("sensor_a", "cmt8"), ("sensor_b", "oceanpark"))


def iso(moment):
    return moment.isoformat()


def write_rows(path, rows):
    fields = sorted({field for row in rows for field in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_artifact(root, *, feature_mutation=None, target_mutation=None, weather_value=None):
    root.mkdir()
    features, targets = [], []
    for sensor_index, (sensor_id, location_id) in enumerate(SENSORS):
        for offset in range(96):
            origin = START + timedelta(hours=offset)
            for horizon in (6, 24):
                target_end = origin + timedelta(hours=horizon)
                split = "train" if origin < VALIDATION else ("validation" if origin < TEST else "test")
                purged = ((split == "train" and target_end > VALIDATION)
                          or (split == "validation" and target_end > TEST))
                target = (10.0 + sensor_index + (offset % 4)
                          if split == "train" else 100.0 + sensor_index + (offset % 3))
                feature = {
                    "sensor_id": sensor_id, "location_id": location_id,
                    "origin": iso(origin), "origin_local_hour": origin.hour,
                    "horizon_hours": horizon,
                    "target_start": iso(target_end - timedelta(hours=1)),
                    "target_end": iso(target_end), "split": split,
                    "purged": str(purged), "target_available": "True",
                    "pm25_last_available": str(40.0 + offset + sensor_index),
                    "pm25_lag_1h": str(30.0 + offset + sensor_index),
                    "pm25_trailing_mean_24h": str(20.0 + offset + sensor_index),
                    "weather_forecast_temperature_2m": "" if weather_value is None else str(weather_value),
                }
                target_row = {
                    "sensor_id": sensor_id, "location_id": location_id,
                    "origin": iso(origin), "horizon_hours": horizon,
                    "target_available": "True", "target_pm25": str(target),
                    "target_quality": "accepted", "target_start": feature["target_start"],
                    "target_end": feature["target_end"], "target_missing_reason": "",
                }
                if feature_mutation:
                    feature_mutation(feature)
                if target_mutation:
                    target_mutation(target_row)
                features.append(feature)
                targets.append(target_row)
    write_rows(root / "phase_7_features.csv", features)
    write_rows(root / "phase_7_targets.csv", targets)
    manifest = {
        "feature_version": "phase7_features_v7", "horizons": [6, 24],
        "availability_basis": "captured", "bundle_sha256": "b" * 64,
        "bundle_file_sha256": "f" * 64,
        "boundary": {"mode": "explicit", "frozen_boundary_applied": False},
        "split": {"validation_start": iso(VALIDATION), "test_start": iso(TEST)},
        "counts": {"rows": len(features)}, "status": "ok",
        "status_missing_families": [],
    }
    summary = {"purpose": "synthetic Phase 7 artifact", "manifest": manifest,
               "manifest_sha256": digest(manifest)}
    (root / "phase_7_feature_summary.json").write_text(
        json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    files = {name: __import__("hashlib").sha256((root / name).read_bytes()).hexdigest()
             for name in ("phase_7_feature_summary.json", "phase_7_features.csv", "phase_7_targets.csv")}
    (root / "SUCCESS.json").write_text(
        json.dumps({"feature_version": "phase7_features_v7", "availability_basis": "captured",
                    "bundle_sha256": "b" * 64, "manifest_sha256": summary["manifest_sha256"],
                    "files_sha256": files}, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return root


class BaselineTests(unittest.TestCase):
    def test_metric_arithmetic_is_exact_and_zero_safe(self):
        from vn_air.baselines import metric_values
        metrics = metric_values([(10.0, 12.0), (0.0, 0.0)], 2.0)
        self.assertEqual(metrics["mae"], 1.0)
        self.assertAlmostEqual(metrics["rmse"], 2.0 ** 0.5)
        self.assertEqual(metrics["mase"], 0.5)
        self.assertEqual(metrics["smape"], 200.0 * 2.0 / 22.0)

    def test_artifact_loads_and_keys_align(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7")
            loaded = load_artifact(artifact)
            self.assertEqual(len(loaded["features"]), 384)
            self.assertEqual(len(loaded["targets"]), 384)

    def test_feature_hash_or_alignment_tampering_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7")
            path = artifact / "phase_7_targets.csv"
            text = path.read_text(encoding="utf-8").replace("sensor_a", "sensor_x", 1)
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(BaselineError):
                load_artifact(artifact)

    def test_climatology_is_fit_on_training_rows_only(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7")
            result = compute_baselines(load_artifact(artifact))
            rows = [row for row in result["predictions"]
                    if row["baseline_id"] == "local_hour_climatology"
                    and row["sensor_id"] == "sensor_a" and row["horizon_hours"] == 6
                    and row["split"] == "validation" and not row["purged"]]
            self.assertTrue(rows)
            self.assertLess(rows[0]["prediction"], 50.0)

    def test_feature_baselines_use_exact_source_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7")
            result = compute_baselines(load_artifact(artifact))
            row = next(row for row in result["predictions"]
                       if row["baseline_id"] == "persistence_lag_1h"
                       and row["sensor_id"] == "sensor_a" and row["origin"] == iso(START))
            self.assertEqual(row["prediction"], 30.0)

    def test_metrics_have_no_purged_rows_and_no_test_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_baselines(make_artifact(Path(directory) / "phase7"))
            self.assertFalse(result["manifest"]["test_selection_used"])
            self.assertTrue(all(row["purged_rows_excluded"] >= 0 for row in result["metrics"]))
            self.assertTrue(any(row["metric_status"] == "available" and row["split"] == "test"
                                for row in result["metrics"]))

    def test_weather_baseline_is_unavailable_without_captured_weather(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_baselines(make_artifact(Path(directory) / "phase7"))
            weather = [row for row in result["metrics"] if row["baseline_id"] == "weather_augmented_climatology"]
            self.assertTrue(weather)
            self.assertTrue(all(row["metric_status"] == "unavailable" for row in weather))
            self.assertTrue(all(row["prediction_reason"] == "no_finite_captured_weather_features"
                                for row in result["predictions"]
                                if row["baseline_id"] == "weather_augmented_climatology"))

    def test_frozen_phase7_artifact_is_limited_but_calendar_diagnostic_runs(self):
        artifact = Path("docs/verification/phase_7_features_2026-09-10_structural_hardened")
        result = run_baselines(artifact)
        self.assertEqual(result["manifest"]["status"], "limited_diagnostic")
        self.assertGreater(sum(row["metric_status"] == "available" for row in result["metrics"]), 0)
        self.assertTrue(all(row["metric_status"] == "unavailable"
                            for row in result["metrics"]
                            if row["baseline_id"] in {"persistence_last_available", "persistence_lag_1h",
                                                       "trailing_mean_24h", "weather_augmented_climatology"}))

    def test_output_refuses_overwrite_and_replay_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7")
            result = run_baselines(artifact)
            output = Path(directory) / "phase8"
            first = write_outputs(output, result)
            self.assertEqual(first["file_count"], 5)
            with self.assertRaises(BaselineError):
                write_outputs(output, result)
            loaded = load_artifact(artifact)
            replay = compute_baselines(loaded)
            self.assertEqual(result["manifest_sha256"], replay["manifest_sha256"])
            self.assertEqual(result["metrics"], replay["metrics"])

    def test_malformed_target_alignment_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7",
                                     target_mutation=lambda row: row.update(target_end=iso(START)))
            with self.assertRaises(BaselineError):
                load_artifact(artifact)

    def test_trailing_mean_uses_exact_source_column(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7")
            result = compute_baselines(load_artifact(artifact))
            row = next(row for row in result["predictions"]
                       if row["baseline_id"] == "trailing_mean_24h"
                       and row["sensor_id"] == "sensor_a" and row["origin"] == iso(START))
            self.assertEqual(row["prediction"], 20.0)

    def test_purged_rows_are_excluded_from_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7")
            loaded = load_artifact(artifact)
            result = compute_baselines(loaded)
            cell = next(row for row in result["metrics"]
                        if row["baseline_id"] == "persistence_lag_1h"
                        and row["sensor_id"] == "sensor_a" and row["horizon_hours"] == 6
                        and row["split"] == "validation")
            expected = sum(1 for row in loaded["features"]
                           if row["sensor_id"] == "sensor_a" and row["horizon_hours"] == 6
                           and row["split"] == "validation" and not row["purged"])
            self.assertGreater(cell["purged_rows_excluded"], 0)
            self.assertEqual(cell["candidate_rows"], expected)
            self.assertEqual(cell["eligible_rows"], expected)

    def test_finite_captured_weather_enables_weather_climatology(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7", weather_value=25.0)
            result = compute_baselines(load_artifact(artifact))
            weather_predictions = [row for row in result["predictions"]
                                   if row["baseline_id"] == "weather_augmented_climatology"
                                   and row["split"] == "validation"]
            self.assertTrue(weather_predictions)
            self.assertTrue(all(row["prediction_status"] == "predicted"
                                for row in weather_predictions))
            cell = next(row for row in result["metrics"]
                        if row["baseline_id"] == "weather_augmented_climatology"
                        and row["sensor_id"] == "sensor_a" and row["horizon_hours"] == 6
                        and row["split"] == "validation")
            self.assertEqual(cell["metric_status"], "available")
            self.assertEqual(result["manifest"]["status"], "ok")

    def test_replay_rejects_summary_bound_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7")
            result = run_baselines(artifact)
            summary = {"purpose": result["purpose"], "manifest": result["manifest"],
                       "manifest_sha256": result["manifest_sha256"]}
            summary["manifest"]["input_feature_version"] = "phase7_features_v0"
            summary_path = Path(directory) / "tampered_summary.json"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(BaselineError):
                replay_baselines(artifact, summary_path, Path(directory) / "replay")

    def test_required_phase7_hash_declaration_cannot_be_omitted(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7")
            success_path = artifact / "SUCCESS.json"
            success = json.loads(success_path.read_text(encoding="utf-8"))
            del success["files_sha256"]["phase_7_features.csv"]
            success_path.write_text(json.dumps(success), encoding="utf-8")
            with self.assertRaises(BaselineError):
                load_artifact(artifact)

    def test_resigned_split_boundary_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = make_artifact(Path(directory) / "phase7")
            result = run_baselines(artifact)
            summary = {"purpose": result["purpose"], "manifest": result["manifest"],
                       "manifest_sha256": result["manifest_sha256"]}
            summary["manifest"]["split"]["test_start"] = "2030-01-01T00:00:00+00:00"
            summary["manifest_sha256"] = digest(summary["manifest"])
            summary_path = Path(directory) / "resigned_summary.json"
            summary_path.write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaises(BaselineError):
                replay_baselines(artifact, summary_path, Path(directory) / "replay")


class IntegrityReplayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.artifact = make_artifact(self.root / "phase7")

    def test_each_required_hash_is_mandatory(self):
        path = self.artifact / "SUCCESS.json"
        original = json.loads(path.read_text())
        for filename in ("phase_7_feature_summary.json", "phase_7_features.csv", "phase_7_targets.csv"):
            with self.subTest(filename=filename):
                success = copy.deepcopy(original)
                del success["files_sha256"][filename]
                path.write_text(json.dumps(success))
                with patch("vn_air.baselines.read_csv") as reader:
                    with self.assertRaises(BaselineError):
                        load_artifact(self.artifact)
                    reader.assert_not_called()

    def test_success_identity_must_match_summary(self):
        path = self.artifact / "SUCCESS.json"
        original = json.loads(path.read_text())
        for field in ("feature_version", "availability_basis", "bundle_sha256", "manifest_sha256"):
            for value in (None, "wrong"):
                with self.subTest(field=field, value=value):
                    success = copy.deepcopy(original)
                    success[field] = value
                    path.write_text(json.dumps(success))
                    with self.assertRaises(BaselineError):
                        load_artifact(self.artifact)

    def test_hash_manifest_cannot_reference_files_outside_contract(self):
        path = self.artifact / "SUCCESS.json"
        original = json.loads(path.read_text())
        for filename in ("../outside.txt", "/outside.txt", ".env"):
            with self.subTest(filename=filename):
                success = copy.deepcopy(original)
                success["files_sha256"][filename] = "0" * 64
                path.write_text(json.dumps(success))
                with patch("vn_air.baselines.sha256_file") as hasher:
                    with self.assertRaises(BaselineError):
                        load_artifact(self.artifact)
                    hasher.assert_not_called()

    def test_metadata_objects_and_duplicate_keys_are_rejected(self):
        path = self.artifact / "SUCCESS.json"
        original = path.read_text()
        duplicate = original.rstrip()[:-1] + ', "files_sha256": ' + json.dumps(
            json.loads(original)["files_sha256"]) + '}'
        for text in ("[]", "null", duplicate, '{"files_sha256": NaN}'):
            with self.subTest(text=text[:30]):
                path.write_text(text)
                with self.assertRaises(BaselineError):
                    load_artifact(self.artifact)

    def test_malformed_replay_metadata_is_rejected_before_computation(self):
        path = self.root / "summary.json"
        for text in ("[]", "null", '{"manifest": NaN}', '{"manifest": {}, "manifest": {}}'):
            with self.subTest(text=text):
                path.write_text(text)
                with patch("vn_air.baselines.run_baselines") as runner:
                    with self.assertRaises(BaselineError):
                        replay_baselines(self.artifact, path, self.root / "replay")
                    runner.assert_not_called()

    def test_valid_summary_bound_replay_matches_all_five_files(self):
        result = run_baselines(self.artifact)
        first, replay = self.root / "first", self.root / "replay"
        write_outputs(first, result)
        replay_baselines(self.artifact, first / "phase_8_baselines_summary.json", replay)
        names = sorted(path.name for path in first.iterdir())
        self.assertEqual(len(names), 5)
        for name in names:
            self.assertEqual((first / name).read_bytes(), (replay / name).read_bytes(), name)

    def test_replay_is_portable_to_another_input_directory(self):
        result = run_baselines(self.artifact)
        self.assertNotIn("input_artifact_directory", result["manifest"])
        first = self.root / "first"
        write_outputs(first, result)
        relocated = self.root / "relocated_phase7"
        shutil.copytree(self.artifact, relocated)
        replay = self.root / "relocated_replay"
        replay_baselines(relocated, first / "phase_8_baselines_summary.json", replay)
        for source in first.iterdir():
            self.assertEqual(source.read_bytes(), (replay / source.name).read_bytes(), source.name)

    def test_summary_digest_is_checked_before_computation(self):
        result = run_baselines(self.artifact)
        path = self.root / "summary.json"
        summary = {key: result[key] for key in ("purpose", "manifest", "manifest_sha256")}
        summary["manifest_sha256"] = "0" * 64
        path.write_text(json.dumps(summary))
        with patch("vn_air.baselines.run_baselines") as runner:
            with self.assertRaises(BaselineError):
                replay_baselines(self.artifact, path, self.root / "replay")
            runner.assert_not_called()

    def test_resigned_manifest_fields_and_purpose_are_bound(self):
        result = run_baselines(self.artifact)
        original = json.loads(json.dumps({key: result[key] for key in
                                         ("purpose", "manifest", "manifest_sha256")}))
        mutations = {
            "split": {"test_start": "2030-01-01T00:00:00+00:00"},
            "boundary": {"mode": "frozen", "frozen_boundary_applied": True},
            "input_rows": 1,
            "input_artifact_directory": "another/location",
            "implementation_sha256": {"baselines.py": "0" * 64},
            "selection_policy": "changed",
            "baseline_definitions": [],
            "status": "changed",
            "metrics": [],
            "unexpected_field": True,
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                summary = copy.deepcopy(original)
                summary["manifest"][field] = value
                summary["manifest_sha256"] = digest(summary["manifest"])
                path = self.root / "summary.json"
                path.write_text(json.dumps(summary))
                with self.assertRaises(BaselineError):
                    replay_baselines(self.artifact, path, self.root / "replay")
                self.assertFalse((self.root / "replay").exists())
        original["purpose"] = "changed"
        path.write_text(json.dumps(original))
        with self.assertRaises(BaselineError):
            replay_baselines(self.artifact, path, self.root / "replay")

    def test_replay_refuses_existing_output_before_computation(self):
        path = self.root / "exists"
        path.mkdir()
        with patch("vn_air.baselines.run_baselines") as runner:
            with self.assertRaises(BaselineError):
                replay_baselines(self.artifact, self.root / "absent-summary.json", path)
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
