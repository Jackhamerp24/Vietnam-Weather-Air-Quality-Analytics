# Supabase Free-Tier Setup

Supabase hosts the Phase 3 PostgreSQL data. The verified project reference
is `rrexplijhvdltxvvmxmi`, giving the public endpoint:

```text
https://rrexplijhvdltxvvmxmi.supabase.co
```

The host resolved and responded during verification. The initial REST-root probe
returned 401, but MCP later confirmed an active publishable key. The
[Supabase OpenAPI changelog](https://supabase.com/changelog/42949-breaking-change-removing-access-to-openapi-spec-via-the-anon-key)
explains that anonymous access to the root OpenAPI spec was removed; that probe
did not establish an invalid key. Backend ingestion, migrations and analysis use
PostgreSQL credentials, not publishable/secret API keys.

The supplied secret key was **not used**; the user reported rotating it. A Supabase secret/service-role key can
bypass Row Level Security and must never be embedded in a dashboard, browser,
repository, notebook or logs. This project does not need it for direct PostgreSQL
access.

## Database Connection

Open **Supabase Dashboard > Connect > Session Pooler** and use the displayed URI.
Session Pooler is preferred because it supports persistent application sessions
and IPv4 networks. Transaction Pooler can be considered later for short stateless
jobs, after testing its prepared-statement/session-setting behavior.

Store the URI only in ignored `.env` or a deployment secret. Change the URI scheme
from `postgresql://` to `postgresql+psycopg://` if desired; the helper accepts both.
Require TLS. If the URI has no
query string, append `?sslmode=require`; if it already has one, append
`&sslmode=require`. Percent-encode special characters in the database password.

Do not send the URI or password through chat. After setting `DATABASE_URL` locally:

```bash
set -a
source .env
set +a
.venv/bin/vn-air db status
.venv/bin/vn-air db upgrade
.venv/bin/vn-air db seed --config configs/study.json
```

Load only a trusted `.env`; `source` executes shell syntax. Avoid shell tracing,
process-list command-line credentials and printing the variable. The CLI hides SQL
parameters and accepts database `postgres` only for a Supabase hostname. A missing
`sslmode` defaults to `require`; explicit non-TLS modes are rejected. This encrypts
transport but is not a claim of `verify-full` CA/hostname verification. Local
`postgres` remains rejected; session pooling on port 5432 is required by ingestion.

Run `db status` first. A new Supabase project should report not migrated; if it
already contains an unrelated `vn_air` schema or migration table, stop rather than
reset it. The migration creates only schema `vn_air` and
`public.vn_air_schema_version`; it does not create roles, extensions, other public
tables, public-access policies or fabricated observations. Phase 3 forward
migrations add checkpoints, provenance diagnostics and deny-by-default RLS.

Schema history is managed by **Alembic**, not Supabase CLI migrations. Therefore
the MCP `list_migrations` tool can return an empty list while
`vn-air db status` correctly reports `0003_response_integrity` from
`public.vn_air_schema_version`. Do not apply a second independent migration history.

## API Keys

- `SUPABASE_PUBLISHABLE_KEY`: safe for a browser only when database policies make
  the exposed operation safe. It is optional until the dashboard deployment.
- Secret/service-role key: backend-only administrative credential. Avoid it for
  this project unless a later task cannot use a least-privilege database role.
- Database password/URI: secret. Required for migration and ingestion through
  PostgreSQL; unrelated to the publishable and secret API keys.

The current schema lives outside `public`. Do not expose `vn_air` through PostgREST
yet. A later dashboard should use a small read-only API/view surface and Row Level
Security, or a read-only database role, rather than granting browser access to raw
responses, quarantine details, source metadata or model administration tables.

## Free-Tier Operations

Use Supabase as an off-machine deployment target after local ingestion passes.
Keep the local `vietnam_environment` database for development and isolated tests.
Before scheduling continuous collection:

1. Verify current free-tier database size, egress, compute/pause and backup terms
   in the Supabase dashboard/docs; provider limits change.
2. Measure raw-response growth. Retaining every response supports reproducibility
   but can consume the free database faster than normalized hourly rows.
3. Start with hourly collection for two sensors and bounded weather/model calls.
4. Add database-size and last-success monitoring before treating it as continuous.
5. Export regular logical backups because free-tier backup guarantees may not meet
   project recovery needs. Test restoration rather than assuming a backup works.

Do not configure GitHub Actions or public dashboard access until Phase 3 proves
idempotent ingestion, retries, revisions and partial-failure recovery locally.
Moving storage to Supabase does not complete those engineering or scientific tasks.

## OpenCode MCP

This repository contains a project-scoped [`opencode.json`](../opencode.json)
entry named `supabase-vietnam-weather`. It targets only project
`rrexplijhvdltxvvmxmi`, enables read-only mode, and exposes these feature groups:

- `docs`
- `database`
- `debugging`
- `development`

Account management is disabled by project scoping. Edge Function deployment,
Storage and paid experimental branching tools are not enabled. Database writes,
including `apply_migration` and write SQL, are disabled by `read_only=true`.
Use the tested direct PostgreSQL migration path for schema changes.

The MCP uses Supabase OAuth, not the database password, publishable key or secret
key. Authenticate from the repository root:

```bash
opencode mcp auth supabase-vietnam-weather
opencode mcp auth list
opencode mcp list
```

Verification on 2026-09-07 reported `authenticated` and `connected`. OAuth state
is stored by OpenCode outside this repository. Do not commit tokens or replace
the URL with PAT headers. Supabase currently requests broad read OAuth scopes for
its hosted MCP flow; the project/reference, read-only flag and selected feature
groups limit the available MCP tools.

Quit and restart OpenCode after changing MCP configuration. The session that made
the change does not hot-load new tools. Keep manual approval enabled, treat values
read from database rows/logs as untrusted content, and use narrow queries because
LLM-connected data sources carry prompt-injection and disclosure risks.

There is also a different global Supabase MCP in the user's OpenCode config. This
project uses a distinct name and does not modify or authenticate that global entry.
Run MCP commands from this repository to include the project-scoped server.

Phase 3 installed and reviewed `supabase` and `supabase-postgres-best-practices`
guidance from `supabase/agent-skills` locally for database writing and security
review. These ignored agent resources are not application/runtime dependencies;
the existing Alembic workflow remains authoritative. No global OpenCode settings
or MCP write permissions were changed.
