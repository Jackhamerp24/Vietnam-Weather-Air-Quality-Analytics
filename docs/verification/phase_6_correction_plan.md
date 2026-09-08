# Phase 6 Correction Plan: Resolve Review Findings

Status: execution handoff for GLM 5.3 Flash
Date: 2026-09-09 UTC
Scope: correct the Phase 6 implementation and regenerate the statistical artifact

This document is self-contained. Execute it from the repository root without
relying on conversation history.

## 1. Objective

The current Phase 6 implementation is operational, but it must remain in
Request changes status until four contract mismatches are fixed:

1. The required complete-weather sensitivity is not implemented. Current fits
   use exposure-specific complete cases only and do not distinguish that from a
   complete-weather analysis.
2. The independent-block gate counts overlapping moving windows. Those windows
   are valid bootstrap candidates but are not independent blocks.
3. The bootstrap samples 92 dates for a 91-day study window when using a
   two-day block because it uses ceil(91 / 2) full blocks.
4. The output labels every gate-passing fit as inferential, including
   unadjusted site-specific, H3, raw-scale, block-length and extreme-value
   sensitivity results.

Resolve only these implementation/contract issues. Do not change the frozen
data, hypotheses, primary estimands, p-value formulas, thresholds, seed or
results in response to their direction or significance.

## 2. Repository and frozen evidence boundary

Work from:

/Users/duong/Desktop/Vietnam-Weather-Air-Quality-Analytics

Before editing, inspect the worktree. Existing Phase 6 files are currently
uncommitted; preserve all user changes and do not reset or clean the worktree.
The current branch is main, and the last committed Phase 5 revision is
173baf2. The existing Phase 6 output is an earlier artifact and must not be
overwritten:

docs/verification/phase_6_statistics_2026-09-08_final/

Use these frozen inputs exactly:

- Phase 5 bundle:
  docs/verification/phase_5_eda_2026-09-07_final/eda_bundle.json
- Frozen Phase 5 bundle digest:
  92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63
- Phase 4 artifact:
  docs/verification/phase_4_quality_2026-09-07_final.json
- Cutoff: 2026-09-06T20:59:00.669630Z
- Study window: 2026-06-08T00:00:00Z through 2026-09-06T00:00:00Z
- Seed: 20260908
- Bootstrap replicates: 2000 per fit
- Gate thresholds: at least 30 non-empty independent blocks and at least
  20 eligible independent blocks

Read before implementation:

1. AGENTS.md
2. README.md
3. docs/verification/phase_6_plan.md
4. docs/verification/phase_6.md
5. src/vn_air/statistics.py
6. src/vn_air/statistics_output.py
7. src/vn_air/cli.py
8. tests/test_statistics.py

Do not read, print, log, commit or paste .env or any credential-bearing
value. Do not add a dependency. Do not add a migration, write to Supabase,
change database state, train a model or create a schedule. The statistics path
must remain a deterministic, offline replay from the frozen Phase 5 bundle.

Do not commit or push as part of this plan unless the user separately
authorizes that action after reviewing the corrected result.

## 3. Pre-change documentation requirement

Before computing any corrected p-value or interval, add a dated correction
addendum to docs/verification/phase_6_plan.md. Do not silently rewrite the
original pre-registration. The addendum must state that this is a mechanical
implementation correction discovered during review, not a change to the
hypotheses or estimands.

The addendum must record all of the following decisions.

### 3.1 Complete-weather definition

Define a complete_weather row as a row with:

- a finite accepted PM2.5 response; and
- finite values for every weather variable present in the Phase 5 row's
  declared weather mapping.

Record the exact weather-variable names observed in the frozen bundle in the
manifest. Do not hard-code a new variable list that differs from the bundle.

Absent PM2.5 or missing weather remains missing; never impute or backfill it.

The existing exposure-specific complete-case analysis must be named
pairwise_complete or exposure_complete in the code and manifest. It is not the
same as complete_weather.

### 3.2 Complete-weather and pairwise-complete sensitivity

Add complete-weather OLS sensitivity variants for the exposure models. At
minimum, include H1 and H2 pooled log1p fits and all five declared secondary
pooled log1p fits using the same full-weather row subset. Preserve the existing
primary and secondary per-exposure fits as exposure-specific complete-case
fits.

Also add a pairwise-complete descriptive comparison for the declared weather
exposure family. The pairwise result for each exposure must use only finite
PM2.5 and finite values of that exposure, and must report at least:

- exposure name;
- response scale/name;
- pairwise-complete row count;
- descriptive correlation/effect value using the Phase 5 convention, or a
  clearly documented pure-Python equivalent if no reusable helper exists;
