# Phase 11 Stage B review corrections

Status: implemented and coordinator-verified on 2026-09-13 (local date). The
OpenCode correction task failed; the user then asked Codex to implement it
directly. [Phase 11 verification](phase_11.md) records the 117 focused, 430
offline and 63 isolated PostgreSQL test results. No independent re-review is
claimed. The original instructions below remain for traceability; do not rerun
OpenCode or repeat the fixes merely because this plan exists.

Do not commit or push during this correction pass. Do not read `.env`, run live
ingestion, access Supabase, install a schedule, provision roles, create a
migration, or create a real project backup. Run only synthetic/disposable
verification where the plan requires it.

## 1. Prevent operator-environment secret inheritance

Finding: `ops/launchd/cycle_wrapper.example.sh:17-21` sources and exports the
whole operator environment file. `src/vn_air/automation.py:838-844` then copies
the complete parent environment into each ingestion child. Any unrelated secret
in the operator file can reach the runner and its descendants.

Fix both boundaries:

- Make `SubprocessSupervisor.child_environment` construct an explicit child
  environment. Keep only the variables required by the existing ingestion
  worker and safe runtime basics: `DATABASE_URL`, `OPENAQ_API_KEY`, `PATH`,
  `HOME`, `LANG`, `LC_ALL`, `TZ`, the applicable temporary-directory variable,
  and the project `PYTHONPATH` built from the reviewed checkout. Do not pass
  `SUPABASE_SECRET_KEY`, service-role/publishable keys, access tokens,
  `SUPABASE_DB_URL`, arbitrary `*_SECRET`, `*_TOKEN`, `*_PASSWORD`, `*_KEY`,
  `PG*`, `PYTHONINSPECT`, `PYTHONSTARTUP`, `LD_*`, `DYLD_*`, or unrelated
  variables. Preserve `DATABASE_URL` and `OPENAQ_API_KEY` only because the
  Phase 3 worker needs them; keep them out of evidence.
- Make backup/restore `sanitized_base_environment` an explicit safe-runtime
  allowlist as well. Add only the derived, validated `PG*` values needed by the
  native PostgreSQL command after sanitization. Do not rely on a name-pattern
  redaction rule as the only defense.
- Change the launchd wrapper so it does not export arbitrary variables from the
  operator file. Accept only the documented required keys and reject unknown
  names or unsafe syntax, or use a small allowlisted loader that exports only
  `DATABASE_URL` and `OPENAQ_API_KEY` to the Python process. Keep the template
  free of real values and keep the operator file outside the repository.
- Update `docs/operations.md` and the launchd comments to state the exact
  allowed environment variables and the rejection behavior.
- Add regression tests that place `UNRELATED_SECRET`, `UNRELATED_TOKEN`,
  `SUPABASE_SECRET_KEY`, and `PGSERVICE` in a parent environment. Prove they
  are absent from ingestion child environments and backup/restore tool
  environments, while `DATABASE_URL` and `OPENAQ_API_KEY` remain available only
  where required. Prove the canaries never appear in cycle summaries or alerts.

## 2. Make archive creation exclusive and race-safe

Finding: `src/vn_air/automation_backup.py:375-389` passes the final fixed
archive path directly to `pg_dump`. PostgreSQL can truncate or replace an
existing final path before the post-dump checks run, violating the documented
exclusive-output contract.

Fix without weakening the fixed filenames in the manifest:

- Before invoking `pg_dump`, reject any existing final archive path, including a
  symlink, with a stable `automation_backup_archive_exists` code.
- Create a unique owner-only temporary file inside the already reserved backup
  directory using exclusive creation. Pass only that temporary path to
  `pg_dump`; never pass `vn_air_schema.dump` or `vn_air_migration.dump` to the
  tool. Remove the temporary file on every failure and timeout.
- After a successful dump, verify the temporary path is a regular, non-symlink,
  non-empty file and set mode `0600`. Atomically publish it to the final name
  with no-replace semantics, such as an exclusive hard-link followed by removal
  of the temporary name. If the final path appears during the dump, fail and
  leave no valid manifest. Do not use `os.replace`, which would overwrite.
- Keep listing, size, SHA-256 and manifest checks on the final published file.
  Preserve the failure marker and ensure a partial/corrupt backup never gets a
  valid manifest or success result.
- Add tests for an existing final archive, a symlink final archive, a fake runner
  that creates the final path during the dump, temporary-file cleanup after a
  dump failure, and the normal two-archive success path. Assert `pg_dump` never
  receives a final fixed archive filename.

## 3. Assess fetch freshness per configured source and target

Finding: `src/vn_air/automation_health.py:191-209` aggregates successful
receipts by provider/product, and `:471-479` assesses that aggregate once per
source. A fresh CMT8 receipt can therefore satisfy the fetch-freshness check
for OceanPark, and one modeled location can mask another.

Fix the health contract:

- Join `vn_air.source_responses` to `vn_air.ingestion_runs` by `run_id` and
  query successful receipts for every configured source+target. For OpenAQ,
  filter the reviewed `target_sensor_id`; for weather/CAMS, filter the reviewed
  `target_location_id`. Keep product/provider-group allowlists and the bounded
  requested/retrieved lookback.
- Count only `http_status = 200`, `error_code IS NULL`, non-null body, and
  requested/retrieved timestamps inside the lookback. Do not infer target
  freshness from a product-level aggregate. Keep the existing separate
  accepted-PM coverage and modeled finite-canonical-value checks.
- Store `source`, `product`, `target`, `target_kind`, `latest_success_at` and
  `successes` in each fetch fact. Evaluate age and missing evidence against
  that exact identity. A successful receipt for another target must not make
  this target healthy. If a source aggregate is retained, label it
  informational and never use it for readiness or exit status.
- Update the health JSON, tests and runbook to expose target-scoped fetch facts.
  Add a two-target regression where one target has a fresh receipt and the
  other has no receipt or a stale receipt. Assert the latter receives
  `fetch_evidence_missing` or `fetch_stale` and the correct exit severity. Cover
  OpenAQ and at least one modeled source.

## 4. Verification and handoff

Run the focused correction tests first. Then run the full offline suite and the
isolated PostgreSQL suite once at the coherent correction boundary. Also run
`git diff --check`, the research/dashboard integrity tests, CLI no-credential
checks, plist/shell/YAML syntax checks, and a stray-process/temp-file check.

Update `docs/verification/phase_11.md`, `AGENTS.md`, `README.md` and the local
deepwork progress file with exact current counts and the correction status. Do
not claim Gate 2 passed. Return a correction handoff for Codex review with the
changed files, exact commands/results, and any remaining limitations.
