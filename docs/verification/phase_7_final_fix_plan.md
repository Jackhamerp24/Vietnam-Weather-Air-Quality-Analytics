# Phase 7 Final Fix Plan: v2 Review Findings

Status: Request changes
Executor: GLM 5.3 Flash
Date: 2026-09-09 UTC
Scope: fix the remaining Phase 7 v2 review findings before final verification

Execute this plan in the current Phase 7 worktree. Preserve all existing Phase
7 artifacts and do not overwrite them.

## 1. Current evidence

The Phase 7 v2 implementation has already passed:

- 68 focused synthetic tests;
- 161 offline tests, with 2 documented credential skips;
- 52 isolated PostgreSQL tests;
- `git diff --check`;
- corrected artifact hash validation;
- independent summary-bound replay for all six output files.

Current v2 diagnostic evidence:

- input bundle:
  `docs/verification/phase_7_input_bundle_2026-09-09_corrected.json`
- output directory:
  `docs/verification/phase_7_features_2026-09-09_corrected/`
- feature version: `phase7_features_v2`
- manifest SHA-256:
  `6971a3a90eac770eda5daa3ca7f12b05c0362483193273f03384b28f21b0f9e6`

Preserve unchanged:

- `docs/verification/phase_7_features_2026-09-09_captured/`
- `docs/verification/phase_7_features_2026-09-09_corrected/`

Generate a new final artifact after the fixes:

`docs/verification/phase_7_features_2026-09-09_final/`

Do not generate an assumed-mode artifact. Do not commit or push.

## 2. P1-A: status counts invalid evidence as available

### Defect

In `src/vn_air/features.py`:

- `pm_available_origin_count` increments when `state["series"]` contains any
  revision, even if every row is invalid, missing, suspect or non-finite.
- `weather_available_origin_count` increments when a snapshot exists, even if
  every value is missing, invalid, temporally misaligned or unavailable at the
  captured origin.

The current code can produce:

`text
all PM rows invalid
all weather values missing
status = ok
status_missing_families = []
rows_with_complete_data_feature_set = 0
`

### Required behavior

Define:

- `pm_available_origin_count`: sensor/origin states with at least one finite
  `accepted` PM2.5 row eligible under the selected availability policy.
- `weather_available_origin_count`: location/origin states with at least one
  finite `accepted` weather value that belongs to an identity-valid selected
  snapshot, passes availability, and passes temporal-support/period-start
  alignment for at least one requested horizon.

Do not count raw revisions or snapshot metadata as usable feature evidence.

Final status:

- `ok` only if both required families have at least one usable origin;
- `limited_diagnostic` otherwise;
- `status_missing_families` names the missing family/families.

Partial but valid weather evidence counts as family availability even if no row
has the complete feature set. Count each location/origin once, not once per
horizon.

Suggested PM change:

`python
accepted = {
    when: item
    for when, item in state["series"].items()
    if item["quality_status"] == "accepted" and finite(item["value"])
}
if accepted:
    counts["pm_available_origin_count"] += 1
`

For weather, calculate the family count after examining usable values for all
requested target intervals at that location/origin.

## 3. P1-B: input table hashes are not verified

### Defect

`check_bundle_structure()` checks row counts but does not recompute and compare:

`text
manifest.input_sha256.measurements
manifest.input_sha256.snapshots
manifest.input_sha256.model_values
`

A changed dataset can currently be accepted after recomputing only the outer
`bundle_sha256`.

### Required behavior

1. Require `manifest.input_sha256` to contain exactly:
   - `measurements`;
   - `snapshots`;
   - `model_values`.
2. Recompute each table digest using the project `digest()` helper.
3. Compare every result to the declared table hash.
4. Raise `FeatureError` on any mismatch.
5. Retain existing count, schema and foreign-key checks.
6. Add an `input_integrity` section to the output manifest recording the
   verified hashes.

Use the same representation used by `features_store.py` when producing
`input_sha256`.

Regression test:

1. start with a valid signed synthetic bundle;
2. change one measurement value;
3. recompute only the outer `bundle_sha256`;
4. verify `load_bundle()` or CLI build still rejects it due to a table-hash
   mismatch.

Keep the existing outer-hash tamper test.

## 4. Small hardening: availability enum

