#!/usr/bin/env python3
"""Serve only the reviewed static dashboard allowlist on loopback."""

import argparse
import http.server
import functools
from pathlib import Path
from urllib.parse import unquote, urlsplit


ALLOWED_FILES = {
    "index.html": "text/html; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "charts.js": "text/javascript; charset=utf-8",
    "data/dashboard.json": "application/json; charset=utf-8",
}


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    server_version = "VietnamAirDashboard/1.0"

    def __init__(self, *args, directory=None, **kwargs):
        self.dashboard_root = Path(directory).resolve()
        super().__init__(*args, **kwargs)

    def asset(self):
        request_path = unquote(urlsplit(self.path).path)
        name = "index.html" if request_path == "/" else request_path.removeprefix("/")
        if name not in ALLOWED_FILES or not request_path.startswith("/"):
            return None
        path = self.dashboard_root / name
        if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
            return None
        return path, ALLOWED_FILES[name]

    def serve_asset(self, head=False):
        asset = self.asset()
        if asset is None:
            self.send_error(404, "Dashboard asset not found")
            return
        path, mime = asset
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404, "Dashboard asset not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                         "connect-src 'self'; font-src 'self'; object-src 'none'; "
                         "base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_GET(self):
        self.serve_asset()

    def do_HEAD(self):
        self.serve_asset(head=True)

    def do_POST(self):
        self.send_error(405, "Dashboard is read-only")

    def do_PUT(self):
        self.send_error(405, "Dashboard is read-only")

    def do_DELETE(self):
        self.send_error(405, "Dashboard is read-only")

    def log_message(self, format, *args):
        # Requests can contain secret-bearing user-supplied paths or queries.
        # The static server intentionally does not log either.
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path,
                        default=Path(__file__).resolve().parents[1] / "dashboard")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")
    if args.directory.is_symlink():
        parser.error("dashboard directory must not be a symlink")
    root = args.directory.resolve()
    if not root.is_dir() or not (root / "index.html").is_file():
        parser.error("dashboard directory must contain index.html")
    handler = functools.partial(DashboardHandler, directory=root)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Dashboard available at http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
