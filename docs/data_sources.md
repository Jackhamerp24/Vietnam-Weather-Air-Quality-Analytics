# Data Sources And API Research

Checked **2026-09-07 Asia/Ho_Chi_Minh** (requests began on 2026-09-06 UTC).
Provider claims below come from official pages linked in each section. Live
evidence covers only the endpoints and samples recorded in
[the Phase 1 report](research/phase_1.md). No paid subscriptions or accounts were
created. Recheck terms before deployment and at least quarterly thereafter.

`Documented` means the provider describes the capability. `Probed` means a real
request returned the stated result. `Unverified` means the project must not depend
on the claim yet. Price and access rights do not guarantee data quality.

## Decision Summary

| Candidate | Free Access And Limits | Historical Data | Decision |
| --- | --- | --- | --- |
| Open-Meteo | No key for non-commercial use; 600/min, 5,000/hour, 10,000/day, 300,000/month published ceilings | Weather reanalysis; archived modeled AQ | Select weather and a separately labeled modeled-AQ stream |
| OpenAQ v3 | Free key; 60/min and 2,000/hour | Available station history, variable by sensor; official public S3 archive | Select two licensed AirGradient sensor locations for MVP; retain instrument/coverage caveats |
| OpenWeather Free | Free key; 60/min, 1,000,000/month | AQ from 2020-11-27; ordinary free weather history excluded | Reserve, not needed for first pipeline |
| WeatherAPI Free | Free key; 100,000/month; numeric burst limit unverified | Past 1 day of weather; no free AQ history | Reject permanent current/forecast archival under present terms |
| WAQI | Free token; published default 1,000 requests/second, subject to quotas | Separate platform, primarily daily pollutant AQIs | Reject historical pipeline without separate permission |
| CAMS ADS | Free datasets after account and licence acceptance; queued retrieval limits | Global forecast archive from 2015; EAC4 from 2003 | Optional direct archive, not independent station truth |
| Vietnam CEM / Envisoft | Public portal; public API pricing and access unverified | Public historical API not established | Investigate permission and documentation; do not scrape |

### Request Budget

For three locations and two Open-Meteo products polled hourly, an upper planning
estimate using separate requests is `3 * 2 * 24 = 144 HTTP requests/day`, or 4,464
in a 31-day month, before retries and backfills. Up to ten variables and short
windows fit the provider's basic call calculation. Multi-location requests,
additional variables, models, and periods longer than two weeks can count as
multiple or fractional calls. Batching reduces HTTP overhead, not necessarily
charged call units. Treat quota as shared across this deployment's traffic.

Hourly polling is a starting operational cadence, not evidence of hourly upstream
updates. Slow or discontinue unneeded feeds. Backfill in small resumable windows
with its own budget; honour HTTP 429 and documented reset/retry semantics. A
three-city request that succeeds is not permission to fetch the world repeatedly.

## Open-Meteo

Official references: [pricing][om-price], [terms][om-terms], [licence][om-licence],
[weather][om-weather], [historical weather][om-history], [air quality][om-aq],
[geocoding][om-geo], [historical forecasts][om-hist-forecast],
[single runs][om-single], [model availability][om-updates].

### Access And Rights

- Free hosted APIs cost zero for non-commercial use, require no key, and publish
  600 calls/minute, 5,000/hour, 10,000/day and 300,000/month limits. The terms say
  to remain below the limits. Free service has no uptime guarantee.
- The free plan includes historical and AQ APIs. Paid Standard does **not**
  include several historical products; Professional or higher does. Do not infer
  paid entitlements from free availability. No paid price is needed for selection.
- Periodic research collection and storage fit the documented non-commercial
  API use and CC BY 4.0 data rights, subject to limits and attribution.
- Attribute Open-Meteo next to displays, link CC BY 4.0, identify changes, and
  credit the relevant upstream dataset, including CAMS, ERA5, and GeoNames.
- Hosted free access is non-commercial even though the data licence permits
  commercial reuse. An ad-free educational portfolio is the intended use, not a
  blanket legal conclusion about promotional or employer-facing deployments.
  Reassess before monetization, advertising, or commercial promotional use.

