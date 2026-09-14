"""Walkthrough 02: pre-registered Phase 6 sensor associations.

Presents the adjusted primary estimands, the Benjamini-Hochberg secondary
family and the declared sensitivities with their inference labels. Reads only
the pinned corrected Phase 6 artifact.
"""

# %% Imports and artifact contract
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_common as pc

ID = "02_sensor_associations"
TITLE = "Pre-registered weather-PM2.5 sensor associations"
COMMAND = pc.INDIVIDUAL_COMMAND.format(module="walkthrough_02_sensor_associations")

PRIMARY_FITS = [
    "H1_pooled_log1p_b1_pairwise_complete",
    "H2_pooled_log1p_b1_pairwise_complete",
    "H3_shared_log1p_b1",
]
PRIMARY_QUESTIONS = {
    "H1": "Within-sensor PM2.5 vs wind speed (adjusted)",
    "H2": "Within-sensor PM2.5 vs relative humidity (adjusted)",
    "H3": "OceanPark minus CMT8 on shared accepted hours",
}


def optional_float(value: str) -> float | None:
    return float(value) if value else None


def row_fields(row: dict) -> dict:
    return {
        "fit_id": row["fit_id"],
        "hypothesis": row["hypothesis"],
        "estimand": row["estimand"],
        "exposure": row["exposure"],
        "scale": row["scale"],
        "scope": row["scope"],
        "block_days": int(row["block_days"]),
        "weather_case": row["weather_case"],
        "n": int(row["n"]),
        "estimate": float(row["estimate"]),
        "ci_low": optional_float(row["ci_low"]),
        "ci_high": optional_float(row["ci_high"]),
        "p_value": optional_float(row["p_value"]),
        "p_value_adjusted": optional_float(row["p_value_adjusted"]),
        "inference": row["inference"],
    }


def select(rows: list[dict], **conditions) -> list[dict]:
    selected = []
    for row in rows:
        if all(row[key] == value for key, value in conditions.items()):
            selected.append(row)
    return selected


