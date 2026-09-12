# Phase 9 Integrity and Replay Hardening Plan

Status: complete; reviewer verified K–M against `phase9_ml_v4` on 2026-09-12
Date: 2026-09-11 UTC
Audience: DeepSeek V4.1 Flash continuation agent

Section 13 records the completed comparison-reporting closeout. The reviewer
verified scoped counts, fit-history digests, location metadata and unchanged
v3/v4 model outputs; see `phase_9.md`, Reviewer closeout. Keep the historical
commands below; do not execute them against existing artifact directories.

This correction plan is authoritative for the Phase 9 review findings below.
Do not overwrite the existing Phase 9 artifact. Preserve it unchanged as
superseded historical evidence and create a new dated correction artifact only
after all changes and gates pass.

## 1. Review disposition

The Phase 9 implementation and frozen artifact are substantially complete:

- the focused suite reported 30 passing tests;
- the full offline suite reported 239 tests with two credential skips;
- the isolated PostgreSQL suite reported 52 passing tests;
- the existing artifact has seven files whose internal `SUCCESS.json` hashes
  match their bytes;
- module, CLI and relocated-input replay were reported byte-identical.

Those results establish deterministic internal consistency, but they do not
establish immutable binding to the authoritative Phase 7/8 input payloads.
The current artifact must therefore not remain the authoritative Phase 9 result
until the findings in this document are fixed and a new artifact is generated.

## 2. Finding A — authoritative input payload hashes are not pinned

### Reproduced code path

`src/vn_air/ml.py::load_phase7()` calls the hardened Phase 8 loader and checks
the Phase 7 summary manifest identity, but the Phase 9 frozen path does not
compare each Phase 7 payload byte hash against a fixed authoritative expected
map. The Phase 8 reference loader has the same problem: it verifies hashes
listed in the reference `SUCCESS.json`, but does not compare all payload bytes
with a fixed expected map for the authoritative Phase 8 v2 artifact.

Consequently, an attacker or accidental process could modify a Phase 7 CSV or
Phase 8 prediction CSV, recompute and re-sign that artifact's `SUCCESS.json`,
and still pass the current Phase 9 loader while keeping the same summary
manifest digest. The Phase 9 manifest would record the altered content hash,
but that is evidence of what was consumed, not proof that the frozen input was
unchanged.

### Required fix

Add exact expected payload maps for the frozen run and enforce them before any
model fitting. The expected maps are:

#### Phase 7 authoritative artifact

```json
{
  "phase_7_assumptions.md": "bb7038c6692d5a7333aa3f01ca927053b99790014db50c3f38d6c0106dcdc06b",
  "phase_7_feature_summary.json": "7fd1bfd725c5bec6df0088adf52af1f6e34f08d7d2244bb95b6172f7896e4d0b",
  "phase_7_features.csv": "2e2829e8cd14444ce4da322dc4f288ebb49baa05dba14423529bea2c866e092c",
  "phase_7_lineage.csv": "621a88c28b2f88f267c3671969cbb4df262a52defd571e3eb689975476056aaa",
  "phase_7_targets.csv": "d3e5198ccba3814259e5c9e8cfe647f481d58481b1bb8d774997e982e0f51073"
}
```

The Phase 7 summary manifest identity remains:

```text
6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa
```

#### Phase 8 authoritative reference artifact

```json
{
  "phase_8_assumptions.md": "e77111278c3456221480f44a173fab0aa99e8a79f9b4e173a095094ac1588ebc",
  "phase_8_baseline_metrics.csv": "9626e4112689f108afba1256100e3911675bc44712b4072e9d87f267b675ca63",
  "phase_8_baselines_summary.json": "e7dbcd35f7d896b2ec7d3ec38b64ddb43f601efe56d4341d6b091cc8e2c9dc26",
  "phase_8_predictions.csv": "ea9f9f4a8568170e4f36a56059c18784a1260bcd1335c8b52df8856180f5a0bf"
}
```

The Phase 8 summary manifest identity remains:

```text
ec651c4df04cb605f8849c1af96a3aea58f0902370e16ec39b9c48fdee22775e
```

### Implementation requirements

1. Keep the existing general `SUCCESS.json` verification. It is still needed
   for new, explicitly authorized artifacts.
2. Add a frozen-identity check that compares the complete declared filename set
   and every actual SHA-256 byte hash against the maps above.
