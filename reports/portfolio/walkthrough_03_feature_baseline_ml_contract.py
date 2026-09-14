"""Walkthrough 03: Phase 7 availability policy, Phase 8 baselines, Phase 9 ML.

Explains why the frozen captured feature artifact, its baselines and its model
comparison are limited diagnostics, using only the pinned Phase 7-9 summaries.
"""

# %% Imports and artifact contract
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import portfolio_common as pc

ID = "03_feature_baseline_ml_contract"
TITLE = "Availability contract, baselines and model diagnostics"
COMMAND = pc.INDIVIDUAL_COMMAND.format(
    module="walkthrough_03_feature_baseline_ml_contract"
)


# %% Hash-verified projection
def build() -> tuple[dict, str]:
    checks: list[dict] = []
    phase7 = pc.load_artifact("phase7", checks)
    phase8 = pc.load_artifact("phase8", checks)
    phase9 = pc.load_artifact("phase9", checks)
    p7_summary_path = pc.payload(phase7, "phase_7_feature_summary.json", checks)
    p8_summary_path = pc.payload(phase8, "phase_8_baselines_summary.json", checks)
    p9_summary_path = pc.payload(phase9, "phase_9_model_summary.json", checks)
    p7 = pc.read_json(p7_summary_path)
    p8 = pc.read_json(p8_summary_path)
    p9 = pc.read_json(p9_summary_path)

    pc.expect_manifest_digest(p7, "phase7_manifest_digest")
    pc.expect_manifest_digest(p8, "phase8_manifest_digest")
    pc.expect_manifest_digest(p9, "phase9_manifest_digest")

    m7, m8, m9 = p7["manifest"], p8["manifest"], p9["manifest"]
    pc.require(
        m7["feature_version"] == pc.IDENTITIES["phase7_feature_version"],
        "Unexpected Phase 7 feature version",
    )
    pc.require(
        m8["baseline_version"] == pc.IDENTITIES["phase8_baseline_version"],
        "Unexpected Phase 8 baseline version",
    )
    pc.require(
        m9["model_version"] == pc.IDENTITIES["phase9_model_version"]
        and m9["revision"] == "comparison_hardened",
        "Unexpected Phase 9 model version or revision",
    )
    pc.require(
        m8["input_feature_version"] == m7["feature_version"]
        and m8["input_manifest_sha256"] == p7["manifest_sha256"]
        and m8["input_summary_sha256"] == pc.sha256_file(p7_summary_path),
        "Phase 8 is not bound to the consumed Phase 7 artifact",
    )
    pc.require(
        m9["phase7"]["manifest_sha256"] == p7["manifest_sha256"]
        and m9["phase8_reference"]["manifest_sha256"] == p8["manifest_sha256"],
        "Phase 9 is not bound to the Phase 7/8 artifact identities",
    )
    pc.require(
        m7["split"] == m8["split"],
        "Phase 7 and Phase 8 split contracts differ",
    )

    baseline_status = Counter(metric["metric_status"] for metric in m8["metrics"])
    baseline_reasons = Counter(
        metric["metric_reason"]
        for metric in m8["metrics"]
        if metric["metric_status"] == "unavailable"
    )
    model_status = Counter(
        (metric["model_family"], metric["metric_status"]) for metric in m9["metrics"]
    )

    results = {
        "phase7": {
            "feature_version": m7["feature_version"],
            "status": m7["status"],
            "status_missing_families": m7["status_missing_families"],
            "availability_basis": m7["availability_basis"],
            "boundary_mode": m7["boundary"]["mode"],
            "horizons": m7["horizons"],
            "origin_count": m7["origin_count"],
            "origin_start": m7["origin_start"],
            "origin_end": m7["origin_end"],
            "warmup_hours": m7["warmup_hours"],
            "history_start": m7["history_start"],
            "split": m7["split"],
            "counts": m7["counts"],
            "target_contract": m7["target_contract"],
            "prospective_collection_period_required": m7[
                "prospective_collection_period_required"
            ],
            "config_validation": m7["config_validation"],
            "input_integrity_verified": m7["input_integrity"]["verified"],
        },
        "phase8": {
            "baseline_version": m8["baseline_version"],
            "status": m8["status"],
            "status_reasons": m8["status_reasons"],
            "baseline_definitions": m8["baseline_definitions"],
            "metric_cells": len(m8["metrics"]),
            "available_cells": baseline_status["available"],
            "unavailable_cells": baseline_status["unavailable"],
            "unavailable_reasons": dict(sorted(baseline_reasons.items())),
            "metric_scope": sorted(
                {metric["metric_scope"] for metric in m8["metrics"]}
            ),
            "test_selection_used": m8["test_selection_used"],
            "input_rows": m8["input_rows"],
        },
        "phase9": {
            "model_version": m9["model_version"],
            "revision": m9["revision"],
            "status": m9["status"],
            "status_reasons": m9["status_reasons"],
            "counts": m9["counts"],
            "feature_sets": m9["feature_sets"],
            "model_families": m9["model_families"],
            "target_transforms": m9["target_transforms"],
            "scopes": m9["scopes"],
            "selection_policy": m9["selection_policy"],
            "fit_partitions": m9["fit_partitions"],
            "metric_status_by_family": {
                f"{family}:{status}": count
                for (family, status), count in sorted(model_status.items())
            },
            "test_selection_used": m9["test_selection_used"],
            "prospective_collection_period_required": m9[
                "prospective_collection_period_required"
            ],
        },
        "shared_split": m7["split"],
        "why_limited": [
            "The frozen historical window contains no evidence timestamp that "
            "predates a forecast origin, so captured PM-history and "
            "forecast-weather feature families are empty.",
            "Missing measured PM2.5 is never replaced with ERA5, CAMS or "
            "assumed-lag values.",
            "Calendar-only diagnostics can still train; no score is fabricated "
            "for an unavailable cell.",
            "A prospective collection period is required before "
            "captured-feature baseline or model evaluation exists.",
        ],
    }

    markdown = render(results)
    payload = pc.base_payload(ID, COMMAND)
    payload["inputs"] = checks
    payload["status"] = "ok"
    payload["results"] = results
    return payload, markdown


