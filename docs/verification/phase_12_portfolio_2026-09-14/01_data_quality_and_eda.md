# Walkthrough 01: Data quality, coverage gaps and descriptive EDA

Command: `python3 -B reports/portfolio/walkthrough_01_data_quality_and_eda.py --output-dir <output-dir>`

Window: 2026-06-08T00:00:00Z to 2026-09-06T00:00:00Z (cutoff 2026-09-06T20:59:00.669630Z); schema `0003_response_integrity`.

Everything below is a descriptive quality or EDA statement. No significance, causal or forecast-skill claim is made.

## Sensor coverage (Phase 4)

| Sensor | Location | Accepted / expected | Completeness | Longest gap |
| --- | --- | --- | --- | --- |
| CMT8 | cmt8 | 2154 / 2160 | 99.7222% | 3 h |
| OceanPark | oceanpark | 2037 / 2160 | 94.3056% | 119 h |

The two sensors share 2035 accepted sensor-hours. They are site-level records, not city averages. Missing periods stay visible: CMT8 has 3 missing run(s) with a longest gap of 3 h; OceanPark has 3 missing run(s) with a longest gap of 119 h.

## Descriptive hourly PM2.5 (Phase 5, accepted hours only)

| Sensor | n | Mean | Median | IQR (p25-p75) | Maximum |
| --- | --- | --- | --- | --- | --- |
| CMT8 | 2154 | 22.7076 | 20.9 | 15.2-28.9 | 82.2 |
| OceanPark | 2037 | 32.0131 | 31.1 | 19.8-41.8 | 149 |

| Sensor | Lag-1 PM2.5 r (n) | Wind-speed r (n) | Complete ERA5 hours |
| --- | --- | --- | --- |
| CMT8 | 0.810071 (2150) | -0.338661 | 2033 |
| OceanPark | 0.869412 (2033) | -0.310363 | 1916 |

Lag and weather values are descriptive pairwise statistics over one 90-day window. They do not adjust for season, time of day, autocorrelation or sensor bias.

## Source separation and missing-data policy

- Measured: OpenAQ PM2.5 at CMT8 and OceanPark (CC BY 4.0 credits in the artifact metadata).
- Reanalysis: ERA5 weather is retrospective context, not what a forecaster had at the historical time.
- Forecast: Open-Meteo forecast snapshots stay in provenance metadata and do not enter the retrospective weather table (5 capture groups recorded).
- Modeled: CAMS remains a separate modeled stream, including modeled-only Da Nang.
- Missing hours remain null and unplotted; no interpolation and no substitution with modeled values.

## Quality audit findings

- Selected measured hours: 4191 provisionally accepted.
- Value-changing revision transitions: 0.
- Interval errors: 0.
- Visible quarantines: 1; failed runs at cutoff: 1.

## Labels

- Coverage and EDA outputs: descriptive_only.
- Lag and weather associations: exploratory pairwise statistics.

Evidence: Phase 4 artifact `c1570b8679b4385d693bb08ab960e4d0564c8315d52e99cf5231d13ce97b3713`; Phase 5 bundle `92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63`.