3. Reject missing, extra, renamed, symlinked or re-signed payload files before
   parsing rows or fitting a model.
4. Ensure the Phase 9 manifest records both the fixed expected input map and the
   observed verified map, or records a digest of the complete map. Do not store
   only a summary manifest digest.
5. Preserve a separate explicit non-frozen path for synthetic tests if needed,
   but the CLI frozen run must use the fixed maps. Do not weaken the check in
   order to make synthetic fixtures resemble the authoritative artifact.
6. Re-check that the Phase 7 and Phase 8 summary identities, feature versions,
   availability basis, horizons, boundary, split, purge metadata and baseline
   version agree with the expected maps.

### Required regressions

Add tests that:

- mutate `phase_7_features.csv`, re-sign Phase 7 `SUCCESS.json`, keep the
  summary manifest unchanged and confirm Phase 9 stops before fitting;
- mutate `phase_7_targets.csv`, re-sign Phase 7 `SUCCESS.json` and confirm it
  stops;
- mutate `phase_7_lineage.csv`, re-sign Phase 7 `SUCCESS.json` and confirm it
  stops even though lineage is not a predictor;
- mutate `phase_8_predictions.csv`, re-sign Phase 8 `SUCCESS.json` and confirm
  the Phase 9 reference loader stops;
- mutate `phase_8_baseline_metrics.csv` or assumptions, re-sign SUCCESS and
  confirm the complete reference artifact check stops;
- change a declared expected filename or add an unexpected payload and confirm
  the loader stops;
- verify the fixed maps pass for the unchanged authoritative artifacts.

The tests must alter only temporary copies. Never modify the committed/handoff
artifact during a regression test.

## 3. Finding B — no-overwrite is checked after computation

### Reproduced code path

`run_ml()` computes and trains models without receiving the requested output
directory. `replay_ml()` reads the summary and calls `run_ml()` before
`write_outputs()` checks whether the output directory exists. The CLI therefore
can spend substantial time parsing and fitting before rejecting an existing
output directory. This violates the Phase 9 plan's explicit requirement that
an existing output directory be rejected before computation.

### Required fix

Add a shared preflight function, for example:

```python
def require_new_output_dir(output_dir):
    output_dir = Path(output_dir)
    if output_dir.exists() or not output_dir.parent.is_dir():
        raise MLError("Phase 9 output directory must be new and its parent must exist")
```

Call it before any input loading or model computation for both `run` and
`replay`, including direct module-level entry points and CLI entry points. The
writer must retain its own final guard as a race-condition defense.

Preferred implementation shape:

- `run_ml(..., output_dir=...)` preflights when an output path is supplied;
- `replay_ml(..., output_dir=...)` preflights before reading/computing;
- the CLI passes the requested output path into those functions;
- direct `write_outputs()` still rejects an existing directory.

If the API shape is changed, update all tests and the module CLI consistently.

### Required regression

Create an existing output directory and monkeypatch `compute_ml` (or the first
model-fitting function) to raise a sentinel error if called. Invoke both module
`run` and `replay` and assert:

- the command fails with the no-overwrite error;
- the sentinel computation is never called;
- no input file is changed;
- no partial output is created.

Also test an absent parent directory. Keep the existing writer-level tests.

## 4. Finding C — undeclared upper clamp in `log1p` inverse

The plan predeclared only a lower non-negative reporting bound:

```text
max(0, expm1(predicted_log_value))
```

`inverse_transform()` currently silently clamps the model-space value to
`[-50, 50]` before applying `expm1`. That is an additional result-dependent
upper transformation not declared in the plan and can hide a numerical/model
failure.

### Required fix

Remove the silent upper clamp. Require a finite model-space value, call
`math.expm1()` directly for `log1p`, catch overflow as a clear model failure,
then apply only the declared lower bound. Record the failure as an unavailable
prediction/model cell with a machine-readable reason rather than fabricating or
silently clipping it.

Add tests for:

- ordinary round-trip `log1p`/`expm1` values;
- negative predictions applying only the lower bound;
- a very large model-space prediction producing the declared overflow error or
  explicit unavailable status, never an undisclosed finite clamp.

## 5. Finding D — Phase 8 reference row alignment is incomplete

The Phase 8 reference loader validates CSV shape and hashes, but the comparison
path does not fully validate reference prediction rows against the Phase 7
feature key set before using them. A tampered/re-signed reference can inject a
prediction for an unknown sensor/origin/horizon or mismatch split/purge identity
and affect a paired comparison.