### Capabilities And Coverage

| Product | Documented Capability | Resolution And Provenance | Vietnam Evidence |
| --- | --- | --- | --- |
| Weather `/v1/forecast` | Current model conditions; default 7 days, up to 16 days forecast; `past_days` 0-92 | Hourly output; weather model depends on chosen product/location; `best_match` can change models | Probed Hanoi, HCMC, Da Nang, eight hourly variables and current temperature |
| Archive `/v1/archive` | ERA5 from 1940, ERA5-Land from 1950, ECMWF IFS from 2017 | ERA5 hourly 0.25 degrees, ERA5-Land hourly 0.1 degrees, IFS about 9 km; reanalysis/assembled model fields | Pinned `models=era5`, 2023-01-01, eight variables and 24 times at each city |
| Historical forecast `/v1/forecast` on its own host | Model-dependent archives, broadly from 2021/2022 with some earlier products | First hours from successive runs stitched into a series; not a complete fixed-origin forecast archive | Documented global applicability, not live-probed |
| Single runs `/v1/forecast` on its own host | `run` specifies initialization; ECMWF IFS HRES from 2024-03-14, most other models from 2026-04-02 | Preserves run structure; older IFS coverage includes material described as hindcasts | Documented global applicability; historical operational availability not established |
| AQ `/v1/air-quality` | Current estimates; default 5 days, parameter accepts up to 7; global archive documented from August 2022 | **CAMS Global**, 0.4-degree grid, about 45 km; see cadence qualification below | Probed current, six-hour output, six pollutants plus US AQI, and 2023-01-01 history for all three cities |
| Geocoding `/v1/search` | Country-filtered search, stable GeoNames IDs; `/v1/get` resolves IDs | Named-place metadata, not station or city-boundary metadata | All three reviewed IDs returned; duplicate-name and timezone anomalies recorded |

Weather variables include `temperature_2m`, `apparent_temperature`,
`relative_humidity_2m`, `precipitation`, `wind_speed_10m`, `wind_direction_10m`,
`surface_pressure`, `cloud_cover`, and `shortwave_radiation`. Select Celsius,
metres/second, and millimetres explicitly; pressure is hPa, humidity/cloud cover
percent, direction degrees, and hourly radiation W/m2. Apparent temperature is
documented but was not part of the eight-variable historical probe.

AQ concentration fields are `pm2_5`, `pm10`, `nitrogen_dioxide`, `sulphur_dioxide`,
`carbon_monoxide`, and `ozone`, in micrograms/m3. `us_aqi` and `european_aqi` are
derived index systems, not Vietnamese VN_AQI or direct concentration values.
Pollutant-specific averaging windows and breakpoint versions matter. European
pollen/ammonia availability and the headline 11 km European resolution must not
be applied to Vietnam.

### Cadence Qualification

The Open-Meteo AQ overview labels CAMS Global as 3-hourly and 0.4 degrees; the
API returns hourly arrays. The [CAMS upstream documentation][cams-detail]
distinguishes hourly surface fields from 3-hourly multi-level fields, with some
additional hourly multi-level output introduced in 2026.

Open-Meteo's public [domain definitions][om-domain-code] classify PM2.5/PM10 as
surface fields and the gases as multi-level fields. Its [importer][om-download-code]
downloads surface PM hourly and skips intermediate multi-level hours. Its reader
supports interpolation. These files were inspected at revisions linked below;
they do not establish the deployed backend version or every historical period.
Therefore **do not label all PM2.5 values as interpolated from three-hour data or
claim every hourly gas value is an independent native hourly value**. Preserve
product/variable/cadence provenance and investigate differences before inference.

CAMS Global forecasts extend five days and update twice daily. A seven-day API
parameter does not guarantee seven complete days for every variable. Nulls and
truncated horizons need validation. The live `current.interval` was 900 seconds
for weather and 3,600 for AQ, despite generic AQ page wording about 15-minute
current data. Neither interval establishes a new station measurement.

