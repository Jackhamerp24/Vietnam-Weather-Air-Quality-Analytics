# Source And Ingestion Contracts

Phase 2 design for Phase 3 adapters. The implemented behavior and deliberate
MVP limits are now in [ingestion.md](ingestion.md); scheduled reconciliation and
page-level resume below remain design goals. API facts and terms are in
[data_sources.md](data_sources.md). Reviewed inputs are in
[`configs/study.json`](../configs/study.json).

## Products

| Product ID | Endpoint / Options | Canonical Output |
| --- | --- | --- |
| `openaq_airgradient_hourly` | `/v3/sensors/{sensors_id}/hours`, UTC `datetime_from`/`datetime_to`, pagination | Hourly measured concentration revisions for configured sensors only |
| `open_meteo_weather_forecast` | `/v1/forecast`, `models=ecmwf_ifs`, UTC epoch, Celsius/m/s/mm | Forecast snapshots and weather values at station or explicitly labeled city points |
| `open_meteo_era5` | `/v1/archive`, `models=era5`, same units/time settings | Retrospective weather reanalysis snapshots; no invented run initialization |
| `open_meteo_cams_global` | `/v1/air-quality`, `domains=cams_global`, UTC epoch | Modeled pollutant concentrations and separately identified US AQI |

Source configuration excludes keys, arbitrary URLs and unknown options. An API
query builder must allowlist parameters again; schema metadata is not a license
to fetch arbitrary hosts. Cross-product response/sensor links are rejected by
database foreign keys. Unknown source variables remain in raw bytes and produce
a quality issue until reviewed, not opportunistic new training features.

## Transport And Recovery

- HTTPS only; OpenAQ key in `X-API-Key`, no credentials in URLs, logging or saved
  headers. Disable redirects for authenticated calls. Reject/redact any response
  that echoes a credential before persistence, recording why bytes were withheld.
- Start with one worker per provider and a cross-job rate budget. Suggested cap:
  20 requests/minute, at most 1,000/hour for OpenAQ; 60/minute and conservative
  daily/monthly accounting for Open-Meteo including weighted calls/backfills.
  These are project caps below provider ceilings, not new provider guarantees.
- Use explicit connect/read timeouts, at most three transient retries with
  exponential backoff plus jitter. Retry timeouts, 429 and 5xx; do not repeatedly
  retry 400/401/403. Respect `Retry-After` and verified quota-reset semantics.
- Persist each attempt and final error code. Auth/quota failures should stop
  the affected provider rather than rotate credentials or spin indefinitely.
- Commit raw responses before normalization. An exception rolls back the
  canonical batch, not the run and raw failure evidence. Resume from the last
  successfully committed interval/page, with an overlap to handle late data.

Expected Phase 3 log fields: timestamp, run ID, product, location/sensor ID,
request window/page, attempt, status/error code, latency, inserted/unchanged/
quarantined counts. Never log request headers, environment dumps or raw exception
strings containing SQL parameters/credentials.

## OpenAQ Measurements

Read actual sensor/parameter/period metadata. Confirm configured external sensor
and location IDs, country, coordinate tolerance, concentration units, licence
dates and reference-monitor status. A moved sensor or materially changed metadata
must pause scientific use and trigger review, not overwrite its old coordinates.

`/hours` uses exclusive period-ending semantics: 03:00 means [02:00, 03:00).
Canonical measurement storage accepts one-hour intervals on UTC hourly boundaries.
If a provider gives incompatible intervals, preserve/quarantine them; no silent
resampling. Original five-minute/raw data may be retained in response bodies for
an explicitly designed aggregation later.

Canonical `pm2_5` maps from OpenAQ `pm25`; `ug/m3` maps from both Unicode micro-sign
spellings. Keep raw units in the response. Gas ppm/ppb conversions are not generic
string replacements; add a reviewed density/temperature/pressure convention
before using them. The measured MVP only selects PM2.5.

The revision transaction must:

1. Acquire a sensor-scoped advisory lock or serialize the job; select the latest
   interval revision. PostgreSQL uniqueness remains the concurrency backstop.
2. Compare normalized scientific fields, flags, coverage, coordinate/metadata
   snapshot and value with the latest revision, using explicit canonical rules.
