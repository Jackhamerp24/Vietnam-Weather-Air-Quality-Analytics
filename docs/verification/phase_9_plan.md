# Phase 9 Plan: Chronological Machine Learning

Status: delivered and verified against `phase_9_models_2026-09-12_comparison_hardened/`
(`phase9_ml_v4`, revision `comparison_hardened`). The integrity corrections
(A–D), the follow-up review corrections (E–J) and the comparison-reporting
closeout (K–M) in
[phase_9_integrity_replay_hardening_plan.md](phase_9_integrity_replay_hardening_plan.md)
are complete. The v1 `phase_9_models_2026-09-11_final/`, v2
`phase_9_models_2026-09-11_corrected/` and v3
`phase_9_models_2026-09-12_review_hardened/` artifacts are preserved unchanged
and superseded. See [phase_9.md](phase_9.md).
Date: 2026-09-11 UTC
Repository: `Vietnam-Weather-Air-Quality-Analytics`

This document is the complete implementation and verification plan for Phase 9.
The executing agent may implement the work described here after reading the
repository instructions. It must preserve every security, source-separation,
availability and scientific boundary in `AGENTS.md`. Do not interpret this plan
as permission to change the database, add a scheduler, expose an API, or build a
dashboard.

## 1. Objective and boundary

Phase 9 adds a reproducible chronological ML runner that tests whether
availability-safe Phase 7 features improve PM2.5 predictions over the Phase 8
reference baselines at the exact 6-hour and 24-hour horizons.

The phase must establish this narrower claim:

> Given a valid Phase 7 artifact, a predeclared model and feature set can be
> fitted using only eligible training rows, selected without using the final
> test period, and evaluated under the inherited chronological split and purge
> contract with deterministic, replayable outputs.

The phase must not claim:

- operational forecast skill for the frozen artifact;
- model superiority, production readiness or deployment fitness;
- causal weather effects, health guidance or city-wide exposure;
- performance for Da Nang as a measured site;
- a population-average prediction;
- that retrospective target labels or backfill timestamps were available to a
  historical forecaster.

Phase 9 is an ML/data-pipeline phase. It does not include UX/UI, Streamlit,
Plotly, dashboard pages, visual branding or frontend work. Dashboard work is
Phase 10.

## 2. Frozen inputs and expected identities

The first Phase 9 run must use the authoritative Phase 7 captured artifact:

```text
docs/verification/phase_7_features_2026-09-10_structural_hardened/
```

The first run must also use the authoritative Phase 8 reference artifact:

```text
docs/verification/phase_8_baselines_2026-09-11_v2_verified/
```

The current expected identities are:

| Input | Expected identity |
| --- | --- |
| Phase 7 feature version | `phase7_features_v7` |
| Phase 7 manifest SHA-256 | `6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa` |
| Phase 8 baseline version | `phase8_baselines_v2` |
| Phase 8 manifest SHA-256 | `ec651c4df04cb605f8849c1af96a3aea58f0902370e16ec39b9c48fdee22775e` |
| Availability basis | `captured` |
| Horizons | `6`, `24` |
| Phase 7 validation start | `2026-07-31T10:00:00+00:00` |
| Phase 7 test start | `2026-08-18T05:00:00+00:00` |

Do not silently substitute another artifact when an identity differs. Stop with
a clear error and record the mismatch. A deliberately new prospective run may
use a different artifact only when its request, hashes, boundary, data status
and limitations are recorded in a new manifest; it must not overwrite the
frozen Phase 9 artifact.

## 3. Required reading before editing

Read these files completely before implementing:

