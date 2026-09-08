# Phase 6 Statistical Analysis Verification

Date: 2026-09-09 UTC. Scope: pre-registered, sensor-level weather–PM2.5
association estimates with dependence-aware uncertainty, replayed from the frozen
Phase 5 dataset. This phase makes no causal, city-wide exposure, operational
forecast, health or model-performance claim. No database migration, schema change
or Supabase write occurred.

**Authoritative artifact: `phase_6_statistics_2026-09-09_corrected/`.** The
earlier `phase_6_statistics_2026-09-08_final/` output is superseded for
verification because a review found four implementation-contract errors (no
complete-weather sensitivity; overlapping moving windows used as the
independent-block gate; two-day bootstrap replicates sampled 92 instead of 91
dates; gate passage labelled every fit inferential). It is preserved unchanged.
The correction is documented in the 2026-09-09 addendum to
[phase_6_plan.md](phase_6_plan.md); it changed implementation mechanics only —
not hypotheses, estimands, scales, seed, replicates, adjustment families, gate
thresholds or the p-value formula. Point estimates and one-day-block intervals
are unchanged from the superseded artifact.

## Pre-registration

The hypotheses, estimands, adjustment set, block policy, seed, multiple-testing
rules, rank policy and extreme-value review rule were fixed in
[phase_6_plan.md](phase_6_plan.md) before any Phase 6 estimate was computed. The
dated correction addendum (section 9) fixed the weather-case definitions, the
non-overlapping independent-partition gate, the exact bootstrap sample-length
rule and the inference-label rule before any corrected p-value or interval was
computed. The statistics implementation reads the frozen Phase 5 EDA bundle
only; it does not touch the database.

## Implementation

`vn-air stats run` (source: `src/vn_air/statistics.py` v2,
`src/vn_air/statistics_output.py`) verifies the Phase 5 bundle integrity and
frozen-boundary hash, reconciles the frozen counts, then fits 31 ordinary least
squares models with pure-stdlib linear algebra:

- Primary scale `log1p(PM2.5)`; raw PM2.5 as labelled sensitivity.
- Adjustment set: sensor fixed effect (pooled/shared fits), Vietnam local-hour
  fixed effects (reference hour 0), weekday fixed effects (reference Monday) and
  a centered linear day trend. Empty levels are dropped deterministically.
- Weather cases: `pairwise_complete` (accepted response plus finite exposure
  only; the exposure-specific complete-case fits), `complete_weather`
  (additionally every observed bundle weather variable finite — H1, H2 and all
  five secondary pooled log1p sensitivity variants) and `not_applicable` (H3,
  which has no exposure term). The observed variable set is recorded in the
  manifest: apparent_temperature, cloud_cover, precipitation,
  relative_humidity_2m, shortwave_radiation, surface_pressure, temperature_2m,
  wind_direction_10m, wind_speed_10m. Nothing is imputed or backfilled.
- Exposures standardized per fit on eligible rows (means and scales in the
  manifest). Complete cases per fit.
- Moving-block bootstrap over Vietnam local calendar days: 2,000 replicates,
  one Mersenne Twister generator seeded `20260908`, replicates outermost.
  Each replicate draws `divmod(91, block_days)` full-length moving windows plus
  one remainder-length window when needed, so every replicate spans exactly 91
  dates (two-day blocks: 45 two-day windows plus one one-day window, never 92;
  seven-day blocks: 13 seven-day windows). Moving windows are resampling
  candidates only — they overlap and are counted separately as
  `candidate_windows`, never as the gate.
- Gate: deterministic non-overlapping partitions of the ordered local calendar
  dates anchored at the first frozen study date (chunks of at most `block_days`
  dates with a final shorter chunk); at least 30 non-empty and 20 eligible
  independent partitions required for inferential output. The frozen window
  yields 91, 46 and 13 independent partitions for one-, two- and seven-day
  blocks, so seven-day fits are descriptive-only by construction.
- Percentile 95% intervals; two-sided bootstrap tail p-values
  `2*min(P(beta<=0), P(beta>=0))` as `(count+1)/(usable+1)`.
- Holm adjustment over the two primary pooled p-values; Benjamini–Hochberg over
  the five declared secondary pooled p-values.
- Inference labels: `inferential` only for the Holm/BH-adjusted family members;
  `exploratory` for gate-passing unadjusted fits (site-specific, H3, raw-scale,
  block-length, complete-weather, extreme-value); `descriptive_only` when the
  gate fails or the output is descriptive. Unadjusted p-values are exploratory
  diagnostics, not findings.
