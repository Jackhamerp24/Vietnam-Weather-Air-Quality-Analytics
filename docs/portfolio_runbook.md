# Portfolio runbook: reproduce the Vietnam Weather & Air Quality Analytics evidence

This runbook lets a new reader reproduce the local, credential-free evidence:
the test suites, the walkthrough bundle, the portfolio summary and the dashboard.
It never asks you to read `.env`, connect to Supabase, run ingestion, create a
database role or install a scheduler. Those are authorization-gated operational
actions described in [operations.md](operations.md) and are not part of
portfolio reproduction.

## 1. Prerequisites

- Python 3.11+ and PostgreSQL 15+ server binaries on `PATH` (only for the
  isolated database suite).
- A checkout of this repository with its frozen verification artifacts.
- No provider API keys or project database credentials are required. Run the
  commands from the repository root.
- The dashboard and walkthroughs use only the Python standard library.

The test suites also require the application dependencies. For a new checkout
without an existing environment, install them once:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps .
```

Installation can need network access unless the packages are cached. Reuse a
working environment; do not recreate it. After setup, walkthroughs and dashboard
builds use local files only. The database suite uses its own synthetic cluster;
the browser uses loopback HTTP, not provider endpoints.

## 2. Offline test suite

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
```

Two checks skip unless exact credentials are exported; they never read a file
for you. Everything else is offline.

## 3. Isolated PostgreSQL suite

The runner creates its own disposable socket-only cluster and removes it. Do
not point it at Supabase or the project database.

```bash
PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
```

## 4. Analytical evidence walkthroughs

The Phase 12 walkthroughs verify pinned artifact hashes before presenting any
value. Each writes Markdown plus machine-readable JSON into a NEW directory and
refuses to overwrite existing output.

```bash
python3 -B reports/portfolio/run_walkthroughs.py --output-dir /private/tmp/phase12-walkthroughs
```

Individual walkthroughs work the same way:

```bash
python3 -B reports/portfolio/walkthrough_01_data_quality_and_eda.py --output-dir /private/tmp/phase12-walkthrough-01
python3 -B reports/portfolio/walkthrough_02_sensor_associations.py --output-dir /private/tmp/phase12-walkthrough-02
python3 -B reports/portfolio/walkthrough_03_feature_baseline_ml_contract.py --output-dir /private/tmp/phase12-walkthrough-03
python3 -B reports/portfolio/walkthrough_04_dashboard_and_reproducibility.py --output-dir /private/tmp/phase12-walkthrough-04
```

The frozen generated bundle is
[verification/phase_12_portfolio_2026-09-14_review_corrected/](verification/phase_12_portfolio_2026-09-14_review_corrected/manifest.json).
Re-running into a different new directory produces byte-identical files.

## 5. Dashboard bundle reproduction

Rebuild the public JSON into a new path and compare it with the committed
bundle. The command rejects an existing output path and verifies pinned input
SUCCESS bytes and payload hashes before projecting any value.

```bash
python3 -B scripts/build_dashboard.py --output /private/tmp/vietnam-air-replay.json
cmp dashboard/data/dashboard.json /private/tmp/vietnam-air-replay.json
```

## 6. Launch the dashboard

```bash
python3 -B scripts/serve_dashboard.py
```

Open http://127.0.0.1:8765/ and stop with Ctrl-C. The server binds loopback and
serves only the reviewed static assets and public JSON; it exposes neither the
repository nor a database API.

## 7. Optional browser verification and screenshots

These use an existing Playwright + Chrome installation. They are verification
tooling, not application dependencies; nothing is installed by the dashboard.

```bash
node scripts/test_dashboard_ui.cjs http://127.0.0.1:8765/ /private/tmp/vietnam-air-ui-evidence
node scripts/capture_dashboard_screenshots.cjs http://127.0.0.1:8765/ /private/tmp/vietnam-air-screenshots
node --test scripts/test_dashboard_capture.cjs
```

Both commands require a NEW output directory. If Playwright is outside
`node_modules`, supply its existing package directory through `NODE_PATH`.
Capture verifies the actual served bundle against its pinned bytes, blocks
off-origin HTTP/websocket requests, and records PNG hashes, file sizes, actual
image dimensions and viewport sizes. Full-page images can be taller than the
viewport. The capture-contract tests require Node only, without Playwright.

## 8. Portfolio summary and walkthrough outputs

- [Curated results summary](../reports/portfolio_summary.md)
- [Walkthrough source and instructions](../reports/portfolio/README.md)
- [Phase 12 verification record](verification/phase_12.md)

## 9. Authoritative phase records

- [Phase 4 data quality](verification/phase_4.md)
- [Phase 5 EDA](verification/phase_5.md)
- [Phase 6 statistics](verification/phase_6.md) and
  [plan](verification/phase_6_plan.md)
- [Phase 7 features](verification/phase_7.md)
- [Phase 8 baselines](verification/phase_8.md)
- [Phase 9 ML](verification/phase_9.md)
- [Phase 10 dashboard](verification/phase_10.md)
- [Phase 11 automation](verification/phase_11.md)

## 10. What this runbook does NOT do

- No live ingestion, provider API request or Supabase connection.
- No database migration, role creation, grants or RLS change.
- No scheduler installation or activation; no real project backup.
- No model fitting or statistical inference outside the frozen artifacts.
- No `.env` reading: portfolio reproduction never needs credentials.

Operational activation is deliberately separate and requires explicit user
authorization; start at [operations.md](operations.md). Real captured-feature
model evaluation requires a prospective collection period; see the Phase 7-9
records above.