1. `AGENTS.md`;
2. `README.md`;
3. `docs/architecture.md`;
4. `docs/database.md`;
5. `docs/source_contracts.md`;
6. `docs/decisions/0001-data-sources.md`;
7. `docs/ingestion.md`;
8. `docs/verification/phase_4.md`;
9. `docs/verification/phase_5.md`;
10. `docs/verification/phase_6.md`;
11. `docs/verification/phase_7.md`;
12. `docs/verification/phase_8.md`;
13. `docs/verification/phase_8_plan.md`;
14. `docs/verification/phase_8_integrity_replay_hardening_plan.md`;
15. `docs/verification/phase_7_features_2026-09-10_structural_hardened/phase_7_feature_summary.json`;
16. `docs/verification/phase_8_baselines_2026-09-11_v2_verified/phase_8_baselines_summary.json`;
17. `src/vn_air/features.py`;
18. `src/vn_air/baselines.py`;
19. `src/vn_air/baselines_output.py`;
20. `src/vn_air/cli.py`;
21. `tests/test_features.py`;
22. `tests/test_baselines.py`;
23. `tests/test_research_artifacts.py`.

Never read or print `.env`. Do not print database URLs, API keys, passwords,
request headers or secret-bearing exceptions.

## 4. Non-negotiable data and scientific contracts

### 4.1 Input source and availability

- Phase 9 consumes a Phase 7 artifact from disk only.
- `run` and `replay` must not connect to PostgreSQL, Supabase, OpenAQ,
  Open-Meteo or any network service.
- Accept only `availability_basis = "captured"` for the operationally named
  feature track. Do not accept an assumed-lag artifact as an operational
  backtest.
- Preserve the Phase 7 distinction between captured availability and eventual
  target labels. A target retrieved after its origin may be used as the future
  evaluation outcome, but its value and timestamps must never be model inputs.
- Use OpenAQ measured PM2.5 only as the target and historical PM feature source.
- Use Open-Meteo forecast variables only when they are eligible captured weather
  features in the Phase 7 artifact.
- Exclude ERA5 reanalysis, CAMS modeled air quality and any provider forecast
  not represented in the Phase 7 captured feature columns.
- Never replace missing PM2.5 history or weather with another source.
- Never interpolate, forward-fill, impute, or silently drop missing rows.

### 4.2 Target and row identity

For every `(sensor_id, origin, horizon_hours)` row:

```text
target_end   = origin + horizon_hours
target_start = target_end - 1 hour
```

The target is the measured hourly PM2.5 interval ending at `target_end`. Use
Phase 7 `phase_7_targets.csv` as the only target-value input. Require exact
feature/target key alignment and re-check the target identity contract before
training.

Only a target with all of the following is eligible for scoring or fitting:

- `target_available = true`;
- `target_quality = accepted`;
- finite `target_pm25`;
- row is not horizon-purged for the relevant split.

Keep absent, invalid, suspect and excluded outcomes in coverage and exclusion
counts. Never put `target_pm25`, target timestamps, target quality, target
revision, or target availability fields into a model design matrix.

### 4.3 Chronological split and purge

Use the one shared Phase 7 split for every sensor, horizon, feature set and
model:

- train: origins before `2026-07-31T10:00:00Z`;
- validation: origins from validation start through before
  `2026-08-18T05:00:00Z`;
- test: origins at or after test start;
- exclude every row whose target interval reaches the next split boundary,
  exactly as Phase 7 records it.

Never randomly shuffle across time, create a random holdout, use test rows for
feature transformation, select hyperparameters on test, or use test metrics to
choose a model. The final test period must be scored only after all choices are
frozen.

For the primary final evaluation, fit the selected specification on all eligible
non-purged train plus validation rows, then score the untouched test rows. This
is allowed only after validation selection is complete and must be recorded as
`fit_partition = train_plus_validation`. Also retain train-fit validation
results with `fit_partition = train` so the selection evidence is auditable.

### 4.4 Sensors and horizons

- Keep CMT8 (`openaq_11357424`) and OceanPark (`openaq_14581375`) separate.
- Treat them as two sensor sites, not city averages.
- Train and evaluate a separate model for horizon `6` and horizon `24`.
- Do not mix target horizons in one model.
- Report pooled results only as a descriptive combination of the two monitored
  sensors. Report per-sensor results as the primary geographic sensitivity.
