# Phase 8 Plan: Reproducible Chronological Baselines

Status: delivered and verified against
`phase_8_baselines_2026-09-11_v2_verified/`; see [phase_8.md](phase_8.md)
Date: 2026-09-11 UTC

## Objective

Evaluate simple, reproducible PM2.5 baselines for the exact Phase 7 target
contracts at horizons 6 and 24 hours. Establish a defensible reference before
any Phase 9 machine-learning model. Phase 8 does not claim forecast skill,
operational readiness, causal effects, city-wide exposure or health guidance.

## Input contract

The runner consumes one Phase 7 artifact directory containing:

- `phase_7_feature_summary.json`;
- `phase_7_features.csv`;
- `phase_7_targets.csv`;
- `SUCCESS.json`.

The summary must bind the exact feature version, input bundle digest and file
hash, horizons, availability basis, boundary, split and purge metadata. The
runner must verify every listed artifact hash before fitting. It must reject
missing files, malformed rows, hash mismatches, unsupported horizons, unknown
availability modes and feature/target key misalignment. No database access is
allowed for `run` or `replay`.

Targets remain separate from features. A target is usable only when
`target_available=true`, `target_pm25` is finite and its quality is accepted.
Feature values must be finite and must be present in the feature row, never
reconstructed from target columns. Nulls and reasons are retained in coverage
counts; no interpolation, forward fill or model replacement is allowed.

## Chronological evaluation

Use Phase 7's one shared split: train 60%, validation 20%, test 20%, with the
recorded validation/test start timestamps and horizon purge. Preserve the final
test period untouched during all fitting and baseline selection. Compute metrics
only for rows with a finite observed target and finite prediction. Report
coverage by sensor, horizon and split, including missing target, missing feature,
purged and unavailable reasons.

The default evaluation unit is each `(sensor_id, origin, horizon_hours)` row.
Report per-sensor metrics and pooled metrics; never describe pooled metrics as a
city average. A pooled summary is a descriptive combination of two sensor sites.

## Predeclared baselines

All baselines are deterministic and require no fitted parameters except those
explicitly listed:

1. `persistence_last_available`: use `pm25_last_available` from the feature row.
   The feature builder already exposes its age; do not reconstruct it from
   targets. This is the primary history-only reference.
2. `persistence_lag_1h`: use `pm25_lag_1h`, reported separately because it is
   stricter than last-available.
3. `trailing_mean_24h`: use `pm25_trailing_mean_24h`; only complete strict
   windows are eligible.
4. `local_hour_climatology`: fit the mean accepted target PM2.5 by sensor and
   Vietnam local hour using training rows only. Require at least one finite
   training observation for a sensor/hour cell; no global fallback is allowed.
5. `weather_augmented_climatology` (diagnostic only): fit the same local-hour
   climatology with a declared weather-availability indicator only if the input
   artifact contains finite captured weather features. It must be omitted and
   marked unavailable when captured weather is absent; do not use ERA5/CAMS or
   assumed mode implicitly.

The runner must not select a “best” baseline using test metrics. Validation may
be used for a predeclared selection report, but the primary output reports all
baselines and identifies the predeclared history-only reference.

## Metrics

For each available baseline × sensor × horizon × split, report:

- `n`; coverage numerator/denominator and exclusion reasons;
- MAE, RMSE, mean error and median absolute error;
- MASE only when a valid in-sample one-step naive denominator exists in the
  training partition; otherwise null with a reason;
- sMAPE only with a predeclared zero-safe denominator rule; report null if the
  denominator is zero for every eligible row.

Do not use MAPE near zero. Do not report a metric for an empty or unavailable
cell. A metric is `descriptive_only` and not an inferential or operational claim.

## Missing-data gate

If the captured artifact has zero eligible target/prediction rows for a
baseline, emit `status=limited_diagnostic`, `metric_status=unavailable` and a
machine-readable reason. The frozen Phase 7 artifact is expected to have no
usable captured feature rows, so the first real Phase 8 artifact must be
limited diagnostic. Synthetic prospective fixtures must demonstrate non-empty
metrics, but their values must never be mixed into the frozen artifact.

## Deliverables

Create a dated directory with exactly these files:

- `phase_8_baselines_summary.json`;
- `phase_8_baseline_metrics.csv`;
- `phase_8_predictions.csv`;
- `phase_8_assumptions.md`;
- `SUCCESS.json`.

The output directory must be new. Replay must regenerate all files byte-for-byte
from the same input artifact and recorded request. SUCCESS must contain hashes
for every output file and the summary manifest hash.

## Tests and gates

Add offline tests for input hash binding, target/feature alignment, train-only
climatology, exact persistence/trailing behavior, missing-data limited status,
metric arithmetic, no test fitting, deterministic replay, no overwrite and
prediction target separation. Run the repository offline suite and isolated
PostgreSQL suite where the existing environment permits; Phase 8 run/replay
itself must remain database-free. Run `git diff --check` and markdown-link
checks. Do not add migrations, writes, schedules or dependencies.

## Phase boundary

Phase 8 ends after the baseline engine and a truthful frozen diagnostic artifact
are verified. Phase 9 ML remains separate and must use the same chronological
contracts, train-only transformations and untouched final test period.

## Integrity and replay correction, 2026-09-11

The post-handoff review reproduced two defects in v1: omission of a required
input hash did not stop loading, and a changed, re-signed split in a replay
summary did not stop replay. The
[integrity/replay correction plan](phase_8_integrity_replay_hardening_plan.md)
records the v2 fix and tests, including valid replay, metadata shape and path
checks. Replay must match the whole manifest, its digest and purpose, including
implementation hashes and input content identities. Exclude the local input
path so replay remains portable across checkouts. This changes no baseline
formula or statistical selection rule. Preserve the existing v1 and intermediate
v2 outputs; generate the completed correction in the new
`phase_8_baselines_2026-09-11_v2_verified/` directory. The correction is now
complete: the v2 artifact is authoritative and all v1/intermediate artifacts
remain preserved as superseded evidence.
