# Phase 11 verification: safe ingestion automation

Version: `phase11_automation_v1`
Initial delivery: 2026-09-12 UTC. Correction closeout: 2026-09-13 local date.
Status: Stage A/B delivered; Codex implemented and verified the three Gate 2
corrections. Gate 1's earlier reviewer approval remains historical evidence;
the correction closeout is coordinator verification, not an independent re-review.
Stage B adds read-only health and recovery, a
project-scoped native logical backup with checksum/listing verification and a
real synthetic dump/restore drill, plus CI and launchd templates (not installed)
and `docs/operations.md`.

Stage A adds a strict reviewed automation profile, a side-effect-free planner,
a supervised bounded poll cycle with a stable checkout-local lock, allowlisted
evidence and focused offline plus isolated-PostgreSQL tests. Stage B adds a
bounded read-only health projection with explicit severity precedence, read-only
recovery guidance, project-scoped `pg_dump` archives in a sanitized libpq
environment, manifest/checksum/listing verification and a real restore into a
fresh private socket-only cluster. No scheduler was installed, no live ingestion,
Supabase access or real project backup was performed, no migration or schema
write was added and no real credential was read, printed or persisted by the agent.

## Delivered code

- `configs/automation.json`: strict versioned non-secret profile. Jobs run in
  order `openaq_poll` (10 requests), `weather_poll` (5), `cams_poll` (5), stop
  on failed/partial, per-job 900 s, cycle 2,700 s, terminate grace 5 s, hourly
  expected cadence. Readiness defaults pin schema `0003_response_integrity`,
  the 400 MiB worker stop as the database budget, 3 h fetch age, 6 h OpenAQ
  accepted-period age, 18/24 accepted UTC intervals, 6 h modeled capture age,
  1,800 s stale-running age and a 36 h backup stale threshold.
  `backup.automatic_deletion` is `false` with operator retention and off-site
  notes; the duplicate backup-age field was removed.
- `src/vn_air/automation.py`: strict pydantic config with duplicate-key,
  unknown-field, exact-int/str/bool literal and exact-type checks; one job per
  target with duplicated source/target work rejected; the cycle per-job limit
  is validated against job timeouts and applied as the effective timeout in the
  planner, summary and supervisor; accepted-interval thresholds cannot exceed
  the 24-hour coverage window (including overrides); the database budget cannot
  exceed the worker's 400 MiB stop; config files must be regular, non-symlink,
  at most 1 MiB and decodable, with stable `automation_config_*` codes.
  Offline `build_plan`; `CycleLock` (owner-only `flock` file under the resolved
  repository `.local/automation/`, symlinked leaf/parent rejected, inode never
  unlinked); `SubprocessSupervisor` with retained process-group ID, monotonic
  job/cycle deadlines, effective timeout cap, SIGTERM-then-SIGKILL group
  cleanup, bounded group reaping and stream drain, 256 KiB output cap and
  event-specific value contracts; `CycleInterrupted` handling for external
  SIGINT/SIGTERM; read-only `database_preflight` inside the cycle deadline with
  bounded connect timeout, parameterized statement timeout and schema/version/
  size checks; exclusive evidence writes; stable exit categories.
  `src/vn_air/database/setup.py` gained a defaulted `connect_timeout` keyword
  used only by the bounded preflight; the ingestion worker behaviour is
  unchanged.
- Event evidence uses per-event schemas with reviewed statuses, source,
  product and target identities, canonical UUIDs, nonnegative integer counts
  (booleans rejected), offset-aware timestamps (calendar-date `window_start`
  retained for model polls), and a constant ingestion/supervision error-code
  registry. Unknown or malformed codes and stderr tokens become
  `unrecognized_child_error`; valid SQLSTATEs become `database_error_<state>`.
  Credential redaction remains a second defense at collection and persistence.
- `src/vn_air/cli.py`: `vn-air automation plan|run`. `plan` opens no database
  or network connection and takes an explicit reproducible `--now`. `run`
  requires `--execute` and `--output-dir` before any engine, credential or
  HTTP use and uses the real clock.
