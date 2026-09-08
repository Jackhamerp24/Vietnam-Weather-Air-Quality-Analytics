# Phase 6 Statistical Analysis Plan

Status: pre-registered 2026-09-08 UTC. The decisions in section 3b were fixed
before any Phase 6 estimate, interval or p-value was computed. This document
defines the phase; it does not report statistical results and does not authorize
model training, scheduling or database writes.

## 1. Objective

Estimate weather–PM2.5 associations at the CMT8 and OceanPark sensor sites with
time-series-aware uncertainty. The study can support sensor-level association
statements over the frozen study period. It cannot support city-wide exposure,
causal effects, operational forecast skill or health advice.

## 2. Frozen evidence boundary

| Input | Required value |
| --- | --- |
| Phase 4 cutoff | `2026-09-06T20:59:00.669630Z` |
| Study window | `2026-06-08T00:00:00Z` to `2026-09-06T00:00:00Z` |
| Phase 4 artifact | `docs/verification/phase_4_quality_2026-09-07_final.json` |
| Phase 5 bundle | `docs/verification/phase_5_eda_2026-09-07_final/eda_bundle.json` |
| Phase 5 bundle hash | `92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63` |
| Repository commit | `173baf2` |
| Schema | `0003_response_integrity` |

The Phase 5 bundle records 4,191 accepted measured hours and 129 absent grid
hours. Complete nine-variable ERA5 rows number 2,033 for CMT8 and 1,916 for
OceanPark. Reconcile these counts before fitting any model. Stop if the Phase 4
or Phase 5 input hashes, configuration hash, schema revision or cutoff differ.
Create a new frozen evidence version before proceeding with changed inputs.

## 3. Primary hypotheses and estimands

Write the final hypothesis wording and formula into the result manifest before
calculating p-values or intervals.

### H1: wind speed

Within a sensor, PM2.5 varies with wind speed after adjustment for sensor, local
hour, weekday and a bounded date trend. The primary estimand is the adjusted
change in `log1p(PM2.5)` for a one-analysis-window-standard-deviation increase in
ERA5 `wind_speed_10m`.

### H2: relative humidity

Within a sensor, PM2.5 varies with relative humidity under the H1 adjustment set.
Use the same standardized `log1p(PM2.5)` estimand for comparability.

### H3: site contrast

CMT8 and OceanPark differ on the shared accepted-hour set. Interpret this as a
site contrast between two non-reference sensors, not a city contrast or a
population exposure estimate.

Temperature, precipitation, pressure, cloud cover and radiation form a
secondary exploratory exposure family. The plan must promote or demote each
secondary exposure before inferential results are calculated. Wind direction is
circular and cannot enter as an ordinary linear exposure. Wind sectors may be
reported as descriptive sensitivity output.

## 3b. Predeclared analysis decisions (fixed before fitting)

These decisions were written before any Phase 6 model was fit. They complete the
promotion/demotion rule required by section 3 and fix the remaining free choices.

### Exposure families

- Primary exposures: `wind_speed_10m` (H1) and `relative_humidity_2m` (H2), each
  in its own separate model with the full adjustment set.
- Declared secondary inferential family (five members, pooled fixed-effect fit,
  log1p scale, Benjamini–Hochberg FDR): `temperature_2m`, `precipitation`,
  `surface_pressure`, `cloud_cover`, `shortwave_radiation`.
- Demoted to descriptive-only (no p-values, no intervals): `apparent_temperature`
  (near-duplicate of `temperature_2m` on the frozen window) and
  `wind_direction_10m` (circular; Phase 5 wind sectors remain the descriptive
  wind-direction output). These two cannot be promoted after seeing results.

### Model terms and transforms

- Primary response scale: `log1p(PM2.5)`. Raw PM2.5 is retained as a declared
  sensitivity scale, fitted identically.
- `day_index` is the integer index of the Vietnam local calendar date
  (Asia/Ho_Chi_Minh) counted from `2026-06-08` local, entered centered on its
  eligible-row mean (predeclared simple linear trend; no higher basis).
- Fixed-effect levels are the observed local hours `0`–`23` (reference `0`) and
  weekdays Monday–Sunday (reference Monday). Levels with zero eligible rows in a
  fit are dropped deterministically before rank checking; any remaining rank
  deficiency stops the run.
- Exposures are standardized (mean 0, sample standard deviation 1) on the
  eligible analysis rows of each fit; the means and scales are recorded in the
  manifest. A zero standard deviation stops the run.
- The pooled fits include a CMT8/OceanPark indicator; site-specific fits omit
  it. For H3 the sensor indicator is the estimand (OceanPark minus CMT8) on the
  shared accepted-hour set.

### Uncertainty and inference

- Bootstrap unit: one contiguous block of Vietnam local calendar dates
  (aligned to local midnight; block lengths 1, 2 and 7 days). Blocks are drawn
  with replacement from every contiguous window of that length (moving starts at
  day granularity). Pooled and H3 fits resample local dates jointly for both
  sensors; site-specific fits resample that sensor's dates. Rows inside sampled
  blocks keep their original missing pattern.
