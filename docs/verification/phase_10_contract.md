# Phase 10 shared implementation contract

Version: `phase10_dashboard_v1`. Product: Vietnam Air Observatory.
Runtime: dependency-free static HTML/CSS/JavaScript plus local Python stdlib.

## Public JSON: `dashboard/data/dashboard.json`

Top-level fields below are required. Extra fields may be added only after
coordinator approval. Keep safe, useful fields rather than copying raw bundles.
All numeric nulls stay null; no NaN/Infinity or missing-to-zero conversion.

```text
schema_version: "phase10_dashboard_v1"
meta: {
  title: "Vietnam Air Observatory", status: "limited_diagnostic",
  window: {start_utc, end_utc, cutoff_utc, local_start, local_end, timezone},
  daily_policy: text, limitations: [text], source_policy: text,
  integrity_notes: [text]
}
sensors: [{id, name, location_id, region, attribution, licence_url}]
hourly: [{sensor_id, period_start, period_end, local_date, local_hour,
          pm25: number|null, quality: text, weather: {variable_code: number|null},
          weather_quality: {variable_code: quality_label}}]
weather_variables: [{code, label, unit, temporal_support, source: "ERA5_reanalysis"}]
daily: [{sensor_id, local_date, accepted_hours, expected_hours, full_local_day,
         coverage_percent, qualified_mean: number|null, mean: number|null}]
diurnal: [{sensor_id, local_hour, n, mean: number|null}]
weather_associations: [{sensor_id, variable, n, pearson_r: number|null}]
cams_daily: [{location_id, local_date, n, mean: number|null}]
statistics: {version, results: [safe Phase 6 result fields], limitations: [text]}
features: {version, status, missing_families: [text], counts: object,
           prospective_collection_period_required: true, split: object}
baselines: {version, status, metrics: [Phase 8 metric records], split: object}
ml: {version, status, counts: object, metrics: [Phase 9 metric records],
     comparisons: [Phase 9 comparison records], split: object}
provenance: [{phase: number, label, directory: repo-relative text,
              identity: manifest/bundle digest, files_sha256: {verified_name: hash},
              integrity_exceptions: [{file, declared_sha256, observed_sha256, reason}]}]
bundle_sha256: digest of the full object with this field omitted
```

The sensors are OpenAQ `openaq_11357424` (CMT8, `cmt8`, Ho Chi Minh City) and
`openaq_14581375` (OceanPark, `oceanpark`, Hanoi urban area). Exact station
coordinates need not be published. Da Nang is modeled context only, not a
measured target. Do not plot an invented geographic polygon/map.

For Phase 6 results retain literal keys fit_id, hypothesis, exposure, estimate,
ci_low, ci_high, p_value_adjusted, inference, scale, scope, role, weather_case,
block_days, n, formula, adjustment, estimand, standardization, coverage,
nonempty_independent_blocks, eligible_independent_blocks and exclude_extreme.
Explain coefficients per one analysis-window SD (not a physical unit). Display
already-computed results; do not
re-fit or apply date filters to them. Never display unadjusted p as inferential.
Baseline/ML model lists and numeric scores stay those from the frozen summaries,
not recomputed in the browser. Missing metrics use an em dash and a reason.

## Data lane

Own `scripts/build_dashboard.py`, `tests/test_dashboard.py` and generated
`dashboard/data/dashboard.json` only. Build with Python stdlib, no vn_air model
import/fitting or network. Pin the SHA-256 of each selected artifact's SUCCESS
file in code, validate its declared payloads/safe paths and mandatory fields,
then parse selected data. Record selected hashes and source manifest identity.
Reject re-signed modified inputs, malformed JSON/duplicate keys, missing source
and non-finite values. Include Phase 7's verified summary for availability.