- `tests/test_automation.py`: 54 offline tests with fake clock, fake
  subprocess runner and fake database responses.
- `tests/integration/test_automation_database.py`: 6 read-only preflight/health/recovery tests
  against the disposable socket-only cluster.
- `src/vn_air/automation_environment.py` and `scripts/run_automation.py`: an
  explicit process-environment allowlist and literal mode-600 operator-file
  parser used by the launchd wrapper; the parser never evaluates shell code.

## Stage A historical commands and results

| Command | Result |
| --- | --- |
| Baseline before changes: `PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v` | `Ran 313 tests`; `OK (skipped=2)`; exit 0 |
| Focused: `PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_research_artifacts tests.test_automation -v` | `Ran 60 tests`; `OK (skipped=2)` |
| Full offline: `PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v` | `Ran 365 tests`; `OK (skipped=2)`; exit 0 |
| Isolated PostgreSQL: `PYTHONPATH=src .venv/bin/python -B scripts/test_database.py` | `Ran 55 tests`; `OK` |
| `git diff --check` | clean |
| `PYTHONPATH=src .venv/bin/python -B -m vn_air.cli automation plan --now 2026-09-12T10:30:00Z` | exit 0; `preflight.network_calls = 0`; schema/role checks reported `unperformed`; jobs ordered openaq, weather, cams |
| `PYTHONPATH=src .venv/bin/python -B -m vn_air.cli automation run` | exit 3; `automation: automation_execute_required`; no side effect |
| Phase 10 public bundle digest recomputation | `dashboard/data/dashboard.json` stored and computed `b3b43813751628cc0d3439c209484a7c588cbdc9f355eb38cbe9233b1e0a167d` |
| Phase 5–10 integrity | `tests.test_dashboard`, `tests.test_dashboard_server`, `tests.test_research_artifacts`: `Ran 60 tests`; `OK (skipped=2)`; no Phase 4–10 artifact changed |

The two skips are the documented credential checks that require an exported
`OPENAQ_API_KEY` or password-bearing `DATABASE_URL`; they were not present in
the test environment and no credential was searched for or read.

## Stage A test coverage

- Config: reviewed profile constants, missing config, duplicate keys, invalid
  JSON, invalid UTF-8, oversize and symlink config files, unknown/typed/bounded
  fields, exact literal types (`true`/`1.0` version, `0` for the false literal,
  boolean literals for string/int literals), duplicate job IDs, duplicated
  source/target work under renamed jobs, one-target-one-job, wrong window
  policy, traversal/absolute output root, schema-pinned readiness,
  400 MiB-bounded database budget, coverage-window-bounded interval
  thresholds and overrides, shell-metacharacter target rejection, unconfigured
  targets.
- Plan: determinism, offline canary (database engine factory never called),
  source order, OpenAQ 72-hour and model 3-day preview windows, unperformed
  preflight labels, effective timeout cap, missing-switch exit codes with no
  side effect.
- Cycle: source order, per-job timeout/grace values, effective timeout and
  cleanup allowance, success evidence and owner-only directory, no
  `SUCCESS.json` for failed/partial/interrupted cycles, stop on failure with
  remaining jobs `not_attempted`, continue-on-failure profile, cycle-deadline
  truncation, lock contention exclusion without output, stable preflight and
  internal failure codes, bounded preflight budget, expired-preflight and
  internal-preflight failure with no child, deterministic summary for a fixed
  clock and cycle ID, existing-output and symlink output refusal.
- Supervision: a real local sleeping child is terminated, reaped and gone
  before the lock is re-acquirable; a real parent-plus-grandchild case proves
  the retained process group is SIGKILLed and reaped after the leader exits on
  TERM; external SIGINT and SIGTERM produce a stable
  `cycle_interrupted` failed summary and alert without `SUCCESS.json`,
  terminate the child and release the lock; output bounding and allowlisted
  events; non-array argv rejection. After the Gate 2 correction, child
  `PYTHONPATH` binds only checkout `src`, with an explicit environment allowlist.
