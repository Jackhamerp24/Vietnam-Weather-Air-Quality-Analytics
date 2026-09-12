# Vietnam Air Observatory

A local, read-only research dashboard for the frozen Phase 5–9 evidence.
The web application has no third-party runtime dependencies or external asset
requests. Use Python 3.11+ for the public-data builder and preview server.

From the repository root:

```bash
python3 -B scripts/serve_dashboard.py
```

Open `http://127.0.0.1:8765/`. Stop with Ctrl-C. Choose another local port with
`--port 8766`. The server binds loopback and serves only the reviewed HTML,
CSS, JavaScript and public JSON; it does not expose repository files, documents,
credentials or a database API. Opening index.html through a file URL is not a
supported launch path because browsers restrict fetching local JSON.

## Explore

- Overview: qualified daily PM2.5, accepted coverage and source roles.
- Air quality: hourly observations, fixed-window diurnal profiles and recorded
  Phase 6 associations with adjusted p-values.
- Weather context: ERA5 fields at stations plus separate CAMS city context.
- Model diagnostics: frozen baseline/ML metrics, missing-feature reasons and
  paired comparisons with fit-history qualifications.
- Methods & provenance: units, temporal support, availability policy, source
  attribution, verified file hashes and the documented metadata exception.

Select a station/date range, switch chart to table, inspect a chart with arrow
keys, export CSV, or switch theme. Time filters use Vietnam-local dates.
Precomputed statistics/model metrics and diurnal/Pearson summaries remain
fixed-window and say so. No scores or models are fitted in the browser.

## Reproduce the public bundle

The reviewed JSON is included at `dashboard/data/dashboard.json`. Rebuild into
a NEW output file; the parent directory must exist:

```bash
python3 -B scripts/build_dashboard.py --output /private/tmp/vietnam-air-replay.json
cmp dashboard/data/dashboard.json /private/tmp/vietnam-air-replay.json
```

The command rejects existing output paths. It checks pinned input SUCCESS
bytes, data hashes and the frozen canonical identities before projection.
The unused Phase 5 README has a pre-existing, exact documented checksum
exception; the UI shows it. All displayed data payloads remain verified. Do
not fix historical source bytes or regenerate baseline/ML artifacts to run
the dashboard.

## Verification

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_dashboard tests.test_dashboard_server -v
```

Optional browser verification uses an existing Playwright + Chrome installation,
not a dashboard dependency:

```bash
node scripts/test_dashboard_ui.cjs http://127.0.0.1:8765/ /private/tmp/vietnam-air-ui-evidence
```

The second argument must be a new directory. The runner checks filters,
navigation, CSV, fixed-window labels, light/dark contrast, responsive layout,
reduced motion, data-error recovery and no external network requests. It also
captures screenshots. If Playwright is outside node_modules, supply its existing
package directory through NODE_PATH. No package installation is needed to use
the dashboard itself.

This is a frozen research presentation, not live monitoring, a city exposure
estimate or health advice. Calendar-only model outputs are limited diagnostics;
captured PM/history and forecast-weather features require a prospective
collection period before real forecasting evaluation.