`validate_request()` currently checks membership in the whole `FEATURE_POLICY`
mapping, which also contains descriptive keys.

Add:

`python
ALLOWED_AVAILABILITY = ("captured", "assumed")
`

Reject every other value at the Python API boundary. Add tests for `fallback`
and an unknown value.

## 5. Required tests

Update `tests/test_features.py` with:

1. invalid-only PM rows give `pm_available_origin_count == 0`;
2. missing/invalid-only weather gives
   `weather_available_origin_count == 0`;
3. PM-only usable evidence reports only `forecast_weather` missing;
4. weather-only usable evidence reports only `pm_history` missing;
5. both usable families give `status == "ok"`;
6. partial valid weather evidence counts as weather availability while complete
   row count may remain zero;
7. a re-signed altered table is rejected by table-hash verification;
8. `availability_basis="fallback"` is rejected;
9. status results are deterministic under input-row reordering.

Use invalid/missing fixtures, not only empty tables.

## 6. Execution order

### Step 0 — Baseline

`bash
git status --short
PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_features -q
git diff --check
`

Do not modify the existing v1/v2 artifacts.

### Step 1 — Add a correction note

Before regenerating an artifact, append a dated note to
`docs/verification/phase_7_plan.md`. State that this is a mechanical correction
to status accounting and input-table integrity. Do not change target,
availability, source or split contracts.

### Step 2 — Implement and run focused tests

Edit:

- `src/vn_air/features.py`;
- `tests/test_features.py`;
- `docs/verification/phase_7_plan.md`.

Run:

`bash
PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_features -v
`

Do not proceed while any new regression test fails.

### Step 3 — Generate a new final frozen diagnostic

Reuse the corrected input bundle only if its declared table hashes validate.
Never overwrite v1 or v2.

`bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli features build \
  --bundle docs/verification/phase_7_input_bundle_2026-09-09_corrected.json \
  --config configs/study.json \
  --output-dir docs/verification/phase_7_features_2026-09-09_final \
  --horizons 6 24 \
  --availability captured \
  --require-frozen-boundary
`

Expected frozen result remains:

- `status = limited_diagnostic`;
- missing families are `pm_history` and `forecast_weather`;
- PM/weather usable-origin counts are both zero;
- all PM/weather data-feature values are null;
- targets and split/purge counts are unchanged.

### Step 4 — Summary-bound replay

`bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli features replay \
  --bundle docs/verification/phase_7_input_bundle_2026-09-09_corrected.json \
  --config configs/study.json \
  --summary docs/verification/phase_7_features_2026-09-09_final/phase_7_feature_summary.json \
  --output-dir <new-replay-directory>
`

Compare SHA-256 for all six files, including `SUCCESS.json`.

### Step 5 — Full gates

`bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
git diff --check
`

Verify:

- output hashes match `SUCCESS.json`;
- `digest(manifest) == manifest_sha256`;
- all input table hashes match;
- replay is byte-identical;
- no existing artifact was overwritten.

### Step 6 — Documentation

Only after all gates pass:

1. Update `docs/verification/phase_7.md` to point to the final artifact.
2. Document corrected status and table-hash semantics.
3. Update `AGENTS.md` and `README.md` to point to the final artifact.
4. Keep the prospective collection blocker and Phase 8 boundary explicit.
5. Do not commit or push without user authorization.

## 7. Acceptance criteria

Phase 7 is finally verified only when:

- invalid-only PM/weather input cannot produce `status = ok`;
- status counts usable accepted feature evidence, not raw rows;
- input table hashes are verified before build;
- re-signed tampered bundles are rejected;
- invalid availability bases are rejected;
- v1/v2 artifacts remain unchanged;
- final artifact and replay are byte-identical;
- focused/offline/PostgreSQL suites pass;
- `git diff --check` passes;
- no migration, database write, scheduler, model training or secret exposure
  occurs.

## 8. Final handoff

Report only:

1. final artifact and input paths;
2. old artifact preservation;
3. final manifest/input/output hashes;
4. status-family counts and invalid-only regression results;
5. table-hash validation result;
6. focused/offline/PostgreSQL results;
7. replay comparison;
8. no-write/no-migration/no-secret confirmation;
9. whether Phase 8 remains blocked by prospective captured data.