### Time, Stability, And Leakage

- Default timezone is GMT. ISO timestamps can omit offsets; timezone parameters
  alter their interpretation and local-day boundaries. Request `timezone=UTC`
  and `timeformat=unixtime` for ingestion. Epoch seconds remain UTC.
- Most hourly fields are instantaneous. Precipitation is the preceding-hour sum;
  radiation is the preceding-hour mean. Store interval semantics explicitly.
- `generationtime_ms` describes response-generation performance, **not** forecast
  initialization, publication, or observation time. Record retrieval separately.
- Returned coordinates identify the selected grid cell; keep both request and
  response coordinates. Do not overwrite station coordinates with grid positions.
- ERA5/ERA5-Land have a documented roughly five-day delay. Their values cannot
  serve as contemporaneously available historical features in an operational
  forecast backtest. Future valid-time forecasts are legitimate inputs only when
  their run was available before the prediction origin.
- Model initialization precedes publication. Single Runs documentation gives
  computation delays, and the availability page notes eventual consistency and
  recommends ten extra minutes after availability for distributed servers.
- The `/v1` docs promise no newly required parameters, but model choice, upgrades,
  revisions, and service availability can change. Pin explicit weather models
  for research and record snapshots. Do not overwrite forecast vintages.

## OpenAQ v3

Official references: [overview][oa-about], [FAQ][oa-faq], [API key][oa-key],
[limits][oa-limits], [terms][oa-terms], [locations][oa-locations],
[hourly endpoint][oa-hours], [time handling][oa-time], [latest][oa-latest],
[pagination][oa-pages], [licences][oa-licences], [S3 setup][oa-aws],
[S3 archive behavior][oa-aws-about].

| Dimension | Verified Documentation And Remaining Limits |
| --- | --- |
| Price and quotas | General use free: 60 requests/minute and 2,000/hour per API key. Higher limits by custom agreement. No daily/monthly free ceiling found in the cited limit policy; do not invent one. |
| Authentication | Register with a valid name/email; send `X-API-Key`. One key per individual; no account rotation to evade limits. The user supplied and authorized a key after initial keyless research; authenticated calls succeeded. |
| Historical data | Original measurements and precomputed hourly means by sensor; archive start/end varies by sensor. No universal multi-year completeness promise. |
| Current data | Latest available station records, conditional on upstream reporting. `latest` is the greatest event time, not the last ingested record. |
| Forecast | No pollutant forecast endpoint in the reviewed v3 resource set. |
| AQ variables | PM2.5, PM10, NO2, SO2, CO, O3, black carbon and others where the station measures them. Concentrations, not AQIs. Units are parameter/sensor-specific, including micrograms/m3 and ppm. |
| Weather variables | Associated temperature and relative humidity at some locations; no complete wind/rain/pressure weather product. |
| Vietnam | Authenticated `iso=VN` discovery returned 59 locations. CMT8 (HCMC) and OceanPark (Hanoi area) have fresh PM2.5 sensor metadata, CC BY 4.0 licences and a verified 90-day sample. No inventory location within 25 km of the Da Nang point. This is OpenAQ inventory coverage, not proof that no physical stations exist there. |
| Resolution | Stationary ground-level data; ingestion criteria accept frequencies between ten minutes and 24 hours. `/hours` provides precomputed hourly means. A daily-only sensor is not made hourly by choosing that endpoint. |
| Timestamps | ISO 8601 with UTC/local objects and IANA location timezone. Datetimes follow exclusive period-ending semantics; 03:00 represents 02:00-02:59. Timezone-less query timestamps default to the station's local timezone. |
| Stability | Use v3. v1/v2 retired on 2025-01-31 and return 410. Hosted API and upstream feeds have no continuity or accuracy guarantee. |
| Attribution/licensing | Credit OpenAQ **and** original providers; inspect licence URLs, attribution, and effective date ranges per location. No blanket CC BY claim for every record. |
| Automation/storage | Registered API use and officially sanctioned export/S3 downloads support analysis and storage under source terms. Do not scrape Explorer, duplicate the core hosted service, exceed limits, or continue requests when the data are no longer needed. |

