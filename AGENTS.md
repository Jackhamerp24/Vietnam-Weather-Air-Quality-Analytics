# Agent Instructions

## Project State

Vietnam Weather & Air Quality Analytics is a Data Science portfolio project.
Phases 1-3 are implemented:

- API/source research and measured-source qualification.
- PostgreSQL/Alembic architecture and Supabase deployment.
- Bounded OpenAQ/Open-Meteo ingestion with provenance, retries, revisions,
  quarantine, checkpoints and read-only reporting.

Phases 4-8 are implemented and verified. Phase 5 provides descriptive EDA from
the frozen Phase 4 dataset. Phase 6 provides pre-registered, sensor-level
weather-PM2.5 association estimates with block-bootstrap uncertainty, replayed
read-only from the frozen Phase 5 bundle; the authoritative Phase 6 artifact is
the 2026-09-09 corrected run, and the 2026-09-08 artifact is superseded but
preserved. Phase 7 provides availability-aware, leakage-safe feature
construction (6h/24h horizons) with a read-only extractor and a captured
limited-diagnostic artifact. The authoritative artifact is the 2026-09-10
structural-hardened `phase7_features_v7` run; v1 through v6 remain preserved as
superseded historical evidence. Phase 8 provides a database-free, deterministic
baseline runner over the Phase 7 artifact with train-only fitting, inherited
chronological split/purge and summary-bound replay. Its authoritative artifact
is the 2026-09-11 v2 verified run; the v1 and intermediate v2 runs are preserved
unchanged and superseded. The frozen window contains no prospectively captured evidence,
so the Phase 8 artifact is a limited diagnostic (72 of 90 metric cells
unavailable; only the local-hour calendar diagnostic runs) and a prospective
collection period is required before baselines on real data. Feature
engineering and baseline evaluation are delivered; model training (Phase 9 ML),
dashboard work and scheduling are not yet implemented. Do not claim model
performance, forecast skill, causal findings, operational readiness or
production automation. The Phase 6 estimates are sensor-level associations over
one 90-day window; treat the Holm- and FDR-adjusted results as the only
inferential outputs and everything else as exploratory sensitivity.

## Required Reading

- `README.md`
- `docs/verification/phase_3.md`
- `docs/ingestion.md`
- `docs/database.md`
- `docs/source_contracts.md`
- `docs/decisions/0001-data-sources.md`
- `docs/research/openaq_qualification.md`
- `docs/verification/phase_3_counts.json`
- `docs/verification/phase_4.md`
- `docs/verification/phase_5.md`
- `docs/verification/phase_5_plan.md`
- `docs/verification/phase_5_eda_2026-09-07_final/eda_bundle.json`
- `docs/verification/phase_6_plan.md`
- `docs/verification/phase_6.md`
- `docs/verification/phase_6_statistics_2026-09-09_corrected/phase_6_statistics_summary.json`
- `docs/verification/phase_7_plan.md`
- `docs/verification/phase_7.md`
- `docs/verification/phase_7_registry_hardening_plan.md`
- `docs/verification/phase_7_snapshot_boundary_hardening_plan.md`
- `docs/verification/phase_7_structural_schema_hardening_plan.md`
- `docs/verification/phase_7_features_2026-09-10_structural_hardened/phase_7_feature_summary.json`
- `docs/verification/phase_8_plan.md`
- `docs/verification/phase_8.md`
- `docs/verification/phase_8_integrity_replay_hardening_plan.md`
- `docs/verification/phase_8_baselines_2026-09-11_v2_verified/phase_8_baselines_summary.json`

The previous runtime's continuation handoff file is no longer present in this
runtime; `docs/verification/phase_8.md` and the dated verification documents are
the continuation authority.

## Data Rules

- Keep measured OpenAQ PM2.5, ERA5 reanalysis, Open-Meteo forecasts and CAMS
  modeled air quality separate.
- Treat CMT8 and OceanPark as sensor-level measurements, not city averages.
- Treat Da Nang as modeled-only until a qualified measured source exists.
- Preserve missing periods, revisions, failed runs, raw responses and quality
  issues. Do not interpolate gaps or silently replace observations with models.
