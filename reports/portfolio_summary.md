# Vietnam Weather & Air Quality Analytics: curated results

Status: Phase 12 portfolio polish. Every number below is traced to a frozen
verification artifact; the generated walkthrough bundle is at
[`docs/verification/phase_12_portfolio_2026-09-14_review_corrected/`](../docs/verification/phase_12_portfolio_2026-09-14_review_corrected/manifest.json).
Nothing here is a model-performance, forecast-skill, causal, city-wide exposure
or health claim.

## Data scope

| Item | Value | Evidence |
| --- | --- | --- |
| Research question | How weather relates to ground-level PM2.5 at monitored sites, and whether forecast-time weather adds skill at 6h/24h beyond PM history | [README](../README.md#research-question), [source decision](../docs/decisions/0001-data-sources.md) |
| Measured sites | CMT8 (HCMC) and OceanPark (Hanoi urban area), non-reference AirGradient sensors | [Phase 4](../docs/verification/phase_4.md) |
| Frozen window | 2026-06-08T00:00Z to 2026-09-06T00:00Z (cutoff 2026-09-06T20:59:00.669630Z) | [Phase 4](../docs/verification/phase_4.md) |
| Measured coverage | 4,191 accepted hours; CMT8 2,154/2,160 (99.72%), OceanPark 2,037/2,160 (94.31%) | [Phase 4](../docs/verification/phase_4.md) |
| Shared hours | 2,035 timestamps with an accepted reading from each sensor (4,070 sensor-hours) | [Phase 5](../docs/verification/phase_5.md) |
| Reanalysis context | ERA5 at station coordinates; 2,033 CMT8 / 1,916 OceanPark complete nine-variable hours | [Phase 4](../docs/verification/phase_4.md) |
| Modeled context | CAMS via Open-Meteo for Hanoi, HCMC and modeled-only Da Nang | [Phase 5](../docs/verification/phase_5_eda_2026-09-07_final/eda_summary.json) |
| Forecast snapshots | Provenance only in Phases 5/6; the only permitted captured weather source in Phase 7, unavailable in this frozen window | [Phase 5](../docs/verification/phase_5.md), [Phase 7](../docs/verification/phase_7.md) |

## Phase 4-5: quality and descriptive EDA

- CMT8 misses 6 hours (longest gap 3 h); OceanPark's 94.31% coverage includes a
  119-hour outage from 2026-07-01T02:00Z to 2026-07-06T00:00Z. Gaps are
  preserved; there is no imputation and no model substitution.
- All 4,191 selected measured hours were provisionally accepted; 24 CMT8
  revision transitions changed source metadata only, never the PM2.5 value.
- Descriptive hourly PM2.5: CMT8 mean 22.71, median 20.9, IQR 15.2-28.9,
  maximum 82.2 ug/m3; OceanPark mean 32.01, median 31.1, IQR 19.8-41.8,
  maximum 149.0 ug/m3. One-hour persistence is r = 0.810 (CMT8) and 0.869
  (OceanPark); the largest descriptive weather correlation is wind speed,
  -0.339 (CMT8) and -0.310 (OceanPark).
- These are sample summaries over one 90-day window at two sites. They do not
  adjust for season, time of day, autocorrelation or sensor bias, and they are
  not city or population estimates.

Evidence: [Phase 4 record](../docs/verification/phase_4.md),
[Phase 5 record](../docs/verification/phase_5.md),
[walkthrough 01](../docs/verification/phase_12_portfolio_2026-09-14_review_corrected/01_data_quality_and_eda.md).

## Phase 6: pre-registered sensor associations

H1/H2 form the primary Holm family (pairwise_complete weather, log1p scale,
1-day blocks). Their estimates are the adjusted change in log1p(PM2.5) per one
analysis-window standard deviation of the exposure. H3 is the temporally
adjusted OceanPark-minus-CMT8 contrast, with no weather exposure term.

| Hypothesis | n (sensor-hours) | Estimate | 95% interval | Raw p | Holm-adjusted p |
| --- | --- | --- | --- | --- | --- |
| H1 wind speed (pooled) | 3,951 | -0.208 | [-0.257, -0.166] | 0.0010 | 0.0020 |
| H2 relative humidity (pooled) | 3,951 | +0.099 | [-0.006, +0.186] | 0.0680 | 0.0680 |
| H3 site contrast (shared hours) | 4,070 | +0.179 | [+0.060, +0.296] | 0.0030 | not applicable |

Only the Holm-adjusted H1/H2 results carry the inferential label; H2 is not
significant. H3 uses 4,070 sensor-hours from 2,035 shared timestamps. Its raw
p-value and interval remain exploratory. After Holm adjustment, only H1
remains significant at 0.05. The secondary
family (temperature, precipitation, surface pressure, cloud cover, shortwave
radiation) is Benjamini-Hochberg adjusted; only cloud cover survives FDR 0.05
(estimate -0.090, interval [-0.127, -0.048], BH p 0.010). Precipitation's raw
p of 0.036 does not survive adjustment. Wind-speed conclusions are stable
across raw scale (-4.51 ug/m3 per SD [-5.49, -3.55]), 48-hour blocks
([-0.259, -0.159]), complete-weather rows ([-0.254, -0.165]) and the
predeclared extreme-value rule ([-0.256, -0.162]); seven-day blocks are
descriptive-only by the pre-declared independent-partition gate.

Uncertainty uses 2,000 moving-block bootstrap replicates over Vietnam local
calendar days (seed 20260908; 1/2/7-day blocks; exactly 91 dates per replicate;
gaps preserved). Sensor-level associations over one frozen 90-day window at two
non-reference sites are the only supported statement: no city-wide exposure,
causal effect or forecast skill.

Evidence: [Phase 6 record](../docs/verification/phase_6.md),
[Phase 6 plan with correction addendum](../docs/verification/phase_6_plan.md),
[corrected statistics summary](../docs/verification/phase_6_statistics_2026-09-09_corrected/phase_6_statistics_summary.json),
[walkthrough 02](../docs/verification/phase_12_portfolio_2026-09-14_review_corrected/02_sensor_associations.md).
The 2026-09-08 output is superseded and preserved unchanged.

## Phase 7: availability-aware feature contract

- Two explicit availability modes: `captured` (evidence strictly before the
  origin) and `assumed` (a declared, user-authorized scenario). There is no
  silent fallback. Horizons are exactly 6 and 24 hours; `target_end = origin + h`
  over the measured interval `[target_end - 1h, target_end)`.
- Source separation is strict: measured OpenAQ PM2.5 for targets/history,
  Open-Meteo forecast snapshots as the only captured weather source; ERA5 and
  CAMS are excluded from the captured matrix and missing PM2.5 is never
  replaced with model output.
- One shared 60/20/20 chronological split (validation starts 2026-07-31T10:00Z,
  test starts 2026-08-18T05:00Z) with horizon purge (112 rows); the test period
  stays untouched.
- The frozen artifact is a limited diagnostic: 8,548 feature rows over 2,137
  origins, but zero captured PM-history and zero forecast-weather origins, all
  data features null with explicit reasons, and
  `prospective_collection_period_required = true`. A prospective collection
  period is required before captured operational features exist.

Evidence: [Phase 7 record](../docs/verification/phase_7.md),
[authoritative feature summary](../docs/verification/phase_7_features_2026-09-10_structural_hardened/phase_7_feature_summary.json),
[walkthrough 03](../docs/verification/phase_12_portfolio_2026-09-14_review_corrected/03_feature_baseline_ml_contract.md).

## Phase 8: chronological baselines

- Declared baselines: `persistence_last_available` (primary history-only
  reference), `persistence_lag_1h`, `trailing_mean_24h`, train-only
  `local_hour_climatology` and `weather_augmented_climatology` (only when
  finite captured weather exists; no ERA5/CAMS/assumed fallback).
- Frozen result: 90 metric cells in total; 72 are unavailable with explicit
  reasons because the captured feature families are empty, and no score was
  fabricated. The 18 available cells are train-only local-hour calendar
  diagnostics; every cell is `descriptive_only`, and test was never used for
  fitting or selection.

Evidence: [Phase 8 record](../docs/verification/phase_8.md),
[authoritative baseline summary](../docs/verification/phase_8_baselines_2026-09-11_v2_verified/phase_8_baselines_summary.json).

## Phase 9: chronological Ridge and shallow bagged-tree diagnostics

- Declared feature sets are exactly `calendar_only`, `history_only`,
  `weather_only` and `history_weather`; target transforms `log1p` and `raw`;
  scopes `pooled` and `per_sensor`; families Ridge (train-only standardization,
  predeclared alpha grid, validation-RMSE selection) and 25-tree shallow bagged
  ensembles. The final model is refit on train plus validation and test is
  scored once.
- Frozen result: 24 of 96 model instances trained (calendar-only), 72 of 288
  metric cells available, 216 unavailable with explicit reasons, 65,424
  auditable prediction rows and 360 descriptive comparison records;
  `test_selection_used = false`. No history or weather model has been evaluated
  on real data, so there is no forecast-skill or model-superiority claim.
- Comparison records label unequal fit histories and are descriptive only; they
  do not isolate an effect of model family or weather features.

Evidence: [Phase 9 record](../docs/verification/phase_9.md),
[authoritative model summary](../docs/verification/phase_9_models_2026-09-12_comparison_hardened/phase_9_model_summary.json).

## Phase 10: local research dashboard

The Vietnam Air Observatory is a static, loopback-only dashboard over a
hash-verified public projection of the frozen Phase 5-9 artifacts. Bundle
identity: schema `phase10_dashboard_v1`, canonical digest
`b3b43813751628cc0d3439c209484a7c588cbdc9f355eb38cbe9233b1e0a167d`.

```bash
python3 -B scripts/serve_dashboard.py
```

Open http://127.0.0.1:8765/. It is a local presentation of limited diagnostics,
not deployed monitoring. Evidence: [Phase 10 record](../docs/verification/phase_10.md),
[walkthrough 04](../docs/verification/phase_12_portfolio_2026-09-14_review_corrected/04_dashboard_and_reproducibility.md).

## Phase 11: automation tooling, not activated

Reviewed Phase 11 tooling (strict profile, supervised bounded cycle, read-only
health/recovery, project-scoped native backups with a synthetic restore drill,
CI and launchd templates) is delivered and locally verified. No scheduler is
installed, no live cycle or real project backup has run, and there is no
least-privilege ingestion role yet. Activation requires explicit authorization
and a grants/RLS review; see [operations](../docs/operations.md) and the
[Phase 11 record](../docs/verification/phase_11.md).

## Remaining work

1. Portfolio polish is complete through Phase 12; no further planned roadmap
   phase remains for the local system.
2. Optional operational activation: least-privilege role, grants/RLS review,
   secret store, backup destination and scheduler installation, all separately
   authorized.
3. Prospective captured collection: run the reviewed cycle over a future period
   so captured PM-history and forecast-weather evidence exists, then re-run
   Phases 7-9 on that new evidence. Real forecast evaluation is blocked until
   then; assumed-lag artifacts remain a declared scenario, never an operational
   backtest.
