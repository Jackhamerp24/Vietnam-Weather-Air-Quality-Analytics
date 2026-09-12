# Phase 9 Machine Learning Verification

Date: 2026-09-12 UTC. Scope: a database-free, deterministic chronological ML
runner over the authoritative Phase 7 captured feature artifact, with the
Phase 8 v2 reference artifact used only for descriptive paired comparisons.
Ridge and shallow bagged-tree models were fitted on train-only transformations,
selected only on validation, refit on train plus validation and scored once on
the untouched test period. No database, network, scheduler, dashboard or UX/UI
work was added. No forecast-skill, model-superiority, causal, city-wide or
operational claim is supported.

**Authoritative artifact: `phase_9_models_2026-09-12_comparison_hardened/`**
(`phase9_ml_v4`, revision `comparison_hardened`, manifest SHA-256
`378f2e7f34476fe885ce6ec9827b7a48c346706f36b548fbc8db78ce94d8a770`). The
output directory must never be overwritten; any new run requires a new dated
directory.

Superseded Phase 9 artifacts, preserved unchanged:

- `phase_9_models_2026-09-11_final/` (`phase9_ml_v1`, manifest
  `1cd67cda5e2c0a12d85872f0f3c169922bb42e81f6954114358c25fa2d04d758`);
- `phase_9_models_2026-09-11_corrected/` (`phase9_ml_v2`, revision
  `integrity_corrected`, manifest
  `f729fe7eee8428c92da1fc3b4becd7f77bc4eb92f7ec5a142ebffaa291256795`);
- `phase_9_models_2026-09-12_review_hardened/` (`phase9_ml_v3`, revision
  `review_hardened`, manifest
  `c5cc4047766c16108beb0e5f0dc46dd7e9ddb871159d37989e7dd4b5a3df0d82`).

All three identities are recorded in the v4 supersession metadata and in
[phase_9_integrity_replay_hardening_plan.md](phase_9_integrity_replay_hardening_plan.md).

## Inputs

| Input | Identity |
| --- | --- |
| Phase 7 feature artifact | `docs/verification/phase_7_features_2026-09-10_structural_hardened/` (`phase7_features_v7`, manifest `6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa`) |
| Phase 8 reference artifact | `docs/verification/phase_8_baselines_2026-09-11_v2_verified/` (`phase8_baselines_v2`, manifest `ec651c4df04cb605f8849c1af96a3aea58f0902370e16ec39b9c48fdee22775e`) |
| Availability basis | `captured`; horizons 6 and 24 |
| Split (shared) | validation `2026-07-31T10:00:00+00:00`, test `2026-08-18T05:00:00+00:00`, inherited purge |

The frozen run preflights the fixed expected payload SHA-256 maps for every
Phase 7 and Phase 8 payload before the inherited loader parses any CSV, then
re-verifies all hashes, manifest digests, feature versions, availability basis,
horizons, boundary, split, purge and reference baseline definitions. Phase 8
reference rows are validated against the Phase 7 keys, including declared
baseline identity/role, location, split, purge, target availability, known
status enum and status/reason consistency, before any comparison.

## Corrections applied

The integrity correction (A–D) and the review-hardened pass (E–J) remain in
force; see the
[correction plan](phase_9_integrity_replay_hardening_plan.md). The final
comparison-reporting closeout applied K–M:

- **K — sensor-scoped finite-row counts.** `model_finite_rows` and
  `reference_finite_rows` now count each side's score-eligible prediction keys
  before pair intersection: correct group, non-purged row, accepted finite
  target and finite `predicted` prediction. Reference rows are scoped by
  baseline, sensor (or the pooled sensor union), split and horizon and filtered
  through the validated Phase 7 target/key map. `paired_rows` is the
  intersection and is required to be `<= min(model_rows, reference_rows)`.
  For the frozen CMT8 train/6h/local-hour comparison the reference count is
  1,275; the pooled count is 2,433 (down from the earlier unscoped 2,564).
- **L — fit-history uses fit-key digests.** Each comparison side records its
  actual eligible fit-row digest; the Phase 8 local-hour reference digest is
  derived from verified Phase 7 train rows with the Phase 8 climatology
  selection (no refit). `history_status` is `not_paired`, `not_applicable`
  (direct persistence/trailing reference), `unknown` (no established fit
  membership), `training_history_mismatch` (partition or digest differs) or
  `matched`. Unequal fit histories cannot isolate an effect of model family or
  weather features.