- Do not present pooled results as Vietnam-wide or city-wide performance.

## 5. Predeclared model and feature matrix

The model and feature definitions below are fixed before fitting. Do not add
feature columns, interactions, lag values, nonlinear terms, model families or
hyperparameters after inspecting results.

### 5.1 Target transforms

Every model must support both predeclared target transforms:

1. `log1p` — primary: fit `log1p(target_pm25)` and invert with `expm1` for
   PM2.5-scale reporting;
2. `raw` — sensitivity: fit target PM2.5 directly.

PM2.5 targets must be finite and non-negative. For inverse `log1p` predictions,
apply the predeclared lower bound `max(0, expm1(predicted_log_value))`. For raw
predictions, apply the same `max(0, prediction)` reporting bound. Record the
transform and bound in every model specification. Do not use a result-dependent
outlier deletion or target clipping rule.

Ridge alpha selection uses validation RMSE on the original PM2.5 scale. Every
declared model-family × feature-set specification is reported; do not select a
single family, feature set or transform from test results. If a later portfolio
summary needs one headline candidate, it must be selected from validation under
a rule written before test scoring and must be recorded separately from the
all-specification results. All reported metrics remain descriptive; there are
no p-values or inferential ML claims in Phase 9.

### 5.2 Feature-set ablations

Implement exactly these four feature sets:

| Feature set | Contents | Purpose |
| --- | --- | --- |
| `calendar_only` | Vietnam local hour one-hot, Vietnam local weekday one-hot, deterministic day index | calendar diagnostic and minimum ML path |
| `history_only` | `calendar_only` plus exact PM lags, last-available value/age and strict trailing summaries | recent measured-history reference |
| `weather_only` | `calendar_only` plus finite captured Open-Meteo forecast weather fields | weather-only diagnostic |
| `history_weather` | `calendar_only` plus both history and captured forecast weather fields | incremental weather ablation |

The exact continuous Phase 7 columns are:

```text
PM history:
pm25_lag_1h, pm25_lag_3h, pm25_lag_6h, pm25_lag_12h,
pm25_lag_24h, pm25_lag_48h, pm25_lag_72h,
pm25_last_available, pm25_last_age_hours,
pm25_trailing_count_3h, pm25_trailing_count_6h,
pm25_trailing_count_12h, pm25_trailing_count_24h,
pm25_trailing_mean_3h, pm25_trailing_mean_6h,
pm25_trailing_mean_12h, pm25_trailing_mean_24h,
pm25_trailing_std_24h

Captured weather:
weather_forecast_apparent_temperature, weather_forecast_cloud_cover,
weather_forecast_precipitation, weather_forecast_relative_humidity_2m,
weather_forecast_shortwave_radiation, weather_forecast_surface_pressure,
weather_forecast_temperature_2m, weather_forecast_wind_direction_cos,
weather_forecast_wind_direction_sin, weather_forecast_wind_speed_10m
```

For all sets, encode the following calendar values from Phase 7 fields:

- `origin_local_hour`: one-hot levels `0` through `23`;
- `origin_local_weekday`: one-hot levels `0` through `6`;
- `day_index`: integer local-calendar-day distance from the earliest origin in
  the input artifact. This is a deterministic calendar coordinate, not a
  target-derived value.

For `history_only` and `history_weather`, a row is complete only when every
declared history column is finite. For `weather_only` and `history_weather`, a
row is complete only when every declared weather column is finite and the Phase
7 weather reason is `ok`. For `calendar_only`, calendar fields must be valid.
Do not impute a partial row. Report feature-family missingness separately.

Do not use any column beginning with `target_`, any lineage column, any
`*_recorded_at`, `*_retrieved_at`, `*_snapshot_id`, `*_response_id`, quality
field, availability reason, source provenance, or target identity field as a
predictor. Enforce the allowlist in code and test rejection of an injected
target column.

### 5.3 Sensor scope

Implement two scopes:

