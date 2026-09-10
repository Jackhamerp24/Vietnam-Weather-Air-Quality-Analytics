# Phase 7 Registry Hardening Plan: Derived Sensor Metadata

Status: Executed and superseded by snapshot-boundary hardening
Executor: current Codex worktree
Date: 2026-09-10 UTC

## 1. Finding

Adversarial review of the registry-validated Phase 7 v4 path found that a
re-signed bundle can mutate a sensor's derived `timezone` (and, separately,
`name`) while leaving the reviewed location registry and configuration digest
unchanged. The builder consumes `sensor.timezone` for its local calendar
features, so this is a real prospective boundary defect. The v4 artifact is
preserved unchanged as historical evidence and must not remain authoritative.
The resulting v5 artifact is also preserved and is superseded by the later
snapshot-boundary hardening.

## 2. Required behavior

When a reviewed configuration is supplied:

- each bundle sensor's `name` must equal the reviewed referenced location name;
- each bundle sensor's `timezone` must equal the reviewed referenced location
  timezone;
- the sensor's referenced location must exist and be a station;
- the builder's timezone contract must therefore be derived from the reviewed
  location registry, not an independently mutable sensor field;
- all prior variable, sensor, location, measurement, modeled-value, snapshot,
  duplicate-key and input-table-hash checks remain active.

Reject every mismatch with `FeatureError`; do not repair or normalize the
bundle silently. Keep the fixture-only unreviewed unit-test path unchanged.

## 3. Implementation

Update `src/vn_air/features.py`:

1. Bump the feature version to `phase7_features_v5`.
2. Extend the reviewed sensor boundary check to validate derived `name` and
   `timezone` against the reviewed location referenced by `location_id`.
3. Ensure the referenced reviewed location is a station before accepting the
   sensor.
4. Keep table-hash verification before registry validation and preserve all
   Phase 7 scientific, availability, lineage, target and split semantics.

## 4. Tests

Add focused regressions in `tests/test_features.py` for:

- re-signed sensor timezone mutation rejection;
- re-signed sensor name mutation rejection;
- valid reviewed registry still produces all three `*_registry_verified` flags;
- the existing frozen substantive counts and status remain unchanged.

Retain all existing v4 registry mutation and tamper tests.

## 5. Artifact policy

Do not overwrite any existing artifact. Preserve v1, v2, v3 and v4 exactly.
After focused tests pass, build a new artifact directory:

`docs/verification/phase_7_features_2026-09-10_hardened/`

Use the existing registry input bundle:

`docs/verification/phase_7_input_bundle_2026-09-10_registry.json`

with the reviewed configuration, captured availability and the frozen-boundary
assertion. Expected substantive counts remain 8,548 feature rows, 8,290
available targets, 258 absent targets, 112 purged rows, PM/weather available
origins 0/0 and `status = limited_diagnostic`.

Replay into a new temporary directory and compare all six output files,
including `SUCCESS.json`, byte-for-byte.

## 6. Verification gates

Run focused feature tests, the full offline suite, the isolated PostgreSQL
suite, `git diff --check`, markdown/link checks, artifact hash checks and the
deterministic replay comparison. Confirm that no database write, migration,
scheduler, model training or secret exposure occurred.

The v5 gates passed, but a later adversarial snapshot review required another
correction. The v5 artifact is preserved as superseded historical evidence;
`phase_7_snapshot_boundary_hardening_plan.md` records the v6 correction. Do not
commit or push in this correction task.

## 7. Execution record — 2026-09-10

- Feature version: `phase7_features_v5`.
- Hardened artifact: `docs/verification/phase_7_features_2026-09-10_hardened/`.
- Input bundle: `docs/verification/phase_7_input_bundle_2026-09-10_registry.json`.
- Input bundle digest: `4cf5e9537758308a67c09e00cc9af3931946bab8ea64c6520cac36f1d3ed3c4e`.
- Input bundle file SHA-256: `c797e03a21f45d00fc5dd92647a0c37106476860cae2d47b19a3a8757c530894`.
- Output manifest SHA-256: `a7808378f711a17e5f8b4dd835bde5912d459c24895564ec3769ceac1c75542c`.
- Derived sensor `name` and `timezone` mutations are rejected; all registry
  validation flags are true for a valid reviewed build.
- Frozen counts remain 8,548 feature rows, 8,290 available targets, 258 absent
  targets, 112 purged rows and PM/weather available origins 0/0; status remains
  `limited_diagnostic`.
- Focused feature tests: 87 passed.
- Full offline suite: 180 passed, with 2 documented credential skips.
- Isolated PostgreSQL suite: 52 passed in the disposable cluster.
- Summary-bound replay matched all six output files byte-for-byte, including
  `SUCCESS.json`; replay output was written under the temporary review
  directory `/private/tmp/phase_7_v5_replay_final.CKHJtH/replay`.
- Existing v1, v2, v3 and v4 artifacts were not overwritten. No database write,
  migration, scheduler, model training or secret exposure occurred.

The v5 artifact is also preserved unchanged and superseded by the v6
snapshot-hardened artifact.
