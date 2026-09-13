"""Operator launcher for a private environment file and a clean child env."""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from vn_air.automation_environment import (  # noqa: E402
    OperatorEnvironmentError,
    ingestion_environment,
    read_operator_environment,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        values = read_operator_environment(args.env_file, checkout=ROOT)
        environment = ingestion_environment(os.environ, ROOT / "src")
        environment.update(values)
        output_root = args.output_root.absolute()
        if any(path.is_symlink() for path in (output_root, *output_root.parents)):
            raise OperatorEnvironmentError("operator_output_unsafe_path")
        output_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        output = output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        os.chdir(ROOT)
        os.execve(sys.executable, [sys.executable, "-B", "-m", "vn_air.cli", "automation",
                                  "run", "--execute", "--output-dir", str(output)], environment)
    except OperatorEnvironmentError as error:
        print(f"automation launcher: {error}", file=sys.stderr)
    except OSError:
        print("automation launcher: operator_launch_failed", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