- whether the row is pairwise_complete or complete_weather.

Pairwise-complete descriptive correlations must not receive bootstrap
intervals, p-values, Holm/BH adjustment or an inferential label. They are
coverage/descriptive sensitivity output only. Do not turn them into a new
hypothesis test.

H3 is a site contrast with no weather exposure term. Keep its shared accepted-
hour definition unchanged. It does not need a pairwise-weather correlation
variant, but its weather coverage and weather_case must be explicit as
not_applicable.

### 3.3 Independent-block gate

Keep moving windows for bootstrap candidate sampling, but never use their
overlapping count as the independent-block gate.

For each block_days value, create deterministic non-overlapping partitions of
the ordered Vietnam local calendar dates, anchored at the first frozen study
date. Partition the date list into consecutive chunks of at most block_days;
include a final shorter chunk when the date count is not exactly divisible.
Every study date belongs to exactly one partition chunk.

For each fit, calculate:

- nonempty_independent_blocks: partition chunks containing at least one
  accepted PM2.5 row in that fit's base data;
- eligible_independent_blocks: partition chunks containing at least one
  eligible complete-case row for that fit.

Use these two values for the >=30 and >=20 gate. A candidate moving window
count may be recorded separately for diagnostics, but it must not be called an
independent-block count and must not control gate_pass.

Expected behavior for the frozen 91-date window is approximately:

- one-day blocks: 91 partition blocks;
- two-day blocks: 46 partition blocks, including the final one-day partition;
- seven-day blocks: 13 partition blocks.

Therefore, the seven-day sensitivity is expected to be descriptive-only under
the 30-block inferential gate. This is an expected limitation, not a runtime
failure. The primary one-day fits should still be eligible if their observed
and eligible partition counts pass both thresholds.

Record the gate method and both independent counts in the manifest, summary
JSON and CSV outputs.

### 3.4 Exact bootstrap sample length

Every bootstrap replicate must contain exactly the number of study-calendar
dates in the frozen window (91 here). Do not use a full-block ceiling that
creates 92 sampled dates for two-day blocks.

Predeclare and implement this deterministic rule:

~~~text
full_blocks, remainder = divmod(n_dates, block_days)
draw full_blocks moving windows of length block_days;
if remainder > 0, draw one additional moving window of length remainder;
aggregate exactly those sampled date spans.
~~~

For the 91-date window this gives:

- block length 1: 91 one-day draws;
- block length 2: 45 two-day draws plus one one-day draw = 91 dates;
- block length 7: 13 seven-day draws = 91 dates.

The RNG remains CPython random.Random(SEED), with replicates outermost and
draws in fixed order. Keep all observed missing hours inside each selected
calendar-date span. Record sampled_dates_per_replicate, the draw-length
policy and the number of full/remainder draws in the manifest.

### 3.5 Inference labels

Use an explicit classification function rather than equating gate_pass with
inferential:

- inferential: the fit passed the gate and its p-value is part of a declared
  multiple-testing family with the required adjustment (Holm for the two
  primary pooled p-values or Benjamini-Hochberg for the five declared
  secondary pooled p-values);
- exploratory: the fit passed the gate but is unadjusted, including
  site-specific fits, H3, raw-scale fits, block-length sensitivities and
  extreme-value sensitivities;
- descriptive_only: the gate failed, the result is a descriptive correlation,
  or no inferential p-value/interval is justified.

Only Holm- or BH-adjusted outputs may be described as inferential in the report.
Do not call an unadjusted p-value a finding. Preserve unadjusted p-values only
as clearly labelled exploratory diagnostics where the existing contract allows
them.

## 4. Implementation changes

### 4.1 src/vn_air/statistics.py

Make the smallest maintainable changes needed to expose the decisions above.
Keep the module stdlib-only and deterministic.

Add or refactor small helpers for:

1. identifying the weather variable set from the frozen bundle;
2. classifying rows as complete_weather versus exposure-specific
   pairwise_complete/exposure_complete;
3. constructing non-overlapping partition chunks and counting accepted/eligible
   independent blocks;
4. producing exact-length bootstrap window specifications for arbitrary
   n_dates and block_days;
5. assigning the inference label from gate status and adjustment method.

Update fit specifications so the weather-case variant is explicit in fit IDs,
result records and formulas/manifest metadata. Use stable names such as:

- ..._pairwise_complete for the existing exposure-specific complete-case
  model;
- ..._complete_weather for the full-weather sensitivity;
- a separate pairwise_correlations manifest section for descriptive
  pairwise correlations rather than pretending they are OLS fits.

Do not change the primary model formula:

