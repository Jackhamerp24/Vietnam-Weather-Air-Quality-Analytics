# OpenAQ: Authenticated Source Qualification

Date: 2026-09-07, Vietnam time. This extends the initially keyless
[Phase 1 investigation](phase_1.md). The user authorized an API key for this
project; no registration, payment or account changes were performed.

## Findings

`GET /v3/locations?iso=VN&limit=1000&page=1` returned 59 locations with country
`VN`. The result fits in one page and contains no duplicate location IDs. This
is the OpenAQ inventory at retrieval, not a census of physical Vietnamese
monitoring stations or evidence that all feeds are active.

| Candidate | Location / PM2.5 Sensor | Coordinates | Sensor History In Metadata | Decision |
| --- | --- | --- | --- | --- |
| CMT8, HCMC | 3276359 / 11357424 | 10.78533, 106.67029 | 2024-11-19 11:00Z to 2026-09-06 17:00Z | Select for MVP, subject to instrument/siting caveats |
| OceanPark, Hanoi urban area | 6123215 / 14581375 | 20.99330, 105.94410 | 2025-11-08 06:00Z to 2026-09-06 17:00Z | Select for MVP; short shared history and long gap need care |
| Hanoi / AirNow | 7441 / 21632 | 21.021939, 105.818806 | 2016-11-09 to 2025-04-09 | Historical candidate only; does not establish a live feed |
| Hanoi Nhan Chinh network location | 4946812 / 13502151 | 21.0031, 105.7947 | 2025-07-03 to 2026-09-06 17:35Z | Fresh metadata, but licence null; defer data redistribution/selection |
| Da Nang | None in the specified neighborhood | Centre 16.06778, 108.22083, radius 25 km | No location within radius in returned inventory | Modeled context only for now |

The closest location in the returned inventory was about 568.84 km from the Da
Nang point, using a haversine distance with Earth radius 6,371 km. This rules out
an OpenAQ location in the stated neighborhood at retrieval, not monitoring
elsewhere in the administrative area or on other platforms.

The older HCMC diplomatic-post location 7440 ended in March 2025 in location
metadata and had no licence record. Other Hanoi government-network entries were
stale or had null licences. We did not infer shutdown causes or permission from
station names. Do not merge similarly named old/new station IDs without checking
instrument continuity, coordinates, overlap and rights.

## Licence And Measurement Type

Both selected feeds use provider **AirGradient (66)**, `isMonitor=false`, and
instrument description **Unknown AirGradient Sensor**. Treat them as measured
non-reference sensor concentrations in micrograms/m3, not CAMS predictions or
reference-grade station data. Exact device model, outdoor siting, sampling height,
calibration, correction algorithm and changes remain unverified. A platform's
ground-level ingestion policy does not replace a sensor-specific siting audit.

Their location metadata lists licence **41, CC BY 4.0**, with `dateFrom=2023-07-15`
and no end date. Authenticated `GET /v3/licenses/41` returned the actual CC BY 4.0
URL, redistribution/modification allowed, attribution required, and no share-alike
requirement. The date range covers the sampled period.

