# Decision 0001: Sources And Scientific Scope

Date: 2026-09-07. Status: **accepted for a two-location measured-data MVP and
three-city modeled context; broader scientific qualification remains required**.

Evidence: [provider research](../data_sources.md) and
[live verification](../research/phase_1.md). This record does not claim that the
database, monitoring, statistics or ML pipeline already exists.

## Decision

Use Open-Meteo weather and ERA5 historical weather for the initial data pipeline.
Select OpenAQ v3 AirGradient PM2.5 sensors CMT8 (`11357424`, location `3276359`)
and OceanPark (`14581375`, location `6123215`) as complementary measured sources.
The authenticated audit verified CC BY 4.0 metadata, fresh sensor timestamps and
90-day completeness of 99.72% and 94.31%, respectively. These are non-reference
sensors with unspecified exact instrument models/calibration, so the study must
report sensor-level measurements rather than validated city-wide concentrations.
Retain Open-Meteo/CAMS Global air quality in a **separate modeled-data stream**, suitable
for geographic context and, after vintage validation, a provider forecast
benchmark. Do not substitute it for measured targets without changing the study
question and labeling the analysis as model-output research.

Prefer a narrow Python/PostgreSQL analytical system over a large service stack.
Source quality, defensible comparisons and reproducible analyses have priority
over implementing every possible provider adapter.

## Research Design

Preferred question: how are weather conditions associated with PM2.5 at monitored
Vietnamese locations, and does available weather information improve 6-hour and
24-hour predictions beyond recent pollutant history?

Six hours tests same-day warning potential and moves beyond a one-step persistence
exercise. Twenty-four hours tests next-day planning and the daily cycle. A one-hour
horizon is optional only if station reporting and availability lags support it.
These are candidates, not locked targets: measure reporting delays and autocorrelation
before finalizing horizons. Forecast origins must be actual decision times, not
the last measurement timestamp with its reporting delay ignored.

The forecasting target will specify whether it is an hourly mean **ending** at
`origin + horizon` or a mean over a future interval. Those are different problems.
Preserve interval bounds and choose one explicit definition before features.

### Measured-Data Qualification

1. Discover Vietnam locations using `iso=VN`, pagination and documented spatial
   filters. Keep provider location/sensor identifiers rather than guessed city IDs.
2. Review original-provider licences for the dates being requested. Save
   attribution, licence URLs/effective periods, instrument type and coordinates.
3. Inspect each PM2.5 sensor's actual first/last usable records, native interval,
   units, quality flags and recent freshness. A station's existence or
   `isMonitor=true` does not establish a live PM2.5 feed.
4. Download a bounded qualification window before a large backfill. Count unique
   expected intervals, missing hours/days, longest gaps, duplicates, revisions,
   anomalous values and overlaps between stations/providers.
5. For seasonal comparisons, seek at least a full annual cycle with overlap
   across compared cities; two or more years would strengthen repeatability.
   Shorter records can support narrower, explicitly dated analyses, not annual
   seasonality or national trend claims.
6. For preliminary modeling, aim for at least 90 days of usable hourly data and
   predeclare coverage thresholds before viewing model scores. Ninety days is a
   practical exploration gate, **not** proof of statistical power or deployment
   readiness. Report sample sizes after lagging, target alignment and purging.
7. Predeclare city/station inclusion and holdout periods after the coverage audit
   but before comparing model scores. Test sensitivity to missingness and station
   selection. Do not select a city because the model performs well there.

The inventory returned no OpenAQ location within 25 km of the Da Nang study point.
Retain Da Nang for explicitly modeled context and exclude it from the measured
comparison until a suitable source is found. If only discontinued
feeds remain, a historical study is possible but cannot establish current
operational reliability. Do not fill measured-data gaps with model output and
then count the replacements as observations.

If no suitable measured source can be obtained, document a narrower question:
"How do meteorology and CAMS-modeled PM2.5 co-vary at Vietnamese grid cells?"
An ML model trained on those outputs is a surrogate for an atmospheric model.
It is not a validated predictor of station exposure, and apparent weather
relationships may reflect the upstream model's own physics or shared inputs.

### Two Analytical Tracks

| Track | Permitted Inputs | Claims It Can Support |
| --- | --- | --- |
| Retrospective association | Quality-qualified measured PM2.5 plus ERA5 at matched station coordinates/intervals | Associations over the study period, with uncertainty, sampling limits and confounding caveats |
| Operational forecasting | Measurements and forecast vintages demonstrably available by each prediction origin | Predictive skill at the stated horizon against future measured targets, subject to latency and evaluation design |

