# Phase 11 implementation plan: safe ingestion automation

Version: `phase11_automation_v1`
Date: 2026-09-12 UTC
Owner: OpenCode DeepSeek V4.1 Flash (`max`) with Codex review and integration

Implementation status (2026-09-13 local date): Stage A/B delivered; Gate 1
passed on its earlier reviewer gate. Codex implemented and coordinator-verified
the three Gate 2 corrections after the delegate task failed. Exact
commands, counts and limitations live in `docs/verification/phase_11.md`; the
activation contract is `docs/operations.md`. No schedule, migration, role,
public API, real project backup or live cycle was installed or performed.
The correction closeout does not claim an independent reviewer approval.

## 1. Objective

Add a locally testable operations layer around the existing bounded ingestion
worker. The layer must support scheduled invocation, safe failure reporting,
operator recovery guidance, and verified PostgreSQL backups without changing the
scientific meaning of Phases 4–10.

Phase 11 delivers automation tooling and an activation runbook. It does not
install a schedule, deploy a service, expose Supabase, provision database roles,
send credentials to a notification provider, or claim operational readiness.
Prospective captured evidence remains required before real feature and forecast
evaluation.

## 2. Codebase context the implementer must preserve

This is a Python 3.11+ portfolio project with a PostgreSQL schema owned by
`vn_air`. Phase 3 already provides on-demand ingestion in
`src/vn_air/ingestion/`:

- `pipeline.py` runs serial bounded source jobs for `openaq`, `weather`, `cams`
  and `era5`, uses a PostgreSQL advisory session lock, enforces provider/database
  budgets, records raw response evidence, preserves revisions and quality issues,
  and recovers stale runs.
- `src/vn_air/cli.py` exposes `vn-air ingest poll|backfill`, database status and
  read-only reports. The installed entry point can lag source code; source-mode
  commands use `PYTHONPATH=src .venv/bin/python -m vn_air.cli`.
- `docs/ingestion.md`, `docs/database.md` and `docs/supabase.md` define the
  current operational limits. The worker requires an explicit PostgreSQL URL,
  uses environment variables for credentials, and never loads `.env` itself.
- `scripts/test_database.py` runs isolated PostgreSQL integration tests against a
  disposable Unix-socket-only cluster. It never uses the project database.
- Phases 4–9 are frozen analytical artifacts. Phase 10 is a static local
  dashboard built from pinned artifacts and must remain database-free and
  read-only. Do not make the dashboard live in Phase 11.

Required invariants:

1. Keep measured OpenAQ PM2.5, Open-Meteo forecasts, ERA5 reanalysis and CAMS
   modeled AQ separate.
2. Do not alter Phase 4–10 artifacts, frozen hashes, model results, or dashboard
   public-bundle semantics.
3. Do not interpolate, replace, or silently relabel missing data.
4. Historical retrieval time is not historical availability.
5. Do not add a database migration, schema write path, Data API endpoint, API
   key, browser credential, external queue, Redis/Kafka service or new runtime
   dependency unless the user explicitly authorizes it.
6. Agents must not read or transmit `.env` or credential values. Activated
   application commands may consume credentials from the process environment
   as the existing worker does. Do not print/log/attach those values, raw
   responses, request headers or exception strings to agent prompts or reports.

## 3. Required implementation boundaries

### 3.1 Automation configuration

Create a reviewed, non-secret configuration for the automation cycle. It must
declare, at minimum:

- enabled source jobs and their order;
- explicit poll windows delegated to the existing worker;
- per-job request budgets below the provider limits;
- maximum cycle duration and stale-run threshold;
- expected cadence and freshness thresholds for health checks;
- output directory for safe operational evidence;
- backup retention policy as documentation, not an automatic deletion job.

Reject unknown keys, duplicate jobs, non-positive budgets, invalid durations,
and unsafe or occupied output paths. Preserve existing poll windows: OpenAQ's
last 72 complete UTC hours and weather/CAMS's three UTC calendar days, including
forecast valid times. ERA5 stays backfill-only. Keep secrets out of config.

