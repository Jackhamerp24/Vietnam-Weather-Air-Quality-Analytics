# Phase 1: Environment And API Verification

Research date: **2026-09-07 in Vietnam**, corresponding to 2026-09-06 UTC for the
captured requests. The original repository contained only `.git/`, with no
commits or project files. No existing application changes required preservation.

## Environment

| Check | Observed Result | Consequence |
| --- | --- | --- |
| Platform | macOS, arm64 | Prefer portable Python; no machine-specific runtime required |
| Python | 3.13.7; pip 25.2 | Standard-library research probe runs without dependency installation |
| PostgreSQL | `psql` 15.17; `pg_isready` reports `/tmp:5432` accepting connections | A server responds; database identity, permissions and application connectivity remain unverified |
| Docker | Not found on PATH | Do not assume Docker-based verification is possible yet |
| uv | Not found on PATH | No package manager installed or configuration changed in this phase |
| Default Python TLS | Default CA file unavailable; live probe failed certificate verification | Failure preserved; existing `/etc/ssl/cert.pem` enabled a verified-TLS retry |

No databases were listed, created, queried or modified. No API keys were searched
for or created. After the initial keyless research, the user supplied and
authorized an OpenAQ key; it was sent only to OpenAQ in the authentication header.
No billing plans were activated. The environment inspection checked tooling and
readiness rather than assuming all dependencies
of a future application exist.

## Evidence Path

Use official pricing and legal terms to establish allowable access. Use product
documentation to establish endpoint/variable contracts. Then use a bounded live
probe to check three-city responses and a small historical slice. These answer
different questions; none alone establishes scientific fitness.

The source comparison covers Open-Meteo, OpenAQ, WAQI, WeatherAPI, OpenWeather,
direct CAMS ADS and the CEM/Envisoft portal. Unknowns remain labeled in
[data_sources.md](../data_sources.md). Third-party tutorials and remembered
pricing were not used to override official sources.

## Recorded Probes

The repeatable tool is [scripts/probe_sources.py](../../scripts/probe_sources.py).
It saves exact UTF-8 response bodies, hashes, parsed copies, request/retrieval
timestamps and contract-check summaries. It stops on failure and does not
overwrite earlier evidence. These are real responses, not generated fixtures.

| Capture | Outcome |
| --- | --- |
| [Default-CA attempt](evidence/open_meteo_2026-09-07.json) | Failed on the first geocoding request with certificate verification error; no coverage assertions |
| [System-CA attempt](evidence/open_meteo_2026-09-07_system_ca.json) | Passed: eight requests, four multi-location data probes and a negative-coordinate test |

Successful command:

```bash
SSL_CERT_FILE=/etc/ssl/cert.pem python3 -B scripts/probe_sources.py --output docs/research/evidence/open_meteo_2026-09-07_system_ca.json
```

That filename already exists. For repetition, choose a new evidence filename.
The CA environment override applied to this process only. TLS certificate
verification remained enabled; no global trust settings changed.

### Reviewed Location Matches

| City | GeoNames ID | Requested Latitude | Requested Longitude | Provider Timezone |
| --- | --- | --- | --- | --- |
| Hanoi | 1581130 | 21.02450 | 105.84117 | Asia/Bangkok |
| Ho Chi Minh City | 1566083 | 10.82302 | 106.62965 | Asia/Ho_Chi_Minh |
| Da Nang | 1583992 | 16.06778 | 108.22083 | Asia/Ho_Chi_Minh |

All selected matches have country `VN`. These identify representative named
places, not pollution stations or administrative-area averages. Future scientific
joins must use qualified station coordinates.

Hanoi search also returned a same-name record whose coordinates do not match its
administrative metadata. Da Nang search returned other similar names and an
airport. Selecting the first string match on every ingestion run is unsafe.
The probe checks the manually reviewed IDs; the application should persist
reviewed metadata and allow new locations through configuration/discovery.

For modern study dates, both returned timezone IDs use UTC+07:00. Retain the
provider's timezone value and use `Asia/Ho_Chi_Minh` as the explicitly selected
Vietnam display/feature timezone. Do not treat the two zones as globally
interchangeable over all historical dates. Ingestion timestamps remain UTC.

### Data Checks

| Request | Sample | Checks |
| --- | --- | --- |
| Geocoding x3 | Hanoi, HCMC, Da Nang | Reviewed IDs present, country VN |
| Weather forecast x1 | Three cities, six hourly entries each, current temperature | Eight requested hourly fields, expected units, UTC epoch hours, no missing sample values |
| Air quality x1 | Three cities, six hourly entries each, current PM2.5; `domains=cams_global` | Six pollutant concentrations plus US AQI; expected units and hourly shape |
| ERA5 archive x1 | Three cities, 2023-01-01 UTC, 24 hours each, `models=era5` | Eight weather variables, consistent array length and UTC hourly grid |
| AQ archive x1 | Three cities, 2023-01-01 UTC, 24 hours each | Same seven AQ fields, units and sample completeness |
| Invalid coordinate x1 | Latitude 91 | HTTP 400 and structured `error=true` |

