# Phase 8 Baseline Verification

Date: 2026-09-11 UTC. Scope: reproducible chronological PM2.5 baselines for the
Phase 7 6-hour and 24-hour target contracts, computed read-only from a captured
Phase 7 artifact. The runner opens no database, performs no imputation, selects
no baseline on test metrics and trains no model. No forecast-skill, causal,
city-wide, operational or health claim is supported.

**Authoritative artifact: `phase_8_baselines_2026-09-11_v2_verified/`**
(`phase8_baselines_v2`, manifest
`ec651c4df04cb605f8849c1af96a3aea58f0902370e16ec39b9c48fdee22775e`). The
original `phase_8_baselines_2026-09-11_final/` v1 artifact and all intermediate
v2 correction artifacts are preserved unchanged and superseded. The v2
correction hardens required Phase 7 hash declarations and binds the complete
Phase 8 replay manifest, including split boundaries and purpose.

## Contract

The implementation follows [phase_8_plan.md](phase_8_plan.md): the runner
consumes one Phase 7 artifact directory (`phase_7_feature_summary.json`,
`phase_7_features.csv`, `phase_7_targets.csv`, `SUCCESS.json`) and verifies every
declared hash, the summary manifest digest, the feature version, horizons,
captured availability basis, chronological split boundaries, feature/target key
alignment, target alignment (`target_end = origin + h`, target row
`[target_end − 1h, target_end)`) and the horizon-purge contract before fitting.
Targets remain separate from features and are never reconstructed from feature
columns; only finite accepted targets are eligible. Local-hour climatology is
fit on non-purged training rows only. Weather-augmented climatology requires
finite captured weather features and never falls back to ERA5, CAMS or assumed
mode. No test row is used for fitting or selection, replay is summary-bound and
deterministic, and output directories are new and never overwritten.

## Implementation

- `src/vn_air/baselines.py` (`phase8_baselines_v2`): hash-verified artifact
  loader, structural row validation, feature/target alignment and
  availability-flag checks, split/purge verification, five declared baselines,
  per-group coverage and exclusion accounting, zero-safe descriptive metrics,
  truthful limited-diagnostic status, summary-bound replay and no-overwrite
  writers.
- `src/vn_air/baselines_output.py`: artifact writers for the five output files.
- `src/vn_air/cli.py`: `baselines run|replay`; both never touch the database and
  `replay` binds the previous summary to feature version, input hashes,
  horizons and availability basis.
- `tests/test_baselines.py`: 26 offline tests covering input hash binding and
  tamper rejection, key/identity alignment, malformed target alignment,
  train-only climatology, exact persistence/trailing source columns,
  finite-captured-weather enablement, weather unavailability, purged-row
  exclusion from metrics, metric arithmetic, no test selection, no overwrite,
  deterministic replay and summary-bound mismatch rejection.

Declared baselines:

| Baseline | Role | Source |
| --- | --- | --- |
| `persistence_last_available` | primary history-only reference | Phase 7 `pm25_last_available` |
| `persistence_lag_1h` | sensitivity | exact Phase 7 `pm25_lag_1h` |
| `trailing_mean_24h` | sensitivity | strict complete Phase 7 24-hour window |
| `local_hour_climatology` | calendar diagnostic | training targets by sensor and Vietnam local hour |
| `weather_augmented_climatology` | weather diagnostic | training climatology stratified by captured-weather availability |

## Frozen artifact (limited diagnostic)

The Phase 7 captured artifact contains no prospectively captured PM/weather
feature evidence, so the frozen Phase 8 artifact reports
`status = limited_diagnostic` with
`status_reasons: ["input_phase7_missing_pm_history", "input_phase7_missing_forecast_weather"]`.
All 72 feature-based and weather-augmented metric cells
(`persistence_last_available` 18, `persistence_lag_1h` 18, `trailing_mean_24h`
18, `weather_augmented_climatology` 18) are `unavailable` with
`metric_reason = no_eligible_target_prediction_pairs`; their predictions are
recorded as `unavailable` with `missing_feature` or
`no_finite_captured_weather_features`. The 18 `local_hour_climatology` cells
(pooled, `openaq_11357424`/cmt8 and `openaq_14581375`/oceanpark × 2 horizons ×
3 splits) are available from non-purged training targets only and remain
`descriptive_only` calendar diagnostics, not forecast-skill estimates. No
score was fabricated for an unavailable cell, and `test_selection_used = false`.