- Replicates: 2,000 per fit and block length. RNG: CPython Mersenne Twister,
  one generator seeded `20260908`, block starts drawn with `randrange` in a
  fixed order (replicates outer, draws inner).
- Interval: percentile 95% interval (2.5th/97.5th percentiles of replicate
  estimates).
- p-value (only where the block gates pass): two-sided bootstrap tail statistic
  `2*min(P(beta*<=0), P(beta*>=0))` computed as `(count+1)/(B+1)` with the sign
  of the point estimate.
- Gate counts are computed on the observed (unsampled) blocks: non-empty blocks
  contain at least one accepted PM2.5 row; eligible blocks contain at least one
  complete-case row for that fit. Inferential output requires >=30 non-empty and
  >=20 eligible blocks.
- Multiple testing: Holm step-down over exactly the two primary p-values (H1
  pooled, H2 pooled); Benjamini–Hochberg over exactly the five declared
  secondary p-values. Site-specific and sensitivity p-values are unadjusted and
  labelled exploratory.
- OLS: normal equations solved by partial-pivoted Gaussian elimination on
  Jacobi-scaled columns; the smallest pivot magnitude must exceed
  `1e-8 * max(diagonal)` of the scaled system and `n` must exceed the column
  count, else the run stops.

### Extreme-value review rule (sensitivity only)

Flag an accepted PM2.5 row when its value exceeds the within-sensor Tukey upper
fence `Q3 + 3*IQR` of accepted PM2.5 over the frozen window (type-7 quartiles).
Flagged rows keep their Phase 4 labels, stay in every primary fit, and are
excluded only in the labelled extreme-value sensitivity refit, with flag counts
reported. No source row is deleted or relabeled.

### Replay and determinism

- `stats run` reads the Phase 5 bundle (verifying its `bundle_sha256` against
  the frozen value in section 2), optionally re-verifies the Phase 4 artifact
  file hash, and writes a new output directory.
- `stats replay` recomputes the identical outputs from the same Phase 5 bundle
  into a new directory without database access; replay equality is checked by
  SHA-256 of every output file.
- Floating-point results are stored rounded to 12 significant digits so replay
  hashes are stable.

## 4. Selection and alignment

- Select the latest eligible OpenAQ revision before quality filtering.
- Use provisionally accepted PM2.5 rows for the primary analysis.
- Keep absent and excluded hours visible in coverage tables.
- Join ERA5 at the actual sensor coordinates.
- Join instantaneous weather at the PM interval start.
- Join preceding-hour precipitation and shortwave radiation at the PM interval
  end.
- Keep CAMS and provider forecast values out of the measured-target inferential
  model.
- Do not use retrospective ERA5 retrieval time as operational availability.
- Do not interpolate, center-roll, backfill or replace missing measurements.

## 5. Statistical design

- Fit the primary response on `log1p(PM2.5)` and retain raw PM2.5 as a declared
  sensitivity scale.
- Include sensor fixed effects, Vietnam local-hour fixed effects, weekday fixed
  effects and a predeclared simple date trend or low-degree temporal basis.
- Fit separate primary models for wind speed and humidity:
  `log1p_pm25 ~ sensor + local_hour + weekday + day_index + standardized_exposure`.
  Report site-specific and pooled fixed-effect fits. Do not add interactions
  after viewing results.
- Standardize exposures using eligible analysis rows only. Store means and scales
  in the manifest.
- Use complete cases per exposure model. Report the resulting sample and coverage.
- Use moving/block bootstrap over Vietnam local calendar days for primary
  uncertainty. Use 2,000 replicates with seed `20260908`. Predeclare a
  24-hour block and evaluate 48-hour and 168-hour blocks as sensitivity checks.
  Preserve gaps inside sampled blocks.
- Require at least 30 non-empty independent blocks and at least 20 blocks with
  eligible rows for the estimate before emitting inferential output. Below that
  threshold, emit descriptive estimates and a limitation.
- Apply Holm adjustment to the two primary p-values. Apply Benjamini–Hochberg
  FDR to the declared secondary exposure family. Keep primary results separate.
- Report effect estimate, interval, p-value where justified, sample size,
  accepted coverage, independent block count, formula and assumptions.

## 6. Required sensitivity matrix

Run and label the following before interpreting results:

- CMT8 and OceanPark separately;
- shared accepted sensor-hours for H3;
- raw PM2.5 and log1p(PM2.5);
- 24-, 48- and 168-hour bootstrap blocks;
- complete-weather rows versus pairwise-complete descriptive correlations;
- with and without the predeclared extreme-value review rule, preserving raw
  rows and Phase 4 quality labels.

## 7. Deliverables

- A read-only statistics module or CLI.
- A frozen analysis manifest with Phase 4/5 hashes, code hash, formulae, sample
  counts, block counts, transforms, model formulas, adjustment methods and random
  seed `20260908`.
- Estimate, interval and result tables.
- An assumptions and limitations report.
- Expected artifact names: `phase_6_statistics_summary.json`,
  `phase_6_estimates.csv`, `phase_6_bootstrap_summary.csv`,
  `phase_6_assumptions.md` and `SUCCESS.json`.
