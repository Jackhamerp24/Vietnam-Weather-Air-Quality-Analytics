# Phase 7 Registry-Boundary Fix Plan: v3 Review Finding

Status: Executed and verified
Executor: GLM 5.3 Flash
Date: 2026-09-10 UTC
Scope: close the remaining configuration and variable-registry integrity gap before final Phase 7 approval

Execute this plan in the current worktree. Preserve every existing Phase 7
artifact. Do not commit or push.

## 1. Finding

The v3 pipeline validates the reviewed configuration digest and some
sensor/location fields, but it does not compare the complete bundle variable
registry with the reviewed configuration.

Reproduction already performed:

1. Start from a valid signed synthetic bundle.
2. Change the `temperature_2m.temporal_support` field from `instant`
   to preceding_hour_mean.
3. Recompute only the outer bundle_sha256.
4. Build with the reviewed configuration.
5. The builder accepts the altered registry.

This is a latent prospective-mode defect. Temporal support, canonical units,
domain membership, sensors and station locations are part of the feature
contract and must not drift while the configuration digest remains unchanged.

## 2. Required behavior

When the real CLI supplies --config, validate the complete reviewed
configuration against the bundle before feature construction.

### 2.1 Variable registry

Compare the exact reviewed configuration variable mapping with
dataset.variables:

- variable-code set: no missing and no extra variables;
- canonical_unit;
- domain;
- temporal_support.

Validate all configured variables, not only variables used by the selected
horizon or current snapshot.

### 2.2 Sensor registry

Compare all identity fields needed by the builder:

- sensor ID;
- location ID;
- product ID;
- variable code;
- canonical unit;
- timezone through the referenced location.

Reject missing or extra bundle sensors. Retain the existing timezone check.

### 2.3 Location registry

For every sensor-referenced location, compare:

- location ID;
- kind;
- latitude;
- longitude;
- timezone.

Use exact reviewed configuration values for this boundary. The existing
1e-6-degree tolerance remains only for forecast snapshot requested-coordinate
validation.

### 2.4 Dataset structural consistency

Retain existing count, table-hash, snapshot-reference and schema checks. Add
deterministic checks that:

- every measurement sensor/product/variable/unit identity matches its reviewed
  sensor;
- every modeled value variable code exists in the validated registry;
- every modeled value canonical unit, domain and temporal_support match the
  registry;
- each modeled-value key (snapshot_id, variable_code, valid_at) is unique;
- every snapshot has product_id, domain and data_kind;
- every feature-relevant snapshot points to a configured station location;
- all declared input-table hashes are verified before registry validation.

Do not silently repair a bundle. Raise FeatureError on every mismatch.

The existing bundle digest is an integrity checksum, not an authentication
signature. Do not add signing infrastructure or a database migration.

## 3. Implementation requirements

Update src/vn_air/features.py:

1. Add a dedicated helper named, for example,
   validate_bundle_against_reviewed(bundle, reviewed).
2. Use the same JSON-normalized configuration representation as
   features_store.py.
3. Call the helper from build_features whenever reviewed is supplied.
4. Keep synthetic Python tests usable without external reviewed configuration
   only where the unit-test path explicitly intends that behavior.
5. The real CLI build and replay paths must always pass and enforce the reviewed
   configuration.
6. Keep input_integrity.verified true only after table hashes and registry
   checks pass.
7. Record a manifest section with:
   - mode;
   - reviewed_sha256;
   - variable_registry_verified;
   - sensor_registry_verified;
   - location_registry_verified.
8. Preserve all existing availability, source, target, warm-up, split and purge
   semantics.

Do not change:

- target contract;
- 6h and 24h horizons;
- captured or assumed availability semantics;
- source separation;
- revision-before-quality ordering;
- warm-up policy;
- missingness behavior;
- v1, v2 or v3 artifacts.

## 4. Tests to add

Update tests/test_features.py with tests for:

