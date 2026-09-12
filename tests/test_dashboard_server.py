"""Offline tests for the dashboard-only local static server (no live socket)."""

import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dashboard_server", ROOT / "scripts/serve_dashboard.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class DashboardServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / "index.html").write_text("<h1>Dashboard</h1>")
        (self.root / "data").mkdir()
        (self.root / "data/dashboard.json").write_text('{"status":"limited_diagnostic"}')
        (self.root / ".env").write_text("do not serve this")
        self.handler = object.__new__(server.DashboardHandler)
        self.handler.dashboard_root = self.root
        self.handler.path = "/"
        self.handler.wfile = io.BytesIO()
        self.status = None
        self.headers = {}
        self.handler.send_response = self.response
        self.handler.send_error = lambda status, message: self.response(status)
        self.handler.send_header = lambda name, value: self.headers.update({name: value})
        self.handler.end_headers = lambda: None

    def response(self, status):
        self.status = status

    def test_root_resolves_to_index_without_listing(self):
        self.handler.do_GET()
        self.assertEqual(self.status, 200)
        self.assertIn(b"Dashboard", self.handler.wfile.getvalue())
        self.assertEqual(self.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("connect-src 'self'", self.headers["Content-Security-Policy"])

    def test_head_has_correct_length_and_no_body(self):
        self.handler.path = "/data/dashboard.json"
        self.handler.do_HEAD()
        self.assertEqual(self.status, 200)
        self.assertEqual(int(self.headers["Content-Length"]), (self.root / "data/dashboard.json").stat().st_size)
        self.assertEqual(self.handler.wfile.getvalue(), b"")

    def test_unlisted_traversal_and_directory_requests_rejected(self):
        for path in ("/.env", "/.git/config", "/data/", "/../index.html",
                     "/%2e%2e/.env", "/data/../index.html", "/data%2F..%2Findex.html",
                     "/README.md", "/data/secrets.json", "/%252e%252e/.env"):
            with self.subTest(path=path):
                self.handler.path = path
                self.handler.do_GET()
                self.assertEqual(self.status, 404)

    def test_payload_and_parent_symlinks_rejected(self):
        (self.root / "app.js").symlink_to(self.root / ".env")
        self.handler.path = "/app.js"
        self.assertIsNone(self.handler.asset())
        elsewhere = self.root / "public-copy"
        elsewhere.mkdir()
        (elsewhere / "dashboard.json").write_text("{}")
        original = self.root / "data"
        original.rename(self.root / "original-data")
        original.symlink_to(elsewhere, target_is_directory=True)
        self.handler.path = "/data/dashboard.json"
        self.assertIsNone(self.handler.asset())

    def test_mutation_methods_rejected(self):
        for method in ("do_POST", "do_PUT", "do_DELETE"):
            getattr(self.handler, method)()
            self.assertEqual(self.status, 405)
            self.assertEqual(self.handler.wfile.getvalue(), b"")

    def test_query_never_logged(self):
        self.handler.path = "/?token=sentinel-private-value"
        self.handler.command = "GET"
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            self.handler.log_message("%s", self.handler.path)
            self.handler.do_GET()
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(self.status, 200)

    def test_no_non_loopback_flag(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            server.main(["--host", "0.0.0.0"])


if __name__ == "__main__":
    unittest.main()