- `pooled`: one model over both sensors with fixed one-hot sensor levels, so the
  model can account for site identity without pretending sites are a city mean;
- `per_sensor`: one independently fitted model for each configured measured
  sensor, with no cross-sensor target rows in its training data.

The pooled sensor levels must be deterministic and sorted. Location metadata is
not a free-form predictor; it remains bound to the reviewed sensor registry.

### 5.4 Required model families

Implement both model families with the Python standard library only. Do not add
NumPy, scikit-learn or another dependency unless a separate user-approved plan
explicitly changes this requirement.

#### Ridge regression — primary

Implement a deterministic Ridge regressor with:

- an unregularized intercept;
- train-only standardization of continuous columns;
- fixed categorical one-hot columns;
- normal equations solved by a checked Gaussian-elimination/pivot routine;
- finite-value validation and a clear failure on malformed or unusable design
  matrices;
- predeclared alpha grid `[0.1, 1.0, 10.0, 100.0]` for `log1p` and raw fits;
- alpha selected using validation RMSE on original PM2.5 scale, with a stable
  tie-break toward the smaller alpha;
- fallback alpha `1.0` only when validation selection is unavailable, with
  `selection_status = validation_unavailable` recorded.

Fit transformations and alpha selection independently for every horizon,
feature set, target transform and sensor scope. Record train means, scales,
dropped constant columns, design rank/column count, alpha and coefficients in
the parameter artifact.

#### Bagged shallow regression trees — secondary

Implement a small deterministic tree ensemble without external dependencies:

- `25` trees;
- maximum depth `4`;
- minimum leaf size `10`;
- bootstrap sample fraction `0.8` of the eligible training rows per tree;
- split candidates restricted to observed finite feature values;
- squared-error split criterion;
- deterministic feature/row ordering and a stable seed derived from the
  declared base seed `20260911` plus the model specification using SHA-256;
- leaf prediction equal to the mean training target in that leaf;
- no validation/test row in any tree sample;
- no hyperparameter selection using test metrics.

Trees do not need standardization, but they must use the same feature allowlist,
complete-case policy, target transforms, horizons, scopes and split contracts as
Ridge. Record the full deterministic tree parameters or a compact serialized
tree representation so the result is inspectable and replay does not depend on
pickle or platform-specific state. Record feature-use counts/importance as
descriptive diagnostics only.

If a tree cannot meet its minimum training-row or leaf gate, emit an explicit
unavailable status for that cell rather than weakening the gate.

## 6. Training and evaluation procedure

Implement the following fixed procedure for each combination of:

```text
horizon ∈ {6, 24}
feature_set ∈ {calendar_only, history_only, weather_only, history_weather}
model_family ∈ {ridge, bagged_tree}
target_transform ∈ {log1p, raw}
scope ∈ {pooled, per_sensor}
```

The runner may skip combinations with no eligible complete rows, but every skip
must appear in machine-readable coverage output with a reason.

### Step A — Load and validate

1. Verify the Phase 7 required files, `SUCCESS.json` hashes, summary manifest
   digest, feature version, bundle identity, horizons, availability basis,
   boundary, split, purge and exact feature/target key alignment.
2. Verify the Phase 8 v2 reference artifact hashes and summary identity when a
   baseline comparison is requested.
3. Parse timestamps as timezone-aware UTC and validate local calendar fields.
4. Validate target alignment and accepted finite target values.
5. Validate all feature values against the feature-set allowlist before building
   any design matrix.
6. Sort rows by stable `(origin, sensor_id, horizon_hours, key)` order. Never
   rely on input CSV order for deterministic fitting.

### Step B — Build eligible partitions

For each model specification, calculate and record:

- candidate rows by split;
- purged rows excluded;
- unavailable target rows;
- incomplete feature rows by family and reason;
- eligible complete rows;
- distinct origins and local calendar dates;
- per-sensor counts and pooled counts.

