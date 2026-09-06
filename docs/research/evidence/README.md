# Live Research Evidence

The Phase 1 probe writes real provider response bodies, parsed JSON, URLs, UTC
request/retrieval times, and SHA-256 hashes here. It refuses to overwrite a file.
The hash covers `body_utf8.encode("utf-8")`, not the formatted parsed JSON.

These small captures establish endpoint access and sampled response contracts.
They are not a historical database, measured ground truth, a coverage study, or
evidence of forecasting skill. `passed` refers to contract checks only. A failure
record retains the response rather than discarding it. The probe stops on the
first failure; unattempted probes do not count as verified.

## Attribution

Weather and air-quality API access: [Open-Meteo](https://open-meteo.com/).
Location metadata: [GeoNames](https://www.geonames.org/).
Historical weather: [ERA5 / Copernicus C3S](https://doi.org/10.24381/cds.adbb2d47).
Modeled air quality: [CAMS global atmospheric composition forecasts](https://doi.org/10.24381/04a0b097).
API data: [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

Contains Copernicus Atmosphere Monitoring Service information retrieved in 2026.
Raw Open-Meteo response bodies remain unchanged; the probe adds parsed copies and summaries.
Credit the appropriate original weather model when using a pinned-model dataset
beyond these small `best_match` contract probes. Nothing here implies provider
endorsement. Do not add archived data from providers that forbid redistribution.

## OpenAQ Qualification

`openaq_qualification_2026-09-07.json` contains selected AirGradient location
metadata, derived 90-day completeness counts, the first 24 enclosed hourly rows
per sensor, and provenance hashes. It is an extract, **not** the full raw OpenAQ
response archive. Original credential-free captures remain in ignored `.local/`
because other providers in the inventory have unresolved licence metadata and
the complete qualification responses are unnecessarily large for Git.

Credit [OpenAQ](https://openaq.org/) for access,
[AirGradient](https://www.airgradient.com/) as provider, Thomas Versteeg for CMT8,
and AirGradient for OceanPark. Their location licence records specify
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) from 2023-07-15 with no
end date at retrieval. Selection, excerpting and completeness recalculation are
the modifications. These non-reference sensor measurements have not been
independently calibrated by this project and do not represent city-wide means.

The offline auditor verifies raw-response hashes and extracted rows against the
local captures. Re-fetching upstream history may give revised values; a hash is
evidence of the captured version, not a promise of immutable upstream data.
