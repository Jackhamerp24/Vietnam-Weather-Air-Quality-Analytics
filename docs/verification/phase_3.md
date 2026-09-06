# Phase 3 Verification

Date: 2026-09-07 Vietnam time. Scope: bounded on-demand ingestion, real PostgreSQL
persistence, provenance, basic quality checks, revisions and resumable backfill.
**No scheduler, EDA, statistical findings, trained models or dashboard are claimed.**

## Evidence

The installed package is version 0.3.0. Supabase PostgreSQL 17.6 and local
PostgreSQL 15.17 have migration head `0003_response_integrity`. Tests use synthetic
edge cases in a disposable local PostgreSQL cluster; study data come only from
real provider requests.

| Verification | Result |
| --- | --- |
| Offline configuration/parser/HTTP/evidence suite | 53 tests passed with no credential-check skips |
| Isolated PostgreSQL schema/ingestion suite | 45 tests passed |
| Live local OpenAQ, ERA5, CAMS one-day windows | Real responses parsed and persisted |
| Live Supabase OpenAQ one-day repeat | Zero inserts, 48 unchanged measured intervals |
| Live Supabase ERA5 one-day repeat | Zero inserts, 432 unchanged modeled values |
| OpenAQ 90-day resume | 26 checkpoints skipped, zero HTTP requests and zero inserts |
| Actual current poll | OpenAQ overlap plus separate weather/CAMS forecast captures |
| Historical load | 90 days measured/CAMS, 85 days ERA5 available at retrieval |
| Safety | Raw/normalized separation, bounds, duplicate/revision checks, secret withholding and RLS tests |

The new tests cover HTTP retries/timeout/401/429, Unicode-escaped credential echoes,
size limits, metadata drift, unit aliases, timezone consistency, interval ends,
missing/invalid/suspect values, failed refresh checkpoint invalidation, lost-session
locking, orphan recovery, transaction rollback and whole-chunk replay. Simulated
revision changes were tested locally; no provider measurement was falsified to
demonstrate a live correction.

## Historical Data

OpenAQ window: **2026-06-08 00:00 through 2026-09-06 00:00 UTC**, with hourly means
fully contained in that interval. Latest-revision counts queried directly from
Supabase match the Phase 1 audit:

| Sensor | Expected Hours | Stored Hours | Missing Hours |
| --- | ---: | ---: | ---: |
| CMT8, HCMC | 2,160 | 2,154 | 6 |
| OceanPark, Hanoi area | 2,160 | 2,037 | 123 |

All 4,191 stored hours pass the basic accepted-value checks. This is structural
quality evidence, not calibration certification. OceanPark's 119-hour outage
remains a gap. No imputation or city-wide aggregation occurred.

ERA5 at the two station coordinates: **2026-06-08 through 2026-09-01 UTC**, 85 days
and 36,720 values (nine weather variables). Five-day publication lag prevents a
matching 90-day reanalysis window at retrieval. Earlier one-day smoke snapshots
also remain, so the stored ERA5 total is 37,152 values across overlapping captures.

CAMS at three city-centre points: **2026-06-08 through 2026-09-06 UTC**, 90 days
and 45,360 values (six pollutants and derived US AQI). These are modeled context,
not measured targets. Da Nang has no measured sensor configured.

Current captures add 1,296 weather model values for the two station points and
1,512 CAMS values for the three city points across 2026-09-06 to 2026-09-09 UTC.
The 72-hour OpenAQ poll supplied 71 of 72 expected intervals per sensor, with latest
period end 2026-09-06 19:00 UTC. Reporting lag is flagged, not filled with zero.

## Stored Totals

The [machine-generated report](phase_3_counts.json), captured at
2026-09-06T20:59:00 UTC, records:

| Entity | Total |
| --- | ---: |
| Distinct measured sensor-hours, including current poll | 4,229 |
| Measured revision rows | 4,253 |
| Modeled values, including overlapping captures | 85,320 |
| Model snapshots | 72 |
| Source responses | 122 |
| Raw response bytes | 4,058,795 |
| Completed backfill checkpoints | 95 |
| Successful ingestion runs | 107 |
| Failed runs retained | 1 |
| Project predictions | 0 |
| Total database bytes | 45,067,411 |