- Full-sample rank deficiency stops the run; rank-deficient replicates are
  discarded and reported (zero were discarded).

Command used:

```bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli stats run \
  --bundle docs/verification/phase_5_eda_2026-09-07_final/eda_bundle.json \
  --phase4-artifact docs/verification/phase_4_quality_2026-09-07_final.json \
  --output-dir docs/verification/phase_6_statistics_2026-09-09_corrected
```

## Frozen boundary

| Item | Value |
| --- | --- |
| Phase 5 bundle digest | `92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63` |
| Phase 5 bundle file SHA-256 | `00012495fd3fc455f5d9e43fdac18de9fd42ef686678f4ee843fa9ade82da18c` |
| Cutoff / window | `2026-09-06T20:59:00.669630Z`; `2026-06-08T00:00:00Z` to `2026-09-06T00:00:00Z` |
| Reconciliation | 4,191 accepted rows; 129 absent; 2,154 CMT8; 2,037 OceanPark; 2,033/1,916 complete-weather; 2,035 shared hours |
| Schema | `0003_response_integrity` |
| Corrected statistics manifest SHA-256 | `71f7b17bff4bd43a406d235bbc585a268ec56b07f2554cc2b19939b5b5dcf918` |

The Phase 5 bundle file hash equals the value recorded in the Phase 5
`SUCCESS.json`, confirming the exact replayed artifact.

## Outputs

[phase_6_statistics_2026-09-09_corrected/](phase_6_statistics_2026-09-09_corrected/)
contains `phase_6_statistics_summary.json` (manifest with gate method, draw
policy, per-fit draw counts, independent-block counts, weather variables,
pairwise correlations, formulas, standardization, adjustments; plus all 31 fit
records), `phase_6_estimates.csv`, `phase_6_bootstrap_summary.csv`,
`phase_6_assumptions.md` and `SUCCESS.json` with per-file hashes.
Wind-direction and apparent-temperature remain descriptive-only per the plan.

## Primary results (pairwise_complete, log1p scale, 1-day blocks)

| Hypothesis | Fit | n | Estimate | 95% interval | Label |
| --- | --- | --- | --- | --- | --- |
| H1 wind speed | pooled (Holm) | 3,951 | −0.208 | [−0.257, −0.166] | inferential; adjusted p 0.0020 |
| H1 wind speed | CMT8 | 2,034 | −0.187 | [−0.235, −0.135] | exploratory |
| H1 wind speed | OceanPark | 1,917 | −0.226 | [−0.304, −0.147] | exploratory |
| H2 humidity | pooled (Holm) | 3,951 | +0.099 | [−0.006, +0.186] | inferential; adjusted p 0.068 |
| H2 humidity | CMT8 | 2,034 | −0.075 | [−0.135, −0.006] | exploratory |
| H2 humidity | OceanPark | 1,917 | +0.179 | [+0.025, +0.323] | exploratory |
| H3 site contrast | shared hours | 4,070 | +0.179 | [+0.060, +0.296] | exploratory; p 0.0030 |

Estimates are the adjusted change in `log1p(PM2.5)` per one analysis-window
standard deviation of the exposure (H3: OceanPark minus CMT8). After Holm
adjustment, H1 remains significant at the 0.05 level; H2 does not. H3 is an
unadjusted exploratory sensor contrast, not a city comparison or a finding.
These are sensor-level associations over one 90-day window, not city-wide
exposure or causal effects.

## Secondary family (pairwise_complete, pooled, BH-adjusted, all labelled inferential)

| Exposure | Estimate | 95% interval | raw p | BH-adjusted p |
| --- | --- | --- | --- | --- |
| temperature_2m | −0.012 | [−0.121, +0.092] | 0.869 | 0.880 |
| precipitation | −0.046 | [−0.082, −0.005] | 0.036 | 0.090 |
| surface_pressure | +0.117 | [−0.033, +0.254] | 0.140 | 0.233 |
| cloud_cover | −0.090 | [−0.127, −0.048] | 0.002 | 0.010 |
| shortwave_radiation | +0.016 | [−0.109, +0.130] | 0.880 | 0.880 |

Only cloud cover survives Benjamini–Hochberg FDR at 0.05. Precipitation's raw
p-value does not survive adjustment. These are exploratory, pre-declared family
members — not confirmed findings.

## Sensitivity

