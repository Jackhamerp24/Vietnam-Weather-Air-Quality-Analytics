# Operations runbook: bounded ingestion automation (Phase 11)

Version: `phase11_automation_v1`. Status: Stage B tooling delivered and locally
verified. No scheduler is installed, no least-privilege ingestion role exists,
no live Supabase check or real project backup has been performed, and a
prospective captured collection period is still required before captured-
feature ML evaluation. This runbook is an activation contract, not an
operational-readiness, forecast-skill or production claim.

Phase 11 wraps the existing bounded Phase 3 worker (`vn-air ingest poll`) with a
strict non-secret profile (`configs/automation.json`), a supervised cycle, a
read-only health projection, read-only recovery guidance, project-scoped
PostgreSQL logical backups and a disposable-cluster restore drill. It adds no
database migration, no public API, no browser credential and no paid service.

## 1. Commands and exit codes

The installed `.venv/bin/vn-air` entry point can lag source code. Until the
package is reinstalled, run source-mode commands from the repository root:

```bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli automation <action> ...
```

| Command | Purpose | Exit codes |
| --- | --- | --- |
| `automation plan [--now ISO]` | Offline, deterministic, side-effect-free cycle preview | `0` planned, `3` invalid configuration |
| `automation run --execute --output-dir NEW` | Supervised bounded poll cycle | `0` succeeded, `2` partial, `1` failed, `3` invalid request, `4` concurrent cycle excluded |
| `automation health [--output NEW] [--backup-dir DIR]` | Read-only health snapshot | `0` healthy, `2` degraded (partial/stale/low coverage/missing backup), `1` failed/unknown/schema/budget, `3` invalid configuration |
| `automation recover [--output NEW]` | Read-only recovery guidance | `0` inspection completed, `1` database unavailable, `3` invalid configuration |
| `automation backup --execute --output-dir NEW` | Project-scoped logical backup | `0` created, `1` dump/verification failure, `3` invalid request |
| `automation backup-verify --backup-dir DIR [--restore-drill]` | Checksum/listing verification; optional disposable restore | `0` verified, `1` verification failed, `3` invalid request |

Health severity precedence is explicit (`failed > degraded > healthy`), never
`max(exit_code)`. `run` derives the executed poll window from the child worker's
own clock; the parent window preview is labelled planned.

## 2. Activation profile

`configs/automation.json` is strict versioned JSON (duplicate keys, unknown
fields and exact types rejected; booleans are not integer budgets). The reviewed
profile runs OpenAQ for both sensors (10 requests), then Open-Meteo weather for
the two stations (5), then CAMS for the three cities (5), stopping on the first
failed/partial job and recording the remainder as not attempted. Per-job timeout
is 900 s, the whole cycle 2,700 s including preflight and cleanup, terminate
grace 5 s. ERA5 and historical backfills stay operator-only and are not part of
the unattended profile.

Readiness defaults are operating choices, not health guidance: schema
`0003_response_integrity`, database stop 400 MiB (matching the worker stop),
fetch success age 3 h, OpenAQ latest accepted period age 6 h with at least 18 of
24 accepted complete UTC intervals per sensor, modeled capture age 6 h,
stale-running age 1,800 s and backup stale age 36 h. Overrides are allowed only
for reviewed targets with bounded positive values.

## 3. Health and alerting

```bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli automation health \
  --backup-dir /path/to/operator/backups
```

The command prints machine-readable JSON to stdout, a constant summary to
stderr and can write a new JSON snapshot with `--output NEW`. It evaluates each
configured source and target separately:

- schema revision and database-size budget status;
- latest run status per target plus last success/partial/failure timestamps and
  provider cooldown/budget indicators;
- fetch freshness from retained successful HTTP receipts per configured source
  and target, separate from accepted-data freshness; the upper health cutoff
  excludes receipts retrieved later;
- OpenAQ latest-revision-before-quality coverage and latest accepted period age;
- modeled snapshot capture/retrieval age and accepted finite canonical values
  (invalid/null-only payloads are not healthy);
- stale `running` rows (suspected stale, not proven orphaned), open quality and
  missing-hour issue counts;
- backup manifest presence, size and age when `--backup-dir` is supplied
  (checksums are only claimed by `backup-verify`).

Missing evidence is never healthy. One healthy sensor cannot hide a failed
second sensor. The run exit code is suitable for cron/launchd alerts: nonzero
means inspect. To connect an approved mail or monitoring channel later, have the
operator consume the stderr summary, the exit code or the `--output` JSON from
outside this repository; do not add provider credentials to this repository.