Require at least `30` eligible non-purged training rows and at least `5`
distinct training dates for any model fit. For the tree family additionally
require at least `60` eligible training rows so the fixed leaf/bootstrap policy
has meaning. Below the gate, return `model_status = unavailable` with no
fabricated metrics.

### Step C — Fit the selection model on train only

1. Fit numeric transformations on eligible non-purged train rows only.
2. Fit Ridge alpha candidates on train only and score each candidate on the
   non-purged validation rows. The validation target is used only for
   predeclared alpha selection and validation scoring. The model family and
   feature set are not silently selected here: each declared specification is
   evaluated independently.
3. If validation has no eligible rows, use the fixed fallback alpha and mark
   the selection as unavailable; never inspect test values to compensate.
4. Fit each fixed tree specification on train only.
5. Save the selection-stage model parameters and validation metrics.

### Step D — Fit the final model and score test once

1. Freeze feature set, model family, target transform and scope. For Ridge,
   freeze the alpha selected by the predeclared validation rule; for trees,
   freeze the declared tree settings and deterministic seed.
2. Refit each declared specification on all eligible non-purged train plus
   validation rows. There is no test-driven family or feature-set selection.
3. Fit all transformations using only that train-plus-validation partition.
4. Score test rows exactly once per declared specification with
   `fit_partition = train_plus_validation`.
5. Do not use test outcomes to select or revise any model. Test metrics are
   reported only as a final descriptive holdout diagnostic.

For complete auditability, output both the train-fit validation predictions and
the final test predictions, with the fit partition explicitly recorded.

### Step E — Compute metrics

For each model × feature set × horizon × scope × target transform × split, report
only finite accepted target/prediction pairs from non-purged rows:

- candidate row count;
- eligible pair count and coverage percentage;
- missing target, missing feature and purged counts;
- MAE;
- RMSE;
- mean error (`prediction - target`);
- median absolute error;
- R², null with an explicit reason when undefined;
- zero-safe sMAPE;
- MASE using the Phase 8 training one-hour naive denominator where valid;
- model status, fit partition, feature-set status and metric scope.

All metrics are `descriptive_only`. Do not report p-values, confidence
intervals, causal effects or a "significant improvement" label.

### Step F — Compare predeclared ablations and baselines

Report comparisons without selecting a winner on the test period:

- `calendar_only` versus `history_only` when both have the same eligible rows;
- `history_only` versus `history_weather` on paired complete rows;
- each ML model against the Phase 8 `local_hour_climatology` reference on the
  exact shared eligible row keys;
- persistence/trailing baselines only when the Phase 8 reference has finite
  predictions on the same keys.

For every comparison, include paired row count, metric delta, split,
fit-partition and a statement that it is descriptive. If the row sets differ,
do not compare unpaired metrics as if the model caused the difference; report
`comparison_status = not_paired` and the reason.

## 7. Current frozen-data expectation

The current Phase 7 captured artifact has:

- `pm_available_origin_count = 0`;
- `weather_available_origin_count = 0`;
- zero rows with any data feature;
- zero rows with complete history/weather features;
- 8,290 accepted eventual target labels and 258 absent target labels.

Therefore the first Phase 9 frozen run must be truthful:

- `calendar_only` may produce a retrospective calendar diagnostic if its target
  gates pass;
- `history_only`, `weather_only` and `history_weather` must be unavailable if
  their complete-case feature rows are absent;
- no score may be fabricated for unavailable models;
- the artifact status must remain `limited_diagnostic` and carry
  `phase7_pm_history_unavailable` and/or
  `phase7_forecast_weather_unavailable`;
- `prospective_collection_period_required = true` must be retained;
- every available metric must remain `descriptive_only` and must not be called
  forecast skill.

The lack of captured PM/weather features is a data-availability limitation, not
a reason to use assumed mode, ERA5, CAMS, target-derived history or backfill
timestamps. A later prospective Phase 7 artifact may unlock additional models,
but that is a separate dated run and must preserve the same split/purge rules.

