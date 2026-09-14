"""Run the four Phase 12 portfolio walkthroughs into a new output directory.

Each walkthrough verifies pinned artifact hashes before presenting a value.
The combined manifest is path-independent, so re-running into a different new
directory yields byte-identical files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_common as pc
import walkthrough_01_data_quality_and_eda as w01
import walkthrough_02_sensor_associations as w02
import walkthrough_03_feature_baseline_ml_contract as w03
import walkthrough_04_dashboard_and_reproducibility as w04

MODULES = [w01, w02, w03, w04]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 12 portfolio walkthroughs")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    output_dir = pc.ensure_new_dir(Path(args.output_dir))

    manifest = {
        "walkthrough_version": pc.WALKTHROUGH_VERSION,
        "command": pc.RUNNER_COMMAND,
        "frozen_window": pc.FROZEN_WINDOW,
        "walkthroughs": [],
        "files": {},
        "status": "ok",
    }

    built = [(module, *module.build()) for module in MODULES]
    for module, payload, markdown in built:
        hashes = pc.write_artifacts(output_dir, module.ID, payload, markdown)
        manifest["files"].update(hashes)
        manifest["walkthroughs"].append(
            {
                "id": module.ID,
                "title": module.TITLE,
                "status": payload["status"],
                "inputs": payload["inputs"],
                "outputs": hashes,
            }
        )
        print(f"OK {module.ID}: {len(payload['inputs'])} inputs verified")

    manifest["files"] = {
        name: manifest["files"][name] for name in sorted(manifest["files"])
    }
    manifest_path = output_dir / "manifest.json"
    pc.write_text_new(
        manifest_path, json.dumps(manifest, sort_keys=True, indent=2, allow_nan=False) + "\n"
    )
    manifest_hash = pc.sha256_file(manifest_path)
    print(f"manifest.json {manifest_hash}")
    print(f"wrote {len(manifest['files']) + 1} files to a new evidence directory")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