3. For unchanged data, leave the canonical row untouched and increment unchanged
   count. Keep the new source response as proof of polling. Do not refresh the
   earlier row's retrieval timestamp.
4. For a change, append `revision + 1`, linking the new response. A later value
   equal to revision 1 after a different revision 2 is still revision 3.
5. For a later explicit invalid/missing report with an identifiable interval,
   append an `invalid`/`missing` null marker. For invalid data, also retain a
   quarantine locator and reason. This prevents an older valid value from
   surviving just because the latest report was invalid.

Do not interpret omission from an API page as a retraction. Missing periods have
no invented observation rows; record gap issues against a sensor/window. For
unparseable identity/time, quarantine without guessing an interval. Unexpected
completeness percentages such as the Phase 1 values above 100 remain visible in
raw data; canonical `coverage_percent` is null pending recomputation, with an issue.

Polling `latest` alone misses late arrivals. Start with hourly `/hours` fetches
over the preceding 72 hours, a daily seven-day reconciliation, and bounded weekly
older reconciliation. Tune overlap after measuring actual delays. Late records
older than the window require reconciliation; this policy is not a completeness
guarantee. `meta.found` may be a string such as `>1000`; paginate by actual page
results with a hard budget. Backfill in bounded windows with checkpoints.

## Open-Meteo Model Values

Validate requested/returned location count, parallel array lengths, UTC offsets,
timestamps, units, and selected model/product. Preserve requested coordinates,
returned grid coordinates and response bytes. Grid displacement is expected;
evaluate distance/land-cell suitability instead of replacing station coordinates.

Normalized units: degC, %, mm, m/s, degree, hPa, W/m2, ug/m3, USAQI. The registry's
temporal support describes **model values**: precipitation preceding-hour sum,
radiation preceding-hour mean, other configured fields instantaneous. OpenAQ's
PM2.5 has its own measured hourly-mean interval despite the model PM2.5 registry
being instantaneous. US AQI is a derived index at its output timestamp with
pollutant-specific averaging rules; it is not a one-hour PM concentration.

Native cadence belongs per variable (`native_interval_seconds`, null if unknown).
Do not assume all hourly gases are native hourly output or all hourly PM is
interpolated; see the researched CAMS caveat. Missing arrays/values do not become
zero. Physical violations go to quarantine, with invalid markers when identity
is known. Large but plausible concentrations survive as `suspect` values.

Create a snapshot for each changed location/model/query capture and insert its values in the
same canonical transaction. Reprocessing the same response cannot add duplicate
values; another response can contain the same valid times without overwriting the
first forecast. Exact identical query/content captures can reuse an earlier
snapshot while preserving new raw-response evidence. Later analytical queries must choose an eligible vintage, not
average repeated captures. Raw retention cost is acceptable at the initial scale.

The live endpoint often stitches runs. Leave `run_initialized_at`/`model_version`
null and `run_provenance=unknown` when unavailable. `generationtime_ms` is response
performance, never forecast publication time. An explicit operational run requires
actual initialization evidence; a retrospectively generated hindcast remains
`hindcast`. A captured live response may be used prospectively after receipt even
when its internal run provenance is unknown, but never advertised as a known
as-issued model run.

## Quality Classes

| Situation | Canonical Handling | Evidence |
| --- | --- | --- |
| Nonnegative finite PM2.5, structurally valid | `accepted` initially | Original flags, unit/period metadata and response |
| Plausible extreme or provider warning | `suspect`, retain value | Quality issue explaining investigation, no automatic deletion |
| Explicit missing value | `missing`, null | Raw null/sentinel interpretation and source flags |
| Impossible value/unsupported unit with known interval | `invalid`, null; quarantine raw record | Reason code and response locator; newer revision supersedes old value |
| Invalid identity, timestamp or malformed payload | No guessed canonical row; quarantine | Retained bytes/error, parser version and locator if available |
| Missing time period | No fabricated measurement; gap issue | Expected-grid count and sensor/window |

Schema checks are guardrails. Phase 4 must implement the scientific validation
policy, calibrated thresholds, context-aware extremes and completeness monitoring.
The schema cannot establish instrument accuracy or infer causality.
