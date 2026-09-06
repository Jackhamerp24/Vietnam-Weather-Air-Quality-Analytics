"""Offline integrity checks for the committed-size research evidence and docs."""

import hashlib
import json
import os
import re
import subprocess
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/research/evidence"


class ResearchArtifactTests(unittest.TestCase):
    def test_markdown_local_links_and_references(self):
        paths = [ROOT / "README.md", *ROOT.glob("docs/**/*.md")]
        for path in paths:
            content = path.read_text(encoding="utf-8")
            references = dict(re.findall(r"^\[([^\]]+)\]:\s*(\S+)", content, re.MULTILINE))
            for reference in re.findall(r"\[[^\]]+\]\[([^\]]+)\]", content):
                self.assertIn(reference, references, f"Undefined reference in {path.name}")
            targets = re.findall(r"\[[^\]]+\]\(([^\s)]+)\)", content)
            for target in [*targets, *references.values()]:
                url = urlsplit(target)
                if not url.scheme and url.path:
                    self.assertTrue((path.parent / unquote(url.path)).exists(), f"Broken link: {path.name}: {target}")

    def test_open_meteo_capture_hashes(self):
        report = json.loads((EVIDENCE / "open_meteo_2026-09-07_system_ca.json").read_text())
        self.assertTrue(report["passed"])
        self.assertEqual(len(report["requests"]), 8)
        self.assertEqual(len(report["checks"]), 4)
        for request in report["requests"]:
            body = request["body_utf8"].encode("utf-8")
            self.assertEqual(hashlib.sha256(body).hexdigest(), request["body_sha256"])
            self.assertEqual(json.loads(body), request["response"])

    def test_failed_capture_is_not_success(self):
        report = json.loads((EVIDENCE / "open_meteo_2026-09-07.json").read_text())
        self.assertFalse(report["passed"])
        self.assertEqual(report["checks"], [])

    def test_openaq_extract_arithmetic_and_rights(self):
        report = json.loads((EVIDENCE / "openaq_qualification_2026-09-07.json").read_text())
        self.assertEqual(len(report["stations"]), 2)
        self.assertTrue(report["licence_metadata"]["redistributionAllowed"])
        for station in report["stations"]:
            audit = station["audit"]
            self.assertEqual(audit["unique_present_hours"] + audit["missing_hours"], audit["expected_hours"])
            self.assertAlmostEqual(audit["present_percent"], 100 * audit["unique_present_hours"] / audit["expected_hours"], places=4)
            self.assertEqual(len(station["first_24_enclosed_rows"]), 24)
            self.assertEqual(station["licenses"][0]["id"], 41)
            self.assertFalse(station["isMonitor"])

    def test_private_paths_are_ignored(self):
        result = subprocess.run(["git", "check-ignore", ".env", ".local/research.json"], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(set(result.stdout.splitlines()), {".env", ".local/research.json"})

    def test_public_text_has_no_trailing_whitespace(self):
        paths = [ROOT / "README.md", ROOT / ".env.example", ROOT / ".gitignore", ROOT / "pyproject.toml", ROOT / "requirements.lock", ROOT / "opencode.json",
                 *ROOT.glob("docs/**/*.md"), *ROOT.glob("scripts/*.py"), *ROOT.glob("tests/**/*.py"),
                 *ROOT.glob("src/vn_air/**/*.py"), *ROOT.glob("src/vn_air/**/*.sql"), *ROOT.glob("configs/*.json")]
        for path in paths:
            for number, line in enumerate(path.read_text().splitlines(), start=1):
                self.assertEqual(line, line.rstrip(), f"Trailing whitespace: {path.name}:{number}")

    def test_authorized_key_not_in_public_files(self):
        key = os.environ.get("OPENAQ_API_KEY")
        if not key:
            self.skipTest("Export OPENAQ_API_KEY for exact credential-leak check")
        result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True, check=True)
        for name in result.stdout.decode().split("\0"):
            if name:
                self.assertFalse(key.encode() in (ROOT / name).read_bytes(), f"Credential detected in {name}")

    def test_configured_database_credentials_not_in_public_files(self):
        uri = os.environ.get("DATABASE_URL")
        if not uri:
            self.skipTest("Export a password-bearing DATABASE_URL for exact credential exclusion")
        password = urlsplit(uri).password
        if password is None:
            self.skipTest("Export a password-bearing DATABASE_URL for exact credential exclusion")
        secrets = [uri, password, unquote(password)]
        names = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.decode().split("\0")
        for name in filter(None, names):
            body = (ROOT / name).read_bytes()
            self.assertFalse(any(value.encode() in body for value in secrets), f"Database credential detected in {name}")

    def test_supabase_mcp_is_project_scoped_and_read_only(self):
        config = json.loads((ROOT / "opencode.json").read_text())
        server = config["mcp"]["supabase-vietnam-weather"]
        url = urlsplit(server["url"])
        self.assertEqual(url.hostname, "mcp.supabase.com")
        parameters = dict(item.split("=", 1) for item in url.query.split("&"))
        self.assertEqual(parameters["project_ref"], "rrexplijhvdltxvvmxmi")
        self.assertEqual(parameters["read_only"], "true")
        self.assertEqual(set(unquote(parameters["features"]).split(",")), {"docs", "database", "debugging", "development"})
        self.assertNotIn("headers", server)


if __name__ == "__main__":
    unittest.main()
