# Phase 5 Exploratory Data Analysis

Date: 2026-09-07 UTC. Scope: descriptive EDA from the frozen Phase 4 dataset.
The phase makes no statistical-significance, causal, model-performance or
operational-forecast claims.

## Frozen inputs

| Item | Value |
| --- | --- |
| Phase 4 cutoff | 2026-09-06T20:59:00.669630Z |
| Measurement window | 2026-06-08T00:00:00Z through 2026-09-06T00:00:00Z |
| Phase 4 artifact | `phase_4_quality_2026-09-07_final.json` |
| EDA bundle | `phase_5_eda_2026-09-07_final/eda_bundle.json` |
| EDA implementation | `phase5_eda_v1` |
| Final bundle SHA-256 | `92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63` |

The EDA command re-extracts the source tables in one repeatable-read, read-only
transaction. It compares the source row hashes with Phase 4 before calculating
summaries. A changed source dataset or selection policy stops the run.

Command used:

```bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli eda run \
  --cutoff 2026-09-06T20:59:00.669630Z \
  --start 2026-06-08T00:00:00Z \
  --end 2026-09-06T00:00:00Z \
  --phase4-artifact docs/verification/phase_4_quality_2026-09-07_final.json \
  --config configs/study.json \
  --output-dir docs/verification/phase_5_eda_2026-09-07_final
```

## Outputs

The [EDA output directory](phase_5_eda_2026-09-07_final/) contains:

- JSON summary and replayable bundle with source and implementation hashes;
- hourly PM2.5/weather grid with `absent` hours preserved;
- daily, diurnal, weekday, lag, weather-association and wind-sector CSV summaries;
- PM2.5-to-ERA5 joined rows at the documented temporal boundaries;
- separate CAMS modeled PM2.5 CSV;
- model snapshot provenance CSV;
- hourly, daily, coverage, diurnal, distribution, lag, CAMS and weather scatter
  SVG plots;
- `SUCCESS.json` with output-file hashes.

The analysis uses accepted OpenAQ PM2.5 rows for descriptive values. It keeps
the full hourly grid, including missing periods. ERA5 joins use instantaneous
variables at PM interval start and preceding-hour precipitation/radiation at
PM interval end. Forecast snapshots stay in provenance metadata and do not enter
the retrospective weather association table. CAMS remains a modeled context.

## Descriptive findings

- CMT8 contributes 2,154 accepted hours. PM2.5 has mean 22.71, median 20.9,
  interquartile range 15.2 to 28.9 and maximum 82.2 ug/m3.
- OceanPark contributes 2,037 accepted hours. PM2.5 has mean 32.01, median 31.1,
  interquartile range 19.8 to 41.8 and maximum 149.0 ug/m3.
- The common accepted sensor-time set contains 2,035 hours. These sensors remain
  site-level records, so the summaries do not represent city averages.
- The CMT8 descriptive hourly profile is lowest near local 02:00 and highest near
  20:00. OceanPark is lowest near 15:00 and highest near 20:00. These are sample
  profiles over one short window, not seasonal or causal effects.
- One-hour PM2.5 persistence is high in both sensor series: descriptive Pearson
  lag-1 values are 0.810 for CMT8 and 0.869 for OceanPark. The lag profile is
  exploratory and does not establish forecast skill.
- The largest absolute weather association in the joined rows is wind speed for
  both sensors: -0.339 at CMT8 and -0.310 at OceanPark. The values are descriptive
  pairwise correlations and do not adjust for season, time of day, autocorrelation,
  sensor bias or confounding.

## Verification

| Check | Result |
| --- | --- |
| Offline tests | 61 passed; 2 credential checks skipped without `.env` |
| EDA source run | Passed against Supabase in a read-only transaction |
| Phase 4 hash match | Passed for all extracted input tables |
| Measured accepted rows | 4,191, matching Phase 4 |
| Absent measured grid rows | 129, preserving CMT8 and OceanPark gaps |
| Complete nine-variable ERA5 rows | 2,033 CMT8; 1,916 OceanPark |
| CSV parsing | Passed: 4,320 grid rows, 6,480 CAMS rows, 72 snapshot rows |
| SVG validity | Passed for the generated plot set |
| Bundle replay | Passed without database access; CSV/SVG outputs compared |
| Final output files | 27 files; `SUCCESS.json` contains per-file SHA-256 values |
| Isolated PostgreSQL suite | 45 tests passed before Phase 5; no schema/migration changes in Phase 5 |
| Inferential outputs | None; no p-values or confidence intervals |

## Limits

The EDA covers the full audited window and does not reserve a modeling holdout.
The measurements cover two low-cost sensor sites and less than a full annual
cycle. ERA5 is retrospective reanalysis, so its availability cannot support an
operational forecast claim. Weather associations use pairwise-complete rows and
do not address causality. Missing hours remain missing. The next phase is
statistical design, with hypotheses and dependence-aware uncertainty specified
before any significance calculation.