### Required fix

After both artifacts are loaded, validate every Phase 8 reference prediction row
against the Phase 7 keys:

- baseline ID belongs to the declared Phase 8 baseline definitions;
- `(sensor_id, origin, horizon_hours)` exists in Phase 7;
- location ID matches the Phase 7 row for the sensor;
- split and purged status match the Phase 7 row;
- target availability identity matches the Phase 7 target row;
- prediction status/reason and finite prediction are internally consistent;
- no duplicate or extra reference keys exist;
- all required declared baselines are represented, including unavailable rows;
- only finite `predicted` values participate in paired comparisons.

Add a test for each mismatch and a valid-reference regression. This is defense
in depth in addition to fixed payload hashes, not a replacement for Finding A.

## 6. New corrected artifact and preservation

Keep the current artifact unchanged:

```text
docs/verification/phase_9_models_2026-09-11_final/
```

Create the corrected authoritative artifact in a new directory:

```text
docs/verification/phase_9_models_2026-09-11_corrected/
```

Do not overwrite the existing final directory. The corrected artifact must
contain the same seven filenames:

```text
phase_9_model_summary.json
phase_9_metrics.csv
phase_9_predictions.csv
phase_9_model_parameters.json
phase_9_feature_manifest.json
phase_9_assumptions.md
SUCCESS.json
```

Use a new implementation version, for example `phase9_ml_v2`, or otherwise
bind the corrected implementation hashes and correction status so that v1 and
v2 cannot be confused. The corrected summary must mark the v1 artifact as
superseded for verification while preserving its files unchanged.

## 7. Required verification gates

Run in this order:

1. Focused Phase 9 suite, including all new integrity, preflight, transform and
   reference-alignment regressions.
2. Full offline suite.
3. Isolated PostgreSQL suite. Do not substitute Supabase if the local cluster
   is blocked.
4. `git diff --check` and Markdown/link/whitespace checks.
5. Build the corrected artifact in the new directory.
6. Verify the corrected `SUCCESS.json` hashes every other output file.
7. Confirm v1 artifact hashes remain unchanged.
8. Run module replay into a new directory and compare all seven files with
   `cmp`.
9. Run CLI replay into a new directory and compare all seven files.
10. Run relocated-input replay and compare all seven files.
11. Run the re-signed-payload tamper tests against temporary copies.
12. Confirm no database, network or secret access.

The corrected frozen result should remain `limited_diagnostic`: the current
Phase 7 artifact has zero captured PM-history and zero captured forecast-weather
origins. Do not claim real captured-feature ML performance merely because the
calendar-only diagnostics produce metrics.

## 8. Documentation updates after correction

Update only after the corrected artifact and gates pass:

- `docs/verification/phase_9.md`: mark v2 corrected artifact authoritative,
  preserve v1 as superseded, record new hashes and exact gate results;
- `docs/verification/phase_9_plan.md`: link this correction plan and mark the
  integrity correction complete;
- `AGENTS.md`: add this correction plan to Required Reading and update the
  Phase 9 Focus to the corrected version without claiming operational skill;
- `README.md`: link the corrected artifact and keep Phase 10 dashboard/UX/UI as
  the next interface phase;
- `.slim/deepwork/phase-9-ml.md`: record findings, remediation, gates and
  remaining prospective-collection limitation.

Do not delete or rewrite the original execution report. It is historical input
to this review and should state that the v1 artifact was superseded after the
integrity review.

## 9. Completion criteria

The correction is complete only when:

- re-signed Phase 7/8 payload tampering is rejected before fitting;
- no-overwrite is rejected before computation for run and replay;
- no undeclared upper prediction clamp remains;
- Phase 8 references are structurally aligned to Phase 7;
- corrected v2 run/replay/relocation outputs are byte-identical;
- all tests and repository gates pass;
- the corrected artifact is `limited_diagnostic` with explicit reasons;
- v1 remains preserved and is clearly marked superseded;
- no database, network, scheduler, UX/UI or secret-related change is introduced.

## 10. Follow-up review findings for `phase9_ml_v2`

Review date: 2026-09-12 Australia/Melbourne. Implement Section 10 onwards next;
Sections 1–9 preserve the original v1 correction instructions. Do not rerun
their build command against the now-existing corrected directory.