- **M — comparison identity includes location.** Every comparison record carries
  the reviewed per-sensor location (`cmt8`, `oceanpark`) or `pooled`, with a
  complete metadata schema (`paired_key_digest = null` when not paired).

The final pass is metadata-only: `phase_9_predictions.csv` and
`phase_9_metrics.csv` are byte-identical to v3, and the fitted parameters and
tree seeds are unchanged.

## Implementation

- `src/vn_air/ml.py` (`phase9_ml_v4`): fixed payload-map and manifest loaders,
  static replay projection with digest binding, fixed feature allowlists,
  complete-case gates, calendar encoding, train-only standardization, checked
  Gaussian-elimination Ridge with an unregularized intercept and the
  predeclared alpha grid `[0.1, 1.0, 10.0, 100.0]`, deterministic 25-tree
  shallow bagged ensembles (depth 4, minimum leaf 10, 80% bootstrap,
  SHA-256-derived seeds), log1p/raw transforms with only the declared
  non-negative lower bound, metrics, scoped paired comparisons with fit
  history, deterministic serialization and summary-bound replay.
- `src/vn_air/ml_output.py`: artifact writers.
- `src/vn_air/cli.py`: `ml run|replay`; database-free, preflights the output
  directory before input loading or computation.
- `tests/test_ml.py`: 53 tests, including independent expected-count
  regressions, fit-history digest regressions, comparison schema/location
  checks and all earlier integrity and leakage regressions.

Feature sets are exactly `calendar_only`, `history_only`, `weather_only` and
`history_weather`; target transforms are `log1p` and `raw`; scopes are `pooled`
and `per_sensor`; families are `ridge` and `bagged_tree`. Row gates remain at
least 30 eligible non-purged training rows and 5 distinct training dates, and
60 training rows for trees.

## Frozen artifact (limited diagnostic)

The frozen Phase 7 captured artifact has zero captured PM-history and zero
captured forecast-weather origins, so only calendar diagnostics could train.
The artifact reports `status = limited_diagnostic` with
`status_reasons: ["phase7_pm_history_unavailable", "phase7_forecast_weather_unavailable", "model_cells_unavailable"]`,
`test_selection_used = false` and
`prospective_collection_period_required = true`.

| Item | Value |
| --- | --- |
| Model instances | 96 declared; 24 trained (`calendar_only`); 72 unavailable |
| Metric cells | 288; 72 available (calendar-only Ridge and trees × 3 splits); 216 unavailable |
| Per-sensor identity | 192 per-sensor metric rows map to `cmt8` (`openaq_11357424`) and `oceanpark` (`openaq_14581375`); prediction rows carry the same mappings |
| Predictions | 65,424 auditable rows; no predictions fabricated for unavailable models |
| Comparisons | 360 records with scoped counts and fit history: 48 `matched`, 24 `training_history_mismatch`, 288 `not_paired` |
| Frozen scoped counts | CMT8 train/6h climatology reference 1,275 (`model_finite_rows` 1,275); pooled 2,433 |
| History/weather cells | Every `history_only`, `weather_only` and `history_weather` cell is unavailable with explicit reasons; no ERA5/CAMS/assumed/target/lineage value entered a design matrix |
| Output files | `phase_9_model_summary.json`, `phase_9_metrics.csv`, `phase_9_predictions.csv`, `phase_9_model_parameters.json`, `phase_9_feature_manifest.json`, `phase_9_assumptions.md`, `SUCCESS.json` |

The 72 available cells are retrospective calendar diagnostics fit on non-purged
training targets and calendar fields only; their metrics are `descriptive_only`.
Validation metrics are tuning diagnostics, not an independent holdout.

v4 output file SHA-256 values:

| File | SHA-256 |
| --- | --- |
| `phase_9_model_summary.json` | `5f2061f3464df4a623fba2e0071e0a373275755b59eb2e13ae6161aff25efa45` |
| `phase_9_metrics.csv` | `33303cfb8b6091a53de07c11cef33b89c9888054dac8598f8acb22a3478d7744` |
| `phase_9_predictions.csv` | `da8e670663b297a4f15f54f332b1e7837bc9c0eb0a5c6dd2debdc6849bcf5940` |
| `phase_9_model_parameters.json` | `87e803972624a627fccc4afbc2f107e9b2ba8e53bc2c2a14829745114f576002` |
| `phase_9_feature_manifest.json` | `6a30f54766cfb5beac6d9cd60a147e5f3bae251784fa7cad4a916fcb75c14503` |
| `phase_9_assumptions.md` | `1dda3b3d3ca285df80e7e8ee751aadeef4ea983baa03e7e5110a86a1f0c1d839` |
| `SUCCESS.json` | `68bdad7e7cc244bde48899b9fbb9934fbba8604aa9c11634d78a705945bcadad` |

