# Phase 5 EDA Plan

Phase 5 produces descriptive exploratory analysis from the frozen Phase 4
dataset. It does not perform hypothesis testing, causal analysis, feature
engineering, model training, forecast evaluation or dashboard work.

## Evidence path

The EDA command re-extracts the source tables in one repeatable-read, read-only
transaction, then compares every extracted input-table hash with the Phase 4
artifact. A changed source database or mismatched cutoff stops the run. The
outputs contain the Phase 4 artifact hash, source schema revision, source row
counts and EDA manifest hash.

The analytical selection rules remain fixed:

- choose the latest eligible OpenAQ revision before quality filtering;
- retain only provisionally accepted PM2.5 rows for descriptive values;
- keep missing hours absent;
- join weather at station coordinates;
- use instantaneous weather at PM interval start;
- use preceding-hour precipitation and radiation at PM interval end;
- select one ERA5 vintage per valid time without averaging overlapping captures;
- keep CAMS and forecast snapshots in a separate modeled-context output.

## Outputs

`vn-air eda run` writes a new directory containing:

- `eda_summary.json` and `eda_bundle.json`: descriptive summaries, exploratory
  associations, modeled-context inventory, limitations and replay data;
- `hourly_pm25_weather_grid.csv`: complete measured interval grid with absent
  hours retained;
- `daily.csv`, `diurnal.csv`, `weekday.csv`, `lag_correlations.csv` and
  `weather_associations.csv`;
- `cams_modeled_pm25.csv` and `snapshot_provenance.csv`;
- SVG plots for hourly, daily, coverage, diurnal, distribution, lag, CAMS
  context and each linear weather-variable comparison;
- `SUCCESS.json` with output hashes.

The implementation uses the Python standard library, so the EDA path does not
add a plotting or dataframe dependency to the ingestion package. Pearson values
serve as descriptive exploration only. The output contains no p-values,
confidence intervals or model claims.

## Verification budget

Run the 61-test offline suite, the previously passing 45-test isolated
PostgreSQL suite, `git diff --check`, CLI help, and one live Supabase EDA
extraction using the Phase 4 cutoff. Check output row counts, SVG parseability,
missing-hour preservation, sensor separation, replay equality and the Phase 4
input-hash match.
