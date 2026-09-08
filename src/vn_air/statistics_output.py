"""Phase 6 artifact writers: summary JSON, estimate/bootstrap CSVs, assumptions, SUCCESS hashes."""

import csv
import hashlib
import json
from pathlib import Path

from vn_air.eda_output import write_csv
from vn_air.quality import digest

SUMMARY_NAME = "phase_6_statistics_summary.json"
ESTIMATES_NAME = "phase_6_estimates.csv"
BOOTSTRAP_NAME = "phase_6_bootstrap_summary.csv"
ASSUMPTIONS_NAME = "phase_6_assumptions.md"
SUCCESS_NAME = "SUCCESS.json"
ESTIMATE_FIELDS = ("fit_id", "family", "hypothesis", "scope", "exposure", "scale", "weather_case",
                   "block_days", "exclude_extreme", "formula", "estimand", "inference", "n",
                   "candidate_windows", "nonempty_independent_blocks", "eligible_independent_blocks",
                   "estimate", "ci_low", "ci_high", "p_value", "p_value_adjusted", "adjustment",
                   "exposure_mean", "exposure_sd", "day_center", "expected_hours", "accepted_hours",
                   "absent_hours", "extreme_flagged_hours", "weather_complete_hours", "eligible_hours",
                   "coverage_percent")
BOOTSTRAP_FIELDS = ("fit_id", "family", "hypothesis", "scope", "exposure", "scale", "weather_case",
                    "block_days", "exclude_extreme", "inference", "candidate_windows",
                    "nonempty_independent_blocks", "eligible_independent_blocks", "gate_pass",
                    "full_draws", "remainder_draws", "draws_per_replicate", "sampled_dates_per_replicate",
                    "replicates", "skipped_replicates", "usable_replicates", "estimate",
                    "bootstrap_mean", "bootstrap_sd", "ci_low", "ci_high", "p_value")
ROLE_NAMES = {"primary": "primary", "secondary": "secondary", "sensitivity": "sensitivity"}


def estimate_row(fit):
    row = {key: fit.get(key) for key in ESTIMATE_FIELDS}
    row["family"] = ROLE_NAMES[fit["role"]]
    row.update(fit["coverage"])
    row.update(fit["standardization"])
    return row


def bootstrap_row(fit):
    row = {key: fit.get(key) for key in BOOTSTRAP_FIELDS}
    row["family"] = ROLE_NAMES[fit["role"]]
    return row


