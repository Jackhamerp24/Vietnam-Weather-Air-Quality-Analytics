"""Phase 7 artifact writers: summary JSON, feature/target/lineage CSVs, assumptions, SUCCESS hashes."""

import hashlib
import json
from pathlib import Path

from vn_air.eda_output import write_csv
from vn_air.features import sig
from vn_air.quality import digest

SUMMARY_NAME = "phase_7_feature_summary.json"
FEATURES_NAME = "phase_7_features.csv"
TARGETS_NAME = "phase_7_targets.csv"
LINEAGE_NAME = "phase_7_lineage.csv"
ASSUMPTIONS_NAME = "phase_7_assumptions.md"
SUCCESS_NAME = "SUCCESS.json"


def rounded(row):
    return {key: sig(value) if isinstance(value, float) else value for key, value in row.items()}


def assumptions_markdown(result):
    manifest = result["manifest"]
    counts = manifest["counts"]
    boundary = manifest["boundary"]
    lines = [
        "# Phase 7 Features: Assumptions and Limitations", "",
        "Availability-aware, leakage-safe feature construction replayed from a frozen input bundle.",
        "No model is trained; no forecast-skill, causal, city-wide, operational or health claim is supported.", "",
        "## Frozen boundary", "",
        f"- Input bundle digest: `{manifest['bundle_sha256']}` (file SHA-256 `{manifest['bundle_file_sha256']}`)",
        f"- Boundary mode `{boundary['mode']}`; frozen-boundary assertion applied: {boundary['frozen_boundary_applied']}",
        f"- Cutoff {manifest['cutoff']}; origin/target window {manifest['start']} to {manifest['end']}",
        f"- Warm-up history from {manifest['history_start']} ({manifest['warmup_hours']} hours before the origin window); pre-window rows support the lag/trailing catalog and are never targets",
        f"- Feature version `{manifest['feature_version']}`; availability basis `{manifest['availability_basis']}`"
        + (f" with assumed lag {manifest['availability_assumption']} hours" if manifest["availability_assumption"] is not None else ""),
        f"- Horizons {manifest['horizons']} hours; origins {manifest['origin_start']} to {manifest['origin_end']} ({manifest['origin_count']} hourly origins)",
        f"- Config validation `{manifest['config_validation']['mode']}` (reviewed digest `{manifest['config_validation']['reviewed_sha256']}`); forecast model key `{manifest['config_validation']['forecast_model_key']}`",
        f"- Status: `{manifest['status']}`; missing families {json.dumps(manifest['status_missing_families'])}"
        + ("; a prospective collection period is required before captured availability exists" if manifest["prospective_collection_period_required"] else ""), "",
        "## Availability policy", "",
        f"- Captured: {manifest['availability_policy']['captured']}",
        f"- Assumed: {manifest['availability_policy']['assumed']}",
        f"- {manifest['availability_policy']['fallback']}",
        f"- {manifest['availability_policy']['backfill_warning']}", "",
        "## Source policy", "",
        f"- Target and PM history: {manifest['source_policy']['target_and_pm_history']}",
        f"- Captured weather: {manifest['source_policy']['captured_weather']}",
        f"- Excluded from the captured matrix: {manifest['source_policy']['excluded_from_captured_matrix']}",
        f"- {manifest['source_policy']['no_substitution']}", "",
        "## Target contract", "",
        f"- {manifest['target_contract']['target_end']}; {manifest['target_contract']['target_start']}",
        f"- {manifest['target_contract']['target_row']}",
        f"- {manifest['target_contract']['target_lookup']}",
        f"- {manifest['target_contract']['storage']}", "",
        "## Catalog", "",
        f"- PM lags (hours): {manifest['catalog']['pm_lag_hours']}",
        f"- Trailing windows (hours): {manifest['catalog']['trailing_hours']}; {manifest['catalog']['trailing_means']}; {manifest['catalog']['trailing_std']}",
        f"- Weather features use the `{manifest['catalog']['weather_prefix']}` prefix over variables {', '.join(manifest['weather_variables'])}; {manifest['catalog']['wind_direction']}",
        "- Calendar features (origin and target local date/hour/weekday, Asia/Ho_Chi_Minh) are deterministic facts, not measurements.", "",
        "## Chronological split", "",
        f"- Shared across both sensors and both horizons: train 60%, validation 20%, untouched test 20%.",
        f"- Validation starts {manifest['split']['validation_start']}; test starts {manifest['split']['test_start']}.",
        f"- Purged origins (target interval reaches the next period): {counts['purged_rows']} of {counts['rows']} rows; reasons {json.dumps(counts['purge_reasons'], sort_keys=True)}.",
        "- Test rows are never purged and test-derived statistics are not used for feature decisions.", "",
        "## Row accounting", "",
        f"- Feature rows: {counts['rows']}; by split {json.dumps(counts['split'], sort_keys=True)}",
        f"- PM available origins: {counts['pm_available_origin_count']}; weather available origins: {counts['weather_available_origin_count']}",
        f"- Rows with any data feature: {counts['rows_with_any_data_feature']}; rows with a complete data-feature set: {counts['rows_with_complete_data_feature_set']}",
        f"- Rows with full 72h lag coverage: {counts['rows_with_full_lag_coverage']}",
        f"- Warm-up selected rows by sensor: {json.dumps(manifest['warmup_selected_rows_by_sensor'], sort_keys=True)}",
        f"- Targets available: {counts['target_available']}; reasons {json.dumps(counts['target_reasons'], sort_keys=True)}",
        f"- PM history reasons {json.dumps(counts['pm_reasons'], sort_keys=True)}",
        f"- Weather reasons {json.dumps(counts['weather_reasons'], sort_keys=True)}",
        f"- Weather values missing or not accepted: {counts['weather_missing_values']}; alignment mismatches rejected: {counts['weather_alignment_rejected']}",
        f"- Snapshot identity rejections: {json.dumps(manifest['snapshot_rejections'], sort_keys=True)}",
        f"- Measurement rows never eligible at any origin: {manifest['measurement_rows_never_eligible']}",
        f"- Forecast snapshots never eligible at any origin: {manifest['forecast_snapshots_never_eligible']}",
        f"- Ambiguous-vintage rejections (assumed mode, unknown run initialization): {manifest['ambiguous_vintage_rejections']}",
        f"- Rows rejected for future evidence: {manifest['future_evidence_rejections']} (the builder stops the run on any violation)", "",
        "## Assumptions", "",
        "- Captured eligibility is a conservative evidence-timestamp policy; the schema has no exact transaction commit time.",
        "- Under the assumed basis, `feature_available_through` is the assumed availability horizon (event time + declared lag), not evidence time; later backfill storage timestamps remain an explicit limitation.",
        "- Overlapping forecast snapshots are never averaged; one deterministic vintage is selected per location/origin after product, domain, data-kind, purpose, model-key, location, requested-coordinate and response-success checks.",
        "- Wind direction enters only as sin/cos components; raw direction is not a linear feature.",
        "- Gaps are never bridged: exact lags require exact timestamps, strict trailing windows require every expected hour, and row position is never a proxy for elapsed time.",
        "- Temporal support validates both the support class and the period_start alignment; mismatched values are rejected as unaligned.",
        "- Unaccepted target values are stored as null labels with explicit reasons; target identity, quality and source timestamps remain for audit.",
        "- Floating-point feature values are rounded to 12 significant digits for deterministic replay; leakage checks run on unrounded values.", "",
        "## Limitations", ""]
    lines.extend(f"- {item}" for item in result["manifest"]["limitations"])
    lines += ["", "## Attribution", "",
        "OpenAQ; AirGradient; Thomas Versteeg (CMT8); Open-Meteo. See docs/verification/phase_7.md for the",
        "verification record and phase_7_plan.md for the contract.", ""]
    return "\n".join(lines)