## 8. Implementation layout

Keep the implementation database-free and phase-scoped:

```text
src/vn_air/ml.py
src/vn_air/ml_output.py
tests/test_ml.py
docs/verification/phase_9_plan.md
docs/verification/phase_9.md
docs/verification/phase_9_models_2026-09-11_final/
```

Add `ml run|replay` to `src/vn_air/cli.py` with these interfaces:

```bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli ml run \
  --artifact docs/verification/phase_7_features_2026-09-10_structural_hardened \
  --baseline-artifact docs/verification/phase_8_baselines_2026-09-11_v2_verified \
  --output-dir docs/verification/phase_9_models_2026-09-11_final

PYTHONPATH=src .venv/bin/python -B -m vn_air.cli ml replay \
  --artifact docs/verification/phase_7_features_2026-09-10_structural_hardened \
  --baseline-artifact docs/verification/phase_8_baselines_2026-09-11_v2_verified \
  --summary docs/verification/phase_9_models_2026-09-11_final/phase_9_model_summary.json \
  --output-dir <new-output-directory>
```

The module entry point may mirror the CLI:

```bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.ml run ...
PYTHONPATH=src .venv/bin/python -B -m vn_air.ml replay ...
```

Both commands must:

- refuse an existing output directory or absent parent;
- reject malformed metadata, duplicate JSON keys and non-finite JSON tokens;
- reject symlink payloads and unsafe/unexpected artifact paths;
- verify all declared Phase 7 and Phase 8 input hashes before fitting;
- exclude local filesystem paths from replay identity so equivalent checkouts
  can replay byte-identically;
- use stable JSON and CSV serialization with no runtime-generated timestamps;
- never write to the database or call a network service.

Do not modify database schema, Alembic migrations, Supabase policies,
ingestion, feature construction or the Phase 8 artifact.

## 9. Required output artifact

The authoritative frozen output directory must be new and contain exactly these
seven files:

```text
phase_9_model_summary.json
phase_9_metrics.csv
phase_9_predictions.csv
phase_9_model_parameters.json
phase_9_feature_manifest.json
phase_9_assumptions.md
SUCCESS.json
```

`phase_9_model_summary.json` must contain:

- purpose and `model_version = phase9_ml_v1`;
- complete manifest and its SHA-256 digest;
- Phase 7 and Phase 8 input content identities;
- feature version, availability basis, boundary, horizons, split and purge;
- model families, feature sets, target transforms, scopes and fixed settings;
- train/validation/test counts and exclusion reasons;
- model statuses and limited-diagnostic reasons;
- selection policy, fit partitions and test-selection flag;
- prospective-collection requirement;
- metric-cell summary and comparison summary.

`phase_9_predictions.csv` must be auditable and sorted deterministically. Each
row must include model identity, feature-set identity, horizon, scope,
sensor/location identity, origin, split, fit partition, purged flag, target
availability/quality, prediction status, prediction reason and prediction on
the PM2.5 scale. It may include the eventual target value for evaluation audit,
but no target value may have been present in the design matrix. Unavailable
models must retain explicit status rows or explicit coverage records; do not
pretend their predictions exist.

`phase_9_model_parameters.json` must store deterministic fitted parameters for
every trained model, including transformations, selected alpha, coefficients or
tree structures, training row keys/counts and feature importance diagnostics.
Do not use pickle.

`phase_9_feature_manifest.json` must state the exact allowlisted columns,
encoding levels, train-only transformation policy, dropped columns, row gates,
source policy and feature-family availability counts for every model spec.

`phase_9_assumptions.md` must plainly state the frozen data limitation, every
model/feature/transform choice, no-imputation policy, split/purge policy,
baseline comparison rule, test non-selection rule and all scientific limits.

`SUCCESS.json` must contain the model version, summary manifest SHA-256 and
SHA-256 hashes for every other output file. The output directory must never be
overwritten.

## 10. Replay contract