The reviewer confirmed fixed payload rejection, output preflight and removal of
the upper clamp. The v2 suite passes, but replay, output identity and numerical
failure handling still have gaps. Keep v1 and v2 artifacts unchanged. Use
`phase9_ml_v3`, revision `review_hardened`, and the new directory
`docs/verification/phase_9_models_2026-09-12_review_hardened/` for the next run.

Do not restart Phase 9 or add new models. Preserve the alpha grid, feature sets,
target transforms, split boundaries, purge policy, row gates and base seed.

### Evidence established in this review

| Check | Reviewer result |
| --- | --- |
| Focused suite | 40 tests passed |
| Full offline suite | 249 tests run: 247 passed, 2 credential checks skipped |
| Isolated PostgreSQL | 52 passed after an approved outside-sandbox retry; the sandbox attempt failed at initdb |
| Frozen CLI replay | All seven files match v2 byte-for-byte, including SUCCESS |
| Artifacts | Phase 7/8 and Phase 9 v1/v2 payload and manifest hashes verified; current implementation hashes match v2 |
| Adversarial probes | E, F, G and I below reproduced; H verified in the frozen comparison schema |

Use these results as baseline evidence, not as proof that the new regressions
already pass. The reviewer did not modify application code or frozen artifacts.

### Finding E: replay accepts type-confused re-signed metadata

`replay_ml()` compares Python dictionaries with normal equality. Python treats
`False == 0` and `30 == 30.0` as true, so a re-signed Phase 9 summary can change
the JSON type of a replay-bound field and still pass. Temporary probes accepted
`test_selection_used: 0` and `row_gates.min_train_rows: 30.0`.

Required fix:

- require the recomputed manifest digest to equal the supplied manifest digest,
  in addition to comparing the manifests. Python dictionary equality alone is
  insufficient. `baselines.digest()` distinguishes `false`, `0`, `30` and `30.0`;
- reject integer/float, boolean/integer, string/non-string and null/value type
  substitutions;
- retain duplicate-key and non-finite-token rejection;
- add tests for `False -> 0`, `30 -> 30.0` and nested replay-bound fields after
  re-signing;
- confirm the unchanged corrected artifact still replays byte-identically.

Both reproduced replays wrote a success artifact with a different manifest
digest from the supplied, re-signed summary. Add an assertion that accepted
replay returns the supplied digest. Reject mismatches before calling the writer.
Use the existing reduced synthetic fixtures for this regression; do not weaken
production frozen identity checks.

The original plan also requires request validation before model computation.
Construct a static replay-contract projection (version/revision/purpose, pinned
input identities, feature and model definitions, splits, seed and row gates)
and compare it before fitting. Compare result-dependent metrics/counts after
recomputation. Do not compare an incomplete result manifest to a full manifest.

### Finding F: per-sensor location identity is wrong

`model_instances()` creates per-sensor identities with `location_id = sensor_id`.
The Phase 7 registry maps the sensors to `cmt8` and `oceanpark`. A probe found
192 per-sensor metric rows whose location ID equals the sensor ID instead of the
reviewed location ID.

The existing prediction CSV already uses the row's correct station location.
Preserve that behavior: the bug is in model/metric/parameter identities, not
the prediction-row location mapping. Pooled predictions also retain their
individual sensor/location identity; only pooled aggregate records use
`location_id = pooled`.

Required fix:

- derive a deterministic sensor-to-location map from validated Phase 7 rows;
- use the reviewed location ID in every per-sensor model, metric, prediction,
  parameter and comparison record;
- keep pooled `location_id = pooled` for pooled descriptive combinations;
- reject conflicting sensor/location mappings before fitting;
- add output and mutation regressions for both sensor mappings.

The corrected artifact must contain `cmt8` for `openaq_11357424` and `oceanpark`
for `openaq_14581375`.

Fix `model_instances()` and the synthetic `compute_instance()` test helper,
which currently duplicates the same location mistake. Derive identities before
computing their SHA-256 seed input. Changing location identity can change the
per-sensor bagged-tree seeds and predictions under the existing seed policy;
record this as an identity-driven numerical change. Do not tune seeds or retain
the wrong identity to force old scores to match. Assert correct mappings in
available and unavailable metric cells and both parameter fit stages.

### Finding G: unknown reference prediction statuses are accepted

`validate_reference_rows()` treats every status other than `predicted` as an
unavailable row. A temporary fixture with `prediction_status = "unknown_status"`
and no prediction was accepted. The Phase 8 contract declares only `predicted`
and `unavailable`.