# %% Hash-verified projection
def build() -> tuple[dict, str]:
    checks: list[dict] = []
    phase6 = pc.load_artifact("phase6", checks)
    summary_path = pc.payload(phase6, "phase_6_statistics_summary.json", checks)
    estimates_path = pc.payload(phase6, "phase_6_estimates.csv", checks)
    bootstrap_path = pc.payload(phase6, "phase_6_bootstrap_summary.csv", checks)
    summary = pc.read_json(summary_path)
    estimates = pc.read_csv_rows(estimates_path)
    bootstrap = pc.read_csv_rows(bootstrap_path)

    pc.expect_manifest_digest(summary, "phase6_manifest_digest")
    manifest = summary["manifest"]
    pc.require(
        manifest["stats_version"] == pc.IDENTITIES["phase6_stats_version"],
        "Unexpected Phase 6 statistics version",
    )
    pc.require(
        manifest["phase5_bundle_sha256"] == pc.IDENTITIES["phase5_bundle_digest"],
        "Phase 6 manifest is not bound to the frozen Phase 5 bundle",
    )
    pc.require(
        pc.same_timestamp(manifest["start"], pc.FROZEN_WINDOW["start"])
        and pc.same_timestamp(manifest["end"], pc.FROZEN_WINDOW["end"]),
        "Phase 6 window does not match the frozen boundary",
    )
    pc.require(
        manifest["reconciliation"]["accepted_rows"] == 4191
        and manifest["reconciliation"]["shared_accepted_hours"] == 2035,
        "Phase 6 reconciliation does not match the frozen counts",
    )

    by_fit = {row["fit_id"]: row for row in estimates}
    pc.require(len(estimates) == 31, "Unexpected Phase 6 fit count")
    primary = [row_fields(by_fit[fit_id]) for fit_id in PRIMARY_FITS]
    for entry in primary:
        if entry["hypothesis"] in {"H1", "H2"}:
            pc.require(
                entry["inference"] == "inferential",
                f"{entry['fit_id']} is not labelled inferential",
            )
        else:
            pc.require(
                entry["inference"] == "exploratory",
                f"{entry['fit_id']} is not labelled exploratory",
            )

    secondary_rows = select(
        estimates,
        family="secondary",
        scope="pooled",
        scale="log1p",
        block_days="1",
        weather_case="pairwise_complete",
    )
    secondary_rows.sort(key=lambda row: row["fit_id"])
    pc.require(len(secondary_rows) == 5, "Unexpected secondary family size")
    secondary = [row_fields(row) for row in secondary_rows]
    for entry in secondary:
        pc.require(
            entry["inference"] == "inferential",
            f"{entry['fit_id']} is not a labelled BH family member",
        )

    sensitivities = {}
    for key, conditions in {
        "raw_scale_primary": {
            "hypothesis": "H1",
            "scale": "raw",
            "block_days": "1",
            "weather_case": "pairwise_complete",
        },
        "raw_scale_humidity": {
            "hypothesis": "H2",
            "scale": "raw",
            "block_days": "1",
            "weather_case": "pairwise_complete",
        },
        "two_day_blocks_h1": {
            "fit_id": "H1_pooled_log1p_b2_pairwise_complete",
        },
        "two_day_blocks_h2": {
            "fit_id": "H2_pooled_log1p_b2_pairwise_complete",
        },
        "seven_day_blocks_h1": {
            "fit_id": "H1_pooled_log1p_b7_pairwise_complete",
        },
        "complete_weather_h1": {
            "fit_id": "H1_pooled_log1p_b1_complete_weather",
        },
        "complete_weather_h2": {
            "fit_id": "H2_pooled_log1p_b1_complete_weather",
        },
        "extreme_rule_h1": {
            "fit_id": "H1_pooled_log1p_b1_pairwise_complete_excl_extreme",
        },
    }.items():
        matches = select(estimates, **conditions)
        pc.require(
            len(matches) == 1, f"Sensitivity selection failed for {key}"
        )
        sensitivities[key] = row_fields(matches[0])

    bootstrap_by_fit = {row["fit_id"]: row for row in bootstrap}
    pc.require(len(bootstrap) == 31, "Unexpected bootstrap summary size")
    h1_bootstrap = bootstrap_by_fit["H1_pooled_log1p_b1_pairwise_complete"]

    results = {
        "stats_version": manifest["stats_version"],
        "manifest_digest": summary["manifest_sha256"],
        "phase5_bundle_digest": manifest["phase5_bundle_sha256"],
        "primary": primary,
        "primary_questions": PRIMARY_QUESTIONS,
        "adjustments": manifest["adjustments"],
        "secondary": secondary,
        "sensitivities": sensitivities,
        "design": {
            "seed": manifest["seed"],
            "replicates": manifest["replicates"],
            "block_days": manifest["block_days"],
            "bootstrap_draw_policy": manifest["bootstrap_draw_policy"],
            "gate_method": manifest["gate_method"],
            "gate_thresholds": manifest["gate_thresholds"],
            "independent_block_counts": manifest["independent_block_counts"],
            "h1_pooled_bootstrap": {
                "candidate_windows": int(h1_bootstrap["candidate_windows"]),
                "nonempty_independent_blocks": int(
                    h1_bootstrap["nonempty_independent_blocks"]
                ),
                "eligible_independent_blocks": int(
                    h1_bootstrap["eligible_independent_blocks"]
                ),
                "sampled_dates_per_replicate": int(
                    h1_bootstrap["sampled_dates_per_replicate"]
                ),
                "usable_replicates": int(h1_bootstrap["usable_replicates"]),
                "skipped_replicates": int(h1_bootstrap["skipped_replicates"]),
            },
            "extreme_review": manifest["extreme_review"],
        },
        "scope_statement": (
            "Sensor-level associations over one frozen 90-day window at two "
            "non-reference low-cost sites; not city-wide exposure, causal "
            "effects or forecast skill."
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
    primary_rows = []
    for entry in results["primary"]:
        primary_rows.append(
            [
                entry["hypothesis"],
                results["primary_questions"][entry["hypothesis"]],
                str(entry["n"]),
                pc.fmt(entry["estimate"]),
                f"[{pc.fmt(entry['ci_low'])}, {pc.fmt(entry['ci_high'])}]",
                pc.fmt(entry["p_value"]),
                pc.fmt(entry["p_value_adjusted"])
                if entry["p_value_adjusted"] is not None else "not applicable",
                entry["inference"],
            ]
        )
    secondary_rows = [
        [
            entry["exposure"],
            pc.fmt(entry["estimate"]),
            f"[{pc.fmt(entry['ci_low'])}, {pc.fmt(entry['ci_high'])}]",
            pc.fmt(entry["p_value"]),
            pc.fmt(entry["p_value_adjusted"]),
        ]
        for entry in results["secondary"]
    ]
    sensitivity_rows = [
        [
            key,
            pc.fmt(entry["estimate"]),
            f"[{pc.fmt(entry['ci_low'])}, {pc.fmt(entry['ci_high'])}]"
            if entry["ci_low"] is not None
            else "point estimate only (gate)",
            entry["inference"],
        ]
        for key, entry in sorted(results["sensitivities"].items())
    ]
    lines = [
        f"# Walkthrough 02: {TITLE}",
        "",
        f"Command: `{COMMAND}`",
        "",
        "Pre-registration: hypotheses, estimands, adjustment set, block policy, "
        "seed, multiple-testing rules and the extreme-value review rule were "
        "fixed before any estimate was computed (Phase 6 plan and the "
        "2026-09-09 correction addendum). The corrected artifact is "
        "`phase_6_statistics_2026-09-09_corrected/`.",
        "",
        "## H1/H2 primary family and H3 exploratory contrast (log1p, 1-day blocks)",
        "",
        pc.md_table(
            [
                "Hypothesis",
                "Question",
                "n (sensor-hours)",
                "Estimate",
                "95% interval",
                "Raw p",
                "Holm-adjusted p",
                "Label",
            ],
            primary_rows,
        ),
        "",
        "H1/H2 use pairwise-complete weather rows and report the adjusted change "
        "in log1p(PM2.5) per one analysis-window standard deviation of the "
        "exposure. Holm adjustment covers H1 and H2; H1 remains significant "
        "at 0.05 and H2 does not. H3 compares OceanPark minus CMT8 on "
        "2,035 shared hours (4,070 sensor-hours), with temporal adjustment but "
        "no weather exposure or multiple-testing adjustment. Its p-value and "
        "interval remain exploratory.",
        "",
        "## Secondary family (pooled, BH-adjusted)",
        "",
        pc.md_table(
            ["Exposure", "Estimate", "95% interval", "Raw p", "BH-adjusted p"],
            secondary_rows,
        ),
        "",
        "Only cloud cover survives Benjamini-Hochberg FDR at 0.05. These are "
        "pre-declared family members labelled inferential after adjustment; the "
        "raw p-values alone are not findings.",
        "",
        "## Declared sensitivities (exploratory unless noted)",
        "",
        pc.md_table(["Sensitivity", "Estimate", "95% interval", "Label"], sensitivity_rows),
        "",
        "Seven-day blocks are descriptive-only by the pre-declared gate "
        "(13 non-overlapping partitions < 30 non-empty / 20 eligible).",
        "",
        "## Uncertainty design",
        "",
        f"- Moving-block bootstrap over Vietnam local calendar days: "
        f"{results['design']['replicates']} replicates, seed "
        f"{results['design']['seed']}, block lengths "
        f"{results['design']['block_days']} days.",
        f"- H1 pooled bootstrap: {results['design']['h1_pooled_bootstrap']['usable_replicates']} "
        f"usable replicates, {results['design']['h1_pooled_bootstrap']['skipped_replicates']} "
        f"skipped, {results['design']['h1_pooled_bootstrap']['sampled_dates_per_replicate']} "
        "sampled dates per replicate.",
        f"- Gate: at least {results['design']['gate_thresholds']['min_nonempty_blocks']} "
        f"non-empty and {results['design']['gate_thresholds']['min_eligible_blocks']} "
        "eligible non-overlapping partitions; one-day blocks give 91/86 "
        "non-empty/eligible partitions.",
        "- Adjustments: Holm over the two primary p-values; Benjamini-Hochberg "
        "over the five secondary p-values.",
        "",
        f"Scope: {results['scope_statement']}",
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