## 4. Recovery guidance

```bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli automation recover --output NEW
```

`recover` is read-only guidance. It lists stale `running` rows and recent
failed/partial runs with source, target, window, normalized error code,
retryability and last attempt. Rules it enforces by construction:

- no run, response, observation, checkpoint or raw body is modified or deleted;
- stale rows are suspected stale, never marked failed from inspection; the
  Phase 3 worker keeps lock-proven stale-run finalization;
- completed checkpoints with missing hours are retained; coverage gaps are
  never silently reconciled;
- unknown error codes are not auto-retryable;
- OpenAQ transient/cooldown failures may get a suggested bounded `vn-air ingest
  backfill` command capped to 72 complete UTC hours, and only after operator
  confirmation with an explicitly recorded window;
- weather and CAMS failures suggest a fresh poll only; historical model backfill
  is unsupported.

Run any suggested retry only while no supervised cycle holds the checkout lock;
`run` reports `already_running` on contention.

## 5. Backup and restore verification

Backups are PostgreSQL-native custom-format project logical dumps of schema
`vn_air` and `public.vn_air_schema_version`. They exclude Supabase-managed
schemas, unrelated schemas and cluster roles, and retain raw response bodies as
append-only evidence. No Python export bypasses PostgreSQL constraints. No
automatic deletion is implemented.

```bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli automation backup \
  --execute --output-dir /path/to/private/backups/2026-09-12T11Z

PYTHONPATH=src .venv/bin/python -B -m vn_air.cli automation backup-verify \
  --backup-dir /path/to/private/backups/2026-09-12T11Z --restore-drill
```

Rules and outputs:

- the output directory must be new; symlinks, existing paths, broad paths and
  ambient output overwrites are refused;
- the connection comes only from the operator's `DATABASE_URL`; the URL,
  password, host and database name never enter argv, logs or the manifest. The
  tool receives a sanitized libpq environment with ambient `PGHOST`,
  `PGSERVICE`, `PGPASSFILE`, `PGOPTIONS` and password routing stripped, and TLS
  is never weakened (Supabase hosts require `require`/`verify-ca`/`verify-full`);
- fixed owner-only files are created: `vn_air_schema.dump`,
  `vn_air_migration.dump` and `phase_11_backup_manifest.json` (tool/server
  version, schema revision, UTC time, byte sizes, SHA-256, read-only content
  counters, restore order). A failed dump leaves `phase_11_backup_failed.json`
  and never a manifest;
- `pg_dump` writes exclusive private `.partial` files, never the fixed final
  filenames. After regular-file/inode validation, the parent publishes a
  no-replace hard link. Pre-existing files/symlinks and late races cause a
  failure without overwriting them; failed/timeout temporary names are removed;
- `backup-verify` checks exact regular-file membership, owner-only permissions,
  strict manifest fields, sizes, SHA-256, archive format and a bounded
  `pg_restore --list`. It reports `checksum_verified`, not `restore_verified`;
- `--restore-drill` additionally restores both archives into a new private
  socket-only cluster (`initdb --auth-local=trust --auth-host=reject`,
  `listen_addresses=''`, fixed synthetic role/database), then verifies schema
  revision, the 4/16/5/2 reference counts, all recorded content counters,
  read-only report views, absent unrelated schemas, and representative
  append-only (SQLSTATE `23514`) and foreign-key (`23503`) constraints. It never
  repairs the restored database with migrations or reseeding, never targets the
  project database, and removes only its own validated temporary cluster. Treat
  archives as trusted operator inputs: restoring SQL is not a security sandbox
  for hostile dumps.

Recommended operator policy: daily backups, 36-hour stale threshold, encrypted
copy off-site, monthly restore drills. Install none of this automatically;
deletion and retention require separate authorization and a recovery policy.

## 6. Scheduling templates (not installed)

`ops/launchd/com.vnair.phase11.automation.plist` is a reviewed template that
runs `ops/launchd/cycle_wrapper.example.sh` hourly at minute 17. It is not
installed, loaded or enabled, and contains no credential values. Placeholders
must be replaced and the activation checklist below must pass first.