log1p_pm25 ~ sensor + local_hour + weekday + day_index + standardized_exposure

Do not change the frozen bundle hash, reconciliation counts, exposure
standardization rule, extreme-value rule, seed, replicate count, Holm family,
BH family or response scales.

When bootstrapping, aggregate the exact selected date spans. Do not duplicate
or silently discard an extra date. Ensure the implementation remains correct
when the remainder is zero and when the remainder is one.

When calculating gate counts, distinguish these fields if both are retained:

- candidate_windows or moving_window_count;
- nonempty_independent_blocks;
- eligible_independent_blocks.

For compatibility, nonempty_blocks and eligible_blocks may remain as output
aliases only if their meaning is explicitly changed and documented as
non-overlapping independent partitions. Do not leave ambiguous names in the
assumptions report.

### 4.2 src/vn_air/statistics_output.py

Update all output writers and schemas:

- Include weather-case metadata and independent-block fields in the estimate and
  bootstrap CSVs.
- Add the pairwise descriptive section to the summary JSON and assumptions
  report.
- Emit the three inference labels exactly as defined above.
- State that seven-day sensitivities are expected to be exploratory or
  descriptive-only when the independent-block gate fails.
- Explain that moving candidate windows are used for resampling but are not
  independent evidence units.
- Report the exact bootstrap date-length rule, including the two-day
  45-plus-one remainder case.
- Keep the assumptions report free of causal, city-wide, forecast-skill,
  health or production claims.

The output directory must continue to contain exactly these required files:

- phase_6_statistics_summary.json
- phase_6_estimates.csv
- phase_6_bootstrap_summary.csv
- phase_6_assumptions.md
- SUCCESS.json

The CLI must continue to refuse an existing output directory.

### 4.3 src/vn_air/cli.py

Keep both commands read-only and deterministic:

~~~bash
.venv/bin/vn-air stats run --bundle ... --phase4-artifact ... --output-dir ...
.venv/bin/vn-air stats replay --bundle ... --output-dir ...
~~~

No CLI redesign is required. Only change it if the new output metadata needs a
small wiring adjustment. Do not add database access to either command.

## 5. Tests to add or update

Extend tests/test_statistics.py with small synthetic tests. Do not increase
the production seed or reduce the real verification scope just to make tests
fast; patch REPLICATES in synthetic tests as the current suite does.

Required tests:

1. Independent partition count:
   - 91 dates give 91, 46 and 13 partitions for block lengths 1, 2 and 7;
   - overlapping moving-window counts are not used as the gate;
   - a synthetic gate fails when independent eligible blocks are below 20 even
     if the overlapping candidate-window count is high.
2. Exact bootstrap length:
   - block length 2 for 91 dates produces 45 windows of length 2 plus one
     window of length 1;
   - total sampled date length is exactly 91, never 92;
   - gaps/missing rows inside selected date spans remain preserved.
3. Complete-weather sensitivity:
   - a row missing an unrelated weather variable is excluded from the
     complete-weather fit;
   - the same row remains eligible for an exposure-specific pairwise fit when
     that exposure is finite;
   - summary output contains both cases and the counts differ as expected.
4. Pairwise descriptive output:
   - descriptive correlations have no p-value, interval, Holm/BH adjustment or
     inferential label.
5. Inference labels:
   - pooled H1/H2 with Holm are inferential when gates pass;
   - the five pooled secondary fits with BH are inferential when gates pass;
   - site-specific, H3, raw-scale, block-length and extreme-value fits are
     exploratory when gates pass;
   - any gate-failing fit is descriptive_only.
6. Regression protection:
   - frozen bundle hash and reconciliation mismatch still stop the run;
   - full-sample rank deficiency still stops the run;
   - Holm/BH arithmetic tests remain passing;
   - deterministic replay remains byte-identical.

Update old assertions that assume exactly 20 or 24 fits. Assert the presence
and semantics of fit IDs/metadata instead of relying only on the count.

## 6. Execution sequence

Follow this order. Do not generate the corrected artifact before the plan
addendum and tests are in place.

### Step 0 — Baseline and scope check

Run:

~~~bash
git status --short
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
~~~

Record the baseline result privately or in the implementation notes. Do not
modify frozen artifacts to make the baseline pass.

### Step 1 — Amend the pre-registration

Add the dated correction addendum described in section 3 to
docs/verification/phase_6_plan.md. Make clear that the previous output is
superseded for verification because of implementation-contract errors, not
because of its numerical conclusions.

### Step 2 — Implement and test the code changes

Edit only the phase-scoped statistics module, output writer, CLI wiring if
needed and tests. Use apply_patch for manual edits. Run the focused tests:

~~~bash
PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_statistics -v
~~~

