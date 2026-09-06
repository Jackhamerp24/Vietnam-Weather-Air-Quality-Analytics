# Ingestion Runbook

Phase 3 provides on-demand ingestion jobs with persistent evidence, revisions and
bounded recovery. **No background schedule is installed.** The same commands can
later run under a scheduler after operational review.

## Setup

Use the existing [database setup](database.md) and [Supabase connection](supabase.md).
Update dependencies/package and apply forward migrations before collection:

```bash
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps .
set -a
source .env
set +a
.venv/bin/vn-air db upgrade
.venv/bin/vn-air db status
```

Only source your own trusted `.env`; do not use shell tracing or print its values.
The CLI reads exported `DATABASE_URL` and `OPENAQ_API_KEY`, not `.env` itself.
The Supabase publishable/secret API keys are not needed by the ingestion worker.
For source development, use `PYTHONPATH=src .venv/bin/python -B -m vn_air.cli` in
place of `.venv/bin/vn-air`. A regular installed package needs reinstalling after
source changes. Current migration head is `0003_response_integrity`.

To target the local development database instead of Supabase, set
`DATABASE_URL=postgresql+psycopg:///vietnam_environment` for that command.

## Poll

```bash
.venv/bin/vn-air ingest poll --source openaq --max-requests 10
.venv/bin/vn-air ingest poll --source weather --max-requests 5
.venv/bin/vn-air ingest poll --source cams --max-requests 5
.venv/bin/vn-air report
```

| Source | Targets | Window / Meaning |
| --- | --- | --- |
| `openaq` | Configured CMT8 and OceanPark sensors | Last 72 complete UTC hours; late/missing reports remain visible |
| `weather` | Actual station coordinates | Three UTC calendar days from today, pinned `ecmwf_ifs`; model output, not measured weather |
| `cams` | Hanoi, HCMC, Da Nang city points | Three UTC calendar days from today; modeled AQ, not station truth |

Use `--target openaq_11357424` or `--target openaq_14581375` for an OpenAQ sensor;
use `--target cmt8`, `--target oceanpark` for weather/ERA5, or `--target da_nang`
for CAMS. Targets must exist in reviewed configuration. `--config` defaults to
`configs/study.json` and may point to another validated reviewed configuration.

Future times in weather/CAMS output are provider forecasts. Current conditions
come from the same hourly model sequence; the ingestion job does not separately
insert 15-minute weather estimates into measured hourly tables.

## Backfill

These reproduce the verified Phase 3 windows:

```bash
.venv/bin/vn-air ingest backfill --source openaq --start 2026-06-08T00:00:00Z --end 2026-09-06T00:00:00Z --resume --max-requests 80
.venv/bin/vn-air ingest backfill --source era5 --start 2026-06-08T00:00:00Z --end 2026-09-01T00:00:00Z --resume --max-requests 50
.venv/bin/vn-air ingest backfill --source cams --start 2026-06-08T00:00:00Z --end 2026-09-06T00:00:00Z --resume --max-requests 60
```

The worker splits windows into at most seven days per target. OpenAQ uses fully
contained measurement intervals `[start,end)`, so the hour **ending** at `end`
is included. Models use `start <= valid_at < end`; model backfills require UTC
midnights. Precipitation/radiation at `valid_at` cover the preceding hour. This
boundary distinction must be handled explicitly by later analytical joins.

Dates above are fixed evidence windows, not rolling current-date defaults. ERA5
rejects a requested end later than UTC today minus five days. The original
90-day measured window therefore had only 85 days of currently available ERA5.
Do not fill its latest gap with forecasts and label them reanalysis. `weather`
supports polling only; use ERA5 for retrospective weather history.

`--resume` skips completed exact target/window/configuration/pipeline checkpoints.
It is a recovery feature, **not reconciliation**: a successful response with
missing hours is still a completed fetch. To revisit late data in completed
windows, run without `--resume`. A failed/partial explicit refresh invalidates
the older completion marker so a subsequent resume retries it. Changing the
window boundaries can create different checkpoints, but measured revisions
remain keyed by sensor and actual interval.

Reprocessing an unchanged measured interval leaves the old row's availability
untouched and increments unchanged count. Changed normalized value, quality or
metadata creates the next revision. A missing/invalid revision supersedes older
values without deleting them. Duplicate conflicting intervals become invalid
markers instead of arbitrarily choosing the first/last value.

For model data, an exact query window with identical normalized content reuses
the previous snapshot. A changed value or grid creates a new snapshot. Overlapping
but different query windows can retain duplicate valid times in separate captures;
analyses must explicitly choose a vintage. Deduplication does not turn stitched
model output into known as-issued runs.