Required fix:

- reject statuses outside `{ "predicted", "unavailable" }`;
- require `predicted` rows to carry a finite prediction and no unavailable
  reason;
- require `unavailable` rows to carry a null prediction and a non-empty reason;
- validate the declared baseline role/id against the Phase 8 summary definition;
- add re-signed reference tests for unknown status, missing reason and a
  predicted row carrying an unavailable reason.

Retain `prediction_reason`, `baseline_role` and the declared baseline
definitions when loading the reference. The present loader discards the reason
and role, so validating only its returned dictionaries cannot cover them.
Treat empty CSV strings as absent reasons. Do not treat a malformed or unknown
status as missing data. Validate SUCCESS's baseline version against the summary.
Update synthetic reference fixtures to carry real Phase 8 roles/definitions,
or generate them through the Phase 8 builder; do not exempt fixtures from the
new checks. Keep the already-passing key/split/purge/status-value regressions.

### Finding H: comparisons omit fit partition

The Phase 9 plan requires each comparison record to include its split and
fit-partition. Current records include `split` but no `fit_partition`, so readers
cannot distinguish train-fit validation from the final train-plus-validation
test refit.

Required fix:

- add `fit_partition` to every paired and `not_paired` comparison record;
- derive it from the ML prediction stage: `train` and `validation` use `train`,
  while `test` uses `train_plus_validation`;
- add a schema/output regression requiring the field and checking its values;
- regenerate the corrected artifact and update all hashes.

Also include `reference_fit_partition`: the frozen Phase 8 climatology uses
`train` for every split, whereas the Phase 9 test prediction uses
`train_plus_validation`. Preserve that predeclared historical comparison, but
label it `training_history_mismatch`/historical-reference diagnostic at test
time; matching row keys does not equal matching training history. Include
`metric_scope = descriptive_only`, paired-key digest and both row counts.
For ML-to-ML ablations record each side's fit partition and fit-key digest.
Keep the existing deltas, with their sign definition, and state that unequal
fit histories cannot isolate an effect of model family or weather features.
Do not retrain Phase 8, change its artifact, or invent a new matched-training
experiment during this correction.

### Finding I: validation overflow aborts the run

The v2 inverse guard works, and `score_instance()` catches its error during
final scoring. `select_alpha()` calls `predict_ridge()` before that guard's
caller, however, so validation overflow still raises out of `compute_instance`
and aborts the whole run. The v2 test exercises only `score_instance()`, not
alpha selection.

The reviewer reproduced this with finite, non-negative data:

```python
train = [model_row(float(i), math.expm1(float(i))) for i in range(6)]
validation = [model_row(1000.0, 1.0)]
select_alpha(train, validation, alpha_fit([], ["x"], "log1p"))
# Raises MLError("prediction_inverse_overflow") instead of returning a status.
```

Here `model_row` is the existing arithmetic test helper. A second probe used
the full synthetic artifact, sufficient training rows/dates and finite history
features: train `pm25_last_age_hours = day_index`, train target
`expm1(day_index + 1)`, validation age `1e6` with target `1.0`. The
`history_only` log1p Ridge instance raises the same error. No input contains
NaN, infinity or a negative target.

Required fix and predeclared failure policy:

1. Record a failed alpha candidate with a null validation score, status and
   exact `prediction_inverse_overflow` or `prediction_inverse_nonfinite` code.
   Score each successful candidate on the same validation keys; never discard
   individual failing rows to improve a score.
2. Select among finite candidates with the existing RMSE/smaller-alpha rule.
   If all candidates fail, mark that model instance unavailable across its
   metric cells, retain coverage and candidate failures, and continue unrelated
   specifications. Do not use fallback alpha 1.0: it is reserved for absent
   validation rows, not numerical failure.
3. Keep a failed final scoring cell unavailable with an explicit reason and no
   fabricated finite prediction. Classify validation-selected metrics as tuning
   diagnostics, not an independent holdout. Keep the final test non-selection
   rule.
4. Catch only the declared numerical prediction failures at these boundaries.
   Structural/identity/rank errors still stop the run. Replace the broad
   `except MLError` in `score_instance()` with a typed or code-checked path so
   programming/schema errors do not masquerade as a valid unavailable cell.