def write_outputs(output_dir, result):
    if output_dir.exists() or not output_dir.parent.is_dir():
        raise ValueError("Features output directory must be new with an existing parent")
    output_dir.mkdir(mode=0o700)
    summary = {"purpose": "Phase 7 availability-aware, leakage-safe features; no model training and no operational forecast claim",
               "manifest": result["manifest"], "manifest_sha256": result["manifest_sha256"]}
    with (output_dir / SUMMARY_NAME).open("x", encoding="utf-8") as handle:
        json.dump(summary, handle, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        handle.write("\n")
    write_csv(output_dir / FEATURES_NAME, [rounded(row) for row in result["rows"]])
    write_csv(output_dir / TARGETS_NAME, [rounded(row) for row in result["targets"]])
    write_csv(output_dir / LINEAGE_NAME, result["lineage"])
    with (output_dir / ASSUMPTIONS_NAME).open("x", encoding="utf-8") as handle:
        handle.write(assumptions_markdown(result))
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output_dir.iterdir())}
    with (output_dir / SUCCESS_NAME).open("x", encoding="utf-8") as handle:
        json.dump({"feature_version": result["feature_version"], "availability_basis": result["availability_basis"],
                   "bundle_sha256": result["manifest"]["bundle_sha256"],
                   "manifest_sha256": result["manifest_sha256"], "files_sha256": files},
                  handle, sort_keys=True, indent=2)
        handle.write("\n")
    return {"output_dir": str(output_dir), "manifest_sha256": result["manifest_sha256"], "file_count": len(files) + 1}
