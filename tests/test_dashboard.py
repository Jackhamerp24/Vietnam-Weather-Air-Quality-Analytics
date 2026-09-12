"""Offline verification of the frozen Phase 10 public-data boundary.

Temporary files here are isolated test fixtures only. No application/model
module, source API, database or environment/credential file is used.
"""

import ast
from collections import Counter, defaultdict
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from scripts import build_dashboard as dashboard


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
TOP_LEVEL = {
    "schema_version", "meta", "sensors", "hourly", "weather_variables", "daily",
    "diurnal", "weather_associations", "cams_daily", "statistics", "features",
    "baselines", "ml", "provenance", "bundle_sha256",
}


def independent_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def signed_fixture(root, files=None, success_changes=None):
    """Small synthetic artifact with an explicitly supplied test trust root."""
    root.mkdir()
    files = files if files is not None else {"payload.json": b'{"value":1}\n'}
    for name, data in files.items():
        (root / name).write_bytes(data)
    success = {"files_sha256": {name: hashlib.sha256(data).hexdigest()
                                for name, data in files.items()}}
    if success_changes:
        success_changes(success)
    encoded = json.dumps(success, sort_keys=True).encode()
    (root / "SUCCESS.json").write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


class DashboardBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phase10-boundary-", dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_success_pins_are_actual_file_digests_not_manifest_digests(self):
        self.assertEqual(set(dashboard.EXPECTED_SUCCESS), set(dashboard.SUMMARIES))
        for rel in dashboard.SUMMARIES:
            with self.subTest(phase=rel.name):
                actual = hashlib.sha256((ROOT / rel / "SUCCESS.json").read_bytes()).hexdigest()
                self.assertEqual(actual, dashboard.EXPECTED_SUCCESS[rel])
                self.assertNotEqual(actual, dashboard.EXPECTED_IDENTITY[rel])

    def test_valid_artifact_checks_every_file_and_returns_verified_bytes(self):
        artifact = self.root / "artifact"
        pin = signed_fixture(artifact, {"payload.json": b'{"value":1}\n', "other.txt": b"other"})
        success, selected, verification = dashboard.verify_artifact(artifact, pin, ("payload.json",))
        self.assertEqual(selected["payload.json"], b'{"value":1}\n')
        self.assertEqual(set(success["files_sha256"]), {"payload.json", "other.txt"})
        self.assertEqual(verification, {"files_sha256": success["files_sha256"],
                                        "integrity_exceptions": []})
        (artifact / "other.txt").write_bytes(b"changed")
        with self.assertRaisesRegex(dashboard.DashboardBuildError, "payload hash"):
            dashboard.verify_artifact(artifact, pin, ("payload.json",))

    def test_resigned_tamper_rejected_for_every_real_phase_before_payload_read(self):
        original_read = dashboard.read_regular
        for rel, summary_name in dashboard.SUMMARIES.items():
            with self.subTest(phase=rel.name):
                success = json.loads((ROOT / rel / "SUCCESS.json").read_bytes())
                summary = json.loads((ROOT / rel / summary_name).read_bytes())
                summary["manifest"]["tamper_test"] = True
                if rel == dashboard.PHASE5:
                    key = "bundle_sha256"
                    summary[key] = independent_digest({k: v for k, v in summary.items() if k != key})
                else:
                    key = "manifest_sha256"
                    summary[key] = independent_digest(summary["manifest"])
                success[key] = summary[key]
                summary_bytes = json.dumps(summary, sort_keys=True).encode()
                success["files_sha256"][summary_name] = hashlib.sha256(summary_bytes).hexdigest()
                modified_success = json.dumps(success, sort_keys=True).encode()
                calls = []

                def changed_success(path):
                    calls.append(path.name)
                    if path == ROOT / rel / "SUCCESS.json":
                        return modified_success
                    return original_read(path)

                with mock.patch.object(dashboard, "read_regular", side_effect=changed_success):
                    with self.assertRaisesRegex(dashboard.DashboardBuildError, "Pinned SUCCESS"):
                        dashboard.verify_artifact(ROOT / rel, dashboard.EXPECTED_SUCCESS[rel],
                                                  (summary_name,))
                self.assertEqual(calls, ["SUCCESS.json"])

    def test_unsafe_declared_paths_fail_before_payload_reads(self):
        attacks = ("../outside.json", "/absolute.json", "nested/file.json",
                   r"..\outside.json", r"C:\outside.json", "https://host/a", "./payload.json",
                   "%2e%2e%2foutside.json", "payload.json\n", ".env", "", "SUCCESS.json")
        for index, attack in enumerate(attacks):
            with self.subTest(path=attack):
                artifact = self.root / str(index)
                pin = signed_fixture(artifact, success_changes=lambda s:
                                     s["files_sha256"].update({attack: "a" * 64}))
                original = dashboard.read_regular
                with mock.patch.object(dashboard, "read_regular", wraps=original) as reader:
                    with self.assertRaisesRegex(dashboard.DashboardBuildError, "Unsafe payload"):
                        dashboard.verify_artifact(artifact, pin)
                    self.assertEqual([call.args[0].name for call in reader.call_args_list],
                                     ["SUCCESS.json"])

    def test_invalid_hash_maps_and_missing_required_declarations(self):
        for index, value in enumerate((None, [], {}, {"payload.json": "x" * 64},
                                       {"payload.json": True}, {"payload.json": "A" * 64})):
            with self.subTest(value=value):
                artifact = self.root / str(index)
                pin = signed_fixture(artifact, success_changes=lambda s: s.update(files_sha256=value))
                with self.assertRaises(dashboard.DashboardBuildError):
                    dashboard.verify_artifact(artifact, pin, ("payload.json",))
        artifact = self.root / "missing-declaration"
        pin = signed_fixture(artifact)
        with self.assertRaisesRegex(dashboard.DashboardBuildError, "not declared"):
            dashboard.verify_artifact(artifact, pin, ("required.csv",))

    def test_missing_extra_and_symlinked_payloads_are_rejected(self):
        for kind in ("missing", "extra", "leaf_link", "success_link", "directory_link"):
            with self.subTest(kind=kind):
                artifact = self.root / kind
                pin = signed_fixture(artifact)
                if kind == "missing":
                    (artifact / "payload.json").unlink()
                elif kind == "extra":
                    (artifact / "undeclared.txt").write_text("extra")
                elif kind == "leaf_link":
                    (artifact / "payload.json").rename(self.root / "real-payload.json")
                    (artifact / "payload.json").symlink_to(self.root / "real-payload.json")
                elif kind == "success_link":
                    (artifact / "SUCCESS.json").rename(self.root / "real-success.json")
                    (artifact / "SUCCESS.json").symlink_to(self.root / "real-success.json")
                else:
                    real = self.root / "real-directory"
                    artifact.rename(real)
                    artifact.symlink_to(real, target_is_directory=True)
                with self.assertRaises(dashboard.DashboardBuildError):
                    dashboard.verify_artifact(artifact, pin)

    def test_ancestor_symlink_is_rejected(self):
        parent = self.root / "parent"
        parent.mkdir()
        pin = signed_fixture(parent / "artifact")
        link = self.root / "link"
        link.symlink_to(parent, target_is_directory=True)
        with self.assertRaisesRegex(dashboard.DashboardBuildError, "Symlink"):
            dashboard.verify_artifact(link / "artifact", pin)

    def test_duplicate_malformed_json_and_nonfinite_values_rejected(self):
        for raw in (b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}', b"{",
                    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}',
                    b'{"x":1e999}', b"\xff"):
            with self.subTest(raw=raw):
                with self.assertRaises(dashboard.DashboardBuildError):
                    dashboard.strict_json(raw)

    def test_numeric_null_zero_and_invalid_values(self):
        self.assertIsNone(dashboard.number(None))
        self.assertIsNone(dashboard.number(""))
        self.assertEqual(dashboard.number("0"), 0)
        for value in ("nan", "inf", "-Infinity", "1e999", True, [], "bad"):
            with self.subTest(value=value):
                with self.assertRaises(dashboard.DashboardBuildError):
                    dashboard.number(value)

    def test_exact_phase5_readme_exception_is_disclosed_and_never_consumed(self):
        artifact = ROOT / dashboard.PHASE5
        original = (artifact / "README.md").read_bytes()
        original_success = (artifact / "SUCCESS.json").read_bytes()
        success, selected, verification = dashboard.verify_artifact(
            artifact, dashboard.EXPECTED_SUCCESS[dashboard.PHASE5], ("eda_bundle.json",))
        self.assertTrue(original.endswith(b"\n"))
        self.assertEqual(hashlib.sha256(original).hexdigest(),
                         "f5de669c0c37f0f3d4e9fd7a02c0c4c21540f233397f34fbbb234082d0e68988")
        # Test the reviewed byte relationship only; no normalized bytes are
        # passed to the production loader or written to any source artifact.
        self.assertEqual(hashlib.sha256(original + b"\n").hexdigest(),
                         "f6e76ba8011e6657c3894124639c7789806a17db9097dc4b82a5921f24d625cd")
        self.assertNotIn("README.md", selected)
        self.assertNotIn("README.md", verification["files_sha256"])
        self.assertIn("README.md", success["files_sha256"])
        self.assertEqual(verification["integrity_exceptions"], [{
            "file": "README.md",
            "declared_sha256": "f6e76ba8011e6657c3894124639c7789806a17db9097dc4b82a5921f24d625cd",
            "observed_sha256": "f5de669c0c37f0f3d4e9fd7a02c0c4c21540f233397f34fbbb234082d0e68988",
            "reason": dashboard.PHASE5_README_REASON,
        }])
        self.assertEqual((artifact / "README.md").read_bytes(), original)
        self.assertEqual((artifact / "SUCCESS.json").read_bytes(), original_success)

    def test_excepted_readme_cannot_be_requested_as_consumed_payload(self):
        with self.assertRaisesRegex(dashboard.DashboardBuildError, "never be consumed"):
            dashboard.verify_artifact(ROOT / dashboard.PHASE5,
                                      dashboard.EXPECTED_SUCCESS[dashboard.PHASE5], ("README.md",))

    def test_exception_requires_exact_repository_relative_directory(self):
        for name in ("arbitrary-fixture", dashboard.PHASE5.name):
            with self.subTest(directory=name):
                artifact = self.root / name
                shutil.copytree(ROOT / dashboard.PHASE5, artifact)
                with self.assertRaisesRegex(dashboard.DashboardBuildError, "payload hash"):
                    dashboard.verify_artifact(artifact, dashboard.EXPECTED_SUCCESS[dashboard.PHASE5],
                                              repo_root=self.root)

    def test_any_other_phase5_readme_bytes_fail_including_declared_hash_variant(self):
        artifact = self.root / dashboard.PHASE5
        shutil.copytree(ROOT / dashboard.PHASE5, artifact)
        readme = artifact / "README.md"
        original = readme.read_bytes()
        for variant in (original[:-1], original + b"\n", original + b"\n\n",
                        original.replace(b"Frozen", b"Edited", 1), b""):
            with self.subTest(digest=hashlib.sha256(variant).hexdigest()):
                readme.write_bytes(variant)
                with self.assertRaisesRegex(dashboard.DashboardBuildError, "exact reviewed exception"):
                    dashboard.verify_artifact(artifact, dashboard.EXPECTED_SUCCESS[dashboard.PHASE5],
                                              repo_root=self.root)

    def test_phase5_data_mutation_still_fails_with_exact_readme_exception(self):
        artifact = self.root / dashboard.PHASE5
        shutil.copytree(ROOT / dashboard.PHASE5, artifact)
        path = artifact / "daily.csv"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(dashboard.DashboardBuildError, "payload hash"):
            dashboard.verify_artifact(artifact, dashboard.EXPECTED_SUCCESS[dashboard.PHASE5],
                                      repo_root=self.root)

    def test_exception_cannot_be_enabled_by_resigning_success_or_declared_hash(self):
        artifact = self.root / dashboard.PHASE5
        shutil.copytree(ROOT / dashboard.PHASE5, artifact)
        original = json.loads((artifact / "SUCCESS.json").read_bytes())
        for change in ("extra_field", "declared_hash"):
            with self.subTest(change=change):
                success = copy.deepcopy(original)
                if change == "extra_field":
                    success["unreviewed"] = True
                else:
                    success["files_sha256"]["README.md"] = dashboard.PHASE5_README_OBSERVED
                encoded = json.dumps(success, sort_keys=True).encode()
                (artifact / "SUCCESS.json").write_bytes(encoded)
                with self.assertRaisesRegex(dashboard.DashboardBuildError, "Pinned SUCCESS"):
                    dashboard.verify_artifact(artifact, dashboard.EXPECTED_SUCCESS[dashboard.PHASE5],
                                              repo_root=self.root)
                # Even an explicitly supplied test trust root cannot broaden
                # this exception: its SUCCESS file digest is separately fixed.
                with self.assertRaisesRegex(dashboard.DashboardBuildError, "exact reviewed exception"):
                    dashboard.verify_artifact(artifact, hashlib.sha256(encoded).hexdigest(),
                                              repo_root=self.root)

    def test_malformed_csv_and_missing_columns_rejected(self):
        for data in (b"a,a\n1,2\n", b"a,b\n1,2,3\n", b"a,b\n1\n",
                     b'a,b\n"unfinished,2\n', b"", b"x,y\n1,2\n"):
            with self.subTest(data=data):
                with self.assertRaises(dashboard.DashboardBuildError):
                    dashboard.read_csv(data, ("a", "b"))

    def test_canonical_identity_covers_entire_bundle_or_manifest(self):
        for rel, name in dashboard.SUMMARIES.items():
            with self.subTest(phase=rel.name):
                success = json.loads((ROOT / rel / "SUCCESS.json").read_bytes())
                summary = json.loads((ROOT / rel / name).read_bytes())
                # Not a selected display field: still covered by the full digest.
                summary["manifest"]["implementation_sha256"] = {"changed.py": "0" * 64}
                with self.assertRaisesRegex(dashboard.DashboardBuildError, "Canonical"):
                    dashboard.parse_summary(rel, success, json.dumps(summary).encode())

    def test_malformed_summary_missing_version_and_wrong_root_rejected(self):
        rel = dashboard.PHASE7
        success = json.loads((ROOT / rel / "SUCCESS.json").read_bytes())
        for value in ([], None, {}, {"manifest": []}, {"manifest": {}},
                      {"manifest": {"feature_version": "wrong"}}):
            with self.subTest(value=value):
                with self.assertRaises(dashboard.DashboardBuildError):
                    dashboard.parse_summary(rel, success, json.dumps(value).encode())

    def test_main_preflights_existing_output_and_missing_parent_before_loading(self):
        existing = self.root / "existing.json"
        existing.write_bytes(b"leave untouched")
        for output in (existing, self.root / "absent" / "new.json"):
            with self.subTest(output=output.name):
                with mock.patch.object(dashboard, "build_payload") as build, redirect_stdout(io.StringIO()):
                    self.assertEqual(dashboard.main(["--output", str(output)]), 1)
                    build.assert_not_called()
        self.assertEqual(existing.read_bytes(), b"leave untouched")

    def test_main_preflights_symlink_output_and_ancestors_before_loading(self):
        target = self.root / "real.json"
        target.write_bytes(b"original")
        leaf = self.root / "leaf.json"
        leaf.symlink_to(target)
        dangling = self.root / "dangling.json"
        dangling.symlink_to(self.root / "does-not-exist")
        real_parent = self.root / "real-parent"
        real_parent.mkdir()
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        for output in (leaf, dangling, linked_parent / "new.json"):
            with self.subTest(output=output.name):
                with mock.patch.object(dashboard, "build_payload") as build, redirect_stdout(io.StringIO()):
                    self.assertEqual(dashboard.main(["--output", str(output)]), 1)
                    build.assert_not_called()
        self.assertEqual(target.read_bytes(), b"original")

    def test_main_missing_source_creates_no_output(self):
        output = self.root / "new.json"
        with redirect_stdout(io.StringIO()):
            self.assertEqual(dashboard.main(["--repo-root", str(self.root),
                                             "--output", str(output)]), 1)
        self.assertFalse(output.exists())

    def test_main_does_not_print_untrusted_exceptions(self):
        output = self.root / "new.json"
        text = io.StringIO()
        with mock.patch.object(dashboard, "build_payload",
                               side_effect=dashboard.DashboardBuildError("untrusted private value")):
            with redirect_stdout(text):
                self.assertEqual(dashboard.main(["--output", str(output)]), 1)
        self.assertNotIn("untrusted private value", text.getvalue())

    def test_cams_null_days_and_zero_are_not_imputed(self):
        def row(date, value, quality="accepted"):
            return {"location_id": "da_nang", "local_date": date, "value": value,
                    "quality": quality, "source_value": 9999, "pm25": 9999}
        result = dashboard.aggregate_cams([
            row("2026-06-08", None, "absent"), row("2026-06-08", "", "missing"),
            row("2026-06-09", 0), row("2026-06-09", 6), row("2026-06-09", None),
        ])
        self.assertEqual(result, [
            {"location_id": "da_nang", "local_date": "2026-06-08", "n": 0, "mean": None},
            {"location_id": "da_nang", "local_date": "2026-06-09", "n": 2, "mean": 3.0},
        ])

    def test_cams_source_separation_and_nonfinite_rejection(self):
        for location, value in (("cmt8", 1), ("da_nang", "NaN"), ("hanoi", "1e999")):
            with self.subTest(location=location, value=value):
                with self.assertRaises(dashboard.DashboardBuildError):
                    dashboard.aggregate_cams([{"location_id": location, "local_date": "2026-06-08",
                                               "value": value, "quality": "accepted"}])

    def test_builder_imports_only_standard_library(self):
        tree = ast.parse((ROOT / "scripts/build_dashboard.py").read_text())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module.split(".")[0])
        self.assertLessEqual(imported, sys.stdlib_module_names)
        self.assertFalse(imported & {"vn_air", "socket", "urllib", "http", "subprocess"})


class DashboardFrozenBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A source-integrity failure outside the exact approved, disclosed
        # documentation exception is a real failure, never patched or skipped.
        cls.payload = dashboard.build_payload(ROOT)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phase10-bundle-", dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_exact_public_contract_and_no_raw_ids(self):
        payload = self.payload
        self.assertEqual(set(payload), TOP_LEVEL)
        self.assertEqual(set(payload["meta"]),
                         {"title", "status", "window", "daily_policy", "limitations", "source_policy",
                          "integrity_notes"})
        self.assertEqual(set(payload["features"]),
                         {"version", "status", "missing_families", "counts",
                          "prospective_collection_period_required", "split"})
        expected_hourly = set(dashboard.HOURLY_FIELDS) | {"weather", "weather_quality"}
        for row in payload["hourly"]:
            self.assertEqual(set(row), expected_hourly)
        for row in payload["daily"]:
            self.assertEqual(set(row), set(dashboard.DAILY_FIELDS))
        for row in payload["statistics"]["results"]:
            self.assertEqual(set(row), set(dashboard.STATS_FIELDS))
            self.assertNotIn("p_value", row)
        forbidden = {
            "response_id", "revision", "measurement_id", "observation_id", "value_id",
            "snapshot_id", "source_value", "source_pm25", "raw_body", "raw_response",
            "request_headers", "database_url", "api_key", "password", "authorization",
            "latitude", "longitude",
        }

        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(set(value) & forbidden)
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        inspect(payload)
        serialized = dashboard.canonical(payload).decode()
        self.assertIsNone(re.search(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", serialized))
        self.assertNotIn(str(ROOT), serialized)
        self.assertNotIn(".env", serialized)

    def test_true_counts_gaps_sensor_identity_and_zero(self):
        p = self.payload
        self.assertEqual([len(p[key]) for key in ("sensors", "hourly", "daily", "diurnal",
                                                 "weather_associations", "cams_daily")],
                         [2, 4320, 182, 48, 16, 273])
        self.assertEqual(Counter(row["quality"] for row in p["hourly"]),
                         Counter({"accepted": 4191, "absent": 129}))
        for sensor, accepted, absent in (("openaq_11357424", 2154, 6),
                                        ("openaq_14581375", 2037, 123)):
            values = [row for row in p["hourly"] if row["sensor_id"] == sensor]
            self.assertEqual(sum(row["pm25"] is not None for row in values), accepted)
            self.assertEqual(sum(row["pm25"] is None for row in values), absent)
            self.assertEqual(len(values), 2160)
        self.assertTrue(any(row["pm25"] == 0 for row in p["hourly"]))
        self.assertNotIn("da_nang", {row["location_id"] for row in p["sensors"]})

    def test_source_weather_units_quality_and_temporal_support(self):
        variables = {row["code"]: row for row in self.payload["weather_variables"]}
        for code, (_label, unit, support) in dashboard.WEATHER.items():
            self.assertEqual(variables[code]["unit"], unit)
            self.assertEqual(variables[code]["temporal_support"], support)
            self.assertEqual(variables[code]["source"], "ERA5_reanalysis")
        self.assertEqual(variables["wind_speed_10m"]["unit"], "m/s")
        self.assertEqual(variables["shortwave_radiation"]["temporal_support"], "preceding_hour_mean")
        for row in self.payload["hourly"]:
            self.assertEqual(set(row["weather"]), set(variables))
            self.assertEqual(set(row["weather_quality"]), set(variables))
            for code, value in row["weather"].items():
                self.assertEqual(value is not None, row["weather_quality"][code] == "accepted")
        self.assertIn("interval start", self.payload["meta"]["source_policy"])
        self.assertIn("interval end", self.payload["meta"]["source_policy"])

    def test_local_dates_are_fixed_vietnam_iso_strings(self):
        window = self.payload["meta"]["window"]
        self.assertEqual(window["local_start"], "2026-06-08T07:00:00+07:00")
        self.assertEqual(window["local_end"], "2026-09-06T07:00:00+07:00")
        self.assertEqual(window["cutoff_utc"], dashboard.CUTOFF)
        for row in self.payload["hourly"]:
            self.assertRegex(row["local_date"], r"^\d{4}-\d{2}-\d{2}$")
            local = dashboard.timestamp(row["period_start"]).astimezone(dashboard.VIETNAM)
            self.assertEqual(row["local_date"], local.date().isoformat())
            self.assertEqual(row["local_hour"], local.hour)
        self.assertNotIn("generated_at", self.payload)

    def test_daily_and_diurnal_values_are_actual_csv_not_recomputed(self):
        source = dashboard.read_csv((ROOT / dashboard.PHASE5 / "daily.csv").read_bytes(),
                                    dashboard.DAILY_FIELDS)
        for frozen, public in zip(source, self.payload["daily"]):
            self.assertEqual(public["mean"], dashboard.number(frozen["mean"]))
            self.assertEqual(public["qualified_mean"], dashboard.number(frozen["qualified_mean"]))
            self.assertEqual(public["accepted_hours"], int(frozen["accepted_hours"]))
        self.assertTrue(any(row["mean"] is not None and row["qualified_mean"] is None
                            for row in self.payload["daily"]))
        self.assertTrue(any(row["mean"] is None for row in self.payload["daily"]))
        source = dashboard.read_csv((ROOT / dashboard.PHASE5 / "diurnal.csv").read_bytes(),
                                    ("sensor_id", "local_hour", "n", "mean"))
        for frozen, public in zip(source, self.payload["diurnal"]):
            self.assertEqual(public, {"sensor_id": frozen["sensor_id"],
                                      "local_hour": int(frozen["local_hour"]), "n": int(frozen["n"]),
                                      "mean": float(frozen["mean"])})

    def test_cams_means_use_independent_modeled_hourly_values(self):
        groups = defaultdict(list)
        source = dashboard.read_csv((ROOT / dashboard.PHASE5 / "cams_modeled_pm25.csv").read_bytes(),
                                    ("location_id", "local_date", "value"))
        for row in source:
            groups[(row["location_id"], row["local_date"])].append(float(row["value"]))
        for row in self.payload["cams_daily"]:
            values = groups[(row["location_id"], row["local_date"])]
            self.assertEqual(row["n"], len(values))
            self.assertAlmostEqual(row["mean"], math.fsum(values) / len(values), places=12)
        self.assertEqual(Counter(row["location_id"] for row in self.payload["cams_daily"]),
                         Counter({"da_nang": 91, "hanoi": 91, "hcmc": 91}))
        self.assertEqual(sum(row["n"] for row in self.payload["cams_daily"]), 6480)

    def test_statistics_keep_adjusted_inference_and_interpretation_fields(self):
        source = json.loads((ROOT / dashboard.PHASE6 / dashboard.SUMMARIES[dashboard.PHASE6]).read_bytes())
        self.assertEqual(len(self.payload["statistics"]["results"]), 31)
        for frozen, public in zip(source["results"], self.payload["statistics"]["results"]):
            for field in dashboard.STATS_FIELDS:
                self.assertEqual(public[field], frozen.get(field))
            if public["inference"] == "inferential":
                self.assertIsNotNone(public["p_value_adjusted"])
                self.assertIn(public["adjustment"].split()[0], {"Holm", "Benjamini-Hochberg"})
        self.assertEqual(sum(row["inference"] == "inferential"
                             for row in self.payload["statistics"]["results"]), 7)

    def test_phase7_availability_is_directly_verified_and_preserved(self):
        source = json.loads((ROOT / dashboard.PHASE7 / dashboard.SUMMARIES[dashboard.PHASE7]).read_bytes())["manifest"]
        features = self.payload["features"]
        self.assertEqual(features["version"], "phase7_features_v7")
        self.assertEqual(features["counts"], source["counts"])
        self.assertEqual(features["split"], source["split"])
        self.assertEqual(features["counts"]["rows"], 8548)
        self.assertEqual(features["counts"]["pm_available_origin_count"], 0)
        self.assertEqual(features["counts"]["weather_available_origin_count"], 0)
        self.assertTrue(features["prospective_collection_period_required"])
        self.assertEqual(features["missing_families"], ["pm_history", "forecast_weather"])

    def test_full_frozen_metric_records_with_null_scores_not_zeroes(self):
        for rel, section, allowed in ((dashboard.PHASE8, "baselines", dashboard.BASELINE_FIELDS),
                                      (dashboard.PHASE9, "ml", dashboard.ML_FIELDS)):
            source = json.loads((ROOT / rel / dashboard.SUMMARIES[rel]).read_bytes())["manifest"]
            for frozen, public in zip(source["metrics"], self.payload[section]["metrics"]):
                self.assertEqual(public, {key: frozen.get(key) for key in allowed})
                self.assertEqual(public["metric_scope"], "descriptive_only")
                if public["metric_status"] == "unavailable":
                    self.assertTrue(public["metric_reason"])
                    self.assertIsNone(public["mae"])
                    self.assertIsNone(public["rmse"])
        self.assertEqual(Counter(row["metric_status"] for row in self.payload["baselines"]["metrics"]),
                         Counter({"available": 18, "unavailable": 72}))
        self.assertEqual(Counter(row["metric_status"] for row in self.payload["ml"]["metrics"]),
                         Counter({"available": 72, "unavailable": 216}))
        self.assertEqual(self.payload["ml"]["counts"]["trained_instances"], 24)
        for row in self.payload["ml"]["metrics"]:
            if row["split"] == "validation":
                self.assertEqual(row["evaluation_type"], "tuning_diagnostic")

    def test_comparison_history_and_fit_partitions_are_preserved(self):
        source = json.loads((ROOT / dashboard.PHASE9 / dashboard.SUMMARIES[dashboard.PHASE9]).read_bytes())["manifest"]
        public = self.payload["ml"]["comparisons"]
        self.assertEqual(len(public), 360)
        for frozen, row in zip(source["comparisons"], public):
            self.assertEqual(row, {field: frozen.get(field) for field in dashboard.COMPARISON_FIELDS})
        mismatched = [row for row in public if row["history_status"] == "training_history_mismatch"]
        self.assertTrue(mismatched)
        self.assertTrue(any(row["fit_partition"] == "train_plus_validation" and
                            row["reference_fit_partition"] == "train" for row in mismatched))

    def test_all_manifests_and_payload_hashes_are_recorded(self):
        self.assertEqual([row["phase"] for row in self.payload["provenance"]], [5, 6, 7, 8, 9])
        for rel, public in zip(dashboard.SUMMARIES, self.payload["provenance"]):
            frozen = json.loads((ROOT / rel / "SUCCESS.json").read_bytes())
            self.assertEqual(set(public), {"phase", "label", "directory", "identity", "files_sha256",
                                           "integrity_exceptions"})
            self.assertEqual(public["directory"], rel.as_posix())
            expected_verified = dict(frozen["files_sha256"])
            if rel == dashboard.PHASE5:
                expected_verified.pop("README.md")
            else:
                self.assertEqual(public["integrity_exceptions"], [])
            self.assertEqual(public["files_sha256"], expected_verified)
            self.assertEqual(public["identity"], dashboard.EXPECTED_IDENTITY[rel])
            for name, expected in public["files_sha256"].items():
                self.assertEqual(hashlib.sha256((ROOT / rel / name).read_bytes()).hexdigest(), expected)

    def test_public_integrity_note_and_exception_report_actual_unverified_document(self):
        phase5 = self.payload["provenance"][0]
        self.assertEqual(len(phase5["integrity_exceptions"]), 1)
        exception = phase5["integrity_exceptions"][0]
        self.assertEqual(set(exception), {"file", "declared_sha256", "observed_sha256", "reason"})
        self.assertEqual(exception["file"], "README.md")
        self.assertEqual(exception["declared_sha256"], dashboard.PHASE5_README_DECLARED)
        self.assertEqual(exception["observed_sha256"], dashboard.PHASE5_README_OBSERVED)
        self.assertNotIn(exception["file"], phase5["files_sha256"])
        self.assertEqual(self.payload["meta"]["integrity_notes"], [
            f"{dashboard.PHASE5.as_posix()}/README.md: {dashboard.PHASE5_README_REASON}"
        ])
        self.assertIn("not fully verified", self.payload["meta"]["integrity_notes"][0])
        for phase in self.payload["provenance"][1:]:
            self.assertEqual(phase["integrity_exceptions"], [])

    def test_json_is_finite_and_canonical_hash_covers_entire_public_object(self):
        expected = independent_digest({key: value for key, value in self.payload.items()
                                       if key != "bundle_sha256"})
        self.assertEqual(self.payload["bundle_sha256"], expected)
        encoded = json.dumps(self.payload, allow_nan=False)
        self.assertNotIn(": NaN", encoded)
        self.assertNotIn(": Infinity", encoded)
        decoded = dashboard.strict_json(encoded.encode())
        self.assertEqual(decoded, self.payload)

    def test_deterministic_rebuild_write_and_default_bundle_bytes(self):
        other = dashboard.build_payload(ROOT)
        self.assertEqual(other, self.payload)
        first, second = self.root / "first.json", self.root / "second.json"
        dashboard.write_bundle(first, self.payload)
        dashboard.write_bundle(second, other)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(first.read_bytes(), dashboard.canonical(self.payload) + b"\n")
        default = ROOT / "dashboard/data/dashboard.json"
        if default.exists():
            self.assertEqual(default.read_bytes(), first.read_bytes())

    def test_relocated_checkout_generates_same_identity_and_bytes(self):
        relocated = self.root / "checkout"
        relocated.mkdir()
        for rel in dashboard.SUMMARIES:
            (relocated / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(ROOT / rel, relocated / rel)
        self.assertEqual(dashboard.build_payload(relocated), self.payload)

    def test_no_model_network_or_environment_reads_during_build(self):
        real_read = dashboard.read_regular
        read_paths = []

        def checked_read(path):
            read_paths.append(path)
            self.assertNotEqual(path.name, ".env")
            self.assertTrue(any(path.is_relative_to(ROOT / rel) for rel in dashboard.SUMMARIES))
            return real_read(path)
        with mock.patch.object(dashboard, "read_regular", side_effect=checked_read):
            rebuilt = dashboard.build_payload(ROOT)
        self.assertTrue(read_paths)
        self.assertEqual(rebuilt, self.payload)

    def test_writer_rejects_bad_hash_and_nonfinite_before_creating_file(self):
        for field, value in (("bundle_sha256", "0" * 64), ("extra", float("nan"))):
            payload = copy.deepcopy(self.payload)
            payload[field] = value
            output = self.root / (field + ".json")
            with self.assertRaises(dashboard.DashboardBuildError):
                dashboard.write_bundle(output, payload)
            self.assertFalse(output.exists())

    def test_writer_rejects_late_existing_file_without_overwrite(self):
        output = self.root / "race.json"
        original = dashboard.canonical

        def create_racing_destination(payload):
            if not output.exists():
                output.write_bytes(b"concurrent owner's file")
            return original(payload)
        with mock.patch.object(dashboard, "canonical", side_effect=create_racing_destination):
            with self.assertRaises(dashboard.DashboardBuildError):
                dashboard.write_bundle(output, self.payload)
        self.assertEqual(output.read_bytes(), b"concurrent owner's file")

    def test_cli_works_from_unrelated_cwd_and_rejects_overwrite(self):
        output = self.root / "cli.json"
        command = [sys.executable, "-B", str(ROOT / "scripts/build_dashboard.py"),
                   "--output", str(output)]
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True,
                                timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(output.read_bytes(), dashboard.canonical(self.payload) + b"\n")
        again = subprocess.run(command, cwd=self.root, capture_output=True, text=True,
                               timeout=30, check=False)
        self.assertEqual(again.returncode, 1)
        self.assertEqual(output.read_bytes(), dashboard.canonical(self.payload) + b"\n")


if __name__ == "__main__":
    unittest.main()