- Evidence contracts: reviewed status/product/target/source identities,
  canonical UUIDs and timestamps, date-only model `window_start`, finite
  nonnegative counts with boolean rejection, unknown/stderr codes normalized
  to a constant registry, SQLSTATE mapping, unknown fields dropped, secret
  canaries absent from summary and alert JSON, and real Phase 3 event shapes
  keeping status/count/window meaning.
- Locks: same-process contention, cross-process contention with a helper
  subprocess, owner-death release, symlinked leaf and parent rejection.
- Safety: no `dotenv`, no `shell=True` or `os.system`; the parent never
  acquires the Phase 3 database advisory lock and no read-only command invokes
  the worker.

## Stage B delivered code

- `src/vn_air/automation_health.py`: bounded read-only `health` and `recover`
  projections. Health evaluates schema revision, database budget, per-target
  latest run status and last success/partial/failure times, fetch freshness from
  retained successful receipts queried per configured source and target through
  the ingestion-run identity, OpenAQ latest-revision-before-quality coverage
  and latest accepted period age, modeled capture/retrieval age with accepted
  finite canonical values, stale `running` rows, open quality/missing-hour
  issues and optional backup evidence. Severity precedence is explicit
  (`failed > degraded > healthy`) and each finding keeps its own status
  (`succeeded`, `partial`, `failed`, `stale`, `schema_mismatch`,
  `budget_exhausted`, `backup_stale`, `unknown`). Recovery is guidance-only:
  stale rows are suspected stale (never marked failed), unknown codes are not
  retryable, completed checkpoints are retained, OpenAQ transient/cooldown
  failures may propose a bounded ≤72 h backfill after operator confirmation and
  model failures suggest a fresh poll only.
- `src/vn_air/automation_backup.py`: project-scoped custom-format `pg_dump`
  archives (`vn_air` schema plus `public.vn_air_schema_version` in separate
  archives because PostgreSQL applies `-t` over `-n`). URLs are parsed into a
  sanitized libpq environment with ambient `PG*` service/passfile/options
  routing stripped, password never in argv, unsupported query options rejected
  and Supabase TLS enforced. Strict manifest validation, fixed owner-only file
  names, exclusive temporary archive publication with no-replace final names,
  failure markers, two-level verification
  (`checksum_verified` vs `restore_verified`) and a real `RestoreDrill` that
  creates a fresh private socket-only cluster, restores both archives, verifies
  schema revision, 4/16/5/2 reference counts, all content counters, report
  views, absent unrelated schemas and representative `23514`/`23503`
  constraints, then removes only its own validated temporary cluster.
- `src/vn_air/automation.py` / `src/vn_air/cli.py`: `automation health`,
  `recover`, `backup --execute --output-dir`, `backup-verify --backup-dir
  [--restore-drill]` with optional new-file health/guidance JSON. Stage A
  `plan`/`run` behaviour is unchanged.
- `.github/workflows/ci.yml`: credential-free offline and disposable
  PostgreSQL jobs on push/pull request/manual dispatch, read-only permissions,
  pinned `actions/checkout` v4.4.0 (`11d5960a…`) and `actions/setup-python`
  v5.6.0 (`a26af69b…`) resolved with `git ls-remote` on 2026-09-12 UTC, no
  secrets, no uploads, bounded timeouts.
- `ops/launchd/com.vnair.phase11.automation.plist` and
  `ops/launchd/cycle_wrapper.example.sh`: reviewed placeholders, hourly minute
  17, no credentials, no install performed; wrapper reserves a new timestamped
  evidence directory.
- `docs/operations.md`: activation, alerts, recovery, backup/restore, pause and
  limitations runbook.
- Current tests: `tests/test_automation_health.py` (26),
  `tests/test_automation_backup.py` (30), `tests/test_automation_environment.py`
  (7), and `tests/integration/test_automation_backup_database.py` (5, including
  the real drill and target/cutoff regression).

## Stage B initial commands and results (before corrections)