### Discovery And Ingestion Implications

The following documented query succeeded with the authorized project key:

```text
GET https://api.openaq.org/v3/locations?iso=VN&limit=1000&page=1
Header: X-API-Key: <private project key>
```

The placeholder deliberately omits the credential. The response returned 59
locations in one page. Subsequent metadata/licence requests and a bounded
90-day audit identified two viable MVP feeds. See the
[authenticated qualification](research/openaq_qualification.md) for sensor IDs,
counts, attribution, incomplete periods and limitations. Repeat discovery when
adding locations using the [selection procedure](decisions/0001-data-sources.md).
Use `datetime_from` and `datetime_to` on `/v3/sensors/{sensors_id}/hours` with
explicit UTC offsets. Documentation prose uses some inconsistent date parameter
names; the linked endpoint reference specifies these snake_case names.

Radius search is capped at 25,000 metres. Use country/bounding-box discovery for
wider urban areas rather than inventing a 50 km radius parameter. `isMonitor`
describes reference-monitor status, **not current activity**. Evaluate sensor
freshness from its measurement history; a location's last timestamp can belong
to a different pollutant. Retain `flagInfo`, interval and coverage metadata.

Use overlapping time-range fetches, pagination, and periodic historical
reconciliation. Polling `latest` alone misses late/out-of-order arrivals. Follow
429 responses and rate headers; the docs describe `x-ratelimit-reset` as a
timestamp but also give a seconds-to-reset example. The authenticated captures
returned small values such as 12 and 9 as requests progressed, consistent with
seconds until reset rather than Unix epoch. Confirm reset behavior under the
production client and use bounded conservative backoff.

Sensor-level coverage metadata in the live response contained percentages far
above 100 and `expectedCount=1` for a multi-year series. Recompute completeness
from explicit measurement intervals rather than using those summary fields. The
hourly samples themselves had interpretable per-period coverage. Retain anomalies
as quality findings rather than silently correcting the raw response.

The official `openaq-data-archive` S3 bucket supports credential-free
`--no-sign-request` downloads for known location IDs. Files arrive **72 hours
after the local end of day** and can be patched later. It is useful for historical
backfill, not live forecasts. Its access route does not remove provider-licence
obligations. No Vietnam objects were downloaded or guessed in this phase. Cloud
query/compute services such as Athena can incur charges even for public data.

## OpenWeather

Official references: [pricing][ow-price], [detailed pricing/licensing][ow-full],
[FAQ][ow-faq], [AQ endpoint documentation][ow-aq], [current weather][ow-current],
[sale terms][ow-terms]. Official `.md` versions expose content that the ordinary
HTML pages did not render in the research fetcher.