The configuration must be safe by default: dry-run or explicit operator
activation is required for a real cycle. A missing configuration must fail
closed with a stable error code.

### 3.2 Cycle runner

Implement a small runner, preferably in `src/vn_air/automation.py` with a
stdlib-only output/helper module if needed. Add a CLI namespace such as
`vn-air automation` with subcommands chosen to fit the existing parser:

- `plan` or `dry-run`: validate local configuration and command plan; open no
  database or network connection. Report actual schema/role checks as unperformed;
- `run`: execute the configured bounded jobs through the existing ingestion
  path, in a deterministic order, with per-job and whole-cycle results;
- `health`: produce a safe read-only health snapshot and exit with a documented
  status code;
- `recover` or `reconcile`: inspect orphaned/failed/partial runs and print
  retry guidance. Any mutating retry must be explicit, bounded and separately
  logged;
- `backup`: create a new backup plus a hash manifest using an external
  PostgreSQL backup tool without exposing its connection string;
- `backup-verify`: verify a backup manifest/listing and, where possible, restore
  only into a disposable isolated database.

The exact command names may differ if the existing CLI structure makes another
name safer, but the capabilities and contracts below are mandatory.

Cycle rules:

- Check that the database is PostgreSQL and schema revision is exactly
  `0003_response_integrity` before starting.
- Never run migrations automatically. Never point at a template database.
- Use one stable local cycle lock independent of config/output paths. Hold it
  until all children are reaped. Retain the worker advisory lock; do not acquire
  that database lock in a parent session that would block the child. Report
  `already_running` on contention. This is concurrent-cycle exclusion, not
  exactly-once delivery or multi-host cycle coordination.
- Preserve/document the existing worker's reference seeding and lock-proven
  stale-run finalization writes. Read-only commands must not invoke the worker.
  Activation requires a separately reviewed grants/RLS design; choosing a role
  does not make the current owner/bypass-RLS worker least-privileged.
- Preserve source order and stop/continue behavior in the config. A failed job
  must make the cycle non-successful even if later jobs complete.
- Pass only allowlisted arguments to the existing ingestion commands. Never
  construct shell strings from provider data; use argument arrays/subprocess
  calls or direct Python calls.
- Supervise subprocesses with monotonic job/cycle deadlines and bounded output.
  Terminate, escalate to kill, and reap a timed-out child/process group before
  releasing the lock or continuing. Bound database waits. Persist allowlisted
  events/error codes rather than arbitrary scrubbed stdout/stderr strings.
- Keep per-job stdout/stderr separate from secrets. Scrub known credential
  values and connection-like strings before persistence or display.
- Return stable exit categories: success, partial, failed, configuration error,
  already running and backup/restore verification failure.
- Write a deterministic safe summary with source, window, status, counts,
  stable error codes, schema version and timestamps explicitly labelled as
  operational timestamps. Do not include response bodies or raw SQL.
- Do not overwrite an evidence file or backup. Require a new output path.

### 3.3 Health and failure alerts

Provide a read-only health projection over existing aggregate/report queries.
Include:

- schema revision and database-size budget status;
- recent run status by product/source;
- last success, last partial and last failure timestamps;
- stale-running jobs and orphaned-run indicators;
- provider cooldown/request-budget indicators when available;
- recent quality-issue counts and missing-hour signals;
- backup age/manifest status when an operator backup directory is supplied;
- an explicit `limited_diagnostic`/prospective-collection note where relevant.

Health output must have a machine-readable JSON form and concise human text.
Use exit codes so cron/systemd/launchd can treat unhealthy output as an alert.
Do not add a paid notification service. A local JSON alert artifact and stderr
summary are sufficient; document how an operator can connect them to an approved
mail/monitoring system later without putting credentials in this repository.

Do not call a failed or stale data run healthy because the process exited zero.
Distinguish `succeeded`, `partial`, `failed`, `stale`, `schema_mismatch`,
`budget_exhausted`, `backup_stale` and `unknown`.