Zero missing values in these samples is not an assertion about the rest of the
archive. Historical dates mark event/valid time, not when the project could have
known those values. A six-hour response starting at the current hour is not six
independent measured future observations.

Returned weather/AQ grid coordinates differ from requested coordinates; this is
documented provider behavior, not something to silently "correct". The response
metadata also showed weather `current.interval=900` versus AQ `3600`. Record
actual intervals instead of inheriting the weather page's generic assumptions.

### Other Live Investigations

- OpenAQ `GET https://api.openaq.org/v3/locations?iso=VN&limit=1` returned HTTP 401
  without a key. This verifies the authentication boundary, not station presence
  or absence. The user subsequently authorized a key, enabling authenticated
  discovery and a 90-day audit described in the next section.
- The documented WAQI Shanghai `token=demo` feed returned JSON. It demonstrated
  pollutant sub-indices, daily forecast arrays and mixed timestamp fields, not
  Vietnamese concentration history. One ozone forecast entry was dated 2025
  despite the current feed being in 2026. Its numeric `time.v` differed from its
  offset-aware ISO timestamp under ordinary Unix interpretation. Both need
  freshness/consistency checks if that provider is adopted. No response values
  or raw archived WAQI payload are distributed here.
- The public WAQI Vietnam page listed Hanoi and Da Nang; this is website-level
  coverage evidence only. The CEM portal exposed a VN_AQI section without a
  verified public collection API contract.
- OpenWeather HTML pricing/docs exposed little rendered content. Its official
  sitemap identified `.md` versions, which supplied the actual product tables.
  An attempted CAMS licence URL returned 404; current dataset catalogues and ADS
  terms supplied the relevant licence evidence instead.

These browser/research-tool observations are summarized session evidence, not
machine-replayable captured datasets. Captured JSON covers the Open-Meteo probe
and the following OpenAQ qualification, not the other providers' live APIs.

## Authenticated OpenAQ Follow-Up

The user authorized a project key during Phase 1. It is stored only in the ignored
local `.env` file with mode 600 and was not included in response captures or logs.
The authenticated probe blocks redirects and keeps response hashes, rate headers
and UTC retrieval times. It does not activate subscriptions or modify OpenAQ data.

Fifteen authenticated GET requests completed: one Vietnam inventory request, six
licence/sensor metadata requests, and eight requests for two sensors' metadata
and paginated hourly history. Requests ran sequentially with three-second delays;
no retry or quota errors occurred.

The 59-location inventory yielded two fresh AirGradient PM2.5 candidates with
CC BY 4.0 metadata. A common 90-day window returned 2,154/2,160 hours for CMT8 and
2,037/2,160 for OceanPark. No returned location lay within 25 km of Da Nang's
study coordinate. Read the [qualification report](openaq_qualification.md) for
licences, sensor limitations, gaps, metadata anomalies and reproduction commands.

## Verification

Offline command:

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
```

The original Phase 1 run used the standard-library Python interpreter and passed
21 tests. The current command above includes Phase 2 package/configuration tests
and requires the [project setup](../database.md). Phase 1 tests cover contract
parsing, UTC conversion, micro-sign unit alias,
incorrect units, array mismatch, missing/nonnumeric/nonfinite values, duplicate
or gapped/reversed timestamps, timezone offset, and coordinate/location-count
validation, OpenAQ interval-boundary/duplicate completeness arithmetic, separate
presence-versus-validity counts, credential-safe redirects, evidence hashes,
documentation links, whitespace, Git ignore rules and exact credential exclusion.
The exact-key exclusion check requires `OPENAQ_API_KEY` exported; otherwise it
is skipped. The final session run exported it without displaying the credential.
Test inputs are
explicitly synthetic edge cases, never portfolio study data or claimed live API responses.

The probes and bounded coverage audit are intentionally narrower than production
ingestion. They have no scheduler, retries, database persistence, database-level
deduplication or extreme-value adjudication. Those belong to Phases 3 and 4 and
require their own tests.

## Gate And Follow-Up

Research supports architecture planning with **two sampled measured sources**,
not a claim of complete empirical coverage. The next actions are:

1. Rotate the key shared in chat and maintain credentials in ignored environment
   files or deployment secrets, not public artifacts. No rotation is performed
   automatically because that could disrupt other authorized uses.
2. Continue scientific qualification of the selected sensors' siting, calibration
   and reporting latency. Investigate additional licensed sources for Da Nang
   and longer overlapping records without merging incompatible instruments.
3. Design the PostgreSQL schema and ingestion contracts around source type,
   measurement intervals, forecast vintages, revisions, units and availability.
4. Implement and verify real persistence before beginning EDA or model training.

The available runtime rejected delegated research and Oracle reviewer agent types,
so this phase used direct official-source research and automated checks. No
independent review or Oracle approval is claimed. See
[Decision 0001](../decisions/0001-data-sources.md) for scientific risks
that remain explicit gates for later implementation.