| Dimension | Verified Documentation And Remaining Limits |
| --- | --- |
| Ordinary Free | Permanent free plan: 60 calls/minute, 1,000,000/month. Includes Current Weather, five-day/three-hour forecast, Air Pollution and Geocoding. Limits apply across account keys. |
| Authentication | Account, verified email, `appid` query parameter. Key activation can take up to two hours. No authenticated probe or plan activation performed. Redact query keys in future logs. |
| One Call | Current offer is **4.0**, with 1,000 free calls/day then GBP 0.0012/call, through a separate billing subscription. FAQ default cap is 2,000/day, above the free allowance. 3.0 is labeled deprecated. Not selected; do not activate automatically. |
| Weather history | Excluded from ordinary Free. One Call and paid historical products differ; student access is advertised but eligibility/activation/continuation must be confirmed. Do not rely on a student offer for permanent operation. |
| AQ history/current/forecast | `/data/2.5/air_pollution`, `/forecast`, `/history`; history documented from 2020-11-27, four-day forecast with hourly granularity. Air Pollution is included in Free; successful history retrieval still needs a key. |
| Pollutants | PM2.5, PM10, CO, NO, NO2, O3, SO2, NH3 in micrograms/m3; proprietary `main.aqi` categories 1-5, not US AQI 0-500 or VN_AQI. |
| Weather | Temperature/feels-like, humidity, wind/direction/gusts, pressure, clouds, precipitation where returned, visibility. Metric option gives Celsius and m/s; pressure hPa. Solar irradiance is a separate product, not an assumed Free field. |
| Vietnam | Global coordinate coverage includes all three study points by documentation. City-specific real responses and completeness not tested without a key. |
| Resolution/provenance | Free weather forecast three-hourly; AQ forecast hourly; exact AQ historical cadence/spatial grid and independent station provenance need qualification. Weather combines models, stations, radar and satellites. Coordinate estimates do not establish measured PM2.5 ground truth. |
| Timestamp | Unix UTC `dt`; current weather defines it as calculation time, not station ingestion time. Weather also supplies a UTC offset. AQ history bounds are Unix UTC. Preserve retrieval time separately. |
| Stability | Free advertises 95% availability, no SLA, current-version support, weather updates every two hours. That cadence is not proof of pollutant update timing. Product migrations require monitoring. |
| Licensing/storage | Self-service data/database under ODbL; visible attribution required. Sale terms also refer to CC BY-SA 4.0 products/services. Publishing adapted reusable databases can trigger share-alike obligations. Keep provider data separate and review obligations before releasing joined data. |
| Periodic collection | API use and stored-data applications are documented under plan/licence conditions. Respect quotas and preserve attribution; do not infer unlimited redistribution or a right to ignore share-alike. |

Reserve rather than primary: the free AQ history is useful, but it adds account
setup and a second data licence without resolving the measured-target problem.
If adopted later, verify model origin, aggregation, update timing and licence
compatibility first. It is not an independent measurement benchmark simply
because its vendor differs from Open-Meteo.

## WeatherAPI.com

Official references: [pricing][wa-price], [API docs][wa-docs], [API terms][wa-terms],
[machine-readable guide][wa-guide]. Pricing controls entitlements; the generic
history documentation describes capabilities that the free plan does not include.

| Dimension | Verified Documentation And Remaining Limits |
| --- | --- |
| Price/limits | Free USD 0, 100,000 calls/month, no credit card stated. Free over-quota access stops until reset. Terms mention a per-minute burst limit, but a numeric value was not found on pricing; **unknown**, not unlimited. |
| Authentication | Account and `key` query parameter on `https://api.weatherapi.com/v1`. No authenticated probe. |
| History | Free weather past 1 day. Deeper archive exists from 2010 for entitled plans. Provider FAQ says historical weather is archived **forecast** data, not actuals. AQ history from 2021-03-01 is Enterprise, not Free. |
| Current/forecast | Realtime weather and three-day weather forecast on Free. AQ is labeled **Limited**; exact free fields/horizon must be confirmed. General docs describe current and three-day AQ conditional on plan. |
| Variables | Weather temperature/feels-like, humidity, pressure, wind/direction, precipitation, cloud, UV and visibility. AQ PM2.5/PM10, CO, O3, NO2, SO2 micrograms/m3; US-EPA 1-6 categories and UK DEFRA index. Solar radiation excluded from Free. |
| Vietnam | Worldwide coordinate weather coverage documented; Hanoi/HCMC/Da Nang responses and free AQ coverage unverified without a key. |
| Resolution | Daily/hourly Free output. Current weather station-based per FAQ, updated 10-15 minutes; forecast updated 4-6 hours per pricing FAQ. SLA text gives other best-effort cadences; do not conflate them. No verified AQ spatial resolution/station lineage. |
| Timezone | Location `tz_id`, localtime and epoch; current `last_updated`/`last_updated_epoch`; hourly `time`/`time_epoch`. Text timestamps are local. Docs confusingly call epoch fields local Unix time; verify epoch/local consistency before use. |
| Stability | Free pricing lists 95.5% uptime but no SLA. API terms describe 12-month deprecation notice and six-month transition. Track changelog and actual schema changes. |
| Licensing | Proprietary limited licence. Free use requires credit by name/logo under terms, despite pricing saying a backlink is appreciated. One application/service per subscription; no sale of weather data. End-user disclaimer required. |
| Automated retention | Collection within plan is allowed, but API terms cap current-condition caching at **60 minutes**, forecasts at **24 hours**, and allow historical caching without a time cap only within the subscription term. Do not assume permanent archival of periodic current/forecast responses is allowed. |