Gate 2 reviewed exception (non-consumed documentation only): Phase 5 README.md
matches committed HEAD but differs from the pinned SUCCESS declaration by one
additional trailing LF. Require exact artifact directory PHASE5, filename,
pinned SUCCESS e32a3ae84bf236504c4b183e277beccbc9682f4811f2e5c8956975f9ac3c4e89,
declared hash f6e76ba8011e6657c3894124639c7789806a17db9097dc4b82a5921f24d625cd,
observed hash f5de669c0c37f0f3d4e9fd7a02c0c4c21540f233397f34fbbb234082d0e68988.
Hash but never consume that README; exclude it from verified files_sha256 and
record both hashes in provenance.integrity_exceptions plus a human-readable
meta.integrity_notes warning. Fail other README variants and any data mismatch.
Do not normalize newline bytes, rewrite README/SUCCESS, or call the complete
Phase 5 artifact fully verified. All displayed data remain strictly verified.

Use actual Phase 5 daily/diurnal CSVs and bundle rows. Strip revision/response/
observation IDs and raw provenance from the public rows. CAMS daily means are
modeled context derived from the Phase 5 CAMS rows, independent from measured
PM2.5. Record counts, gaps and units. No inventing data or averaging two sites.
Use the reviewed variable metadata from configs/study.json (verify its frozen
hash if read) or literal metadata from that registry: wind m/s, temperature
degC, humidity %, pressure hPa, precipitation mm, radiation W/m2. Radiation is
preceding_hour_mean per the registry, precipitation preceding_hour_sum; use
the frozen registry value, not a guessed support. Instantaneous weather aligns
to the measured interval start; preceding-hour fields to the interval end.

Precomputed diurnal/Pearson summaries remain full-window and say so in the UI;
selected-date views must never relabel them as selected-range results. All date
selection compares supplied Vietnam-local ISO date strings, not browser timezone.

CLI: `python3 -B scripts/build_dashboard.py --output PATH`, default root derived
from the script; optional `--repo-root PATH` for tests. Existing output/absent
parent/symlink output is rejected before reading. Default output may be
`dashboard/data/dashboard.json`. No `--force`. Expose testable `build_payload`,
`write_bundle` and `main` functions, deterministic sorted JSON serialization.

## UI lane

Own `dashboard/index.html`, `dashboard/styles.css`, `dashboard/app.js` and
optional `dashboard/charts.js` only. Read the user-named ui-ux-pro-max skill
and design-system files. Use the reviewed page override over generic marketing
recommendations. Fetch `./data/dashboard.json` once, render from the contract.

Five views: Overview / Air quality / Weather context / Model diagnostics /
Methods & provenance. Default to a clear overview with evidence KPIs and a
qualified daily PM2.5 trend + station coverage card. Native labelled controls
for station/time scope, theme, chart/table, export, diagnostic horizon/split/
feature/model scope. Always show frozen dates (no live status), accepted-only
PM values, missingness and source labels. Date filters apply to descriptive
views only; statistics, diurnal/Pearson summaries and metrics stay fixed-window
and say so. Model comparison tables display history_status, fit_partition,
reference_fit_partition and paired_rows beside deltas; mismatch warnings stay
visible. Validation metrics retain tuning_diagnostic labels.

Use SVG line charts with separate segments at nulls, labelled axes/unit and
legends distinguishing shape/dash too. At least one readily accessible data
table per chart (paginated for hourly rows) and CSV export of the displayed
scope. Prefer daily trend by default; no need to render 4320 SVG focus nodes.
Safe text insertion/escaping for data; no eval, remote fonts/JS/map tiles,
innerHTML of raw source strings, automatic calls beyond static local assets.
Error/loading/empty states, reset filters, URL hash navigation, light/dark
theme, keyboard focus and mobile reflow required. No inert fake buttons.

## Coordinator ownership

Plan, reviewed design overrides, packaging/static-server CLI, E2E tests,
verification evidence, screenshots and documentation. Safe local server must
bind loopback and serve only index/styles/app/charts/data (not repo root or
private paths). Read-only GET/HEAD, no traversal/symlink leakage or logging
secret-bearing query strings. A `dashboard serve` package command and/or
`scripts/serve_dashboard.py` are allowed. No database or source API access.

The coordinator will integrate, visually inspect desktop/mobile layouts,
test all nav/filter/theme/table/download/error paths and confirm no external
network requests. No commit/push or Phase 9 code edits in this task.