- Synthetic tests for block sampling, gaps, period alignment, rank deficiency,
  deterministic replay and multiple-comparison correction.
- No database migration, Supabase write, model training or operational forecast
  claim.

## 8. Verification gates

Before declaring Phase 6 complete, run:

1. The offline unittest suite.
2. The isolated PostgreSQL suite.
3. `git diff --check`.
4. Deterministic-seed replay of the complete statistical artifact.
5. Synthetic block-bootstrap, gap, alignment, rank-deficiency and FDR tests.
6. One narrow live read-only run against the frozen Supabase dataset.

Stop on input-hash mismatch, rank deficiency, failed assumptions, insufficient
independent blocks or ambiguous availability semantics. No independent Oracle
review occurred in prior phases.

## 9. Correction addendum (2026-09-09 UTC)

This addendum is a dated amendment to the pre-registration above. It records a
mechanical implementation correction discovered during review of the first
Phase 6 run. It does not change the hypotheses, primary estimands, model
formulas, exposure standardization rule, extreme-value rule, seed, replicate
count, response scales, Holm family, Benjamini–Hochberg family, gate thresholds
or p-value formula. The 2026-09-08 artifact
(`phase_6_statistics_2026-09-08_final/`) is superseded for verification because
of the implementation-contract errors below, not because of its numerical
conclusions; it is preserved unchanged. No corrected p-value or interval was
computed before this addendum was written.

### 9.1 Weather-case definitions

- `complete_weather` row: a row with a finite accepted PM2.5 response and finite
  values for every weather variable present in the Phase 5 row's declared
  weather mapping. The exact variable names observed in the frozen bundle are
  recorded in the statistics manifest; no new variable list is hard-coded.
- `pairwise_complete` (previously the implicit default): a row with a finite
  accepted PM2.5 response and a finite value of the fit's exposure only. The
  existing exposure-specific complete-case fits are renamed to this case. It is
  not the same analysis as `complete_weather`.
- `not_applicable`: the H3 site contrast, which has no weather exposure term.
  Its shared accepted-hour definition is unchanged.

Absent PM2.5 and missing weather remain missing; nothing is imputed or
backfilled. New OLS sensitivity variants use the `complete_weather` row subset
for: H1 pooled log1p, H2 pooled log1p, and all five declared secondary pooled
log1p fits. Pairwise-complete descriptive correlations for the declared weather
exposure family are reported per sensor with row counts and the Phase 5 Pearson
convention; they receive no bootstrap interval, p-value, Holm/BH adjustment or
inferential label, and no new hypothesis is created for them.

### 9.2 Independent-block gate

Moving windows remain the bootstrap sampling candidates, but they overlap and
are not independent evidence units; their count is recorded only as
`candidate_windows` diagnostics. The inferential gate now uses deterministic
non-overlapping partitions of the ordered Vietnam local calendar dates, anchored
at the first frozen study date: consecutive chunks of at most `block_days`
dates, with a final shorter chunk when the count is not divisible, so every
study date belongs to exactly one chunk. For each fit the gate counts
`nonempty_independent_blocks` (chunks with at least one accepted PM2.5 row in
the fit's base data) and `eligible_independent_blocks` (chunks with at least one
eligible row for the fit) against the unchanged thresholds (>=30 and >=20). For
the frozen 91-date window this yields 91 one-day partitions, 46 two-day
partitions (including one final one-day partition) and 13 seven-day partitions;
seven-day sensitivity fits are therefore expected to be descriptive-only under
the gate. This is an expected limitation, not a runtime failure.

### 9.3 Exact bootstrap sample length

Every bootstrap replicate spans exactly the number of study calendar dates in
the frozen window (91). The predeclared draw rule replaces the previous
full-block ceiling (which sampled 92 dates for two-day blocks):

```
full_blocks, remainder = divmod(n_dates, block_days)
draw full_blocks moving windows of length block_days;
if remainder > 0, draw one additional moving window of length remainder;
aggregate exactly those sampled date spans.
```

For 91 dates: block length 1 draws 91 one-day windows; length 2 draws 45
two-day windows plus one one-day window (91 dates, never 92); length 7 draws 13
seven-day windows. The RNG remains one CPython `random.Random(20260908)`
generator, replicates outermost, draws in fixed order, with all observed gaps
preserved inside sampled spans. `sampled_dates_per_replicate` and the full/
remainder draw counts are recorded in the manifest and fit records.

### 9.4 Inference labels

Gate passage no longer implies an inferential label. A deterministic
classification assigns:

- `inferential`: the fit passed the gate and its p-value is a member of a
  declared multiple-testing family with the required adjustment (Holm for the
  two primary pooled p-values; Benjamini–Hochberg for the five declared
  secondary pooled p-values);
- `exploratory`: the fit passed the gate but is unadjusted (site-specific fits,
  H3, raw-scale, block-length, complete-weather and extreme-value
  sensitivities);
- `descriptive_only`: the gate failed, the output is a descriptive correlation,
  or no inferential p-value or interval is justified.

Only Holm- or BH-adjusted outputs may be described as inferential in any report.
Unadjusted p-values remain clearly labelled exploratory diagnostics; they are
not findings.
