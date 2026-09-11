# Phase 8 Integrity and Replay Hardening Plan

Status: correction complete and verified
Date: 2026-09-11 UTC

## Finding

Review of the Phase 8 v1 runner found two contract gaps:

1. `load_artifact()` verified only the hashes listed in Phase 7 `SUCCESS.json`.
   If a required feature or target file hash was removed from that manifest, the
   loader still read and used the file.
2. `replay_baselines()` compared selected manifest fields but did not bind the
   complete split/boundary contract. A summary with a re-signed `test_start` or
   `validation_start` could be accepted.

These are input-integrity and reproducibility defects. They do not change the
baseline definitions or scientific target contracts.

## Required behavior

- Phase 7 `SUCCESS.json` must declare hashes for the required summary, feature
  and target files; missing declarations must raise `BaselineError`.
- The declared Phase 7 feature version, availability, bundle identity, summary
  manifest hash and required file hashes must agree with the summary.
- Summary-bound replay must validate the previous Phase 8 summary's own
  manifest digest and compare the complete replay contract, including baseline
  version, Phase 7 input hashes, bundle identity, availability, horizons,
  boundary, split, row counts, status and baseline policies.
- A re-signed summary with any changed replay-bound field must be rejected.
- Preserve all baseline calculations, train-only fitting, purge exclusion and
  limited-diagnostic semantics.

## Implementation and tests

- Bump `BASELINES_VERSION` to `phase8_baselines_v2`.
- Harden `src/vn_air/baselines.py` loader and replay binding.
- Add tests for omitted required input hash and re-signed split-boundary change.
- Keep v1 artifact unchanged and generate a new
  `docs/verification/phase_8_baselines_2026-09-11_integrity_hardened/` artifact.

### Final verification scope

The directory above contains an intermediate v2 build made before the complete
replay fix. Preserve it, both v1 directories and the later intermediate
`phase_8_baselines_2026-09-11_integrity_hardened_final/` and
`phase_8_baselines_2026-09-11_v2_final/` directories. The completed portable v2
build is `phase_8_baselines_2026-09-11_v2_verified/`.

The final correction requires the summary, feature and target hashes; permits
only the five known Phase 7 payload filenames; checks declared files against
files present in the artifact; and rejects payload symlinks. It rejects
non-object metadata, duplicate JSON keys and non-finite JSON tokens before
processing the metadata. Checksums verify consistency, not authentication.

Compare the complete Phase 8 manifest and its digest on replay, plus purpose.
This includes implementation hashes and input content identities, but excludes
the local input-directory string. Identical inputs can replay from another
checkout path without changing the output. Baseline definitions use a JSON list
so deserialized metadata matches the in-memory manifest. Reject an existing
output directory or absent parent before replay computation. Both ordinary and
relocated-input replay must pass alongside the tamper tests.

These changes do not alter the baseline formulas, eligibility or metrics. The
calendar baseline remains a retrospective diagnostic using training-partition
targets; its numerical scores do not establish historical model availability
or an untouched prospective holdout.

## Verification

Run the focused baseline suite, full offline suite, isolated PostgreSQL suite,
`git diff --check`, markdown/link checks, v2 CLI/module run and summary-bound
replay. Compare every output hash and confirm the v1 artifact remains valid.
No database write, migration, schedule, model training or secret exposure is
allowed.

The v1 review also confirmed that these two cases are real: removing the
feature-file hash from `SUCCESS.json` was accepted, and a re-signed Phase 8
summary with a changed split boundary was accepted. The correction must test
both cases after re-signing the altered metadata.

### Completed evidence

Verification owner: the continuation agent. The input-integrity and replay
claims are covered by the 26-test baseline suite, including missing hashes,
unsafe paths, symlinks, duplicate JSON keys, re-signed manifest changes and
relocated-input replay. CLI run, module replay and CLI replay each reproduced
the authoritative v2 artifact byte-for-byte (5/5 files).

The offline suite ran 209 tests: 207 passed and two exact-credential checks
skipped because no credentials were exported. The disposable PostgreSQL suite
passed 52 tests after an approved retry outside the sandbox; the initial
sandboxed attempt stopped at initdb. No study database was accessed. See
[phase_8.md](phase_8.md) for the artifact identity and final gates. Baseline
formulas and frozen diagnostic results are unchanged. Checksums establish
content consistency, not publisher authenticity or operational availability.