def assumptions_markdown(result):
    manifest = result["manifest"]
    fits = result["results"]
    lines = [
        "# Phase 6 Statistics: Assumptions and Limitations", "",
        "Pre-registered sensor-level weather-PM2.5 association analysis replayed from the frozen",
        "Phase 5 EDA bundle. No causal, city-wide exposure, operational forecast or health claim is supported.", "",
        "## Frozen boundary", "",
        f"- Phase 5 bundle digest: `{manifest['phase5_bundle_sha256']}` (file SHA-256 `{manifest['phase5_bundle_file_sha256']}`)",
        f"- Cutoff: {manifest['cutoff']}; window: {manifest['start']} to {manifest['end']}",
        f"- Seed {manifest['seed']}; {manifest['replicates']} replicates per fit; block lengths {manifest['block_days']} local calendar days",
        f"- Gate thresholds: >= {manifest['gate_thresholds']['min_nonempty_blocks']} non-empty and >= {manifest['gate_thresholds']['min_eligible_blocks']} eligible independent partitions",
        f"- Reconciliation: {json.dumps(manifest['reconciliation'], sort_keys=True)}",
        f"- Weather variables observed in the frozen bundle: {', '.join(manifest['weather_variables'])}", "",
        "## Model", "",
        "Each fit is ordinary least squares on accepted PM2.5 hours with sensor fixed effects (pooled and",
        "shared fits), Vietnam local-hour fixed effects (reference hour 0), weekday fixed effects",
        "(reference Monday) and a centered linear day trend. Exposures are standardized on each fit's",
        "eligible rows; the estimand is the adjusted change in the response per one analysis-window",
        "standard deviation of the exposure. H3 is the sensor contrast (OceanPark minus CMT8) on the",
        "shared accepted-hour set and has no exposure term. Complete cases per fit; no imputation; CAMS",
        "and provider forecasts are excluded.", "",
        "Weather cases:", "",
        "- `pairwise_complete`: accepted response plus a finite value of the fit's exposure only.",
        "- `complete_weather`: additionally finite values for every weather variable observed in the",
        "  bundle rows (listed above). Complete-weather OLS variants exist for the pooled H1, H2 and all",
        "  five declared secondary log1p fits and are exploratory sensitivity output.",
        "- `not_applicable`: H3, which has no weather exposure term.",
        "",
        "Formulas per fit are recorded in the summary manifest.", "",
        "## Uncertainty and inference", "",
        "Uncertainty uses a moving-block bootstrap over Vietnam local calendar days. Moving windows are",
        "resampling candidates only; they overlap and are not independent evidence units. Each replicate",
        "draws `divmod(n_dates, block_days)` full-length windows plus one remainder-length window when",
        "needed, so every replicate spans exactly 91 study dates (two-day blocks draw 45 two-day windows",
        "plus one one-day window, never 92). Percentile 95% intervals; p-values are the two-sided",
        "bootstrap tail statistic 2*min(P(beta<=0), P(beta>=0)) computed as (count+1)/(usable+1).", "",
        "The inferential gate uses deterministic non-overlapping partitions of the ordered local calendar",
        "dates anchored at the first frozen study date (chunks of at most block_days dates with a final",
        "shorter chunk): at least 30 non-empty and at least 20 eligible independent partitions are",
        "required. The frozen 91-date window yields 91, 46 and 13 independent partitions for one-, two-",
        "and seven-day blocks, so seven-day sensitivity fits are expected to be descriptive-only under",
        "the gate; this is a documented limitation, not a failure.", "",
        "Inference labels: only the two Holm-adjusted primary pooled p-values and the five",
        "Benjamini-Hochberg-adjusted secondary pooled p-values are `inferential`. Gate-passing but",
        "unadjusted fits (site-specific, H3, raw-scale, block-length, complete-weather and",
        "extreme-value) are `exploratory`. Gate-failing or descriptive outputs are `descriptive_only`.",
        "Unadjusted p-values are exploratory diagnostics, not findings.", "",
        "## Fit inventory", "",
        "| fit | family | weather case | n | coverage % | independent blocks (non-empty/eligible) | estimate | CI | p | inference |",]
    for fit in fits:
        interval = f"[{fit.get('ci_low')}, {fit.get('ci_high')}]" if fit["gate_pass"] else "n/a"
        p_value = fit.get("p_value", "n/a")
        lines.append(f"| {fit['fit_id']} | {ROLE_NAMES[fit['role']]} | {fit['weather_case']} | {fit['n']} "
                     f"| {fit['coverage']['coverage_percent']} | {fit['nonempty_independent_blocks']}/"
                     f"{fit['eligible_independent_blocks']} | {fit['estimate']} | {interval} | {p_value} "
                     f"| {fit['inference']} |")
    lines += ["", "## Pairwise-complete versus complete-weather descriptive correlations", "",
        "Descriptive per-sensor Pearson correlations using the Phase 5 convention. `pairwise_complete`",
        "rows have finite accepted PM2.5 and a finite exposure value; `complete_weather` rows also have",
        "every bundle weather variable finite. These are coverage/descriptive sensitivity output only:",
        "no bootstrap interval, p-value, adjustment or inferential label applies, and no new hypothesis",
        "is created. Wind direction is circular and stays excluded; Phase 5 wind sectors remain the",
        "descriptive wind-direction output.", "",
        "| sensor | exposure | weather case | n | Pearson r |",]
    for record in manifest["pairwise_correlations"]:
        lines.append(f"| {record['location']} | {record['exposure']} | {record['weather_case']} "
                     f"| {record['n']} | {record['pearson_r']} |")
    lines += ["", "## Extreme-value review rule (sensitivity only)", ""]
    for location, fence in sorted(manifest["extreme_review"].items()):
        lines.append(f"- {location}: Q1 {fence['q1']}, Q3 {fence['q3']}, fence Q3+3*IQR = {fence['fence']} ug/m3, "
                     f"{fence['flagged_hours']} accepted hours flagged; flagged rows keep Phase 4 labels and stay in primary fits")
    lines += ["", "## Assumptions", "",
        "- Accepted OpenAQ values are provisional screening labels, not calibration certification.",
        "- ERA5 reanalysis at station coordinates represents site weather; it is retrospective and its retrieval time is not historical availability.",
        "- Within-block serial dependence is preserved by design; across-block independence is approximate.",
        "- Effects are linear on the fitted scale over the observed range; log1p and raw scales are both reported.",
        "- Fixed effects for hour, weekday and a linear trend absorb major temporal structure, not all confounding.",
        "- Bootstrap p-values are exact only under the resampling model; they are not parametric p-values.",
        "- Floating-point outputs are rounded to 12 significant digits for deterministic replay.", "",
        "## Limitations", ""]
    lines.extend(f"- {item}" for item in result["limitations"])
    lines += ["", "## Attribution", "",
        "OpenAQ; AirGradient; Thomas Versteeg (CMT8); Open-Meteo; ERA5/Copernicus C3S. CC BY 4.0.",
        "See docs/verification/phase_6.md for the verification record, phase_6_plan.md for the",
        "pre-registration and its 2026-09-09 correction addendum.", ""]
    return "\n".join(lines)


def write_outputs(output_dir, result):
    if output_dir.exists() or not output_dir.parent.is_dir():
        raise ValueError("Statistics output directory must be new with an existing parent")
    output_dir.mkdir(mode=0o700)
    with (output_dir / SUMMARY_NAME).open("x", encoding="utf-8") as handle:
        json.dump(result, handle, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
        handle.write("\n")
    write_csv(output_dir / ESTIMATES_NAME, [estimate_row(fit) for fit in result["results"]])
    write_csv(output_dir / BOOTSTRAP_NAME, [bootstrap_row(fit) for fit in result["results"]])
    with (output_dir / ASSUMPTIONS_NAME).open("x", encoding="utf-8") as handle:
        handle.write(assumptions_markdown(result))
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output_dir.iterdir())}
    with (output_dir / SUCCESS_NAME).open("x", encoding="utf-8") as handle:
        json.dump({"stats_version": result["manifest"]["stats_version"],
                   "manifest_sha256": result["manifest_sha256"], "files_sha256": files},
                  handle, sort_keys=True, indent=2)
        handle.write("\n")
    return {"output_dir": str(output_dir), "manifest_sha256": result["manifest_sha256"], "file_count": len(files) + 1}
