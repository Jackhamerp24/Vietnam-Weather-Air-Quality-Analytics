# Phase 10: Vietnam Air Observatory verification

Date: 2026-09-12. Scope: local read-only dashboard over frozen Phase 5–9
artifacts. The implementation uses static HTML/CSS/JavaScript and a Python
standard-library public-data builder and preview server. No deployment,
scheduler, database change, API request, credential read or model fit occurred.

## Delivery and design

The user-requested `ui-ux-pro-max` skill informed the navy/sidebar dashboard,
semantic blue/teal/amber colors, responsive spacing, keyboard focus, reduced
motion, chart/table alternatives and independent light/dark contrast checks.
The reviewed design lives in
`design-system/vietnam-air-observatory/MASTER.md` and
`design-system/vietnam-air-observatory/pages/dashboard.md` (page override wins).
The generic sales/marketing pattern returned by the skill did not fit, including
on retry. We retained the analytics style and replaced that pattern with
research navigation. Fonts use local fallbacks; no Google Fonts/CDN requests.

The static implementation replaces the originally suggested Streamlit/Plotly
stack. No new runtime package is required; the browser reads a single local
JSON file and the server exposes only an exact public asset allowlist.

| View | Delivered interactions and boundaries |
| --- | --- |
| Overview | Station/date filters, accepted-hour and qualified-day counts, daily PM2.5 chart/table/CSV, station coverage and source roles |
| Air quality | Hourly PM2.5 with gaps, daily qualification ledger, fixed-window diurnal profile, precomputed Phase 6 estimates with adjusted p-values and fit details |
| Weather context | ERA5 variable/units/support/quality, fixed-window Pearson table, independent CAMS modeled-city selector and modeled daily means |
| Model diagnostics | Frozen baseline/ML tables, horizon/split/feature/scope/family/transform filters, explicit unavailable cells, paired deltas and fit-history qualifications |
| Methods & provenance | Frozen boundaries, source attribution, limitations, artifact identities, verified-file maps and the exact historical metadata exception |

Descriptive dates compare supplied Vietnam-local ISO dates. Full-window
diurnal/Pearson/statistics and model results keep fixed-window labels and do not
recalculate under those dates. Measured daily means require a full local day
and at least 18 accepted hours; partial UTC-window boundary days stay unplotted.
Hourly nulls break paths. CAMS is a separate modeled context stream, including
modeled-only Da Nang, never a replacement for measured values.

## Code and public data

- `dashboard/index.html`, `styles.css`, `app.js`: five-view interface,
  native controls, safe text escaping, CSV formula-string neutralization,
  explicit load/error/retry/empty states, local theme preference.
- `scripts/build_dashboard.py`: pinned SUCCESS file bytes, mandatory
  declarations, payload checks and canonical identities before data projection;
  strict JSON/CSV and non-finite checks, no model/application imports, exclusive
  new-output writing and preflight-before-input-read.
- `scripts/serve_dashboard.py`: loopback-only GET/HEAD for index/styles/app/
  optional charts/data; traversal, private paths, listings and symlinks rejected.
  Mutation methods are rejected. Requests/queries are not logged. CSP restricts
  scripts/connections to local assets; no repository or database endpoint.
- `tests/test_dashboard.py`, `tests/test_dashboard_server.py`: 44 data-boundary
  and 7 server checks. `scripts/test_dashboard_ui.cjs` provides the browser
  smoke/visual evidence using the existing verification runtime.

Public bundle: `dashboard/data/dashboard.json`, schema `phase10_dashboard_v1`.

| Identity | SHA-256 |
| --- | --- |
| Canonical bundle excluding its digest field | `b3b43813751628cc0d3439c209484a7c588cbdc9f355eb38cbe9233b1e0a167d` |
| JSON file bytes | `d2c017952150828f30a1a6617940983ece43c06c20aa4498a44d933046fe131d` |

Counts: 4,320 hourly grid rows (4,191 accepted, 129 absent), 182 local-day rows,
48 diurnal summaries, 273 CAMS modeled-day rows, 31 recorded statistical fits,
90 baseline metric cells, 288 ML metric cells and 360 comparisons. Source
observation/revision/response IDs and raw payloads are excluded from public
measurement rows. Null values remain null, distinct from zero.

