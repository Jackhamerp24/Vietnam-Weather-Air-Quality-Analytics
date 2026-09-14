"""Walkthrough 04: dashboard bundle identity and reproducibility.

Verifies the public dashboard bundle byte identity and canonical digest,
cross-checks its provenance maps against the frozen phase SUCCESS files, and
prints the exact rebuild/serve commands. Produces no dashboard change.
"""

# %% Imports and artifact contract
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_common as pc

ID = "04_dashboard_and_reproducibility"
TITLE = "Dashboard bundle identity and local reproducibility"
COMMAND = pc.INDIVIDUAL_COMMAND.format(
    module="walkthrough_04_dashboard_and_reproducibility"
)

REBUILD_COMMAND = (
    "python3 -B scripts/build_dashboard.py --output /private/tmp/vietnam-air-replay.json"
)
COMPARE_COMMAND = "cmp dashboard/data/dashboard.json /private/tmp/vietnam-air-replay.json"
SERVE_COMMAND = "python3 -B scripts/serve_dashboard.py"

PHASE_KEYS = {
    5: "phase5",
    6: "phase6",
    7: "phase7",
    8: "phase8",
    9: "phase9",
}

PHASE_IDENTITIES = {
    5: "phase5_bundle_digest",
    6: "phase6_manifest_digest",
    7: "phase7_manifest_digest",
    8: "phase8_manifest_digest",
    9: "phase9_manifest_digest",
}


# %% Hash-verified projection
def build() -> tuple[dict, str]:
    checks: list[dict] = []
    bundle_path = pc.verify_file("dashboard/data/dashboard.json", checks)
    bundle = pc.read_json(bundle_path)

    canonical = pc.digest_without(bundle, "bundle_sha256")
    pc.require(
        bundle["bundle_sha256"] == canonical == pc.IDENTITIES["dashboard_canonical_digest"],
        "Dashboard canonical digest does not match the pinned identity",
    )

    provenance_checks = []
    for entry in bundle["provenance"]:
        phase = entry["phase"]
        artifact = pc.load_artifact(PHASE_KEYS[phase], checks)
        pc.require(
            entry["identity"] == pc.IDENTITIES[PHASE_IDENTITIES[phase]],
            f"Dashboard provenance identity mismatch for phase {phase}",
        )
        exceptions = {
            exception["file"]: exception
            for exception in entry.get("integrity_exceptions") or []
        }
        verified = 0
        for filename, declared in sorted(entry["files_sha256"].items()):
            if filename in exceptions:
                continue
            success_hash = artifact["success"]["files_sha256"].get(filename)
            pc.require(
                declared == success_hash,
                f"Dashboard provenance mismatch for phase {phase} {filename}",
            )
            verified += 1
        provenance_checks.append(
            {
                "phase": phase,
                "label": entry["label"],
                "directory": entry["directory"],
                "identity": entry["identity"],
                "hash_declarations_matched": verified,
                "integrity_exceptions": entry.get("integrity_exceptions") or [],
            }
        )

    hourly = bundle["hourly"]
    accepted = sum(1 for row in hourly if row["quality"] == "accepted")
    absent = sum(1 for row in hourly if row["quality"] == "absent")
    counts = {
        "hourly_rows": len(hourly),
        "hourly_accepted": accepted,
        "hourly_absent": absent,
        "daily_rows": len(bundle["daily"]),
        "qualified_daily_rows": sum(row["qualified_mean"] is not None for row in bundle["daily"]),
        "diurnal_rows": len(bundle["diurnal"]),
        "cams_modeled_days": len(bundle["cams_daily"]),
        "recorded_statistics_fits": len(bundle["statistics"]["results"]),
        "baseline_metric_cells": len(bundle["baselines"]["metrics"]),
        "ml_metric_cells": len(bundle["ml"]["metrics"]),
        "ml_comparisons": len(bundle["ml"]["comparisons"]),
    }
    pc.require(
        counts["hourly_rows"] == 4320
        and counts["hourly_accepted"] == 4191
        and counts["hourly_absent"] == 129
        and counts["daily_rows"] == 182
        and counts["qualified_daily_rows"] == 172
        and counts["ml_comparisons"] == 360,
        "Dashboard bundle counts do not match the frozen records",
    )
    statuses = {
        bundle["features"]["status"],
        bundle["baselines"]["status"],
        bundle["ml"]["status"],
    }
    pc.require(
        statuses == {"limited_diagnostic"},
        "Phase 7-9 dashboard statuses are not uniformly limited_diagnostic",
    )

    results = {
        "schema_version": bundle["schema_version"],
        "canonical_digest": bundle["bundle_sha256"],
        "file_sha256": checks[0]["sha256"],
        "counts": counts,
        "phase_status": {
            "features": bundle["features"]["status"],
            "baselines": bundle["baselines"]["status"],
            "ml": bundle["ml"]["status"],
        },
        "provenance": provenance_checks,
        "integrity_notes": bundle["meta"]["integrity_notes"],
        "daily_policy": bundle["meta"]["daily_policy"],
        "source_policy": bundle["meta"]["source_policy"],
        "commands": {
            "rebuild": REBUILD_COMMAND,
            "compare": COMPARE_COMMAND,
            "serve": SERVE_COMMAND,
            "browser_checks": (
                "node scripts/test_dashboard_ui.cjs http://127.0.0.1:8765/ "
                "<new-evidence-dir>"
            ),
            "screenshots": (
                "node scripts/capture_dashboard_screenshots.cjs "
                "http://127.0.0.1:8765/ <new-evidence-dir>"
            ),
        },
        "boundary": (
            "Loopback-only static server, read-only public JSON, no database "
            "API, no external assets, no model fitting in the browser."
        ),
    }

    markdown = render(results)
    payload = pc.base_payload(ID, COMMAND)
    payload["inputs"] = checks
    payload["status"] = "ok"
    payload["results"] = results
    return payload, markdown