- Use UTC `timestamptz` for storage. Respect OpenAQ exclusive period-ending
  intervals and Open-Meteo temporal support.
- Historical retrieval time is not historical availability. Do not use ERA5 or
  retrospective data as operational features without an explicit availability
  policy.
- Do not treat provider forecasts or CAMS values as ground truth.

## Security

- Never read, print, commit or paste values from `.env`.
- Never log API keys, database URLs, passwords, request headers or raw secret-
  bearing exceptions.
- `.env` is ignored and owner-only. Use environment variables for credentials.
- Supabase MCP is project-scoped and read-only. Use it for narrow inspection,
  docs and advisors. Apply schema changes through the tested Alembic workflow.
- The Supabase database has deny-by-default RLS and no browser policies by design.
  Do not expose `vn_air` through the Data API without an explicit dashboard
  access design and reviewed policies.
- Do not create paid services, branches, schedules or database roles without
  explicit user authorization.

## Commands

Use the installed package for CLI commands:

```bash
.venv/bin/vn-air db status
.venv/bin/vn-air report
```

Use the documented runbook for ingestion. It requires a trusted local `.env`:
`docs/ingestion.md`.

Run offline tests:

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
```

Run isolated PostgreSQL tests:

```bash
PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
```

The isolated suite creates and removes its own PostgreSQL cluster. Do not point it
at Supabase or the project database.

## Editing And Verification

- Inspect worktree status before changes. The repository has commits and may have
  untracked analysis artifacts; do not clean or reset them.
- Use `apply_patch` for manual edits.
- Keep changes incremental and phase-scoped.
- Add tests for parser, provenance, time alignment, database constraints and
  failure recovery before changing ingestion behavior.
- Run `git diff --check`, offline tests and relevant isolated database tests.
- Update the appropriate verification document when live data or Supabase state
  changes. Do not duplicate large evidence payloads in prose.
- No independent Oracle review was available in the previous runtime. Do not
  claim independent review unless a future runtime actually performs it.

## Phase 4 Focus

The frozen, reproducible audit is recorded in `docs/verification/phase_4.md` and
the dated JSON artifact beside it. Preserve its cutoff, selection rules,
uncertainty and limitations when using the data for EDA. Keep the audit separate
from automatic deletion or imputation.

## Phase 5 Focus

EDA outputs live under `docs/verification/phase_5_eda_2026-09-07_final/`. Preserve the
Phase 4 cutoff, input hashes, source separation, hourly gaps and interval
alignment. Treat correlations, lag profiles and descriptive group summaries as
exploration only. Do not turn them into significance or causal claims.

The final EDA bundle hash is
`92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63`.
Phase 5 added no database migration or schema change. Phase 6 consumed this
bundle read-only; its frozen boundary remains authoritative for any re-analysis.

## Phase 6 Plan: Statistical Analysis

Phase 6 is delivered and verified against the corrected artifact
`docs/verification/phase_6_statistics_2026-09-09_corrected/` (see
`docs/verification/phase_6.md`). The 2026-09-08 artifact is superseded: review
found four implementation-contract errors (missing complete-weather sensitivity,
overlapping moving windows used as the independent-block gate, 92-date two-day
bootstrap replicates, and gate passage labelled inferential) that were corrected
per the 2026-09-09 addendum in `docs/verification/phase_6_plan.md`. Preserve the
following contract; the next phase is Phase 7: availability-aware feature
engineering. Do not implement feature engineering or model training while
completing a handoff/read-only task.

### Objective

Estimate descriptive and adjusted weather–PM2.5 associations at the two monitored
sensor sites, with time-series-aware uncertainty. The analysis supports
sensor-level association statements over the frozen study window. It does not
support city-wide exposure, causal effects, operational forecast skill or health
advice.

### Frozen inputs and selection

- Use the Phase 4 cutoff `2026-09-06T20:59:00.669630Z`.
- Use the Phase 4 window `2026-06-08T00:00:00Z` through `2026-09-06T00:00:00Z`.
- Use the final Phase 5 bundle and its input hashes:
  `docs/verification/phase_5_eda_2026-09-07_final/eda_bundle.json`.
- Select the latest eligible OpenAQ revision before quality filtering.
- Use accepted PM2.5 rows only for the primary analysis; retain absent and
  excluded rows in coverage tables.
- Join ERA5 at station coordinates with the Phase 5 interval policy.
- Keep CAMS and provider forecasts out of the measured-target statistical model.
- Stop if Phase 4/5 input hashes, configuration hash, schema revision or cutoff
  do not match the frozen artifacts.

### Predeclared estimands and hypotheses

Before calculating p-values or confidence intervals, write the exact hypotheses
and estimands to the Phase 6 plan/report. The minimum primary set is:

1. `H1`: within-sensor PM2.5 varies with wind speed after adjustment for sensor,
   Vietnam local hour, weekday and a bounded date trend. Report the adjusted
   change in log1p(PM2.5) per one training-window standard deviation of wind speed.
2. `H2`: within-sensor PM2.5 varies with relative humidity under the same temporal
   adjustment. Report the same standardized adjusted effect.
3. `H3`: the two sensor distributions differ over the shared accepted-hour set.
   Treat this as a site contrast, not a city contrast or population estimate.

Temperature, precipitation, pressure, cloud cover and radiation are secondary
exploratory exposures unless the Phase 6 plan explicitly promotes one before
fitting. Exclude linear Pearson treatment of wind direction because direction
is circular; use predeclared wind sectors only as descriptive sensitivity output.

### Statistical design

- Model PM2.5 on the concentration scale and log1p scale; choose one primary
  scale before looking at results and retain the other as sensitivity analysis.
- Include sensor fixed effects, local hour fixed effects, weekday fixed effects
  and a simple date trend or predeclared low-degree temporal basis.
- Standardize exposures using eligible training/analysis rows only and record
  the means/scales in the manifest.
- Use complete cases for each exposure model. Never fill missing PM2.5 or weather.
- Use moving/block bootstrap over Vietnam local calendar days as the primary
  uncertainty method. Use 2,000 replicates with seed `20260908`. Predeclare a
  24-hour block and evaluate 48-hour and 168-hour blocks as sensitivity checks.
  Preserve gaps inside blocks.
- Require at least 30 non-empty independent blocks and at least 20 blocks with
  eligible rows for the estimate before inferential output; below that threshold,
  report descriptive estimates only.
- Fit separate primary models for wind speed and humidity:
  `log1p_pm25 ~ sensor + local_hour + weekday + day_index + standardized_exposure`.
  Report site-specific and pooled fixed-effect fits. Do not add interactions
  after viewing results.
- Apply Holm adjustment to the two primary p-values and Benjamini–Hochberg FDR
  to the declared secondary exposure family. Keep primary results separate.
- Report effect estimate, uncertainty interval, p-value where justified, sample
  size, accepted coverage, independent block count, model formula and assumptions.

### Required sensitivity analyses

- CMT8 and OceanPark separately.
- Shared accepted sensor-hours only for the site contrast.
- Raw PM2.5 versus log1p(PM2.5).
- 24/48/168-hour bootstrap blocks.
- Complete weather rows versus pairwise-complete descriptive correlations.
- With and without the predeclared extreme-value review rule, without deleting
  source rows or silently changing the Phase 4 quality labels.

### Deliverables and verification gates

Delivered outputs are the versioned Phase 6 plan (pre-registered before fitting,
with the 2026-09-09 correction addendum), the read-only `vn-air stats run|replay`
commands, the frozen statistics manifest, estimate/interval/bootstrap tables and
the assumptions report under
`docs/verification/phase_6_statistics_2026-09-09_corrected/` with the expected
names `phase_6_statistics_summary.json`, `phase_6_estimates.csv`,
`phase_6_bootstrap_summary.csv`, `phase_6_assumptions.md` and `SUCCESS.json`. No
database migration or Supabase write was added. The superseded 2026-09-08
artifact remains in place unchanged.

Completed gates for the corrected artifact: the offline suite (93 tests,
including 32 statistics tests covering partitions, exact draw lengths,
weather cases, inference labels and regression protection), the isolated
PostgreSQL suite (45 tests), `git diff --check`, a byte-identical
deterministic-seed replay, and the narrow live read-only cutoff-count check
recorded in `docs/verification/phase_6.md`. Independent-block gates use
non-overlapping date partitions (91/46/13); every replicate spans exactly 91
dates; only Holm/BH-adjusted outputs are labelled inferential. Stop conditions
(hash mismatch, rank deficiency, insufficient independent blocks) remain active
for any re-analysis. No independent reviewer is available unless a future
runtime explicitly performs one.

## Phase 7 Focus: Availability-Aware Feature Engineering

Phase 7 is delivered and verified against the authoritative artifact
`docs/verification/phase_7_features_2026-09-10_structural_hardened/`
(`phase7_features_v7`; see `docs/verification/phase_7.md`). The earlier
artifacts (`phase7_features_v1` captured, `phase7_features_v2` corrected and
`phase7_features_v3` final, `phase7_features_v4` intermediate,
`phase7_features_v5` hardened and `phase7_features_v6` snapshot-hardened) are
preserved unchanged and superseded: review
corrections A–J in
`docs/verification/phase_7_correction_plan.md` fixed prospective-window
boundaries, 72h warm-up extraction, assumed-mode forecast value policy,
source/vintage identity checks, value-level lineage and leakage, null-label
target semantics, period_start validation, summary-bound replay binding and
config/bundle boundary checks, and the final fix
(`docs/verification/phase_7_final_fix_plan.md`) made status count usable
accepted evidence only (invalid-only input cannot produce `status = ok`) and
added input-table hash verification with re-signed tamper rejection. The
registry-boundary correction in `docs/verification/phase_7_registry_fix_plan.md`
now validates the complete reviewed variable, sensor and location registries,
modeled-value identity/support, duplicate keys, derived sensor name/timezone,
snapshot/product identity, embedded IDs and structural required-field checks
before construction. The next phase was Phase 8: reproducible chronological
baselines (delivered; see the Phase 8 Focus section). Do not implement ML while
completing a handoff/read-only task.

Contract to preserve:

- Two explicit availability modes: `captured` (evidence timestamps strictly
  before the origin; conservative, never described as as-issued provider
  availability) and `assumed` (declared lag on event times; user-authorized
  scenario only; never an operational backtest). No silent captured→assumed
  fallback. The Phase 3 backfill's `retrieved_at` is not historical
  availability.
- Source separation: measured OpenAQ PM2.5 is the target/history source;
  Open-Meteo forecast snapshots are the only captured weather source; ERA5 and
  CAMS are excluded from the captured measured-target matrix; missing measured
  PM2.5 is never replaced with model output.
- Target contract: `target_end = origin + h`, target row
  `[target_end − 1h, target_end)`; targets live in `phase_7_targets.csv` only
  and never enter feature lineage. Horizons are exactly 6 and 24 hours.
- Revision-before-quality selection with a deterministic composite tie-break;
  exact-timestamp lags; strict trailing windows with reported counts; wind
  direction only as sin/cos; one deterministic forecast vintage per
  location/origin with the documented ranking and no averaging.
- One shared 60/20/20 chronological split (2026-07-31T10:00Z and
  2026-08-18T05:00Z for the frozen window) with horizon purge reported
  separately; the final test period stays untouched.
- The captured artifact is a limited diagnostic (`status =
  limited_diagnostic`): all PM and forecast-weather features are null with
  explicit reasons because no evidence predates any historical origin. A
  prospective collection period is required before captured operational
  features or Phase 8 baselines on real data exist.

Delivered code: `src/vn_air/features.py` (v7), `src/vn_air/features_store.py`
(v3), `src/vn_air/features_output.py`, `vn-air features extract|build|replay`
(`--config` required for build/replay; `--require-frozen-boundary` optional;
summary-bound replay binds bundle digest, file digest, version, horizons,
availability and lag), `tests/test_features.py` (85 non-CLI v7 tests executed;
five CLI replay tests remain blocked by the local package stall) and
`tests/integration/test_features_database.py` (7 isolated-PostgreSQL tests).
Evidence completed: 85 non-CLI v7 builder/regression tests, pure-builder v7
build/replay with byte-identical six-file output, preserved v1–v6 artifact
hashes, complete registry and input-table hash verification, `git diff --check`,
and full repository gates (209 offline tests with two documented credential
skips, 52 isolated PostgreSQL tests). Assumed-mode artifacts require explicit
user authorization per scenario.

## Phase 8 Focus: Reproducible Chronological Baselines

Phase 8 is delivered and verified against the authoritative artifact
`docs/verification/phase_8_baselines_2026-09-11_v2_verified/`
(`phase8_baselines_v2`; see `docs/verification/phase_8.md`). The v1 artifact and
all intermediate v2 correction artifacts are preserved unchanged and
superseded. The next phase is Phase 9: chronological ML.
Do not implement ML while completing a handoff/read-only task.

Contract to preserve:

- Phase 8 consumes a Phase 7 artifact only: every declared hash, the summary
  manifest digest, feature version, horizons, captured availability basis,
  split/purge metadata and feature/target key and identity alignment are
  verified before any baseline is computed. No database access for `run` or
  `replay`.
- Declared baselines: `persistence_last_available` (primary history-only
  reference), `persistence_lag_1h`, `trailing_mean_24h`, train-only
  `local_hour_climatology`, and `weather_augmented_climatology` only when finite
  captured weather features exist (no ERA5/CAMS/assumed fallback). No
  imputation, no target-derived features and no test-based selection.
- Metrics are `descriptive_only`, computed on finite accepted targets and finite
  predictions from non-purged rows; MASE uses the training one-hour naive
  denominator and sMAPE a zero-safe denominator. Coverage and exclusion reasons
  are reported per baseline × sensor × horizon × split, and pooled metrics
  remain a descriptive combination of two non-reference sensors.
- The frozen artifact is a limited diagnostic (`status = limited_diagnostic`,
  reasons `input_phase7_missing_pm_history` and
  `input_phase7_missing_forecast_weather`): 72 of 90 metric cells are
  unavailable with explicit reasons and no fabricated scores, and the 18
  local-hour climatology cells are calendar diagnostics fit on non-purged
  training targets only.
- Replay is summary-bound and deterministic; required Phase 7 hashes cannot be
  omitted, unsafe payload paths and symlinks are rejected, output directories
  must be new, and the local input path is excluded so equivalent checkouts can
  replay identically;
  no database write, migration, schedule or paid resource was added.

Delivered code: `src/vn_air/baselines.py` (`phase8_baselines_v2`),
`src/vn_air/baselines_output.py`, `vn-air baselines run|replay` and
`tests/test_baselines.py` (26 tests). Evidence completed: 209 offline tests
(2 credential skips) and 52 isolated PostgreSQL tests passed, CLI and module
replay byte-identical (5/5 files), `git diff --check` clean. The installed
`.venv/bin/vn-air` entry point predates the Phase 7/8 subcommands; use
`PYTHONPATH=src .venv/bin/python -m vn_air.cli` until the package is
reinstalled.

## Suggested Skills

Call the Skill tool as applicable:

- `verification-planning` before Phase 4 or any behavior-changing data pipeline work.
- `supabase` for Supabase database, MCP, RLS, advisor, migration or log work.
- `supabase-postgres-best-practices` before SQL, schema, index, trigger, RLS or
  database performance changes.
- `deepwork` only for genuinely multi-stage/high-risk work.
- `simplify` for a targeted readability pass after behavior is verified.
- `stop-slop` when writing analytical findings or portfolio prose.
- `customize-opencode` only when changing OpenCode configuration or MCP setup.
