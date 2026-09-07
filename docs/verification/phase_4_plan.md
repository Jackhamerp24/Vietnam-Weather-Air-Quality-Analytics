# Phase 4 Verification Plan

Scope: a bounded, read-only audit of the stored dataset, followed by a dated
quality report. No ingestion refresh, migration, deletion, imputation, training,
dashboard or scheduling belongs to this phase.

## Claims And Evidence

The implementing agent owns the following verification claims. No independent
review is claimed.

| Claim | Minimum evidence |
| --- | --- |
| A frozen audit cannot mix database states | One PostgreSQL REPEATABLE READ, READ ONLY transaction; concurrency/isolation test |
| Later invalid revisions cannot resurrect old measurements | Synthetic as-of and invalid-marker tests, including alignment |
| Model overlaps cannot inflate environmental sample counts | Synthetic snapshot-selection tests; separate rows, captures, valid-time counts |
| Missingness uses requested hourly denominators | Empty series, edge gaps, internal gaps, UTC/local day and hour tests |
| Quality screening preserves evidence | Unit/range, sentinel, flag, flatline and metadata-change tests; zero source writes |
| Reproduction identifies the same inputs | Configuration, query, source-code and input-content hashes; repeated live result hash |
| The command is safe to operate | Explicit bounds/cutoff, bounded extraction, no overwrite, credential-safe errors, installed CLI test |

Prefer isolated synthetic cases plus a narrow live extraction of the existing
Supabase dataset. Existing aggregate counts alone cannot establish revision or
alignment correctness. A full provider backfill would change the subject of
the audit and is unnecessary.

Freeze the measured window at 2026-06-08 through 2026-09-06 UTC and the extraction
cutoff at 2026-09-06T20:59:00.669630Z. Model history uses the same coverage window;
poll captures retain their own requested windows and source labels. Select
eligible revisions before assessing quality. Resolve model captures before
looking for usable values, including absent values in a newer capture.

The artifact must include a selection policy, content hashes, counts, gaps,
quality findings, metadata/revision diagnostics and limitations. Database
timestamps establish row eligibility, not historical commit or availability
times. Repeatable-read freezes the present extraction; it does not reconstruct
past commit visibility. Retain the dated report and compare input hashes on replay.

Required checks: offline unittest suite, isolated PostgreSQL suite, installed
CLI smoke/repeat checks and git diff --check. Repeat a check after changing its
code, inputs or boundary. Use only the existing direct PostgreSQL connection;
keep the Supabase MCP read-only and Alembic as schema owner.

## Result

The implementation and dated live artifact are recorded in
`phase_4_quality_2026-09-07_final.json`. The command used the reviewed
`0003_response_integrity` schema and the existing stored configuration. It ran
one repeatable-read, read-only extraction with 30-second statement, 5-second
lock and 60-second idle-in-transaction limits. The artifact records hashes for
the configuration, SQL queries, implementation inputs and extracted source rows.