| Command | Result |
| --- | --- |
| pg_dump selection round trip (disposable cluster, inspected before coding) | `-n vn_air` alone restored schema, functions, triggers, views and data; `-t public.vn_air_schema_version` alone restored the migration table and row; combining `-n vn_air -t …` dumped only the table, confirming the documented selection trap and requiring two archives |
| Local Supabase/PostgreSQL skills plus `https://supabase.com/changelog.md` re-checked 2026-09-12 | No breaking change affects project-scoped `pg_dump`: recent entries cover Supabase-managed backup scheduling/credential resync, `log_connections` defaults, and the end of Postgres 14 support (2026-07-01; this project requires 15+). Supabase-managed backups remain out of scope |
| Focused: `PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_automation tests.test_automation_backup tests.test_automation_health` | `Ran 100 tests`; `OK` |
| Full offline: `PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v` | `Ran 413 tests`; `OK (skipped=2)`; exit 0 |
| Isolated PostgreSQL: `PYTHONPATH=src .venv/bin/python -B scripts/test_database.py` | `Ran 62 tests`; `OK`; includes the real synthetic dump/restore drill returning `restore_verified` |
| `git diff --check` | clean |
| `automation plan --now 2026-09-12T10:30:00Z` | exit 0; jobs `openaq, weather, cams`; `preflight.network_calls = 0` |
| `automation backup --output-dir …` (no `--execute`) | exit 3; `automation: automation_execute_required`; no output created |
| `automation health` with no `DATABASE_URL` | exit 1; `automation: database_url_missing` |
| `automation recover` with no `DATABASE_URL` | exit 1; `automation: database_url_missing` |
| `plutil -lint`, `sh -n` wrapper, Ruby YAML parse of `ci.yml` | all syntax checks pass (local checks do not prove a hosted CI run) |
| Phase 10 public bundle and Phase 4–10 artifacts | unchanged; `git status` shows only Phase 11 Stage A/B paths |

The two skips remain the documented credential checks that require an exported
`OPENAQ_API_KEY` or password-bearing `DATABASE_URL`; they were not present and no
credential was searched for or read.

## Stage B test coverage

- Health: fully healthy all-target dataset exit 0; schema missing/mismatch;
  database budget stop and near-budget degradation; per-target success, partial,
  failed, stale-running, cooldown and missing-run states; fetch missing/stale
  separate from accepted data; OpenAQ low coverage, stale period, missing
  evidence and non-accepted latest revision; modeled stale capture, invalid-only
  snapshots and missing evidence; stale-running rows; open error and
  missing-hour issues; backup missing/invalid/stale; severity precedence and
  deterministic output; fake read-only collection with parameterized SQL; final
  health-command exit codes; optional backup directory inspection.
- Recovery: stale guidance never marks runs failed or retries; OpenAQ cooldown
  bounded ≤72 h suggestion; weather poll-only and no backfill; unknown codes not
  retryable; completed checkpoint retained with confirmation required; missing
  window blocks a suggested command; read-only statement assertions.
- Backup: libpq env mapping with password never in argv/artifacts; ambient
  `PG*`/URL stripping; socket mapping; unsupported option/template/TLS
  rejection; two separate selection archives; owner-only files; manifest and
  hashes; failure markers without a manifest; empty dumps, missing tools and
  incomplete listings rejected; strict manifest mutation rejection; tampered,
  missing, extra, symlinked and insecure files rejected; checksum-only vs
  restore-verified reporting; drill orchestration with sanitized child env,
  disposable-cluster flags, cleanup on success and failure; dispatch of all four
  new actions; no `dotenv`, `shell=True` or `os.system`.
- Correction pass: ingestion and backup child environments use explicit
  allowlists; the operator-file parser rejects unknown/duplicate/shell
  assignments; `pg_dump` receives only exclusive `.partial` paths and a final
  archive race is rejected; fetch facts and findings carry source+target IDs.
- Isolated integration: healthy synthetic dataset via the real schema, real
  `pg_dump` archive with recorded counters (5 distinct raw body hashes,
  max revision 2, 48 intervals, 1 checkpoint, 1 issue), `restore_verified`
  drill with reference counts, report views, absent `unrelated` schema and
  constraint probes, degrade/recovery after synthetic failures, and CLI exit
  codes without live services.