# %% Markdown presentation
def render(results: dict) -> str:
    p7, p8, p9 = results["phase7"], results["phase8"], results["phase9"]
    split = results["shared_split"]
    counts = p7["counts"]
    lines = [
        f"# Walkthrough 03: {TITLE}",
        "",
        f"Command: `{COMMAND}`",
        "",
        "Phase 7-9 artifacts are frozen limited diagnostics. This walkthrough "
        "separates what is implemented and tested from what the frozen window "
        "can actually evaluate.",
        "",
        "## Phase 7 availability contract",
        "",
        pc.md_table(
            ["Item", "Value"],
            [
                ["Feature version", p7["feature_version"]],
                ["Availability basis", p7["availability_basis"]],
                ["Boundary mode", p7["boundary_mode"]],
                ["Horizons", ", ".join(f"{h}h" for h in p7["horizons"])],
                [
                    "Origins",
                    f"{p7['origin_count']} hourly UTC origins "
                    f"({p7['origin_start']} to {p7['origin_end']})",
                ],
                ["Warm-up", f"{p7['warmup_hours']}h from {p7['history_start']}"],
                ["Status", p7["status"]],
                [
                    "Missing families",
                    ", ".join(p7["status_missing_families"]),
                ],
                [
                    "Target contract",
                    p7["target_contract"]["target_end"]
                    + "; "
                    + p7["target_contract"]["target_row"],
                ],
                [
                    "Prospective collection required",
                    str(p7["prospective_collection_period_required"]),
                ],
            ],
        ),
        "",
        "Feature rows "
        f"{counts['rows']}: split train {counts['split']['train']}, validation "
        f"{counts['split']['validation']}, test {counts['split']['test']}; "
        f"purged {counts['purged_rows']} "
        f"({counts['purge_reasons']['target_reaches_validation']} "
        f"validation-reaching, "
        f"{counts['purge_reasons']['target_reaches_test']} test-reaching). "
        f"Targets available {counts['target_available']}, absent "
        f"{counts['target_reasons']['target_absent']}. Shared chronological "
        f"split: validation {split['validation_start']}, test "
        f"{split['test_start']}.",
        "",
        f"Usable captured evidence: PM-history origins "
        f"{counts['pm_available_origin_count']} and "
        f"forecast-weather origins {counts['weather_available_origin_count']}; "
        f"rows with any data feature {counts['rows_with_any_data_feature']}. "
        f"Input-table hash verification: {p7['input_integrity_verified']}.",
        "",
        "## Phase 8 baselines",
        "",
        pc.md_table(
            ["Baseline", "Role", "Kind"],
            [
                [
                    definition["baseline_id"],
                    definition["role"],
                    definition["kind"],
                ]
                for definition in p8["baseline_definitions"]
            ],
        ),
        "",
        f"Status: {p8['status']} ({', '.join(p8['status_reasons'])}). "
        f"Metric cells {p8['metric_cells']}: {p8['available_cells']} available "
        f"and {p8['unavailable_cells']} unavailable with reason "
        f"`{', '.join(p8['unavailable_reasons'])}`. All cells are "
        f"{', '.join(p8['metric_scope'])}; test selection used: "
        f"{p8['test_selection_used']}. The available cells are train-only "
        "local-hour calendar diagnostics, not forecast-skill estimates, and no "
        "score was fabricated for an unavailable cell.",
        "",
        "## Phase 9 model comparison",
        "",
        f"Model version {p9['model_version']} (revision {p9['revision']}), "
        f"status {p9['status']} ({', '.join(p9['status_reasons'])}).",
        "",
        pc.md_table(
            ["Item", "Value"],
            [
                ["Feature sets", ", ".join(p9["feature_sets"])],
                ["Families", ", ".join(p9["model_families"])],
                ["Target transforms", ", ".join(p9["target_transforms"])],
                ["Scopes", ", ".join(p9["scopes"])],
                [
                    "Model instances",
                    f"{p9['counts']['trained_instances']} trained, "
                    f"{p9['counts']['unavailable_instances']} unavailable of "
                    f"{p9['counts']['model_instances']} declared",
                ],
                [
                    "Metric cells",
                    f"{p9['counts']['available_metric_cells']} available, "
                    f"{p9['counts']['unavailable_metric_cells']} unavailable of "
                    f"{p9['counts']['metric_cells']}",
                ],
                ["Prediction rows", str(p9["counts"]["prediction_rows"])],
                ["Comparison records", str(p9["counts"]["comparison_records"])],
                [
                    "Selection",
                    "validation only; test scored once after the "
                    "train-plus-validation refit",
                ],
            ],
        ),
        "",
        "The trained instances are calendar-only Ridge/tree diagnostics. Every "
        "history-only, weather-only and history_weather cell is unavailable "
        "with an explicit reason; no ERA5, CAMS, assumed-lag or target value "
        "entered a design matrix, and test was never used for selection.",
        "",
        "## Why the artifacts are limited diagnostics",
        "",
        *[f"- {reason}" for reason in results["why_limited"]],
        "",
        "Labels: Phase 8-9 metric outputs are descriptive_only; Phase 7-9 "
        "overall status is limited_diagnostic until a prospective captured "
        "collection period exists.",
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