- Raw PM2.5 scale (exploratory): H1 −4.51 µg/m³ per SD [−5.49, −3.55]; H2 +1.51
  [−0.82, +3.81] (not significant); H3 +8.97 [+6.12, +11.92]. Conclusions match
  the log1p scale.
- Two-day blocks (exploratory, 46 partitions, 45+1 draw rule): H1 CI
  [−0.259, −0.159]; H2 remains non-significant. Seven-day blocks (13
  partitions): descriptive-only under the gate — point estimates are reported,
  no intervals or p-values (H1 −0.208; H2 +0.099; H3 +0.179).
- Complete-weather fits (exploratory, 3,949 rows each): H1 −0.208
  [−0.254, −0.165]; H2 +0.099 [−0.001, +0.195]; cloud cover −0.090
  [−0.128, −0.049]. Exposure-specific complete cases and complete-weather rows
  are distinguished throughout; pairwise-complete rows for wind total 3,951
  (CMT8 2,034, OceanPark 1,917) and for humidity 3,951.
- Pairwise-complete versus complete-weather descriptive correlations (28
  per-sensor records: 7 exposures × 2 sensors × 2 row classes) are in the
  summary manifest and assumptions report with counts and Pearson values; they
  carry no interval, p-value, adjustment or inferential label.
- Extreme-value rule (Tukey fence Q3+3·IQR within sensor; exploratory): CMT8
  fence 70.0 µg/m³ flagged 1 hour; OceanPark fence 107.8 flagged 5 hours.
  Excluding flagged hours changes no conclusion (H1 −0.207 [−0.256, −0.162]).
  Flagged rows keep their Phase 4 labels everywhere.

## Verification

| Check | Result |
| --- | --- |
| Offline unittest suite | 93 passed (69 prior + 24 statistics tests incl. new partition/draw/label/weather-case tests); 2 credential checks skipped without `.env` |
| Corrected-run manual checks | Frozen digest and reconciliation unchanged; manifest lists the 9 bundle weather variables; pairwise-complete and complete-weather fits distinguishable (3,951 vs 3,949 pooled eligible hours); 28 descriptive correlations present and non-inferential; independent partitions 91/46/13 by block length; every fit sampled exactly 91 dates (no 92); only Holm/BH family members labelled inferential; all seven-day fits descriptive-only; SUCCESS.json hashes present |
| Deterministic-seed replay | `stats replay` byte-identical for all five required files (summary JSON SHA-256 `12a7236c50365c7777a0b07a7ac497167f0cb1bea6e57e963aa97dc5e3fb838d`, estimates CSV `3d6a3f7e5a0ff4764da9596a4864af0619284fe78ae2b887c0f505d5d7cab306`, bootstrap CSV `1fb8df8d339dce542c99a45be2b30f4c44a1b41fad9d02cb5c701fdf090b58f3`, assumptions MD `49f05deba3955319120c2c0b1ea8403e6dac5b2ddb756c5a0a630c7a647133d4`) |
| Isolated PostgreSQL suite | 45 passed (own disposable cluster; no schema or migration changes in Phase 6) |
| `git diff --check` | Clean |
| Narrow live read-only check | Supabase counts at the cutoff match the Phase 4 extraction exactly: schema `0003_response_integrity`, 4,215 measurement rows, 72 snapshots, 122 responses, 108 runs, 85,320 model values |
| Database writes | None; the statistics path reads the Phase 5 bundle only |

Corrected complete-weather versus pairwise-complete row counts (pooled): wind
3,949 complete-weather versus 3,951 pairwise-complete eligible hours; humidity
3,949 versus 3,951; each secondary exposure 3,949 versus 3,949–3,951 depending
on that exposure's own pairwise gaps. Per-fit values are in the estimates CSV.

## Limits

Two non-reference low-cost sensors over one 90-day window; no annual cycle, no
calibration certification and no city-wide representativeness. ERA5 is
retrospective reanalysis, not a site measurement, and its retrieval time is not
historical availability. Adjustment removes measured temporal structure, not
confounding; residual autocorrelation beyond 7-day blocks may remain. Overlapping
moving windows are resampling candidates, not independent evidence units; the
gate uses non-overlapping date partitions, and seven-day sensitivity is
descriptive-only by construction. Bootstrap p-values are exact only under the
resampling model. Site-specific, raw-scale, block-length, complete-weather and
extreme-value results are unadjusted exploratory output; unadjusted p-values are
diagnostics, not findings. The next phase is availability-aware feature
engineering (Phase 7); no forecast skill or model performance has been evaluated.