Evaluate each configured source and target; one healthy sensor cannot hide a
failed second sensor. Separate fetch freshness from accepted-data freshness
and coverage. OpenAQ can succeed with missing hours; model `valid_at` does not
measure capture freshness. Missing/inaccessible evidence is not healthy. Age
alone means suspected stale, not proven orphaned. Inspection cannot mark a live
worker failed or bypass the existing lock-proven recovery mechanism.

### 3.4 Recovery

Implement safe recovery guidance based on persisted ingestion state:

- identify stale `running` rows and failed/partial chunks;
- show source, target, explicit window, error code, retryability and last attempt;
- respect existing checkpoint semantics: a successful response with missing
  hours is not silently treated as complete coverage;
- never delete raw evidence or rewrite append-only observations;
- never auto-reconcile a completed checkpoint merely because coverage is low;
- require explicit operator confirmation for any retry command;
- keep retry windows bounded and avoid concurrent cycles.

Add deterministic synthetic tests for interrupted workers, provider cooldown,
budget exhaustion, partial jobs, retryable versus non-retryable errors and
duplicate invocation.

### 3.5 Backup and restore verification

Use PostgreSQL-native tooling (`pg_dump`, `pg_restore` or an equivalent
validated local mechanism) through argument arrays. Do not implement a Python
export that bypasses PostgreSQL constraints or omits raw evidence.

The backup command must:

- require an explicit output path in a new directory/file;
- refuse symlink, existing-output and broad/ambiguous targets;
- use the operator's environment-provided connection only; never accept a
  password or URI in a command-line argument;
- record tool version, schema revision, dump format, UTC creation time, byte
  size and SHA-256 in a manifest without recording the URI;
- include `vn_air`, `public.vn_air_schema_version`, required project functions,
  views, constraints and retained raw evidence; exclude Supabase-managed schemas
  and cluster-wide roles. Describe this as a project logical backup;
- map environment credentials to libpq without URL/password argv and without
  weakening TLS. Use owner-only directories/files. Do not silently inherit
  ambient PGHOST, PGSERVICE, PGOPTIONS or password-file settings;
- fail if the dump tool fails or produces an empty/unexpected result;
- leave a failed output clearly marked and never claim a valid backup;
- support an offline manifest/listing verification path.

Restore verification must target a new disposable PostgreSQL cluster/database,
never the configured project database. It must check migration/schema version,
reference metadata counts, append-only/provenance constraints and representative
read-only report queries. Use a fresh private socket-only cluster, sanitized
child environment and bounded processes. Offer no caller-supplied restore URL.
Do not run migrations/seeding to repair a broken restore. Checksum/listing
checks are not restoration evidence: perform a real synthetic dump and restore
before claiming the restore gate passed. Do not print dump data or TOC output.

Do not implement automatic backup deletion in this phase. Provide retention and
off-site storage instructions in the runbook; deletion requires a separate
authorization and recovery policy.

### 3.6 Scheduling and activation runbook

Provide templates or documented commands for one of cron, launchd or systemd,
but do not install or enable them. The runbook must require the operator to
choose:

- a dedicated least-privilege ingestion role;
- an explicit secret store/environment with owner-only permissions;
- a working directory and log/alert destination;
- schedule/cadence appropriate to provider limits;
- backup destination and restore drill cadence;
- escalation contacts and pause/rollback steps.

The activation checklist must include a dry run, isolated database run, live
read-only health check, quota review, backup restore drill, and manual stop
test. State clearly that completion of the checklist does not establish forecast
skill, causal validity, city-wide coverage or production readiness.

## 4. Files and documentation expected

The implementer may add or adjust only phase-scoped paths after inspection.
Expected deliverables are:

- `src/vn_air/automation.py` and any narrowly scoped helper/output module;
- CLI integration in `src/vn_air/cli.py`;
- reviewed non-secret automation configuration under `configs/`;
- backup/restore or health scripts only when their responsibility cannot stay in
  the package;
