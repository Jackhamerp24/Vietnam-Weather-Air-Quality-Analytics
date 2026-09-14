"""Offline checks for the Phase 12 portfolio walkthroughs.

The walkthroughs are a read-only presentation layer. These tests run them from
pinned local artifacts into temporary directories and verify deterministic,
fail-closed behavior. No database, network or credential is used.
"""

import ast
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
TEMP_ROOT = Path(tempfile.gettempdir()).resolve()
WALKTHROUGH_DIR = ROOT / "reports" / "portfolio"
FROZEN_DIR = ROOT / "docs" / "verification" / "phase_12_portfolio_2026-09-14_review_corrected"
LEGACY_DIR = ROOT / "docs" / "verification" / "phase_12_portfolio_2026-09-14"
SCREENSHOTS_DIR = ROOT / "docs" / "verification" / "phase_12_screenshots_2026-09-14_review_verified"
WALKTHROUGH_FILES = [
    "01_data_quality_and_eda",
    "02_sensor_associations",
    "03_feature_baseline_ml_contract",
    "04_dashboard_and_reproducibility",
]

sys.path.insert(0, str(WALKTHROUGH_DIR))

import portfolio_common as pc
import run_walkthroughs
import walkthrough_01_data_quality_and_eda as w01
import walkthrough_02_sensor_associations as w02
import walkthrough_04_dashboard_and_reproducibility as w04


ALLOWED_IMPORTS = {
    "__future__",
    "argparse",
    "collections",
    "csv",
    "hashlib",
    "json",
    "pathlib",
    "sys",
    "portfolio_common",
    "walkthrough_01_data_quality_and_eda",
    "walkthrough_02_sensor_associations",
    "walkthrough_03_feature_baseline_ml_contract",
    "walkthrough_04_dashboard_and_reproducibility",
}


def run_into(directory):
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        exit_code = run_walkthroughs.main(["--output-dir", str(directory)])
    return exit_code, buffer.getvalue()


def tree(directory):
    return {
        path.name: path.read_bytes()
        for path in sorted(Path(directory).iterdir())
        if path.is_file()
    }


class PortfolioWalkthroughTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phase12-walkthroughs-", dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_runner_writes_new_directory_deterministically(self):
        first, second = self.root / "first", self.root / "second"
        exit_code, output = run_into(first)
        self.assertEqual(exit_code, 0)
        self.assertIn("OK 01_data_quality_and_eda", output)
        run_into(second)
        self.assertEqual(tree(first), tree(second))
        expected = {f"{name}{suffix}" for name in WALKTHROUGH_FILES for suffix in (".md", ".json")}
        self.assertEqual(set(tree(first)), expected | {"manifest.json"})
        manifest = json.loads((first / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "ok")
        self.assertEqual(
            [entry["id"] for entry in manifest["walkthroughs"]], WALKTHROUGH_FILES
        )
        for entry in manifest["walkthroughs"]:
            self.assertTrue(entry["inputs"])
            for check in entry["inputs"]:
                self.assertTrue(check["verified"])
                self.assertEqual(check["sha256"], check["expected_sha256"])

    def test_existing_output_directory_is_rejected(self):
        existing = self.root / "existing"
        existing.mkdir()
        with self.assertRaises(pc.WalkthroughError):
            run_into(existing)

    def test_hash_mismatch_fails_closed(self):
        with self.assertRaises(pc.WalkthroughError):
            pc.verify_file("dashboard/data/dashboard.json", [], expected="0" * 64)

    def test_walkthrough_sources_import_only_offline_helpers(self):
        for path in sorted(WALKTHROUGH_DIR.glob("*.py")):
            tree_ = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree_):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                for name in names:
                    self.assertIn(name, ALLOWED_IMPORTS, f"{path.name} imports {name}")

    def test_artifact_claims_are_pinned_and_truthful(self):
        target = self.root / "claims"
        run_into(target)
        features = json.loads((target / "03_feature_baseline_ml_contract.json").read_text())
        results = features["results"]
        self.assertEqual(results["phase7"]["status"], "limited_diagnostic")
        self.assertEqual(
            results["phase7"]["counts"]["pm_available_origin_count"], 0
        )
        self.assertEqual(
            results["phase7"]["counts"]["weather_available_origin_count"], 0
        )
        self.assertEqual(results["phase8"]["available_cells"], 18)
        self.assertEqual(results["phase8"]["unavailable_cells"], 72)
        self.assertFalse(results["phase8"]["test_selection_used"])
        self.assertEqual(results["phase9"]["counts"]["trained_instances"], 24)
        self.assertEqual(results["phase9"]["counts"]["unavailable_metric_cells"], 216)
        self.assertFalse(results["phase9"]["test_selection_used"])
        dashboard = json.loads(
            (target / "04_dashboard_and_reproducibility.json").read_text()
        )
        self.assertEqual(
            dashboard["results"]["canonical_digest"],
            pc.IDENTITIES["dashboard_canonical_digest"],
        )

    def test_individual_walkthrough_cli(self):
        target = self.root / "single"
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = w01.main(["--output-dir", str(target)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(
            set(tree(target)),
            {"01_data_quality_and_eda.json", "01_data_quality_and_eda.md"},
        )

    def test_h3_raw_p_is_not_displayed_as_adjusted(self):
        payload, markdown = w02.build()
        h3 = next(row for row in payload["results"]["primary"] if row["hypothesis"] == "H3")
        self.assertEqual(h3["n"], 4070)
        self.assertIsNone(h3["p_value_adjusted"])
        self.assertIn("| Raw p | Holm-adjusted p |", markdown)
        h3_line = next(line for line in markdown.splitlines() if line.startswith("| H3 |"))
        self.assertIn("| not applicable | exploratory |", h3_line)
        self.assertIn("2,035 shared hours", markdown)

    def test_daily_grid_and_qualified_days_are_distinct(self):
        payload, markdown = w04.build()
        self.assertEqual(payload["results"]["counts"]["daily_rows"], 182)
        self.assertEqual(payload["results"]["counts"]["qualified_daily_rows"], 172)
        self.assertIn("| Qualified full sensor-days | 172 |", markdown)
        self.assertNotIn("| Qualified local days | 182 |", markdown)

    def test_provenance_declarations_are_not_claimed_as_file_reads(self):
        payload, markdown = w04.build()
        self.assertIn("Hash declarations matched", markdown)
        self.assertNotIn("Files verified", markdown)
        self.assertTrue(all("hash_declarations_matched" in row for row in payload["results"]["provenance"]))

    def test_dangling_output_symlink_is_not_followed(self):
        output = self.root / "output"
        output.mkdir()
        victim = self.root / "must-not-be-created"
        (output / "sample.json").symlink_to(victim)
        with self.assertRaises(pc.WalkthroughError):
            pc.write_artifacts(output, "sample", {}, "text")
        self.assertFalse(victim.exists())
        self.assertTrue((output / "sample.json").is_symlink())

    def test_symlinked_input_is_rejected_before_reading(self):
        (self.root / "alias.json").symlink_to(self.root / "missing.json")
        with mock.patch.object(pc, "REPO_ROOT", self.root), mock.patch.object(pc, "sha256_file") as read:
            with self.assertRaisesRegex(pc.WalkthroughError, "[Ss]ymlink"):
                pc.verify_file("alias.json", [], expected="0" * 64)
            read.assert_not_called()

    def test_late_input_failure_publishes_no_partial_walkthroughs(self):
        output = self.root / "failed"
        with mock.patch.object(w04, "build", side_effect=pc.WalkthroughError("synthetic input mismatch")):
            with self.assertRaises(pc.WalkthroughError):
                run_into(output)
        self.assertEqual(tree(output), {})

    def test_builds_need_no_environment_network_or_child_process(self):
        fail = AssertionError("Forbidden runtime access")
        original_open = io.open

        def guarded_open(file, *args, **kwargs):
            if not isinstance(file, int):
                self.assertNotIn(".env", Path(file).parts)
            return original_open(file, *args, **kwargs)

        with mock.patch("io.open", side_effect=guarded_open), \
             mock.patch.object(os, "getenv", side_effect=fail), \
             mock.patch.object(socket, "socket", side_effect=fail), \
             mock.patch.object(socket, "create_connection", side_effect=fail), \
             mock.patch.object(subprocess, "Popen", side_effect=fail):
            self.assertEqual(run_into(self.root / "guarded")[0], 0)

    def test_unknown_pin_is_rejected_before_reading(self):
        with mock.patch.object(pc, "sha256_file") as read:
            with self.assertRaisesRegex(pc.WalkthroughError, "No pinned hash"):
                pc.verify_file("unregistered.json", [])
            read.assert_not_called()

    def test_exclusive_writer_preserves_late_existing_file(self):
        target = self.root / "manifest.json"
        pc.write_text_new(target, "original")
        with self.assertRaises(pc.WalkthroughError):
            pc.write_text_new(target, "replacement")
        self.assertEqual(target.read_text(), "original")

    def test_original_v1_artifact_is_preserved(self):
        manifest_path = LEGACY_DIR / "manifest.json"
        self.assertEqual(pc.sha256_file(manifest_path), "d25caf1ffa85778fe3101ec792b50a5ee9ac02a37a715ddd90890f12e54026d2")
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(set(tree(LEGACY_DIR)), set(manifest["files"]) | {"manifest.json"})
        for name, expected in manifest["files"].items():
            self.assertEqual(pc.sha256_file(LEGACY_DIR / name), expected)

    def test_corrected_screenshot_manifest_binds_pngs_and_served_bundle(self):
        manifest = json.loads((SCREENSHOTS_DIR / "screenshots_manifest.json").read_text())
        self.assertEqual(manifest["screenshot_version"], "phase12_screenshots_v2")
        self.assertTrue(manifest["dashboard"]["served_bytes_verified"])
        self.assertTrue(manifest["dashboard"]["served_stylesheet_verified"])
        self.assertEqual(manifest["dashboard"]["stylesheet_sha256"], pc.sha256_file(ROOT / "dashboard/styles.css"))
        self.assertEqual(manifest["dashboard"]["served_file_sha256"], pc.PINNED_FILES["dashboard/data/dashboard.json"])
        self.assertEqual(manifest["dashboard"]["canonical_digest"], pc.IDENTITIES["dashboard_canonical_digest"])
        self.assertEqual(manifest["errors"], [])
        self.assertEqual(manifest["external"], [])
        self.assertEqual(len(manifest["screenshots"]), 5)
        self.assertEqual(set(tree(SCREENSHOTS_DIR)), {row["file"] for row in manifest["screenshots"]} | {"screenshots_manifest.json"})
        for row in manifest["screenshots"]:
            file = SCREENSHOTS_DIR / row["file"]
            self.assertFalse(file.is_symlink())
            png = file.read_bytes()
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(pc.sha256_file(file), row["sha256"])
            self.assertEqual(len(png), row["bytes"])
            self.assertEqual(int.from_bytes(png[16:20], "big"), row["image_pixels"]["width"])
            self.assertEqual(int.from_bytes(png[20:24], "big"), row["image_pixels"]["height"])

    def test_walkthrough_sources_contain_documented_cell_markers(self):
        for path in WALKTHROUGH_DIR.glob("walkthrough_0*.py"):
            self.assertGreaterEqual(path.read_text().count("# %%"), 4)

    def test_portfolio_markdown_links_resolve(self):
        for path in (ROOT / "reports").rglob("*.md"):
            for target in re.findall(r"\[[^\]]+\]\(([^\s)]+)\)", path.read_text()):
                parsed = urlsplit(target)
                if not parsed.scheme and parsed.path:
                    self.assertTrue((path.parent / unquote(parsed.path)).exists(), f"Broken link in {path.name}: {target}")

    def test_frozen_walkthrough_artifact_replays_byte_identically(self):
        self.assertTrue(FROZEN_DIR.is_dir(), "Delivered Phase 12 evidence must be present")
        replay = self.root / "replay"
        run_into(replay)
        self.assertEqual(tree(replay), tree(FROZEN_DIR))


if __name__ == "__main__":
    unittest.main()