Reject for the required persistent current/forecast archive unless the provider
grants written permission. Historical-only collection within terms would still
not provide free AQ history and would not establish measured weather actuals.

## WAQI / World Air Quality Index

Official references: [API and terms][wq-api], [historical platform][wq-history],
[Vietnam coverage page][wq-vietnam], [official demo code][wq-demo].

| Dimension | Verified Documentation And Remaining Limits |
| --- | --- |
| Price/limits/auth | API described as free with valid token and quotas; published default 1,000 requests/second. No separate daily/monthly ceiling found. Obtain own token; never design to saturate the published ceiling. |
| Current/forecast | Current station/city AQI, geolocation, map bounds, search, attribution and selected weather. AQ forecast described as 3-8 days, variable by pollutant/station. Weather forecast on API page remains listed as future functionality, not a verified entitlement. |
| History | Ordinary feed API does not establish historical concentration retrieval. Separate historical platform offers daily pollutant AQI data, broadly from about 2012; raw concentrations/hourly data require a detailed request. |
| AQ variables | PM2.5, PM10, NO2, CO, SO2, O3 individual pollutant **AQI sub-indices**, not raw micrograms/m3. Do not invert rounded/averaged indices into fabricated hourly concentration targets. |
| Weather | Demo lists temperature, wind, precipitation, humidity, dew point and pressure when present. Per-field units/averaging are not verified for Vietnam. |
| Vietnam | Public country page listed Hanoi and Da Nang during review. HCMC active feed and API-level coverage across all three remain unverified. A public listing does not prove fresh, complete station history. |
| Resolution | Station-based current reporting cadence varies; daily forecast min/mean/max appears in official demo response. No guaranteed city-wide sampling density, hourly archive or spatial grid. |
| Timestamps | Public Shanghai demo returned `time.s`, `time.tz`, `time.iso`, and `time.v`; prefer offset-aware ISO and check consistency. In that sample `time.v` did not agree with ISO as ordinary UTC epoch. No Vietnam time behavior verified. |
| Stability | Terms permit changes without notice and disclaim accuracy/continuity; data are unvalidated and revisable. |
| Attribution/rights | Credit WAQI and originating EPA. No sales or paid services; **no redistribution as cached or archived data**. Corporate public use requires agreement; nonprofit organizations must notify WAQI. |
| Periodic collection | Programmatic feeds are allowed under token/quota/app rules. That does not grant the archival redistribution needed by an open historical portfolio. Separate historical-platform terms also restrict redistribution. |

A single documented `token=demo` Shanghai GET verified response semantics only;
no payload is redistributed in this repository and it says nothing about Vietnam
coverage. Reject the historical pipeline role; linking to official current pages
or seeking a specific research agreement could be separate later options.

## Direct CAMS / Copernicus ADS

Official references: [global forecasts][cams-forecast], [EAC4][cams-eac4],
[API setup][cams-api], [limits and workflow][cams-guide],
[upstream detailed documentation][cams-detail], [ADS terms][cams-terms].