- `tests/test_automation.py` and focused integration coverage under
  `tests/integration/`;
- `docs/verification/phase_11.md` with actual evidence and limitations;
- `docs/verification/phase_11_plan.md` updated with implementation status;
- `docs/operations.md` or an equivalent runbook covering activation, alerts,
  recovery, backups, restore drills and pause procedures;
- concise updates to `README.md`, `AGENTS.md` and
  `.slim/deepwork/phase-11-automation.md`.

Do not modify historical Phase 4–10 verification artifacts except for a
cross-reference when necessary. Do not add `.env` examples containing real
values. Do not change the Phase 10 dashboard contract.

## 5. Verification gates

Run and record, in order:

1. Focused automation unit tests with fake clock, fake subprocess runner and
   fake database responses.
2. Full offline suite:
   `PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v`.
3. Isolated PostgreSQL suite:
   `PYTHONPATH=src .venv/bin/python -B scripts/test_database.py`.
4. Backup/restore smoke test only against the disposable PostgreSQL cluster.
5. CLI dry-run, health and failure exit-code checks with no network call.
6. Secret and path safety checks: no `.env` read, no credential output, no
   unsafe symlink/traversal/output overwrite, no shell injection.
7. `git diff --check` plus deterministic JSON/artifact replay where applicable.
8. Confirm Phase 5–10 hashes and dashboard tests remain unchanged.

Evidence must name the command, result, test count and any documented skip.
Live Supabase checks belong to future operator activation, not this execution.
Do not run live ingestion, migrations, role changes, schedules or real backup
exports. Add a real local sleeping-child termination/kill/reap test and confirm
lock release happens after the child is gone.

## 6. Hard stops

Stop and report a stable blocker if any of these occur:

- missing/ambiguous database URL or schema revision mismatch;
- attempted migration, schema mutation, public API exposure or role creation;
- credentials, raw responses or private database identifiers would enter logs,
  artifacts, prompts or commits;
- process lock cannot prevent duplicate cycles;
- backup cannot be verified in a disposable restore;
- output path is existing, symlinked, broad or outside the requested scope;
- a feature would require a new external service/dependency without approval;
- tests cannot distinguish partial ingestion from successful complete coverage.

## 7. Definition of done

Phase 11 is complete when a reviewer can execute a dry-run, inspect a safe
health result, simulate a failed/partial/stale cycle, verify recovery guidance,
create and validate a disposable-database backup, and follow the activation
runbook without guessing. The repository still has no installed scheduler,
public data API, live dashboard refresh, automatic retraining or operational
forecast claim.

## 8. Execution decisions and delivery order

This section fixes the implementation choices left open above. It incorporates
the Codex Gate 0 review. If general wording above conflicts with this section,
follow these explicit decisions and record any further change before coding it.

### Default operating profile

- `configs/automation.json` uses strict versioned JSON with duplicate-key,
  unknown-field and exact-type checks (booleans are not integer budgets).
- Jobs: OpenAQ for both configured sensors (10 attempts total), weather for
  CMT8/OceanPark (5 total), CAMS for the three configured cities (5 total).
  Run in that order, stop on failed/partial job, record remaining jobs as
  not attempted. No unattended ERA5 or backfill in this profile.
- Operator schedule: one local hourly cycle at minute 17. This is a template,
  not an installed schedule or guarantee of provider issuance/uptime.
- Per-job timeout 900 seconds; cycle 2,700 seconds including preflight and
  finalization; terminate grace 5 seconds then kill/reap. A timeout must not
  leave a detached collector. No automatic outer retries; the Phase 3 worker
  already retries within its budgets and persists cooldowns.
- Stable cycle lock: one owner-only ignored lock file under the resolved
  repository `.local/` directory; use an OS lock, not a stale PID marker. Do
  not unlink the inode while releasing it. Reject a symlink lock/parent. Same
  checkout has the same lock regardless of output or configuration path. Other
  checkouts/hosts retain only the existing global ingestion advisory session
  lock and are not supported as
  concurrent scheduler installations.