Reanalysis is useful for explaining historical weather but arrives late and can
use later information. Even same-hour reanalysis features are unavailable to a
real-time forecaster. Chronological splitting alone does not solve this problem.
Retrospective analysis of weather-assisted predictions must not be called an
operational backtest unless the availability constraint is verified.

Open-Meteo Historical Forecast stitches successive runs. Its values at a future
target hour need not match the forecast available at the earlier origin. Single
Runs preserves initialization structure, but some older IFS data are described
as hindcasts. Verify run origin, publication lag and operational provenance before
using that archive to simulate a historical deployment. When uncertain, build a
prospective snapshot collection and report a shorter genuine evaluation.

Backfilled station measurements lack local ingestion times from the historical
period. Record their actual retrieval time and unknown original availability.
Use explicitly assumed lag scenarios only as retrospective sensitivity analyses;
do not fabricate historical `available_at` timestamps.

### Statistical And ML Implications

- Weather-PM relationships need nonlinear plots, seasonal/diurnal adjustment,
  effect sizes, and dependence-aware uncertainty. Use block bootstrap or an
  appropriate time-dependent error model after inspecting autocorrelation.
- Rainy/dry comparisons can be confounded by season, hour, location and emissions.
  Lower-cost sensors can have humidity-related measurement bias. Statistical
  significance and feature importance alone cannot establish causal effects.
- Fit imputation, scaling, feature selection and seasonal averages on training
  data only. Reindex on real hourly time within each station; row shifts across
  gaps do not create valid hour-based lags.
- Use trailing features known at origin, no centred rolling windows or backward
  fills from future observations. Identify in-progress hourly averages and lag
  them until their intervals finish and reports arrive.
- Train/validate/test on chronological periods with shared cutoffs across
  locations. Purge training labels whose target intervals overlap validation or
  test periods. Walk-forward evaluation must respect the maximum horizon and
  reporting delays; do not shuffle observations.
- Baselines: latest available PM2.5 persistence with age, trailing mean, previous
  day at the target hour when known, and training-only hour-of-week climatology.
  Compare on exactly the same eligible targets and disclose forecast coverage.
- Start with Ridge and a justified tree-based model. Compare PM-history-only,
  weather-only, and combined features to isolate incremental value. Adding
  SARIMA/boosting libraries requires a demonstrated modeling need.
- Report MAE as the primary concentration-error metric, RMSE for extreme errors,
  R-squared with its caveats, city/horizon breakdowns and dependence-aware intervals
  on error differences. Avoid MAPE near zero. Retain a baseline if ML does not win.
- When using CAMS as a model benchmark, compare the **as-issued** forecast against
  independent measurements. Predicting a future value already in the same CAMS
  run is not an honest improvement over that provider forecast.

## Location And Schema Consequences

The API supplies GeoNames IDs for Hanoi, HCMC and Da Nang. Those reviewed seed
matches belong in future editable configuration/metadata tables, not a permanent
hard-coded application list. Geocoding assists discovery; review candidate
matches and persist them so provider search-rank changes cannot move a city.

Maintain separate city, station/sensor, and grid-cell identities. A future schema
needs source/product, instrument/variable/unit, requested and returned coordinates,
measurement interval, valid time, retrieval time, publication/availability when
known, model initialization/version, and revision provenance. Unknown timing
stays null with an explicit status rather than a guessed timestamp.

Station rows need uniqueness by sensor, variable and interval, with revision
handling. Provider forecasts need a vintage-aware key, not only location and
valid time. Otherwise the next forecast run overwrites the evidence needed for
leakage-safe evaluation. Project predictions need model version, training cutoff,
forecast origin, target time and horizon.

No complex event-stream infrastructure is required to preserve these distinctions.
PostgreSQL tables, immutable request evidence and clear analytical views are
sufficient starting points. Phase 2 now specifies the
[schema](../database.md) and [source transactions](../source_contracts.md).

## Remaining Gate

Proceed to schema and adapter design for the two selected sensor locations. The
[qualification report](../research/openaq_qualification.md) defines what the
authenticated evidence establishes and what remains unknown. In particular,
OceanPark has a 119-hour gap, and its record starts in November 2025, so no full
shared annual cycle is available yet. Do not claim the measured-data study covers
all three cities or publish annual seasonal findings from this sample.

Confirm outdoor siting, correction/calibration history and prospective reporting
latency before making strong environmental or deployment claims. The historical
audit establishes data access and missingness, not scientific accuracy. Do not
report significance, model superiority or forecast accuracy from Phase 1 probes.