Implementation hashes bound in the manifest: `ml.py`
`dc95836bb6629caafd18b086a8b4260f37c9742d009f67dd272bcebb2ef7574b`,
`ml_output.py` `2b05e863757a1a2446eedb4391cb4315dd50d5002f856031265b0a5f8c440b13`.

## Tests and verification

| Check | Result |
| --- | --- |
| `tests/test_ml.py` | 53 tests passed |
| Offline suite | 262 tests run: 260 passed, 2 credential checks skipped |
| Isolated PostgreSQL suite | 52 passed via `scripts/test_database.py`; Phase 9 added no database code |
| Markdown/local-link and trailing-whitespace checks | Passed as part of the offline suite |
| `git diff --check` | Clean |
| CLI `ml run` | Built the comparison-hardened artifact once into the new dated directory (~47s) |
| v3 → v4 invariance | `phase_9_predictions.csv` and `phase_9_metrics.csv` byte-identical; parameter fits and seeds unchanged |
| Module replay | All 7 output files byte-identical to the v4 artifact |
| CLI replay | All 7 output files byte-identical |
| Relocated-input replay | Copied Phase 7/8 artifacts at a different path; all 7 output files byte-identical |
| Re-signed payload/replay tamper tests | Retained from the earlier passes and passing |
| Input immutability | Phase 7/8 and the v1/v2/v3 Phase 9 artifacts re-verified unchanged |
| Database/network | None; `run` and `replay` open no database and make no network calls |

The local macOS dataless `.venv` was hydrated on demand during this runtime. The
installed `.venv/bin/vn-air` entry point still predates the Phase 7/8/9
subcommands; the documented `PYTHONPATH=src .venv/bin/python -m vn_air.cli`
invocation was used.

## Reviewer closeout (2026-09-12)

The reviewing agent accepts K–M for the v4 artifact. The reviewer read the
changed comparison code, reran the tests, and independently reconstructed
reference eligibility and fit-key digests from the frozen Phase 7/8 CSVs.
The independent calculation did not call the production comparison helpers.

- All 360 comparison records have correct scoped side counts, paired counts,
  paired-key digests and location fields. History labels reconcile to 48
  `matched`, 24 `training_history_mismatch` and 288 `not_paired` records.
- The reviewer compared v3/v4 prediction and metric files byte-for-byte and
  compared all 96 parameter `fits`: predictions, standalone metrics, fitted
  values, seeds and comparison MAE/RMSE deltas are unchanged.
- Reviewer reruns: 53 focused tests passed; 262 offline tests ran (260 passed,
  2 credential checks skipped); 52 isolated PostgreSQL tests passed. The
  PostgreSQL check used the approved disposable-cluster command, not a study
  database. Diff and documentation checks passed.
- A reviewer source-CLI replay reproduced all seven frozen v4 files, including
  SUCCESS. Focused tests also cover module-level and relocated-input replay;
  the full frozen module/relocated reruns above are executor evidence.
- The reviewer verified Phase 7/8 and Phase 9 v1/v2/v3/v4 manifest and payload
  hashes, plus v4 implementation hashes. No application code or frozen
  artifact changed during review. Three stale current-status sentences in
  README, AGENTS and the correction plan were updated to reflect this result.

No material K–M finding remains open. This accepts the diagnostic runner and
artifact contract, not operational forecasting performance. No commit or push
was performed during review.

## Limits and next-phase boundary

The frozen artifact evaluates no history or weather model on real data; those
paths are implemented and tested on synthetic fixtures only. A prospective
collection period is required before captured-feature ML evaluation exists.
Assumed-lag mode, ERA5, CAMS, retrospective backfill timestamps and target
columns remain excluded from every design matrix. Comparison records are
descriptive and label unequal fit histories; they do not isolate effects of
model family or weather features. Phase 9 does not include UX/UI; Phase 10 owns
the dashboard. Any future re-analysis must preserve the same shared
chronological split, purge, train-only transformation and untouched test-period
rules and must use a new dated output directory.