- Readiness defaults: max database 400 MiB; schema `0003_response_integrity`;
  fetch success age 3 hours; OpenAQ latest accepted period age 6 hours and at
  least 18/24 accepted complete UTC intervals per sensor; modeled snapshot
  capture age 6 hours; stale-running age 1,800 seconds. Allow per-target
  threshold overrides only for reviewed target IDs, with positive bounded
  values. These thresholds are operating choices, not health guidance.
- Use latest revision before quality filtering in coverage queries. Model
  freshness uses source capture/retrieval/recording timestamps, not future
  `valid_at`. Recent successful HTTP receipt with invalid/null-only canonical
  data is not sufficient. Report missing evidence as `unknown`/unhealthy.
- Health exit mapping: `0` for all configured checks healthy, `2` for degraded
  (partial/stale/low coverage/missing backup), `1` for failure/unknown evidence/
  schema/budget stop, `3` for invalid configuration. Preserve all reasons and
  use severity precedence `1 > 2 > 0`; do not select severity with `max(code)`.
  Cycle uses `0` succeeded, `2` partial, `1` failed, `3` invalid request, and
  `4` concurrent cycle excluded. Document command-specific meanings.

### CLI and local evidence

- Commands: `automation plan`, `run`, `health`, `recover`, `backup`,
  `backup-verify`. Reuse `--config` for the study registry and introduce
  `--automation-config` for the new profile. Defaults remain repo-relative.
- `plan` requires no credentials, DB, clock-dependent network results or
  schema lookup. Support explicit `--now` for reproducible planning only.
  Live `run` must use the actual current clock, not a supplied historical one.
- `run` requires `--execute` and `--output-dir` before any engine/HTTP use.
  Reserve a new owner-only output directory before external actions. A missing
  switch reports a constant code and does nothing. Do not expose arbitrary
  executables, SQL, shell fragments or child environment through profile JSON.
- CLI execution delegates to supervised `sys.executable -B -m vn_air.cli`
  children with checked source/target arguments. Child processes derive the
  actual poll window from the existing worker clock; any parent preview is
  labelled planned. Do not claim a fixed preview is the executed window if a
  cycle crosses UTC midnight.
- Save `phase_11_cycle_summary.json` and allowlisted alerts to the reserved
  directory; add `SUCCESS.json` only after a wholly successful cycle. Preserve
  failed/partial summaries without a success marker. Operational wall times
  are real evidence, so distinct live runs need not be byte-identical.
- `recover` is read-only guidance only. Do not implement another orphan
  finalizer or automatic replay. For weather, suggest a fresh poll (historical
  weather backfill is unsupported); for OpenAQ suggest a bounded explicit
  operator backfill where appropriate. Unknown error codes are not auto-retryable.
- Health/recovery use bounded read-only transactions, parameterized SQL and
  explicit UTC as-of time. Avoid global historical scans where the existing
  target/time indexes can constrain the query. Reuse the existing report only
  where its fields suffice; last-12-runs alone cannot prove each target healthy.
- Keep operational logs local. No Slack/email/webhook destination is configured
  or invoked. Write constant stderr status suitable for an external monitor;
  the operator supplies an approved notification channel at activation.

### Native backup and drill

- `backup --execute --output-dir NEW` is an explicit read-only DB export and
  local file write. This task may execute it only against synthetic test data.
- Use project-scoped PostgreSQL custom archives. Ensure the selected object
  set includes all `vn_air` schema objects and the public migration table;
  check PostgreSQL selection-option semantics with a synthetic round trip.
  Retain responses/quarantine privately; do not include roles, auth, storage or
  unrelated schemas. Separate project-scoped archives are acceptable if one
  manifest binds each file and restore order.
- Dump tool credentials come from a sanitized libpq environment. Parse the
  validated SQLAlchemy URL, preserve host/socket, port, database, user and TLS
  options, reject unsupported security-affecting query options, never emit its
  value. Do not inherit ambient service/passfile/PGOPTIONS routing. Do not print
  dump stderr, arbitrary TOC names or provider payloads.