5. Add direct candidate and end-to-end regressions: one candidate fails; all
   candidates fail; train/refit passes but test inversion fails; malformed model
   input raises a hard error. Verify other instances continue, JSON has no
   NaN/Infinity, and finite ordinary scores stay unchanged except the seed
   consequence in F.

### Complete the earlier ordering requirement

`load_phase7()` currently calls `baselines.load_artifact()` before
`verify_payload_map()`. The inherited loader parses the CSVs, so the fixed-map
check does not run before parsing as the v2 report claims. Perform the fixed
payload preflight before invoking that inherited loader when expected payloads
are supplied. Keep the inherited SUCCESS/schema checks afterwards. Add a spy
on `baselines.read_csv` and prove that a re-signed altered frozen payload never
reaches parsing. Do not change the Phase 8 implementation for this fix.

## 11. Execution order and verification budget for the follow-up

The DeepSeek executor owns implementation and the following evidence. The
reviewer will check the new regressions, artifact identity and changed numerical
paths; do not repeat the entire project history or introduce a new orchestrator.

1. Record pending status and preserve v1/v2 hashes. Read this follow-up and the
   relevant Phase 9/8 code; reuse unchanged contract knowledge from the earlier
   run. Inspect worktree status and keep unrelated changes.
2. Add failing tests for E and I, then fix replay binding and numeric-failure
   handling. Run those tests, including preflight-before-parsing.
3. Fix F/G/H in one output/reference-boundary pass. Add tests for identities,
   enums/reasons, comparison fit history and unchanged source separation.
4. Set `ML_VERSION = phase9_ml_v3` and `REVISION = review_hardened`, record both
   preserved Phase 9 artifact identities in supersession metadata and update
   bound implementation hashes. Use the corrected identity seed derivation;
   do not add models, bootstrap inference, UI or new dependencies.
5. Run focused and full offline suites once on final code, isolated PostgreSQL,
   and `git diff --check`. Re-run focused checks only for code subsequently
   changed. A sandbox PostgreSQL failure may use the approved isolated retry,
   never Supabase.
6. Build `docs/verification/phase_9_models_2026-09-12_review_hardened/` through
   the source CLI with the same frozen Phase 7 and Phase 8 inputs. Stop if that
   output already exists. Preserve the seven output filenames from Section 6.
7. Compare all seven output bytes for module replay, CLI replay and relocated
   copies of the input directories in fresh temporary outputs. Keep exact
   digest checking; do not ignore differences in SUCCESS or metadata.
8. Assert frozen counts remain 96 declared instances, 24 trained calendar-only,
   288 metric cells with 72 available and 216 unavailable, unless a documented
   defect correction changes a count. Expect 192 correctly mapped per-sensor
   metric rows, and correct row locations in the prediction CSV. Do not force
   old floating-point scores, tree seeds or new schema hashes to match.
9. Verify original v1/v2 and Phase 7/8 artifact hashes unchanged, then close
   docs/README/AGENTS/progress with actual evidence. No commit or push without
   the user's request for this execution.

## 12. Follow-up handoff to the reviewer

Report:

- new directory, version, manifest and seven file hashes;
- E/G rejected mutations and proof of no output/fitting on early failures;
- candidate-failure counts and I's unavailable-vs-hard-error tests;
- F's two sensor/location mappings and whether identity-derived seeds changed;
- H's model/reference fit histories and descriptive-only mismatch labels;
- focused/full/database totals with passed/skipped separated;
- seven-file module/CLI/relocated replay equality and v1/v2 preservation;
- code paths changed, any unresolved gate, and scope boundaries.

Keep the frozen data limitation: missing captured PM/weather features cannot
support real forecast skill. Phase 10 dashboard work remains a separate task.

### Follow-up gates

### Finding J: offline gate count is reported incorrectly

The v2 report and documentation say `249 offline tests passed, 2 credential
skips`. The reviewer reran the suite and got `Ran 249 tests` with `247 passed`
and `2 skipped`; the two credential checks are included in the 249-test total.

Required fix:

- report `249 tests run: 247 passed, 2 skipped`;
- update `phase_9.md`, `README.md`, `AGENTS.md`, the deepwork record and the
  execution-report addendum without rewriting historical raw output;
- keep the focused result as 40 passed and isolated PostgreSQL as 52 passed;
- distinguish total tests from passed tests in the final handoff.

## 13. V3 comparison-reporting closeout (2026-09-12)