| Dimension | Verified Documentation And Remaining Limits |
| --- | --- |
| Price/auth | Data free under dataset licences. Account, personal access token and manual licence acceptance required. `cdsapi` uses `https://ads.atmosphere.copernicus.eu/api`. No account or retrieval performed. |
| Limits | Queue/concurrency/field/volume limits can change with workload. Published table lists 10,000 fields/request for global forecasts, 100,000 for EAC4, 175 GB GRIB / 30 GB netCDF volume limits. The table itself says last reviewed 2024-10-02; reconfirm rather than treating it as a current throughput guarantee. No fixed free calls/minute verified. |
| History/current/forecast | Global composition forecasts from 2015 to present, five-day forecasts at 00/12 UTC. Analyses also exist but are model-assimilated products. EAC4 catalogue currently spans 2003-2025, twice-yearly updates with 4-6 month delay; it is not live data or a forecast feed. |
| AQ | PM2.5/PM10 in kg/m3, reactive gases including CO, NO2, SO2, O3 often mass mixing ratios kg/kg, aerosols/column fields. Select correct level/quantity; a column integral is not ground-level concentration. No universal AQI product assumed. |
| Weather | Temperature/dew point K, wind u/v m/s, surface/sea-level pressure Pa, humidity at relevant levels, cloud fraction; forecast precipitation m and radiation J/m2 with accumulation semantics. Verify variable availability and vertical level per product. |
| Geography/resolution | Global coverage includes the three cities. Forecast native grid about 40 km, ADS regular 0.4-degree grid; hourly surface, three-hourly multi-level with selected 2026 changes. EAC4 0.75 degrees, three-hourly. No authenticated city extraction tested. |
| Time | UTC initialization plus lead time produces valid time. Retrieval/publication is later. Docs give 10:00/22:00 UTC availability for 00/12 runs while warning of ADS delivery delays. |
| Stability | ECMWF-supported archive; operational model changes about annually. EAC4 targets more consistent long-term analysis. ADS can queue/delay or discontinue access and does not guarantee fitness or uninterrupted availability. |
| Licensing/automation | Both catalogues label datasets CC-BY; preserve actual accepted licence/version, dataset citation, attribution and modifications. Programmatic scheduled downloads are an official access route. No claim of ECMWF/EU endorsement. |

Defer the direct adapter: it adds GRIB/netCDF handling and account workflow for
data already accessible more simply through Open-Meteo. It could later provide
explicit-run benchmarks, model-change investigations or longer climatology, but
cannot serve as independent station validation of another CAMS-derived series.

## Vietnam Government/Open Portals

The [CEM / Enviinfo portal][cem] exposes an hourly VN_AQI section and links to
environmental reporting and forecast services. Its public interface establishes
neither an unrestricted API nor permission to archive and redistribute data.

| Requirement | Research Outcome |
| --- | --- |
| Pricing, free tier, quotas, rate limits | No documented public collection contract established on the reviewed portal. All **unverified**. |
| Authentication and stable endpoint | Portal includes login/registration. No supported public observation API endpoint verified. Do not reverse-engineer internal authenticated services. |
| Current data | Public VN_AQI display exists; station response freshness and concentrations not verified. |
| Historical/forecast API | Portal links forecast information and reports; no programmatic entitlements/history ranges established. |
| AQ/weather variables and units | VN_AQI is named; raw PM2.5 and other pollutants/weather fields for bulk research not verified. |
| Vietnam cities and resolution | Vietnam monitoring remit; Hanoi/HCMC/Da Nang usable station inventories, cadence, intervals and spatial representativeness unverified. |
| Timezone/stability | No verified timestamp contract, revision policy or API SLA. |
| Licence/attribution/automation | Site footer says all rights reserved. No open-data licence or periodic archival permission established. Ask the data owner for supported access and written terms before selection. |

This is an unresolved candidate, **not a claim that no Vietnamese government API
exists**. A data agreement could materially strengthen the measured-data study.

## Cross-Source Rules

1. Keep measured concentrations, modeled concentrations, reanalysis, derived
   AQIs, provider forecasts, and project predictions distinct in storage and UI.
2. Choose API coordinates from reviewed location metadata, then use station
   coordinates for scientific joins. Save provider identifiers and metadata changes.
3. Validate units instead of guessing. `kg/m3 * 1e9` converts PM to micrograms/m3;
   gas mixing-ratio conversions additionally need a stated density convention.
4. Use time intervals and `available_at <= prediction_origin`, not merely a
   timestamp sort. Preserve backfilled/revised data as retrospectively retrieved.