Credit **OpenAQ**, **AirGradient**, and **Thomas Versteeg** for CMT8; credit
**OpenAQ** and **AirGradient** for OceanPark. Preserve the licence link and state
modifications. AirGradient's [terms summary](https://www.airgradient.com/terms-conditions/)
says owners retain their data and encourages OpenAQ sharing. Its
[privacy notice](https://www.airgradient.com/privacy-policy/) explains that opted-in
public measurements and locations can be downloaded, republished and combined by
third parties. These support the specific OpenAQ licence records; they do not
grant blanket access to private sensors or unrestricted scraping of AirGradient's
site/service, whose detailed terms impose separate restrictions.

The live licence 41 response correctly had `shareAlikeRequired=false`; the
documentation's example payload had a contradictory true value. Follow the
actual legal licence, not illustrative booleans copied from documentation.

## Ninety-Day Audit

Requested bounds: **2026-06-08T00:00:00Z to 2026-09-06T00:00:00Z**. Fetches used
`/v3/sensors/{id}/hours`, `datetime_from`, `datetime_to`, `limit=1000` and three
pages per sensor. We avoided the in-progress current day.

For a window `[start, end)`, the audit counts hourly intervals fully contained
within it, with period ends `start + 1 hour` through `end` inclusive. This yields
90 * 24 = **2,160 expected hours**. It verifies interval duration, uniqueness,
parameter/unit, finite nonnegative values and flags. Counting returned rows alone
would hide duplicates, boundary errors and missing periods.

| Metric | CMT8 | OceanPark |
| --- | --- | --- |
| Expected hours | 2,160 | 2,160 |
| Unique present hours | 2,154 | 2,037 |
| Present percentage | 99.7222% | 94.3056% |
| Missing hours | 6 | 123 |
| Longest consecutive missing run | 3 hours | 119 hours |
| Duplicate intervals | 0 | 0 |
| Nonfinite/negative concentration rows | 0 | 0 |
| Provider-flagged rows | 0 | 0 |
| Partially complete returned hours | 0 | 0 |

The finite/nonnegative/unflagged counts equal the present counts in this sample.
That is a basic structural check, **not proof of accuracy, correct calibration,
or absence of outliers**. Extreme-value adjudication belongs to Phase 4.

OceanPark's long gap begins at period end 2026-07-01T02:00Z. Do not interpolate
through it for forecasting targets, use row shifts as hourly lags, or silently
drop it from coverage metrics. Analysis should disclose missingness by day/hour
and compare sensitivity to restricted common periods.

The sensor metadata describe a common history beginning in November 2025, less
than one complete annual cycle at research time. This audit covers 90 days only.
It supports starting ingestion and preliminary analysis, not claims about annual
seasonality, city-wide exposure, or long-term trends.

## API Anomalies

- Sensor summary coverage returned `expectedCount=1` and values such as
  `percentComplete=1435100.0` for CMT8. The auditor recalculated completeness from
  periods instead of displaying that impossible percentage.
- Several lifetime summaries had null quantiles and zero standard deviation
  despite variable extrema. Do not treat them as computed EDA statistics.
- Hanoi/AirNow sensor summary included a minimum of `-999`, a candidate missing or
  error sentinel. Retain and flag it if that history is ingested; do not interpret
  it as a negative environmental concentration. No hourly AirNow history was
  downloaded in this phase.
- Some newer government-network timestamps occur at five-minute boundaries,
  despite generic OpenAQ FAQ statements about accepted frequencies. Read actual
  period metadata before aggregation; do not hard-code the FAQ as a universal
  sensor cadence.

These are observations from real payloads. They justify dedicated data-quality
checks, not blanket rejection of OpenAQ.

## Reproduce

The project scripts use only the standard library. `probe_openaq.py` reads an
exported `OPENAQ_API_KEY`, blocks redirects, uses a 45-second timeout, waits three
seconds between requests, and stops on non-200 responses without retry. It caps
requests at 120, inventory pages at five and hourly pages at ten per sensor.
Keep full captures local until licences have been reviewed. Use new output names.

In this workspace `.local/` and `.env` already exist and are ignored by Git. The
user-approved key is stored in `.env` with mode 600. Load only your own trusted
environment file; `source` executes shell syntax. Avoid shell tracing (`set -x`).

```bash
set -a
source .env
set +a
SSL_CERT_FILE=/etc/ssl/cert.pem python3 -B scripts/probe_openaq.py --output .local/inventory_repeat.json
SSL_CERT_FILE=/etc/ssl/cert.pem python3 -B scripts/probe_openaq.py --output .local/metadata_repeat.json --license-id 41 --license-id 33 --sensor-id 11357424 --sensor-id 14581375 --sensor-id 21632 --sensor-id 13502151
SSL_CERT_FILE=/etc/ssl/cert.pem python3 -B scripts/probe_openaq.py --output .local/sample_repeat.json --sensor-id 11357424 --sensor-id 14581375 --from-utc 2026-06-08T00:00:00Z --to-utc 2026-09-06T00:00:00Z
python3 -B scripts/audit_openaq.py --inventory .local/inventory_repeat.json --metadata .local/metadata_repeat.json --samples .local/sample_repeat.json --output docs/research/evidence/openaq_repeat.json
```

The certificate override is specific to the inspected macOS environment; omit it
where Python's default trust store works. In a fresh clone, create an ignored
local staging directory before running probes. The scripts refuse to overwrite
files or create missing parent directories.

Full session captures remain in `.local/openaq_*_2026-09-07.json`. The public
[qualification extract](evidence/openaq_qualification_2026-09-07.json) contains
selected licensed metadata, the first 24 enclosed hours per selected sensor,
audit counts and request hashes, not every raw measurement. The auditor verifies
local raw-body hashes, parsed copies and paginated sample consistency before
writing an extract. A fresh API query can reflect upstream revisions, so keep
dated captures for exact reproducibility.

The original Phase 1 suite passed 21 tests. Run the current offline suite,
including Phase 2 checks after [project setup](../database.md), with:

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
```

With the key exported as above, the suite also checks that no public/non-ignored
file contains it, without printing the key. Without the variable, that one check
is skipped; the other tests do not need authentication or network access.

## Next Phase Constraints

Proceed with PostgreSQL ingestion for the two selected measured locations and
separate CAMS context for all three cities. Use weather at sensor coordinates
for measured-data joins, not the city-centre probe coordinates. Keep unavailable
Da Nang measurements visibly unavailable.

Capture real ingestion and forecast-vintage availability from the start. Latest
sensor values were fresh when requested, but a single freshness check cannot
establish a latency distribution or uptime. Models, EDA, significance and
environmental associations remain uncomputed; the Phase 1 result is a defensible
source choice and a reproducible coverage audit.