Limit this pass to comparison metadata and its tests. The reviewer accepts the
new E/F/G/I behavior and the already-tested input pinning/preflight guards. H's
fields exist, but their counts and matching labels need the changes below.
The missing comparison location in M completes the earlier F output contract.
Do not restart Phase 9, add new estimators or alter fitting to close these items.

Reviewer evidence on unchanged v3 code:

- 51 focused tests pass; the full suite runs 260 tests (258 pass, 2 skips).
- All 52 isolated PostgreSQL tests pass using the disposable local cluster.
- A source-CLI replay matches v3 byte-for-byte across seven files, including
  SUCCESS. Phase 7/8 and Phase 9 v1/v2/v3 payload and manifest hashes verify.
- Re-signed `false -> 0` and `30 -> 30.0` summaries stop before `compute_ml`.
- All 192 per-sensor metric rows and 65,424 prediction rows have the correct
  location mapping. This correction must preserve those mappings and values.
- The reviewer reproduced K in the frozen artifact and L with one missing
  training history value in the existing synthetic fixture. M is a schema gap.

### Finding K: reference finite-row counts are not sensor-scoped

`build_comparisons()` indexes reference predictions by baseline, split and
horizon, then reports finite reference rows from both sensors in a per-sensor
comparison. A CMT8 train/6h/calendar-versus-climatology comparison reports
`reference_finite_rows = 2564`. That includes both sensors and purged rows;
CMT8 has 1,277 non-purged finite reference predictions, of which 1,275 have
accepted finite targets. The MAE/RMSE deltas already use the correct 1,275 paired
keys. Fix counts without changing those deltas.

Required fix:

- Scope reference rows by baseline, sensor (or the pooled sensor union), split
  and horizon. Reject no source rows; retain the input artifacts unchanged.
- Define `model_finite_rows` and `reference_finite_rows` as each side's number
  of score-eligible prediction keys before pair intersection: correct group,
  non-purged row, accepted finite target and finite prediction with status
  `predicted`. Use the validated Phase 7 target/key map for the reference side.
  These two sets may differ because of model feature availability.
- Derive `paired_rows` and its digest from the intersection. Require
  `paired_rows <= min(model_finite_rows, reference_finite_rows)`.
- For frozen CMT8 train/6h/local-hour reference, the new reference count is
  1,275; the corresponding pooled count is 2,433. An optional separate finite
  prediction-only count may be 1,277 for CMT8, but label it separately and do
  not substitute it for the comparable target/prediction count.
- Add independent expected-count regressions with two sensors, a purged row,
  an absent target and different model feature completeness. Calculate the
  expected key sets directly in tests; do not call the production counter to
  obtain the expected result.

### Finding L: fit-history status ignores fit-key digests

`comparison_record()` labels history `matched` when partition names match. A
temporary fixture removed one history feature from the train rows. The ablation
comparison had different fit-key digests but still reported `history_status =
matched`.

Required fix:

- compute a digest for each comparison side's actual eligible fit-row keys;
- add `reference_fit_key_digest` for Phase 8 comparisons;
- add `counterpart_fit_key_digest` for ML ablations;
- set `history_status = training_history_mismatch` whenever partition names or
  fit-key digests differ;
- keep the metric deltas descriptive and label unequal fit histories.

Use actual fit membership, not evaluation pairs or feature-column names. Both
ML sides already expose `parameters.training_key_digest.selection/final`. For
the Phase 8 local-hour climatology, derive its fit keys from the verified Phase
7 rows using `baselines.fit_climatology`'s selection: same horizon/sensor scope,
`split == train`, not purged, accepted finite target. Do not require the ML
feature set to be complete when deriving the baseline fit set. This derives
metadata without refitting or rewriting Phase 8.

Compute a reference fit digest with the same deterministic sort/key convention
as the ML `key_digest`; include sensor, UTC origin and horizon. For an ablation,
set `reference_fit_key_digest` from its counterpart's actual fit keys and retain
`counterpart_fit_key_digest` for compatibility. A matched key set must give the
same digest on both paths; input row order must not affect the result.

Use these status rules in order:

1. No counterpart/pairs: `not_paired`, with the existing reason and explicit
   null digest if no fit exists.
2. A baseline uses no learned fit (direct persistence/trailing feature):
   `not_applicable` for training-history comparison. Do not invent train keys.
3. A fitted reference has no established fit membership: `unknown` with a
   reason. Do not call it matched.
4. Different partitions or different fit digests: `training_history_mismatch`.
5. Equal partitions and equal established fit digests: `matched`.

