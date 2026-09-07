# Agent Instructions

## Project State

Vietnam Weather & Air Quality Analytics is a Data Science portfolio project.
Phases 1-3 are implemented:

- API/source research and measured-source qualification.
- PostgreSQL/Alembic architecture and Supabase deployment.
- Bounded OpenAQ/Open-Meteo ingestion with provenance, retries, revisions,
  quarantine, checkpoints and read-only reporting.

Phase 4 data-quality auditing is implemented and verified. The next planned
phase is **Phase 5: EDA**. Statistical analysis, feature engineering, model
training, dashboard work and scheduling are not yet implemented. Do not claim
model performance, significance, causal findings or production automation.

## Required Reading

- `README.md`
- `docs/verification/phase_3.md`
- `docs/ingestion.md`
- `docs/database.md`
- `docs/source_contracts.md`
- `docs/decisions/0001-data-sources.md`
- `docs/research/openaq_qualification.md`
- `docs/verification/phase_3_counts.json`

The detailed continuation handoff is outside the repository at:
`/var/folders/wf/z4hrd0fd667599w3yq_gbvpr0000gn/T/opencode/vietnam-weather-handoff-2026-09-07.md`.

## Data Rules

- Keep measured OpenAQ PM2.5, ERA5 reanalysis, Open-Meteo forecasts and CAMS
  modeled air quality separate.
- Treat CMT8 and OceanPark as sensor-level measurements, not city averages.
- Treat Da Nang as modeled-only until a qualified measured source exists.
- Preserve missing periods, revisions, failed runs, raw responses and quality
  issues. Do not interpolate gaps or silently replace observations with models.
- Use UTC `timestamptz` for storage. Respect OpenAQ exclusive period-ending
  intervals and Open-Meteo temporal support.
- Historical retrieval time is not historical availability. Do not use ERA5 or
  retrospective data as operational features without an explicit availability
  policy.
- Do not treat provider forecasts or CAMS values as ground truth.

## Security

- Never read, print, commit or paste values from `.env`.
- Never log API keys, database URLs, passwords, request headers or raw secret-
  bearing exceptions.
- `.env` is ignored and owner-only. Use environment variables for credentials.
- Supabase MCP is project-scoped and read-only. Use it for narrow inspection,
  docs and advisors. Apply schema changes through the tested Alembic workflow.
- The Supabase database has deny-by-default RLS and no browser policies by design.
  Do not expose `vn_air` through the Data API without an explicit dashboard
  access design and reviewed policies.
- Do not create paid services, branches, schedules or database roles without
  explicit user authorization.

## Commands

Use the installed package for CLI commands:

```bash
.venv/bin/vn-air db status
.venv/bin/vn-air report
```

Use the documented runbook for ingestion. It requires a trusted local `.env`:
`docs/ingestion.md`.

Run offline tests:

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
```

Run isolated PostgreSQL tests:

```bash
PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
```

The isolated suite creates and removes its own PostgreSQL cluster. Do not point it
at Supabase or the project database.

## Editing And Verification

- Inspect worktree status before changes. This repository has no commits yet and
  contains untracked project artifacts; do not clean or reset them.
- Use `apply_patch` for manual edits.
- Keep changes incremental and phase-scoped.
- Add tests for parser, provenance, time alignment, database constraints and
  failure recovery before changing ingestion behavior.
- Run `git diff --check`, offline tests and relevant isolated database tests.
- Update the appropriate verification document when live data or Supabase state
  changes. Do not duplicate large evidence payloads in prose.
- No independent Oracle review was available in the previous runtime. Do not
  claim independent review unless a future runtime actually performs it.

## Phase 4 Focus

The frozen, reproducible audit is recorded in `docs/verification/phase_4.md` and
the dated JSON artifact beside it. Preserve its cutoff, selection rules,
uncertainty and limitations when using the data for EDA. Keep the audit separate
from automatic deletion or imputation.

## Suggested Skills

Call the Skill tool as applicable:

- `verification-planning` before Phase 4 or any behavior-changing data pipeline work.
- `supabase` for Supabase database, MCP, RLS, advisor, migration or log work.
- `supabase-postgres-best-practices` before SQL, schema, index, trigger, RLS or
  database performance changes.
- `deepwork` only for genuinely multi-stage/high-risk work.
- `simplify` for a targeted readability pass after behavior is verified.
- `stop-slop` when writing analytical findings or portfolio prose.
- `customize-opencode` only when changing OpenCode configuration or MCP setup.