## Gate 2 correction closeout

Codex took over implementation after the OpenCode correction task reported
`failed`. No new OpenCode run was started. The original review findings and
their remediation requirements remain in [the correction plan](phase_11_stage_b_corrections.md).

- Environment inheritance: a shared explicit allowlist protects ingestion,
  backup and restore children. Only ingestion receives the two required
  application credentials. The launch helper parses a bounded external,
  current-user-owned mode-600 file as literal assignments, rejects shell syntax,
  unknown/duplicate keys and symlinks, and execs without credential arguments.
  Tests inspect the actual exec environment and a real harmless child process.
- Archive publication: `pg_dump` writes an exclusively created private
  `.partial` file. The parent retains its descriptor, checks its inode and
  regular-file type, syncs it, and publishes with a no-replace hard link.
  Existing files/symlinks and racing destination creation do not get overwritten;
  failure/timeout paths remove the temporary name and produce no valid manifest.
- Fetch freshness: bounded read-only queries join receipts to ingestion-run
  source/target identity and apply the requested upper cutoff. OpenAQ matches
  by sensor even when the run also records its station location. Each target
  has its own fetch facts/findings and configured threshold. Tests cover missing
  and stale OpenAQ/weather/CAMS targets, overrides, and actual SQL selection in
  the disposable database. No measurement or forecast data was relabelled.

Final evidence for the corrected working tree:

| Check | Observed result |
| --- | --- |
| `PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_automation tests.test_automation_backup tests.test_automation_health tests.test_automation_environment` | 117 tests, OK |
| `PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests` | 430 run, 428 passed, 2 documented credential skips; exit 0 |
| `PYTHONPATH=src .venv/bin/python -B scripts/test_database.py` | 63 tests, OK; includes real synthetic dump/restore and per-target receipt/cutoff regression |
| `plutil -lint`, `sh -n`, Ruby YAML parse | Pass; syntax verification only, not installed launchd or a hosted CI run |
| Frozen Phase 4–10 paths and dashboard digest | No tracked frozen-path changes; stored and recomputed dashboard canonical digest agree |
| `git diff --check` and repository documentation checks | Clean |

The first sandboxed PostgreSQL attempts failed before tests: `initdb` could not
create shared memory (`shmget: Operation not permitted`). The approved isolated
run outside the sandbox passed. This was not a collision with the offline suite.
Early focused failures reflected old source-aggregate fixtures and a final-path
error assertion; later checks added missing target/launcher regressions and
closed an unclosed test pipe. No failure was converted into a test skip.

Coordinator review closes the three scoped findings using the evidence above.
The earlier reviewer session could not be resumed in this runtime; no new
independent reviewer approval is claimed. Nothing was committed or pushed.

## Limitations

- No schedule, launchd/cron/systemd unit or alert destination is installed. The
  templates are reviewed starting points only; `docs/operations.md` requires an
  operator grants/RLS review before the first live cycle.
- No least-privilege ingestion role exists. The current worker uses the
  operator credential with reference seeding and owner/bypass-RLS behaviour; a
  separate grants/RLS activation review is still required.
- No live cycle, Supabase check, migration, role change, real project backup or
  live restore was performed. The drill ran only against synthetic isolated-
  cluster data.
- Backup verification detects corruption and inconsistency; archives are trusted
  operator inputs and restoring SQL is not a security sandbox.
- Health and recovery read bounded 7-day windows and may report `unknown` when
  evidence is missing or inaccessible; a non-zero exit is the alert signal.
- The frozen Phase 5–10 artifacts remain limited diagnostics. A prospective
  captured collection period is still required before captured-feature ML
  evaluation, and no forecast-skill, causal, city-wide or production-readiness
  claim is made.
- The hosted CI workflow has not been observed running; only local YAML syntax
  and exact pin lookups are evidenced.
- Codex completed the correction pass locally after OpenCode reported failure;
  no OpenCode completion message is evidence for these fixes.