The frozen local-hour reference uses train rows; Phase 9 test fits include
validation. Keep those test comparisons labelled mismatch. For the synthetic
regression, start with the existing complete fixture, null one accepted,
non-purged train row's `pm25_lag_1h`, and fit only calendar/history Ridge with
the same transform. The calendar model retains that row, history excludes it.
All affected paired comparisons must report mismatched fit histories despite
matching partition names. A separate identical-membership fixture must report
matched. Keep paired evaluation deltas descriptive in both cases; do not retrain
on a common subset or claim the ablation isolates a weather/history effect.

### Finding M: comparison identity omits location ID

Comparison records contain sensor ID and scope but no `location_id`. Add the
reviewed location for per-sensor records and `pooled` for pooled records. Add a
schema regression for paired and `not_paired` rows.

Copy `identity.location_id` into comparisons after validating the existing
sensor-to-location mapping. Keep a complete comparison metadata schema even
when unavailable: use `paired_key_digest = null` and fit digests/reasons as
applicable, rather than dropping schema fields. This is not a new output file.

### Closeout implementation boundary

Expected code edits: `build_comparisons`, `comparison_record` and narrow helpers
in `src/vn_air/ml.py`, with tests in `tests/test_ml.py`. Pass validated row/fit
metadata into comparison construction explicitly. Do not load data from the
database, use test labels for fitting, or weaken fixed input/replay guards.

Preserve Ridge/tree parameters, hyperparameters, transforms, seeds and
train/validation/test membership. The reviewed numerical model outputs are not
the target of K–M. Preserve stored model fit-key digests where their convention
already suffices; use that convention for reference keys.

Use `phase9_ml_v4`, revision `comparison_hardened`, and a new directory:

```text
docs/verification/phase_9_models_2026-09-12_comparison_hardened/
```

Refuse to overwrite any existing directory, including that path if it already
exists. Record v1/v2/v3 in supersession metadata; preserve their files unchanged.
V3 manifest: `c5cc4047766c16108beb0e5f0dc46dd7e9ddb871159d37989e7dd4b5a3df0d82`.
Keep the seven Phase 9 output filenames. Update code/output hashes as usual.

### Verification and handoff for this pass

The DeepSeek executor owns these checks. Reuse the accepted E–J tests; add K–M
tests before building the new frozen artifact. Run the full suite once on final
code, then repeat only tests affected by subsequent edits plus repo-required
gates. Do not create another dependency or review pipeline.

1. Assert scoped counts, paired-key digests, location fields and matched/
   mismatched/unavailable history states on independent synthetic key sets.
2. Run focused ML tests, full offline suite, isolated PostgreSQL and diff/docs
   checks. Keep all original E–J regressions.
3. Build v4 from the same pinned Phase 7/8 artifacts. Assert 96 instances,
   24 trained, 288 metric cells (72 available, 216 unavailable), 65,424
   predictions, 360 comparisons and `limited_diagnostic`.
4. Compare v3 and v4 `phase_9_predictions.csv` and `phase_9_metrics.csv`
   byte-for-byte: both must remain identical for this metadata-only correction.
   Compare parameter `fits` separately from the new top-level version. Require
   unchanged fitted parameters and seeds. Comparison counts/labels/schema and
   versioned metadata are expected to change, not the MAE/RMSE deltas.
5. Replay v4 through the module, source CLI and relocated input copies into
   fresh temporary directories; compare all seven files, including SUCCESS.
   Verify original Phase 7/8 and v1/v2/v3 hashes unchanged.
6. Update current-status prose in README, AGENTS, Phase 9 verification, plan
   status and local progress together. Keep historical test logs and preserved
   artifacts intact. Do not claim numerical model failure or forecast skill
   based on this reporting review.

Report the new manifest and seven hashes, scoped CMT8/pooled counts, equal and
unequal fit-history regression results, seven-file replay evidence, and test
totals with passed/skipped separated. State that the predictions, standalone
metrics, seeds and fitted parameter values stayed unchanged. Do not commit or
push unless the user requests it for the execution task.

### Follow-up gates

After K–M, retaining E–J coverage, run the focused suite, full offline suite, isolated PostgreSQL suite,
`git diff --check`, corrected artifact hash validation, module/CLI/relocated
replay and v1/v2 preservation checks. The final status remains
`limited_diagnostic`; these findings do not create captured PM/weather
availability.
