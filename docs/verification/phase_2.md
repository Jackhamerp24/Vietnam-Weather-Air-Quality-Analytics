# Phase 2 Verification

Date: 2026-09-07. Scope: architecture, schema, migrations, source contracts,
reviewed configuration and database setup. No live ingestion, statistical study,
model training or dashboard was implemented or represented as complete.

## Environment

Python 3.13.7, macOS arm64, PostgreSQL 15.17 (Homebrew). Runtime dependency versions
are in [`requirements.lock`](../../requirements.lock). Installation stayed inside
the local `.venv`. PostgreSQL server binaries were available; Docker and uv were
not required or installed.

The existing PostgreSQL service accepted a connection as the current OS role. The
initial check queried only connection/version information and whether the chosen
project database name existed. No unrelated database/schema/data were modified.

## Evidence

| Claim | Verification | Result |
| --- | --- | --- |
| Reviewed configuration is runnable | Installed `vn-air validate-config configs/study.json` | 5 locations, 2 sensors, 4 products |
| Runtime dependencies resolve | `.venv/bin/python -m pip check` | No broken requirements |
| Schema works on real PostgreSQL | Disposable socket-only cluster, synthetic integration fixtures | 25 tests passed |
| Reference metadata is idempotent | Initial seed then repeated seed | Initial 4/16/5/2 rows, second seed zero inserts |
| Migration is transactional/reversible | Upgrade, repeated upgrade, downgrade, re-upgrade and reseed in isolated tests | Passed; explicit owned-object drops, no CASCADE |
| Migration failure does not partially alter the schema | Deliberate schema conflict inside a rollback boundary | Version and existing seeded state preserved |
| Measured/model data cannot be substituted | Composite product/domain/unit/sensor FK tests | Incorrect provenance rejected |
| Revised and missing values preserve history | Duplicate/revision-chain/chronology/invalid-marker tests | Old revisions retained; later invalid/missing wins in latest view |
| Forecast vintages coexist | Two snapshots with identical variable/valid time | Both retained; duplicate within same snapshot rejected |
| As-of behavior is possible | Exclude a later retrieved/recorded revision before latest selection | Earlier value selected at historical cutoff |
| Structural DQ bounds work | Bad units, NaN/infinities, negative PM, humidity, periods and coordinates | Rejected; plausible high PM retained as suspect |
| Quarantine preserves evidence | Raw bytes, generated SHA-256 and linked quarantine locator | Hash matches, record retained |
| Prediction metadata distinguishes backtests | Training/horizon/availability/uncertainty tests | Assumed historical availability cannot be operational |
| Existing research and new config remain valid | Offline unit/artifact suite with authorized key exported | 27 tests passed, no skipped exact-key exclusion |
| Package includes schema resources | Build/install normal wheel, then run migration from installed CLI | Successful on dedicated local database |

The integration runner used:

```bash
PYTHONPATH=src .venv/bin/python -B scripts/test_database.py --temp-parent /var/folders/wf/z4hrd0fd667599w3yq_gbvpr0000gn/T/opencode
```

The temporary parent is specific to this machine. Other machines can use the
default temp directory or an existing short private path. The runner starts its
own PostgreSQL with TCP disabled, executes tests, stops it and removes only its
own temporary directory. Synthetic fixtures never enter the project database.

## Persistent Setup

Created the new dedicated local database `vietnam_environment`, applied
`0001_environmental_core`, and seeded reviewed metadata using the installed CLI.
Repeated seed inserted zero records. A direct SQL count confirmed:

| Entity | Rows |
| --- | ---: |
| Source products | 4 |
| Variables | 16 |
| Locations | 5 |
| Sensors | 2 |
| Ingestion runs | 0 |
| Measured AQ observations | 0 |
| Model snapshots | 0 |
| Modeled values | 0 |
| Model runs | 0 |
| Model predictions | 0 |

This is a working historical-storage foundation, **not accumulated production
history**. Phase 1 JSON captures remain separate evidence. No API calls or
credential use against providers occurred in Phase 2.

## Issues Resolved

- A raw SQL migration containing `%` reached psycopg with an empty parameter
  mapping. Setting SQLAlchemy's `no_parameters` execution option preserves literal
  SQL and allowed the full transactional migration to execute.
- The local filesystem marked an editable-install `.pth` file hidden, so Python
  3.13 skipped it. A normal wheel install works; source-development commands use
  `PYTHONPATH=src`. No global Python configuration was changed.
- Initial schema review identified the need for explicit null invalid revisions
  and an assumed-availability mode for retrospective experiments. Both are
  implemented and covered by PostgreSQL tests before the persistent migration.

## Limits And Gate

The previous runtime offered no working research/review agents. This phase used
direct review and reproducible tests; no independent expert review is claimed.
Database constraints validate supplied metadata, not sensor calibration, data
licensing authority, secret-free arbitrary payloads, feature lineage, or causal
claims. Insertion time is not transaction commit time. The future ingestion and
prediction jobs must implement the documented availability/commit contracts.

Role separation, monitored retries, scheduling, backups, runtime failure recovery,
and complete data-quality detection remain future work. Schema support for those
concepts is not their implementation. Phase 3 may now build the bounded HTTP
adapters and verify real persistence plus unchanged/revision handling end to end.