`ml replay` must read the prior `phase_9_model_summary.json`, reject duplicate
keys/non-finite JSON and require exactly the expected top-level fields. Before
computation it must verify:

- prior summary manifest digest equals the digest of its manifest;
- purpose and `model_version` match the current implementation;
- Phase 7 summary, feature, target and SUCCESS hashes match;
- Phase 8 reference summary/SUCCESS and manifest identities match;
- boundary, horizons, split, purge, availability and status policy match;
- complete model definitions, feature allowlists, target transforms, scopes,
  seeds, alpha grid and tree settings match;
- no output directory already exists.

Do not include the local artifact directory string in the replay identity. A
copy of the same input artifact at a different checkout path must replay to the
same seven output bytes. The current implementation hash values may be
included in the manifest and must be updated by the run; a changed
implementation must cause a deliberate new artifact or a replay mismatch, not
silent acceptance.

## 11. Tests to add before the frozen run

Add focused offline tests in `tests/test_ml.py` covering at least:

### Input and alignment

1. Required Phase 7/Phase 8 hashes are mandatory.
2. Missing or altered input hashes stop before fitting.
3. Re-signed split, horizon, availability, target contract or baseline identity
   is rejected.
4. Feature/target key, sensor, location, origin and horizon misalignment stops.
5. Target columns injected into a feature allowlist are rejected.
6. ERA5/CAMS/assumed-mode inputs never enter an ML matrix.

### Chronology and leakage

7. Purged rows never enter fitting or metrics.
8. Test target mutation changes only test metric values, never fitted parameters
   or train/validation predictions.
9. Validation mutation cannot alter train-only transformations before selection
   (except the recorded alpha decision).
10. Standardization means/scales come from the declared fit partition only.
11. Train-plus-validation refit excludes all test rows.
12. Per-sensor models never consume the other sensor's targets.
13. Future target values, target timestamps and lineage fields cannot become
    predictors.

### Model arithmetic

14. Ridge recovers coefficients on an exact synthetic linear fixture.
15. Ridge rejects non-finite or unusable design matrices with a clear error.
16. Ridge alpha selection uses validation RMSE and deterministic tie-breaking.
17. Log1p and raw transforms have deterministic, non-negative inverse outputs.
18. Tree split/leaf gates, tree structure and predictions are deterministic for
    a fixed seed and differ only when the declared seed/specification changes.
19. Tree leaves never contain test rows and respect minimum leaf size.

### Coverage, metrics and comparison

20. Complete-case feature gates preserve missing rows and reasons.
21. Zero-safe sMAPE and undefined R² return null plus a reason.
22. MASE uses only the declared training naive denominator.
23. Paired comparisons reject mismatched row keys and compute exact deltas on
    matched rows.
24. Frozen limited-diagnostic fixture yields unavailable history/weather models
    without fabricated metrics.
25. A finite synthetic prospective fixture trains every intended path and emits
    non-empty metrics without changing the frozen artifact.

### Artifact integrity and determinism

26. Output refuses overwrite and missing parent.
27. Duplicate JSON keys, NaN/Infinity tokens, symlinks and unsafe paths stop.
28. Normal run, module replay and CLI replay regenerate every output file
    byte-identically.
29. Relocating equivalent input directories does not change output bytes.
30. Tampering with any summary/model/feature manifest field is rejected.
31. `SUCCESS.json` hashes all required output files and is itself stable.

Tests may use temporary synthetic fixtures only. Never mix synthetic values into
the frozen dated artifact. Do not use network calls, `.env`, Supabase or the
project database in these tests.

## 12. Verification gates and order

Run the gates in this order after implementation:

1. `git diff --check`.
2. Focused suite:

   ```bash
   PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_ml -v
   ```

3. Full offline suite:

   ```bash
   PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
   ```

4. Isolated PostgreSQL regression suite, with no Phase 9 database writes:

   ```bash
   PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
   ```