The extra 24 CMT8 revision rows reflect addition of preserved timezone metadata
between initial smoke runs, **not 24 pollution corrections**. Model-value totals
include an overlapping ERA5 smoke window; analyses must select an eligible capture
per valid time. All statistics above are collection evidence, not EDA findings.

The database is about 45.1 MB / 43.0 MiB. Current
[Supabase pricing](https://supabase.com/pricing) lists 500 MB free database size,
5 GB egress, no automatic backups, and pausing after one week of inactivity.
No paid resource, branch, upgrade or account was created. The worker checks a
400 MiB soft threshold before requests, but continuous raw/snapshot accumulation
will still require measured retention planning and backups.

## Live Anomalies

OceanPark metadata supplied the specific instrument name
`AirGradient Open Air Generation 1 (O-1PST)` and timezone `Asia/Bangkok`, rather than
the initial unknown instrument/Ho Chi Minh timezone metadata. The first local
run stopped at the instrument change. A subsequent Supabase run stopped on the
timezone change, preserving a failed run/quarantine record. After review, the
parser allowed only that unknown-to-known enrichment and offset-equivalent
timezone alias. Coordinates, provider and non-reference status remained checked.

Calibration, exact siting and correction history still need qualification.
Successful retried collection did not erase the earlier failure evidence.

## Security

The pre-ingestion advisor found an exposed public version table without RLS and
an unset function search path. Direct permission checks showed `vn_air` itself
was not browser-accessible, despite a broader generic advisory message.
Migration 0002 enabled defense-in-depth RLS, revoked anon/authenticated access,
set fixed function search paths and marked views security-invoker. No public
read/write policies were added; owner access remains available for this backend.

Migration 0003 was added **after backfill**, following final null-semantics review,
to prevent withheld-success bodies from supporting canonical rows. No affected
rows existed in Supabase before the migration. Original migrations were not
rewritten after application.

The advisor then reported only informational
[RLS enabled without policies](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy)
notices. That deny-by-default state is intentional. Relevant remediation references:
[public-table RLS](https://supabase.com/docs/guides/database/database-linter?lint=0013_rls_disabled_in_public)
and [fixed function search paths](https://supabase.com/docs/guides/database/database-linter?lint=0011_function_search_path_mutable).

The performance advisor reports informational
[unindexed foreign keys](https://supabase.com/docs/guides/database/database-linter?lint=0001_unindexed_foreign_keys)
and [unused indexes](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index).
These are recorded for query-plan review, not blindly fixed by adding every
composite index or removing unexercised analytical indexes on a newly loaded
database. Several references concern small immutable metadata/append-only rows;
bulk analytical query performance and deletion workloads have not been evaluated.
No security warning/error remained in the post-migration advisor run.

The Supabase migration list is empty because this repository uses Alembic's
`public.vn_air_schema_version`, not `supabase_migrations`. Both local and remote
Alembic heads were checked explicitly; no second migration history was created.

The current worker still connects using the operator credential. Least-privilege
runtime role provisioning and unattended scheduling remain required before a
production deployment. `sslmode=require` encrypts PostgreSQL transport; it does
not itself establish full hostname/CA verification. The HTTP clients verify CA
certificates. Do not claim the database transport uses `verify-full` yet.

## Reproduction And Limits

Commands, windows, exit codes, retry/rate budgets and resume semantics are in
[the ingestion runbook](../ingestion.md). `vn-air report` reads aggregate evidence;
it does not download all raw data. Exact provider bytes remain in PostgreSQL.

No random splitting, feature engineering or model training took place. Backfilled
values retain their real present-day retrieval timestamp; historical availability
was not invented. One-hour polling commands exist, but no recurring process was
installed. Daily/weekly reconciliation and alerting are operational designs for
Phase 11, not active jobs.

The independent reviewer agent returned `Unknown agent type`; this phase used
direct review and reproducible tests, not an independent expert approval.
The next phase is a full data-quality audit of the acquired dataset before EDA.