launchd does not inherit an interactive shell. Provide credentials through the
owner-only regular environment file referenced by `VN_AIR_ENV_FILE`, stored
outside the repository with mode `600`. The file may contain only the exact
assignment names `DATABASE_URL` and `OPENAQ_API_KEY`, plus blank/comment lines.
The wrapper rejects symlinks, files owned by another user, non-600 permissions,
duplicate keys, unknown names and unsafe lines. Use unquoted `KEY=value` lines;
shell `export`, expansion, escapes, whitespace and inline comments are not
supported. Percent-encode URL characters that need escaping; `.env` and files
inside the checkout are rejected. `scripts/run_automation.py` parses assignments
without shell evaluation, then uses an explicit child allowlist. Ingestion
children receive only the required database/API values and safe runtime basics;
unrelated secrets, `PG*` routing, startup hooks and dynamic-loader variables do
not cross the boundary. Never put `DATABASE_URL` or API keys in the plist or in
git. The wrapper reserves a new UTC-timestamped evidence directory per
invocation and fails if that directory already exists.

Safe runtime variables are `PATH`, `HOME`, `LANG`, `LC_ALL`, `TZ`, `TMPDIR`,
`TMP`, and `TEMP`. Ingestion additionally accepts explicit `SSL_CERT_FILE` and
`SSL_CERT_DIR` trust-store paths and binds `PYTHONPATH` to this checkout's `src`.
Native backup/restore tools receive no application API keys or inherited `PG*`
variables; the backup command supplies only its validated libpq connection
settings. Do not use the operator credential file as general shell configuration.

Local limitations: a laptop sleeps, loses network and changes IP; launchd will
miss intervals. This is not continuous collection, exactly-once delivery or
multi-host coordination. Pause with
`launchctl bootout gui/"$(id -u)"/com.vnair.phase11.automation` and remove the
plist to uninstall. Standard output/error logs and per-cycle summaries live
under `.local/automation/`; treat them as local evidence, rotate deliberately
and never copy credentials or raw responses into tickets. A cron example with
the same wrapper:

```cron
17 * * * * /bin/sh /path/to/checkout/ops/launchd/cycle_wrapper.example.sh >> /path/to/checkout/.local/automation/cron.log 2>&1
```

Schedule backups separately from the ingestion cycle.

## 7. Continuous integration

`.github/workflows/ci.yml` runs credential-free offline tests and the
disposable socket-only PostgreSQL suite on push, pull request and manual
dispatch only. It uses read-only repository permissions, no secrets, no
`pull_request_target`, no scheduled ingestion and no artifact uploads, with
bounded jobs and source-mode Python commands. Actions are pinned to verified
upstream commits. Local YAML checks do not prove a hosted run; do not claim a
GitHub run until one has actually happened.

## 8. Activation checklist

1. Create a dedicated least-privilege ingestion role and a reviewed grants/RLS
   design (separate authorization required; choosing a role does not by itself
   make the owner/bypass-RLS worker least-privileged).
2. Provide an explicit secret store/environment with owner-only permissions;
   confirm no secrets or `.env` values are printed, logged or committed.
3. Choose the working directory, evidence root, log destination and alert
   channel (local stderr/JSON first).
4. Confirm provider quotas and the per-job request budget against current
   OpenAQ/Open-Meteo limits.
5. Run `automation plan` and confirm ordered jobs, windows and zero network
   calls.
6. Run `automation run` against the isolated PostgreSQL test cluster, then check
   the summary, alerts and `SUCCESS.json` semantics.
7. Run a live read-only `automation health` with `--backup-dir`; confirm exit
   codes and expected findings.
8. Run `automation recover` and verify the guidance matches persisted state.
9. Create a backup, run `automation backup-verify --restore-drill` and confirm
   `restore_verified: true`.
10. Perform a manual stop test: terminate a running cycle, confirm the child is
    reaped, the lock is released and the failed summary carries
    `cycle_interrupted` without `SUCCESS.json`.
11. Install the schedule only after 1–10 pass, using the reviewed template, and
    record the first authorized live cycle separately.

Completing this checklist does not establish forecast skill, causal validity,
city-wide coverage, exactly-once delivery or production readiness.

## 9. Limitations

- The frozen Phase 5–9 artifacts remain limited diagnostics; the health command
  describes ingestion facts only.
- The dashboard stays static and database-free; Phase 11 adds no live refresh.
- No real project backup, live Supabase check, migration, role provisioning or
  installed schedule was performed during implementation.
- Backup archives are trusted operator inputs; verification detects corruption
  and inconsistency, not malicious SQL.
- The restore drill requires PostgreSQL 15+ native binaries on `PATH`
  (`initdb`, `pg_ctl`, `createdb`, `pg_dump`, `pg_restore`) and a temporary path
  short enough for Unix sockets.