| Item | Value |
| --- | --- |
| Input feature version | `phase7_features_v7`; availability `captured` |
| Input rows | 8,548 feature rows = 8,548 target rows (2 sensors × 2,137 origins × 2 horizons) |
| Input manifest SHA-256 | `6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa` |
| Input summary SHA-256 | `7fd1bfd725c5bec6df0088adf52af1f6e34f08d7d2244bb95b6172f7896e4d0b` |
| Input features SHA-256 | `2e2829e8cd14444ce4da322dc4f288ebb49baa05dba14423529bea2c866e092c` |
| Input targets SHA-256 | `d3e5198ccba3814259e5c9e8cfe647f481d58481b1bb8d774997e982e0f51073` |
| Input SUCCESS SHA-256 | `a7ea4cb56d378766ca83561d9e290bec3703ac161b88f69d4200ff155fbd2297` |
| Input bundle digest / file SHA-256 | `4cf5e9537758308a67c09e00cc9af3931946bab8ea64c6520cac36f1d3ed3c4e` / `c797e03a21f45d00fc5dd92647a0c37106476860cae2d47b19a3a8757c530894` |
| Boundary | mode `frozen`, assertion applied; cutoff `2026-09-06T20:59:00.669630Z`, window `2026-06-08`–`2026-09-06` |
| Split (shared) | train/validation/test 60/20/20; validation `2026-07-31T10:00Z`, test `2026-08-18T05:00Z` |
| Horizons | 6 and 24 hours |
| Implementation SHA-256 | `baselines.py 3b1dbe3af26be8724f68ea80b6167fcd6cd87622c8cdd415246061542c0f102d`; `baselines_output.py b6ec11df961abb687fc5ba888b62028e7596ee53b4fbb9db907b57101928de85` |
| Metric cells | 90 total; 18 available (calendar climatology only); 72 unavailable |
| Manifest SHA-256 | `ec651c4df04cb605f8849c1af96a3aea58f0902370e16ec39b9c48fdee22775e` |

Output directory files: `phase_8_baselines_summary.json`,
`phase_8_baseline_metrics.csv`, `phase_8_predictions.csv`,
`phase_8_assumptions.md` and `SUCCESS.json`.

## Tests and verification

| Check | Result |
| --- | --- |
| `tests/test_baselines.py` | 26 tests passed |
| Offline suite | 209 passed, 2 credential skips (`unittest discover -s tests`) |
| Isolated PostgreSQL suite | 52 passed via the disposable-cluster `scripts/test_database.py`; Phase 8 added no database code |
| Markdown/local-link integrity | `tests.test_research_artifacts` passed as part of the offline suite |
| `git diff --check` | Clean |
| CLI `baselines run` | `python -m vn_air.cli baselines run` reproduced the v2 artifact byte-identical (5/5 files including SUCCESS.json) |
| Deterministic replay | Module and CLI replay regenerated all five files byte-identical from the same input artifact and recorded summary; replay is portable across equivalent input paths |
| Database writes / migrations | None; run and replay are database-free |

The local macOS dataless `.venv` was hydrated on demand during this runtime, so
the full offline and isolated PostgreSQL gates completed. The installed
`.venv/bin/vn-air` entry point predates the Phase 7/8 subcommands and rejects
`baselines`/`features` until the package is reinstalled; the documented
`PYTHONPATH=src .venv/bin/python -m vn_air.cli` invocation was used instead, as
in the Phase 7 record.

## Limits and next-phase boundary

The frozen window still has no captured evidence, so Phase 8 evaluated no
baseline on real data and produced no baseline performance result. The
feature-based and weather-augmented mechanics are implemented and tested on
synthetic fixtures (including a finite-captured-weather case), but their frozen
cells remain unavailable. A prospective collection period is required before
captured operational baselines exist; assumed-lag artifacts remain an
explicitly user-authorized scenario, never an operational backtest. Phase 9 ML
must reuse the same shared chronological split, purge, train-only
transformations and untouched test period; pooled metrics remain a descriptive
combination of two non-reference sensor sites, not a city or population
estimate.