5. Research-artifact and Markdown/link checks through the offline suite.
6. Build the frozen Phase 9 artifact once into the new dated directory.
7. Validate every output hash and verify status/metric counts against the
   no-feature expectation in Section 7.
8. Run module replay into a new temporary directory and compare every required
   file with `cmp`.
9. Run CLI replay into another new temporary directory and compare every
   required file with `cmp`.
10. Run a relocated-input replay from an equivalent copied input directory and
    compare every output byte.
11. Re-check that the authoritative Phase 7 and Phase 8 artifacts remain
    unchanged.
12. Run `git status`, inspect the diff for secret leakage, and record all gates
    in `docs/verification/phase_9.md`.

If isolated PostgreSQL cannot start because of an environment restriction,
record the exact environment failure and do not substitute Supabase. Phase 9
itself must still remain database-free.

## 13. Documentation and handoff requirements

After the implementation and gates pass:

- Create `docs/verification/phase_9.md` with artifact paths, manifest hashes,
  exact model/feature counts, test results, replay evidence, limitations and
  the next-phase boundary.
- Update `AGENTS.md` only with the verified Phase 9 state and required reading;
  do not claim model performance if the frozen artifact is limited.
- Update `README.md` with the Phase 9 plan/verification links and an honest
  status paragraph. Keep Phase 10 dashboard as planned.
- Preserve every earlier Phase 7 and Phase 8 artifact unchanged.
- Update `.slim/deepwork/phase-9-ml.md` with stage status, validation evidence,
  unresolved limitations and the next handoff.
- Do not commit or push unless the user explicitly requests it in the current
  execution task.

## 14. Acceptance criteria

Phase 9 is complete only when all of the following are true:

- the plan was present before the first p-value/metric computation or model
  fitting run;
- the loader verifies Phase 7 and Phase 8 content identities and all row
  contracts before fitting;
- both Ridge and bagged-tree paths are implemented or explicitly blocked by a
  documented technical failure, with no silent fallback;
- all four feature-set ablations, both target transforms, both scopes and both
  horizons are represented as trained, unavailable or gated cells;
- train-only transformations and chronological validation selection are tested;
- final test scoring uses a train-plus-validation refit and never informs model
  choice;
- no target, lineage, retrospective timestamp, ERA5, CAMS or assumed value
  enters a model matrix;
- the frozen artifact is `limited_diagnostic` when captured PM/weather features
  are absent, with explicit reasons and no fabricated scores;
- output hashes, summary-bound replay, relocation replay and no-overwrite rules
  pass;
- focused, offline, PostgreSQL, diff and documentation gates are recorded;
- no database/schema/network/UI/scheduler change was introduced;
- the final handoff clearly says that Phase 10 is dashboard/UX/UI and that
  prospective collection is still required for real captured-feature model
  evaluation.

## 15. Suggested execution sequence for DeepSeek V4.1 Flash

Execute this file in order:

1. Inspect status and read all required files.
2. Confirm the plan is already saved before implementing or fitting anything.
3. Create/update `.slim/deepwork/phase-9-ml.md` with the active stage and
   acceptance gates.
4. Implement loader and feature schema checks first; add tests and run the
   focused loader tests.
5. Implement Ridge arithmetic and train-only transformations; add exact
   synthetic tests before wiring evaluation.
6. Implement deterministic bagged trees and their gates; add tree tests.
7. Implement evaluation, metrics, paired comparisons and parameter serialization.
8. Add CLI/output/replay and integrity tests.
9. Run all verification gates before creating the frozen artifact.
10. Create the authoritative artifact in the exact new dated directory; never
    overwrite existing Phase 8 or earlier artifacts.
11. Update verification docs and AGENTS/README only with observed facts.
12. Report changed files, artifact hashes, model availability, all test results,
    limitations and any blocker. Do not claim success until every acceptance
    criterion is evidenced.

The current user request is to prepare this plan. Do not begin Phase 9 code or
model fitting merely by reading this file; execute it only when the user starts
the Phase 9 implementation task.
