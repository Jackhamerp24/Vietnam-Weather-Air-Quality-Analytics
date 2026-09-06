"""Run integration tests in a disposable socket-only PostgreSQL cluster.

Never reads DATABASE_URL or touches the existing PostgreSQL service. PostgreSQL
15+ server binaries must be on PATH. --temp-parent must exist; choose a short
private path so Unix socket names fit the OS limit.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlencode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp-parent", type=Path)
    args = parser.parse_args()
    binaries = {}
    for name in ("initdb", "pg_ctl", "createdb"):
        executable = shutil.which(name)
        if executable is None:
            parser.error("initdb, pg_ctl and createdb must be available on PATH")
        binaries[name] = executable
    if args.temp_parent is not None and not args.temp_parent.is_dir():
        parser.error("Temporary parent must exist")
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="vnpg_", dir=args.temp_parent) as directory:
        base = Path(directory)
        data, socket = base / "d", base / "s"
        socket.mkdir(mode=0o700)
        if len(str(socket).encode()) + 20 >= 104:
            parser.error("Temporary parent path is too long for PostgreSQL Unix sockets")
        subprocess.run([binaries["initdb"], "-D", str(data), "--auth-local=trust", "--auth-host=reject", "--username=vn_test", "--encoding=UTF8", "--no-locale"], check=True, capture_output=True, text=True)
        started = False
        try:
            subprocess.run([binaries["pg_ctl"], "-D", str(data), "-l", str(base / "postgres.log"), "-o", f"-k {socket} -c listen_addresses='' -c fsync=off", "-w", "start"], check=True, capture_output=True, text=True)
            started = True
            subprocess.run([binaries["createdb"], "--host", str(socket), "--username=vn_test", "vn_air_test"], check=True)
            env = os.environ.copy()
            env.pop("DATABASE_URL", None)
            env["VN_AIR_TEST_DATABASE_URL"] = "postgresql+psycopg://vn_test@/vn_air_test?" + urlencode({"host": str(socket)})
            result = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests/integration", "-v"], cwd=root, env=env)
            return result.returncode
        finally:
            if started:
                subprocess.run([binaries["pg_ctl"], "-D", str(data), "-m", "fast", "-w", "stop"], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    sys.exit(main())