5. Do not assume multiple vendors provide independent data. Shared upstream model
   output does not validate either vendor against measured pollution.
6. Publish actual coverage, bias and missingness results before assigning cities
   to the final study. Recheck provider licences before publishing datasets.

[om-price]: https://open-meteo.com/en/pricing
[om-terms]: https://open-meteo.com/en/terms
[om-licence]: https://open-meteo.com/en/licence
[om-weather]: https://open-meteo.com/en/docs
[om-history]: https://open-meteo.com/en/docs/historical-weather-api
[om-aq]: https://open-meteo.com/en/docs/air-quality-api
[om-geo]: https://open-meteo.com/en/docs/geocoding-api
[om-hist-forecast]: https://open-meteo.com/en/docs/historical-forecast-api
[om-single]: https://open-meteo.com/en/docs/single-runs-api
[om-updates]: https://open-meteo.com/en/docs/model-updates
[om-domain-code]: https://github.com/open-meteo/open-meteo/blob/a5d7f0d89b8a59e9abf46defd583132eca71566b/Sources/App/Cams/CamsDomain.swift
[om-download-code]: https://github.com/open-meteo/open-meteo/blob/e2afd8af19aaa4885ffeda05adfec512987d86ff/Sources/App/Cams/CamsDownload.swift
[oa-about]: https://docs.openaq.org/about/about
[oa-faq]: https://docs.openaq.org/about/faq
[oa-key]: https://docs.openaq.org/using-the-api/api-key
[oa-limits]: https://docs.openaq.org/using-the-api/rate-limits
[oa-terms]: https://docs.openaq.org/about/terms
[oa-locations]: https://docs.openaq.org/api/operations/locations_get_v3_locations_get
[oa-hours]: https://docs.openaq.org/api/operations/sensor_hourly_measurements_get_v3_sensors__sensors_id__hours_get
[oa-time]: https://docs.openaq.org/using-the-api/dates-datetimes
[oa-latest]: https://docs.openaq.org/resources/latest
[oa-pages]: https://docs.openaq.org/using-the-api/pagination
[oa-licences]: https://docs.openaq.org/resources/licenses
[oa-aws]: https://docs.openaq.org/aws/quick-start
[oa-aws-about]: https://docs.openaq.org/aws/about
[ow-price]: https://openweathermap.org/price.md
[ow-full]: https://openweathermap.org/full-price.md
[ow-faq]: https://openweathermap.org/faq.md
[ow-aq]: https://openweathermap.org/api/air-pollution.md
[ow-current]: https://openweathermap.org/api/current.md
[ow-terms]: https://openweather.co.uk/api/files/file/OpenWeather_T%26C_of_sale.pdf
[wa-price]: https://www.weatherapi.com/pricing.aspx
[wa-docs]: https://www.weatherapi.com/docs/
[wa-terms]: https://www.weatherapi.com/terms.aspx
[wa-guide]: https://www.weatherapi.com/llms.txt
[wq-api]: https://aqicn.org/api/
[wq-history]: https://aqicn.org/data-platform/
[wq-vietnam]: https://aqicn.org/country/vietnam/
[wq-demo]: https://aqicn.org/json-api/demo/waqi-api-demo.js
[cams-forecast]: https://ads.atmosphere.copernicus.eu/datasets/cams-global-atmospheric-composition-forecasts?tab=overview
[cams-eac4]: https://ads.atmosphere.copernicus.eu/datasets/cams-global-reanalysis-eac4?tab=overview
[cams-api]: https://ads.atmosphere.copernicus.eu/how-to-api
[cams-guide]: https://confluence.ecmwf.int/display/CKB/Atmosphere+Data+Store+%28ADS%29+documentation
[cams-detail]: https://confluence.ecmwf.int/spaces/CKB/pages/212454117/CAMS+Global+atmospheric+composition+forecast+data+documentation
[cams-terms]: https://ads.atmosphere.copernicus.eu/disclaimer-privacy
[cem]: https://enviinfo.cem.gov.vn/