# %% Markdown presentation
def render(results: dict) -> str:
    counts = results["counts"]
    lines = [
        f"# Walkthrough 04: {TITLE}",
        "",
        f"Command: `{COMMAND}`",
        "",
        "The dashboard is a local presentation of frozen Phase 5-9 artifacts. "
        "The browser fetches only the same-origin public JSON and static assets. "
        "It filters descriptive views; it does not refit statistics or models.",
        "",
        "## Bundle identity",
        "",
        pc.md_table(
            ["Identity", "SHA-256"],
            [
                ["Canonical bundle excluding the digest field", results["canonical_digest"]],
                ["JSON file bytes", results["file_sha256"]],
            ],
        ),
        "",
        "## Projected counts",
        "",
        pc.md_table(
            ["Dataset", "Rows"],
            [
                [
                    "Hourly PM2.5 grid",
                    f"{counts['hourly_rows']} "
                    f"({counts['hourly_accepted']} accepted, "
                    f"{counts['hourly_absent']} absent)",
                ],
                ["All local sensor-day rows (includes unqualified dates)", str(counts["daily_rows"])],
                ["Qualified full sensor-days", str(counts["qualified_daily_rows"])],
                ["Diurnal summaries", str(counts["diurnal_rows"])],
                ["CAMS modeled days", str(counts["cams_modeled_days"])],
                ["Recorded statistical fits", str(counts["recorded_statistics_fits"])],
                ["Baseline metric cells", str(counts["baseline_metric_cells"])],
                ["ML metric cells", str(counts["ml_metric_cells"])],
                ["ML comparison records", str(counts["ml_comparisons"])],
            ],
        ),
        "",
        "## Provenance cross-check",
        "",
        pc.md_table(
            ["Phase", "Artifact", "Identity (manifest/bundle digest)", "Hash declarations matched"],
            [
                [
                    str(entry["phase"]),
                    entry["label"],
                    entry["identity"],
                    str(entry["hash_declarations_matched"]),
                ]
                for entry in results["provenance"]
            ],
        ),
        "",
        "This walkthrough verifies the public bundle and SUCCESS.json bytes, "
        "then compares their hash declarations. It does not re-read each "
        "underlying payload; run the dashboard builder below for those checks. "
        "All three Phase 7-9 statuses remain "
        f"`{results['phase_status']['features']}`.",
        "",
        "## Reproduce locally",
        "",
        "```bash",
        results["commands"]["rebuild"],
        results["commands"]["compare"],
        results["commands"]["serve"],
        "```",
        "",
        f"Then open http://127.0.0.1:8765/. Browser verification and the Phase "
        f"12 screenshot set use the existing Playwright/Chrome runtime; see "
        f"`docs/portfolio_runbook.md`.",
        "",
        f"Boundary: {results['boundary']}",
        "",
        "## Documented integrity notes",
        "",
        *[f"- {note}" for note in results["integrity_notes"]],
        "",
        f"- Daily qualification: {results['daily_policy']}",
        f"- Sources: {results['source_policy']}",
        "",
    ]
    return "\n".join(lines)


# %% Command-line execution
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=TITLE)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    output_dir = pc.ensure_new_dir(Path(args.output_dir))
    payload, markdown = build()
    hashes = pc.write_artifacts(output_dir, ID, payload, markdown)
    print(f"OK {ID}: {len(payload['inputs'])} inputs verified")
    for name, value in sorted(hashes.items()):
        print(f"  {name} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