1. valid bundle plus reviewed config succeeds;
2. re-signed variable temporal-support mutation is rejected;
3. re-signed variable canonical-unit mutation is rejected;
4. re-signed variable domain mutation is rejected;
5. added variable is rejected;
6. removed variable is rejected;
7. sensor product, variable or unit mutation is rejected;
8. sensor location mutation is rejected;
9. station coordinate or timezone mutation is rejected;
10. measurement identity mismatch is rejected;
11. modeled-value variable, unit or support mismatch is rejected;
12. duplicate modeled-value key is rejected;
13. city or unknown feature snapshot location is rejected;
14. existing input-table hash mismatch rejection remains active;
15. valid synthetic bundle without external reviewed config remains usable only
    through the explicitly documented unit-test path;
16. valid frozen build retains the same substantive counts and status;
17. registry-validation manifest fields are all true for a valid reviewed build.

For re-signed registry-tamper tests, mutate the dataset and recompute only the
outer bundle digest. Do not update the reviewed configuration. The test must
prove that the reviewed registry catches changes outside the three table hashes.

## 5. Documentation addendum

Before regenerating any artifact, append a dated section to
docs/verification/phase_7_plan.md titled:

Phase 7 registry-boundary correction addendum — 2026-09-10

State that:

- this is a mechanical registry-boundary correction found during review;
- it does not change the scientific target, horizons, availability modes,
  source policy, split/purge rules or any model result;
- complete reviewed variable, sensor and location registries are validated
  before build;
- synthetic validation may omit external configuration only in explicit unit
  tests;
- real CLI build and replay require reviewed configuration validation;
- no corrected artifact is generated before this addendum exists.

## 6. Artifact and preservation policy

Preserve unchanged:

- docs/verification/phase_7_features_2026-09-09_captured/
- docs/verification/phase_7_features_2026-09-09_corrected/
- docs/verification/phase_7_features_2026-09-09_final/
- docs/verification/phase_7_input_bundle_2026-09-09.json
- docs/verification/phase_7_input_bundle_2026-09-09_corrected.json

Generate a new output directory:

docs/verification/phase_7_features_2026-09-10_final/

Use a new input bundle only if the existing corrected bundle fails the
strengthened validation. Never overwrite an existing directory.

Expected frozen diagnostic semantics:

- status = limited_diagnostic;
- missing families = pm_history and forecast_weather;
- PM/weather usable-origin counts = 0/0;
- all PM/weather data features are null;
- targets = 8,290 available and 258 absent;
- split/purge counts remain unchanged;
- registry-validation fields are true.

## 7. Execution sequence

### Step 0 — Baseline

Run:

    git status --short
    PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_features -q
    git diff --check

Do not modify existing artifacts.

### Step 1 — Add the plan addendum

Update docs/verification/phase_7_plan.md before generating the new artifact.

### Step 2 — Implement and test

Edit only the phase-scoped code, tests and plan first:

- src/vn_air/features.py;
- tests/test_features.py;
- docs/verification/phase_7_plan.md.

Run:

    PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_features -v

Do not regenerate the real artifact while focused tests fail.

### Step 3 — Build the new frozen artifact

Run:

    PYTHONPATH=src .venv/bin/python -B -m vn_air.cli features build \
      --bundle docs/verification/phase_7_input_bundle_2026-09-09_corrected.json \
      --config configs/study.json \
      --output-dir docs/verification/phase_7_features_2026-09-10_final \
      --horizons 6 24 \
      --availability captured \
      --require-frozen-boundary

Confirm the output manifest records successful registry validation and the
frozen substantive counts remain unchanged.

### Step 4 — Summary-bound replay

Run into a new directory:

    PYTHONPATH=src .venv/bin/python -B -m vn_air.cli features replay \
      --bundle docs/verification/phase_7_input_bundle_2026-09-09_corrected.json \
      --config configs/study.json \
      --summary docs/verification/phase_7_features_2026-09-10_final/phase_7_feature_summary.json \
      --output-dir <new-replay-directory>