Phase 9 uses the accepted v4 artifact
`phase_9_models_2026-09-12_comparison_hardened/` (manifest
`378f2e7f34476fe885ce6ec9827b7a48c346706f36b548fbc8db78ce94d8a770`). Only 24
calendar-only model instances trained; 72/288 model cells are available and
216 remain unavailable. The UI preserves descriptive/tuning labels and shows
both fit partitions and paired rows next to comparisons. Test comparisons with
unequal training histories remain visibly qualified.

## Exact historical documentation exception

All consumed data payloads verify. The pre-existing Phase 5 `README.md` does
not match its old SUCCESS entry. Its working bytes equal committed HEAD; one
additional LF would produce the declared checksum. We did not change it.

| Phase 5 README checksum | Value |
| --- | --- |
| Declared in pinned SUCCESS | `f6e76ba8011e6657c3894124639c7789806a17db9097dc4b82a5921f24d625cd` |
| Observed (committed HEAD) | `f5de669c0c37f0f3d4e9fd7a02c0c4c21540f233397f34fbbb234082d0e68988` |

Gate 2 reviewer approved this exact non-consumed exception only. The builder
checks the Phase 5 path, filename, pinned SUCCESS and both hashes; other README
variants or data mutations fail. It never parses that README as dashboard
content. The public verified-file map excludes it, and a separate exception
entry plus Methods warning records both hashes. We do not claim the complete
historical Phase 5 artifact is checksum-valid. No general normalization/skip
rule was added.

## Verification evidence

| Gate | Result |
| --- | --- |
| Data + static-server tests | 51 passed (44 + 7) |
| Full offline suite | 313 tests run: 311 passed, 2 exact-credential checks skipped |
| Isolated PostgreSQL | 52 passed in its disposable local cluster |
| Bundle replay | Rebuilt into a new temporary path; byte-identical JSON and canonical digest |
| Browser | 13 interaction groups passed; no script errors or external page requests |
| Responsive | All five views checked at 375, 768, 1024, 1440px and 812×375 landscape; no page-level horizontal overflow (wide tables/nav scroll within their containers) |
| Accessibility checks | Keyboard chart inspection, skip link preserving view, native labelled controls, focus, table fallback, light/dark rendered text contrast ≥4.5:1 on tested selectors and reduced-motion preference |
| Server live checks | Local HTTP assets load; private/unlisted paths return 404, mutation returns 405 |
| Diff/docs | `git diff --check`, local-link and trailing-whitespace checks pass |

The existing Playwright/Chrome runtime was used only for verification with a
temporary browser profile. Local binding/headless launch required sandbox
approval. This does not add a browser automation dependency to the dashboard.
The browser tests intentionally use a New York timezone to verify that display
scope stays on Vietnam-local dates. We did not perform a full assistive-
technology certification or claim WCAG conformance from these smoke tests.

Evidence:

- [Browser checks](phase_10_ui_2026-09-12_final/browser_checks.json)
- [Desktop overview](phase_10_ui_2026-09-12_final/overview-desktop.png)
- [Dark overview](phase_10_ui_2026-09-12_final/overview-dark.png)
- [Mobile overview](phase_10_ui_2026-09-12_final/overview-mobile.png)
- [Weather view](phase_10_ui_2026-09-12_final/weather-desktop.png)
- [Model view](phase_10_ui_2026-09-12_final/models-desktop.png)

Review gates: the Codex reviewer passed contract Gate 1 on attempt 2 and
integration Gate 2 on attempt 1. The coordinator completed final browser and
visual Gate 3. The reviewer service returned a rate-limit error during the
optional final notification, so no additional reviewer approval is claimed.

## Run and next boundary

```bash
python3 -B scripts/serve_dashboard.py
```

Open `http://127.0.0.1:8765/`; Ctrl-C stops the server. See
[dashboard runbook](../../dashboard/README.md) and
[shared contract](phase_10_contract.md). The preview is local and is not deployed.

Phase 11 automation remains a separate task requiring explicit scheduling and
service authorization. Prospective captured evidence is still required for
real forecast evaluation. Phase 10 does not alter the frozen Phase 4–9 data,
train models, install a schedule, expose Supabase, or claim operational readiness.
Existing uncommitted Phase 9 work is preserved; nothing was committed or pushed.
