# Phase 7 Structural Schema Hardening Plan

Status: Executed; artifact verified, full rerun environment-limited
Executor: current Codex worktree
Date: 2026-09-10 UTC

## 1. Finding

Adversarial bundle fuzzing after the v6 snapshot-boundary correction found that
some malformed input could still raise a raw `KeyError`, `TypeError` or
`AttributeError`, or omit a required modeled-value field without a clear
`FeatureError`. The integrity checksum and reviewed registry checks are useful
only if malformed table rows are rejected deterministically before feature
construction.

## 2. Required behavior

Before any feature construction, validate the bundle shape and required fields:

- dataset registries must be mappings whose values are JSON objects;
- measurements, snapshots and modeled values must be lists of JSON objects;
- registry keys must match embedded IDs where an embedded ID exists;
- every measurement must contain the identity, time, revision and quality
  fields used by revision selection and target/history construction;
- every snapshot must contain required identity/provenance fields; a missing
  feature-snapshot location remains a recorded `location` rejection rather than
  a raw exception;
- every modeled value must contain `id`, `snapshot_id`, `variable_code`,
  `valid_at`, `period_start`, support, quality, unit/domain and recorded-time
  fields;
- every malformed case must raise `FeatureError`, never `KeyError`, `TypeError`
  or `AttributeError`;
- preserve all v6 registry, table-hash, availability, source, target, lineage,
  split and purge semantics.

## 3. Implementation

Update `src/vn_air/features.py`:

1. Bump the feature version to `phase7_features_v7`.
2. Add small stdlib-only required-field/type helpers in
   `check_bundle_structure`.
3. Validate all required table fields before any direct indexing or timestamp
   conversion.
4. Keep the input table hash checks first and keep reviewed-registry checks
   after structural checks.
5. Do not repair, fill or normalize malformed bundle rows.

## 4. Tests

Add focused regressions for missing modeled-value fields (`id`, `valid_at`,
`period_start`), missing measurement fields, non-object registry/table rows,
non-mapping datasets and malformed snapshots. Every case must raise
`FeatureError`. Retain all v1–v6 tests.

## 5. Artifact policy

Preserve v1 through v6 exactly. After focused tests pass, build:

`docs/verification/phase_7_features_2026-09-10_structural_hardened/`

from `docs/verification/phase_7_input_bundle_2026-09-10_registry.json`, with
the reviewed config, captured availability and frozen-boundary assertion.
Expected substantive counts remain 8,548 feature rows, 8,290 available
targets, 258 absent targets, 112 purged rows, PM/weather available origins 0/0
and `status = limited_diagnostic`.

Replay into a new temporary directory and compare all six output files.

## 6. Verification

Run focused structural/builder tests, artifact hash checks, replay comparison,
`git diff --check` and markdown/link checks. Report the local `.venv` hydration
blocker precisely if it still prevents the full offline/PostgreSQL rerun. Do
not commit or push in this correction task.

## 7. Execution record — 2026-09-10

- Feature version: `phase7_features_v7`.
- Artifact: `docs/verification/phase_7_features_2026-09-10_structural_hardened/`.
- Input bundle: `docs/verification/phase_7_input_bundle_2026-09-10_registry.json`.
- Input bundle digest: `4cf5e9537758308a67c09e00cc9af3931946bab8ea64c6520cac36f1d3ed3c4e`.
- Input bundle file SHA-256: `c797e03a21f45d00fc5dd92647a0c37106476860cae2d47b19a3a8757c530894`.
- Output manifest SHA-256: `6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa`.
- Structural fuzz/regression builder tests: 85 passed; malformed rows now
  consistently raise `FeatureError`.
- Pure-builder/output-writer artifact generation and independent replay matched all six files
  byte-for-byte, including `SUCCESS.json`; the CLI was unavailable during this
  pass because local macOS `.venv` SQLAlchemy/Pydantic files stalled on
  hydration.
- Counts remain 8,548 feature rows, 8,290 available targets, 258 absent
  targets, 112 purged rows, PM/weather available origins 0/0 and
  `status = limited_diagnostic`.
- v1 through v6 artifacts remain hash-valid and unchanged. No database write,
  migration, scheduler, model training or secret exposure occurred.