Compare SHA-256 for all six files, including SUCCESS.json.

### Step 5 — Full verification

Run:

    PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
    PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
    git diff --check

The PostgreSQL suite must use its disposable cluster. If initdb is blocked,
record the exact OS error and do not substitute a Supabase write.

Also verify:

- output hashes match SUCCESS.json;
- manifest digest matches manifest_sha256;
- input-table hashes are verified;
- registry-validation fields are all true;
- no target value appears in the feature CSV or lineage;
- no unaccepted target has a non-null target_pm25;
- v1, v2 and v3 artifacts are byte-preserved;
- frozen counts and boundary remain unchanged.

## 8. Documentation updates

Only after all gates pass:

1. Update docs/verification/phase_7.md to identify the 2026-09-10 artifact as
   authoritative.
2. Record the registry-validation behavior and actual test counts.
3. Preserve v1, v2 and v3 as historical superseded evidence.
4. Update AGENTS.md and README.md to point to the new artifact.
5. Keep Phase 8 blocked until genuinely captured prospective data exists.
6. Do not commit or push without explicit user authorization.

## 9. Acceptance criteria

The fix is complete only when:

- re-signed variable-registry mutations are rejected;
- complete reviewed variable, sensor and location registries are validated;
- modeled-value identity and temporal-support consistency are enforced;
- duplicate modeled-value keys are rejected;
- valid frozen input builds with unchanged substantive counts;
- registry-validation fields are recorded and true;
- v1, v2 and v3 artifacts remain unchanged;
- focused tests pass;
- offline suite passes;
- isolated PostgreSQL suite passes or its exact OS blocker is documented;
- replay is byte-identical for all six files;
- git diff --check passes;
- no database write, migration, scheduler, model training or secret exposure
  occurs.

Do not mark Phase 7 verified while registry validation can be bypassed by
re-signing only the outer bundle digest.

## 10. Final handoff format

Report only:

1. new artifact and input paths;
2. preservation status for v1, v2 and v3;
3. registry-validation results;
4. focused, offline and PostgreSQL test results;
5. final and replay hashes;
6. frozen count comparison;
7. no-write, no-migration and no-secret confirmation;
8. whether Phase 8 remains blocked by prospective captured data.

## 11. Execution record — 2026-09-10

The correction was executed in this worktree. Its intermediate v4 artifact is
`docs/verification/phase_7_features_2026-09-10_final/`, built from
`docs/verification/phase_7_input_bundle_2026-09-10_registry.json` with
`--config configs/study.json --require-frozen-boundary`.

- Feature version: `phase7_features_v4`.
- Input bundle digest: `4cf5e9537758308a67c09e00cc9af3931946bab8ea64c6520cac36f1d3ed3c4e`.
- Input bundle file SHA-256: `c797e03a21f45d00fc5dd92647a0c37106476860cae2d47b19a3a8757c530894`.
- Output manifest SHA-256: `91d1d993ebd70664b6f0ab486e1a6bfbc55c507d710de2c03b67f6046d908e58`.
- Variable, sensor and location registry validation: all verified.
- Frozen substantive counts: 8,548 feature rows; 8,290 available targets;
  258 absent targets; 112 purged rows; PM/weather available origins 0/0;
  `status = limited_diagnostic`.
- Focused feature tests: 86 passed. Offline suite: 179 passed, 2 documented
  credential skips. Isolated PostgreSQL suite: 52 passed.
- Deterministic replay: all six output files, including `SUCCESS.json`, matched
  byte-for-byte.
- The v1, v2 and v3 artifacts were not overwritten. No database write,
  migration, scheduler, model training or secret exposure occurred.

The subsequent derived-sensor-metadata hardening supersedes v4 with the
authoritative v5 artifact documented in
`docs/verification/phase_7_registry_hardening_plan.md`. Phase 8 remains blocked
for real captured baselines until a prospective
collection period produces evidence timestamps before the forecast origins.