Fix all failures before running the real 2,000-replicate analysis.

### Step 3 — Generate a new corrected artifact

Use a new output directory; never overwrite the old one. A suitable name is:

docs/verification/phase_6_statistics_2026-09-09_corrected/

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli stats run \
  --bundle docs/verification/phase_5_eda_2026-09-07_final/eda_bundle.json \
  --phase4-artifact docs/verification/phase_4_quality_2026-09-07_final.json \
  --output-dir docs/verification/phase_6_statistics_2026-09-09_corrected
~~~

Confirm manually from the generated summary that:

- the frozen digest and reconciliation counts are unchanged;
- the manifest identifies the complete-weather variable set;
- primary exposure-specific fits and complete-weather sensitivity fits are
  distinguishable;
- pairwise descriptive correlations are present and non-inferential;
- one-day independent block counts are about 91, two-day counts about 46 and
  seven-day counts 13 for the frozen full date range;
- every bootstrap fit reports exactly 91 sampled dates per replicate;
- no two-day fit reports 92 sampled dates;
- only Holm/BH-adjusted fits are inferential;
- seven-day fits are not incorrectly labelled inferential;
- output hashes are present in SUCCESS.json.

Do not judge success by whether a p-value becomes smaller or larger.

### Step 4 — Deterministic replay

Run stats replay into a second new directory, for example
docs/verification/phase_6_statistics_2026-09-09_replay/, or into a temporary
directory whose parent exists. Compare SHA-256 hashes for every required output
file. The corrected run and replay must be byte-identical. Do not compare only
the top-level manifest hash.

### Step 5 — Full verification gates

Run all of the following after the corrected artifact succeeds:

~~~bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
git diff --check
~~~

The isolated PostgreSQL suite must use its own disposable cluster and must not
point at Supabase. The Phase 6 code must not add a migration or alter schema.

Perform the narrow read-only Supabase cutoff check only if the existing project
credentials and approved read-only workflow are available. Follow the project
Supabase skill/instructions first. Do not print credentials or use the database
as the statistics input. Confirm that the frozen inputs remain unchanged; do
not write anything.

### Step 6 — Update verification documents

Only after all gates pass:

1. Update docs/verification/phase_6.md to identify the corrected artifact as
   authoritative and the 2026-09-08 artifact as superseded/request-changes.
2. Replace stale claims that all moving-window counts were independent.
3. Report the actual corrected independent-block counts, exact sample-length
   rule, complete-weather/pairwise-complete coverage and inference labels.
4. Report actual test and replay results; do not invent counts.
5. Update AGENTS.md so it points to the corrected artifact and states that
   Phase 6 is verified only after the corrected gates pass.
6. Update README.md links or status text if they point to the superseded
   artifact. Preserve the limitations and the Phase 7 next-step boundary.

Do not edit the external OpenCode handoff unless separately requested. This
file is the self-contained execution handoff for the correction.

## 7. Acceptance criteria

The correction is complete only when every item below is true:

- The correction addendum exists in docs/verification/phase_6_plan.md and
  predates the corrected p-value/interval computation.
- Complete-weather OLS sensitivity is implemented and distinguishable from
  exposure-specific pairwise complete cases.
- Pairwise-complete descriptive output is present and is not inferential.
- Independent gate counts use non-overlapping partitions, not overlapping
  moving windows.
- Two-day bootstrap replicates contain exactly 91 sampled dates, not 92.
- Inference labels follow the Holm/BH-only rule.
- Frozen Phase 5 digest, Phase 4 hash, cutoff and reconciliation counts pass.
- Rank-deficiency and insufficient-gate stop/label behavior remains active.
- Required synthetic tests pass.
- Offline tests pass.
- Isolated PostgreSQL tests pass.
- git diff --check is clean.
- Corrected run and deterministic replay are byte-identical for every required
  output file.
- No database migration, Supabase write, model training, schedule or secret
  exposure occurred.
- phase_6.md, AGENTS.md and README.md contain only evidence-backed claims.

If any acceptance criterion fails, stop and report the exact failure. Do not
mark Phase 6 verified, commit, push or continue to Phase 7.

## 8. Final handoff format

After successful execution, report:

1. corrected artifact directory;
2. files changed;
3. exact test commands and results;
4. corrected independent-block counts by block length;
5. complete-weather and pairwise-complete row counts;
6. replay hash comparison result;
7. confirmation of no database writes/migrations and no secrets exposed;
8. any remaining limitation or exploratory-only output.

Do not summarize unadjusted p-values as confirmed findings. Do not claim causal
effects, city-wide exposure, forecast skill, health guidance or production
automation.
