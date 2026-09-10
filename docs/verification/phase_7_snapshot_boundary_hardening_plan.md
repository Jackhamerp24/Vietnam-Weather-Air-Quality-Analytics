# Phase 7 Snapshot Boundary Hardening Plan

Status: Executed and superseded by structural-schema hardening
Executor: current Codex worktree
Date: 2026-09-10 UTC

## 1. Finding

Adversarial review of the v5 builder found that snapshot metadata was not fully
structurally bound. A re-signed bundle could omit or mutate `domain` or
`data_kind`, or introduce an unknown `product_id`, and the builder could either
ignore the snapshot or fail with an unhelpful `KeyError`. The reviewed product
registry and the required snapshot identity boundary must be enforced before
feature construction.

## 2. Required behavior

For every bundle snapshot:

- `id`, `product_id`, `domain` and `data_kind` must be present and non-empty;
- `product_id` must exist in the reviewed product registry when a reviewed
  configuration is supplied;
- snapshot `domain` and `data_kind` must exactly match the reviewed product;
- feature-relevant forecast snapshots must continue to be rejected/countable
  when their location, purpose, model key, coordinates or response identity is
  invalid;
- missing feature-snapshot location must produce a recorded location rejection,
  not a raw `KeyError`;
- modeled values must remain consistent with their referenced snapshot domain;
- sensor/location dictionary keys and embedded IDs must agree, so a re-signed
  nested identity cannot bypass the reviewed registry.

Do not silently ignore unknown products or malformed snapshot identity under the
real CLI path. Preserve the fixture-only unreviewed unit-test path where it is
explicitly intended.

## 3. Implementation

Update `src/vn_air/features.py`:

1. Bump the feature version to `phase7_features_v6`.
2. Extend structural validation for snapshot identity and embedded registry IDs.
3. Validate reviewed product metadata for every snapshot before construction.
4. Make snapshot identity rejection handling safe for missing location fields.
5. Enforce modeled-value/reference-snapshot domain consistency.
6. Preserve all prior v5 checks and all scientific, availability, target,
   lineage, split and purge semantics.

## 4. Tests

Add focused regressions in `tests/test_features.py` for:

- missing snapshot `domain`/`data_kind`/`product_id` rejection;
- unknown snapshot product rejection under reviewed configuration;
- snapshot product domain/kind mutation rejection;
- missing feature-snapshot location is recorded as a location rejection rather
  than raising `KeyError`;
- modeled-value domain mismatch with its snapshot rejection;
- sensor/location embedded-ID mutations and dictionary-key mismatches;
- valid reviewed bundles retain all registry flags and v5 substantive counts.

Retain all prior v1–v5 regression tests.

## 5. Artifact policy

Never overwrite an existing artifact. Preserve v1, v2, v3, v4 and v5 exactly.
After focused tests pass, generate:

`docs/verification/phase_7_features_2026-09-10_snapshot_hardened/`

Use `docs/verification/phase_7_input_bundle_2026-09-10_registry.json` with the
reviewed configuration, captured availability and frozen-boundary assertion.
Expected substantive counts remain 8,548 feature rows, 8,290 available
targets, 258 absent targets, 112 purged rows, PM/weather available origins 0/0
and `status = limited_diagnostic`.

Replay into a new temporary directory and compare all six output files,
including `SUCCESS.json`, byte-for-byte.

## 6. Verification gates

Run focused tests, the full offline suite, the isolated PostgreSQL suite,
`git diff --check`, markdown/link checks, artifact hash checks and deterministic
replay. Confirm no database write, migration, scheduler, model training or
secret exposure occurred. Only after every gate passes, make the v6 artifact
authoritative in `phase_7.md`, `AGENTS.md` and `README.md` and record v6 in the
handoff. Do not commit or push in this correction task.

## 7. Execution record — 2026-09-10

- Feature version: `phase7_features_v6`.
- Snapshot-hardened artifact:
  `docs/verification/phase_7_features_2026-09-10_snapshot_hardened/`.
- Input bundle: `docs/verification/phase_7_input_bundle_2026-09-10_registry.json`.
- Input bundle digest: `4cf5e9537758308a67c09e00cc9af3931946bab8ea64c6520cac36f1d3ed3c4e`.
- Input bundle file SHA-256: `c797e03a21f45d00fc5dd92647a0c37106476860cae2d47b19a3a8757c530894`.
- Output manifest SHA-256: `a05d86b9247fbf2f6bed9d4d0050211a3cff1da885073c95b2f7933703239357`.
- Required snapshot identity, reviewed product domain/kind, modeled-value
  domain, embedded registry IDs and missing-location handling are enforced.
- Frozen counts remain 8,548 feature rows, 8,290 available targets, 258 absent
  targets, 112 purged rows and PM/weather available origins 0/0; status remains
  `limited_diagnostic`.
- Focused builder/regression tests: 84 passed. The five CLI replay tests and
  full post-v6 suites were blocked by macOS stalling on dataless `.venv`
  SQLAlchemy/Pydantic files; the v6 CLI build and summary-bound replay were run
  manually and matched all six files. Prior v5 gates were 180 offline tests and
  52 isolated PostgreSQL tests, and v6 changed no database code.
- Summary-bound replay matched all six output files byte-for-byte, including
  `SUCCESS.json`.
- v1 through v5 artifacts remain unchanged. No database write, migration,
  scheduler, model training or secret exposure occurred.

The v6 artifact remains preserved and is superseded by the v7 structural-
hardened artifact documented in `phase_7_structural_schema_hardening_plan.md`.