- Use owner-only directories/files, exclusive creation and fixed filenames.
  Record tool/server major versions, schema, UTC time, byte size, SHA-256 and
  `scope=project_logical`. No valid manifest/success marker for empty, partial,
  corrupt or timed-out dumps. Dumps can vary in bytes; this is not analytical
  deterministic replay.
- `backup-verify` checks exact regular-file membership, strict manifest fields,
  hashes/sizes, format and bounded listing; report `checksum_verified`, not
  `restore_verified`. Reject renamed/symlinked/tampered/missing/extra files.
- Add an explicit `--restore-drill` option using a new private socket-only
  cluster, fixed synthetic role/database, no external restore target, stripped
  project/PG environment, bounded native commands and cleanup of only its own
  validated temporary resources. Treat archives as trusted operator inputs;
  restoring SQL is not a security sandbox for hostile dumps. Never repair the
  restored DB with migrations or reseeding.
- Round-trip evidence must cover schema revision, 4/16/5/2 reference counts,
  synthetic raw body hashes, measurement revisions, model snapshots/values,
  checkpoints/issues, SELECT report behavior, and representative FK/append-only
  constraints. Test that an unrelated source schema is absent after restore.
- Recommend daily operator backups, 36-hour stale threshold, encrypted off-site
  copy and monthly drills, but install none and delete no existing backups.

### CI and scheduling deliverables

Add `.github/workflows/ci.yml` for credential-free offline and disposable
PostgreSQL gates on push/pull request/manual dispatch only. Use read-only
repository permissions, no live secrets, no `pull_request_target`, no scheduled
source ingestion, no uploads of database dumps/raw evidence, bounded jobs and
source-mode Python commands. Pin action revisions to verified upstream commits;
if offline, report that lookup as a blocker instead of inventing a hash. Use
existing pinned application dependencies. Do not claim a GitHub run happened
until it has happened; local YAML checks alone do not prove hosted CI.

Provide one launchd template under `ops/launchd/`, with explicit placeholders
for checkout/interpreter/operator environment, no credential values, no install
command executed. Document secret injection for launchd (it does not inherit
an interactive shell), local sleep/offline limitations, pause/removal, log
handling, nonzero-alert integration and backup schedule separately. Do not
promise continuous collection from a laptop. A separate grants/RLS activation
review and first authorized live cycle are still required.

### Delivery gates in this same OpenCode conversation

1. **A: configuration, offline planner, supervised cycle and safety tests.**
   Implement these first and return a Gate 1 report to Codex. Do not proceed
   to backup tooling until Codex acknowledges the gate. Report source-order,
   contention, process cleanup, deadlines, no-side-effect preflight and secret
   canary tests. Keep analytical modules unchanged.
2. **B: health, recovery, project backup/drill, CI/template, docs and closeout.**
   After Codex's follow-up in this same session, execute remaining work, run
   focused/offline/isolated gates, and return exact evidence. Read local
   Supabase/PostgreSQL skills before writing SQL/restore tests; project Alembic
   history overrides generic migration advice. Never delegate to other models.
3. **Final review.** Codex reviews the delivered diff/evidence, writes or sends
   focused corrections in this same session, and handles escalated issues here.
   Do not create another chat or run `oc escalate --new`. To request Codex help,
   return a blocker or use `oc notify --type escalation --status needs-codex`;
   do not start another model or recursively delegate. No commit/push.

The existing 313-test baseline had one new-plan trailing-whitespace failure;
Codex removed the two trailing spaces. This was a plan-only formatting defect.
Rerun that regression and record a current baseline before implementation.

Gate 0 factual sources: public Supabase changelog and backup guidance inspected
2026-09-12; project schema/ingestor source inspected at `31a1d68`. Free-tier
logical export recommendations do not establish project-specific capacity or
live backup success. Sources: https://supabase.com/changelog.md and
https://supabase.com/docs/guides/platform/backups.
