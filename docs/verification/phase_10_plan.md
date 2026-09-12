# Phase 10 Plan: Vietnam Air Observatory Dashboard

Status: delivered and verified; see [phase_10.md](phase_10.md)
Date: 2026-09-12 UTC

## Objective

Build a read-only, source-aware portfolio dashboard over the frozen Phase 5–9
artifacts. The dashboard must help a reader understand coverage, PM2.5 trends,
weather context, statistical associations, baselines and ML diagnostics without
turning limited evidence into operational or causal claims.

## Boundary

- Static web assets only: HTML, CSS and dependency-free JavaScript.
- No database, Supabase, API key, `.env`, external network request or client-side
  secret. Same-origin requests to static public assets are allowed.
- No model fitting, data mutation, schedule or migration.
- The current frozen window remains `limited_diagnostic`; the UI must show this
  state wherever model/baseline results appear.
- Measured PM2.5, ERA5 weather, CAMS modeled AQ and project diagnostics remain
  visibly separated.
- Phase 10 does not claim forecast skill, production readiness, causal effects,
  city-wide exposure or health guidance.

## Design system

The UI follows the persisted `ui-ux-pro-max` system:

- `design-system/vietnam-air-observatory/MASTER.md`;
- `design-system/vietnam-air-observatory/pages/dashboard.md`;
- data-dense dashboard layout, navy/blue data palette with amber status accent;
- offline system fonts with Fira Sans/Fira Code if already present;
- visible focus rings, keyboard-operable controls, reduced-motion support;
- 4.5:1 normal text contrast and responsive gutters at 375/768/1024/1440px.

The dashboard adapts the generated enterprise template to research analytics:
the primary path is Overview → Air quality → Weather context → Methods &
provenance, with a persistent diagnostic-status banner instead of sales/login
CTAs.

## Views and interactions

1. **Overview** — status banner, frozen-window facts, sensor cards, evidence
   counts and a short methods boundary.
2. **Air quality** — sensor and date-range filters, PM2.5 hourly trend SVG,
   daily summary table, missingness indicators and source labels.
3. **Weather context** — weather-variable selector, synchronized hourly trend,
   descriptive association cards and source separation notice.
4. **Model diagnostics** — Phase 8/9 coverage, baseline/model cells,
   descriptive comparison table and train/validation/test explanation.
5. **Methods & provenance** — phase timeline, artifact hashes, data rules,
   limitations and links to verification records.

Use native `<button>`, `<select>`, `<input type=date>` and `<details>` controls.
Provide a skip link, landmark headings, `aria-live` status updates, visible
focus, keyboard chart navigation where possible, and a table fallback for every
chart. Do not use emoji as icons; use inline SVG icons with labels or
`aria-hidden="true"` when decorative.

## Data contract

Create `scripts/build_dashboard.py` using only the Python standard library. It
must read these frozen inputs:

- `docs/verification/phase_5_eda_2026-09-07_final/eda_bundle.json`;
- Phase 5 daily/hourly CSVs;
- `docs/verification/phase_6_statistics_2026-09-09_corrected/phase_6_statistics_summary.json`;
- `docs/verification/phase_8_baselines_2026-09-11_v2_verified/phase_8_baselines_summary.json`;
- `docs/verification/phase_9_models_2026-09-12_comparison_hardened/phase_9_model_summary.json`.

The builder must:

- verify data inputs against pinned SUCCESS/hash manifests before extraction;
  preserve the exact reviewed, non-consumed Phase 5 README exception in the
  public provenance note (see shared contract), without altering source bytes;
- emit only the fields needed by the UI;
- preserve source, sensor, date, quality and coverage labels;
- include `provenance`, `meta.window`, `schema_version` and `bundle_sha256`;
  runtime timestamps do not enter the reproducible JSON;
- refuse to overwrite `dashboard/data/dashboard.json`; choose a new output
  path to reproduce a build. No force-overwrite option;
- serialize deterministic JSON with sorted keys and no non-finite values.

The output must not include response IDs, API credentials, database URLs, raw
payloads or target lineage not needed for display.

## Implementation stages

1. Freeze the design system and dashboard data contract.
2. Build the deterministic public data bundle and its unit tests.
3. Implement the responsive shell, navigation and diagnostic banner.
4. Implement SVG trend charts, tables and synchronized filters.
5. Implement diagnostics/provenance views and source labels.
6. Add accessibility, responsive, reduced-motion and no-network checks.
7. Run the static server and browser smoke tests; update verification docs.

### Implementation decision and review gates

The roadmap suggested Streamlit/Plotly. This implementation uses dependency-free
HTML/CSS/JS and a Python stdlib artifact builder/local static server. That keeps
the current offline stack, allows detailed responsive design, and serves no
repository files except a reviewed public allowlist. It is not a new database
API. No Tailwind, remote fonts, map tiles, analytics or CDN scripts are added.

Use three gates: contract/design review before parallel implementation; data/UI
integration review after focused tests; final review after browser checks. A
Codex subagent in reviewer (Oracle) role owns each review, one initial and at
most two material re-reviews per gate. The main agent integrates and verifies;
data and designer lanes have disjoint file ownership. This is internal task
work, not OpenCode delegation or a new user-facing task. Do not commit/push
until requested; existing uncommitted Phase 9 work must be preserved.

See `phase_10_contract.md` for the exact shared public data contract.

## Verification gates

- `git diff --check`.
- `PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_dashboard -v`.
- Full offline suite.
- Isolated PostgreSQL suite; dashboard must not use it.
- Build bundle twice and compare bytes.
- Serve with `python3 -B scripts/serve_dashboard.py` on loopback and check
  HTTP 200 for listed assets/JSON only. Reject unlisted paths, traversal,
  symlinks, directory listings and mutation methods; never log request queries.
- Browser smoke test: overview, nav, filters, date controls, chart/table
  fallback, details sections and keyboard focus.
- Verify no external `<script src>`, stylesheet, fetch URL or network request.
- Check 375px, 768px, 1024px and 1440px layout bounds.
- Check `prefers-reduced-motion` CSS path and accessible names.

## Deliverables

- `dashboard/index.html`;
- `dashboard/styles.css`;
- `dashboard/app.js`;
- `dashboard/data/dashboard.json`;
- `scripts/build_dashboard.py`;
- `tests/test_dashboard.py`, `tests/test_dashboard_server.py`;
- `scripts/serve_dashboard.py`, `scripts/test_dashboard_ui.cjs`;
- `docs/verification/phase_10.md`;
- updated `README.md`, `AGENTS.md` and `.slim/deepwork/phase-10-dashboard.md`.

## Acceptance criteria

Phase 10 is complete when the dashboard is useful at desktop and mobile widths,
all views load from the frozen bundle without network/database access, filters
update charts and tables deterministically, every chart has a table fallback,
the limited-diagnostic status remains prominent, provenance labels are visible,
and all listed verification gates pass.

Observed completion: contract and integration gates passed; final browser
evidence is recorded in `docs/verification/phase_10_ui_2026-09-12_final/`.