## Limits And Failures

- Global session advisory lock: only one worker uses this database at a time.
  Supabase Session Pooler port 5432 or direct PostgreSQL is required. Transaction
  pooling is not supported for this session lock.
- HTTPX: 10-second connect, 45-second read timeout, no redirects, at most four
  attempts (three retries), exponential backoff/jitter, `Retry-After`/OpenAQ reset.
  A wait above 300 seconds stops the job; its provider cooldown persists across
  invocations rather than retrying early.
- Maximum decoded body: 2 MiB. Streaming checks enforce a 120-second response
  deadline between chunks; an in-progress read can additionally consume its read
  timeout. Oversize/deadline/credential-echo bytes are withheld with an error code.
- Every actual attempt is recorded before retry. Raw bodies, when safe and within
  limits, remain byte-for-byte response evidence with a database-computed SHA-256.
- Minimum spacing: 3.7 seconds after OpenAQ response receipt, 1.1 seconds after
  Open-Meteo. Project rolling caps: OpenAQ 1,000/hour; Open-Meteo 2,000/hour,
  3,000/day, 80,000/31 days. Requests are single-location, seven-day maximum,
  at most nine variables; these conservative caps leave headroom under weighted
  provider quotas. They do not track use of the same key from other databases or
  third-party clients; avoid concurrent external bulk downloads.
- Default 250 requests per command; CLI permits 1-500. Metadata and retries count.
- Database soft limit: 400 MiB checked before requests. It is a safety buffer, not
  an exact guarantee against concurrent outside writers or internal storage growth.
- 400/401/403 stop; 429/5xx/network errors retry within budgets. Malformed data is
  quarantined. Valid rows plus rejected rows make a partial run; missing model
  fields/hours also make a partial run, with no completed checkpoint.
- Missing measured hours create sensor-window issues, not fake null observations.
  `succeeded` means collection succeeded, not 100% environmental-data coverage.
- Raw response commits precede the canonical chunk. Chunk failures roll back
  normalized data, retain raw evidence, and retry the **whole failed chunk** on
  restart; already completed target/chunks can be skipped. Page-level resume is
  not implemented. Pagination itself is capped at ten pages per chunk.
- Losing the database session stops the worker; it cannot reconnect and continue
  without its lost lock. The next worker recovers interrupted runs after obtaining
  the exclusive lock. Full database unavailability can prevent finalizing a run;
  the process emits a constant failure code and stops rather than claiming success.

Exit codes: `0` for successful/skipped chunks, `2` for completed commands containing
partial chunks, `1` for stopped commands/errors. JSON logs contain safe identifiers,
counts and error codes, never request authentication headers or exception dumps.

## Metadata And Quality

OpenAQ location and licence metadata are fetched once per command, validated for
each chunk and preserved in raw evidence. Invalid station identity, movement over
100 m, licence coverage, provider, or reference-monitor status pauses ingestion.
One reviewed enrichment is permitted: `Unknown AirGradient Sensor` may become
`AirGradient Open Air Generation 1 (O-1PST)`, as observed for OceanPark. Later
changes to a known instrument are blocked. Calibration is still unverified.

`Asia/Bangkok` and `Asia/Ho_Chi_Minh` are accepted only when their offsets agree
throughout the requested window, with original timezone retained. Historical
differences are not erased. UTC/local timestamp pairs must represent the same
instant.

Basic quality treatment retains plausible extremes above 500 ug/m3 as `suspect`
for investigation, never automatic deletion. An hour with unknown flags, unknown
coverage or less than 75% provider completeness is suspect. These are provisional
screening thresholds, not calibrated sensor-error detection or health thresholds.
Full quality audits and analysis remain Phase 4 onward.

## Reports And Security

`vn-air report` performs read-only aggregate queries. To create a new evidence file:

```bash
.venv/bin/vn-air report --output docs/verification/new_ingestion_report.json
```

It refuses to overwrite a file and does not emit raw responses/credentials.
The report contains counts of **values**, **hours**, **revisions** and **snapshots**
separately; do not sum these as independent environmental observations.

The private schema and public version table now have RLS enabled with no browser
policies and explicit revoked anon/authenticated grants. Views are security-invoker.
The current worker uses the operator's database credential. Before unattended
deployment, provision a dedicated ingestion role with explicit grants/RLS policies,
backup/restore procedures and failure alerting. Do not expose raw-response tables
to a future dashboard.
