# Walkthrough 03: Availability contract, baselines and model diagnostics

Command: `python3 -B reports/portfolio/walkthrough_03_feature_baseline_ml_contract.py --output-dir <output-dir>`

Phase 7-9 artifacts are frozen limited diagnostics. This walkthrough separates what is implemented and tested from what the frozen window can actually evaluate.

## Phase 7 availability contract

| Item | Value |
| --- | --- |
| Feature version | phase7_features_v7 |
| Availability basis | captured |
| Boundary mode | frozen |
| Horizons | 6h, 24h |
| Origins | 2137 hourly UTC origins (2026-06-08T00:00:00+00:00 to 2026-09-05T00:00:00+00:00) |
| Warm-up | 72h from 2026-06-05T00:00:00+00:00 |
| Status | limited_diagnostic |
| Missing families | pm_history, forecast_weather |
| Target contract | origin + horizon hours; measured hourly interval [target_start, target_end), represented by the observation with period_end = target_end |
| Prospective collection required | True |

Feature rows 8548: split train 5128, validation 1708, test 1712; purged 112 (56 validation-reaching, 56 test-reaching). Targets available 8290, absent 258. Shared chronological split: validation 2026-07-31T10:00:00+00:00, test 2026-08-18T05:00:00+00:00.

Usable captured evidence: PM-history origins 0/8548 rows and forecast-weather origins 0; rows with any data feature 0. Input-table hash verification: True.

## Phase 8 baselines

| Baseline | Role | Kind |
| --- | --- | --- |
| persistence_last_available | primary_reference | feature |
| persistence_lag_1h | sensitivity | feature |
| trailing_mean_24h | sensitivity | feature |
| local_hour_climatology | diagnostic_calendar | local_hour_climatology |
| weather_augmented_climatology | diagnostic_weather | weather_climatology |

Status: limited_diagnostic (input_phase7_missing_pm_history, input_phase7_missing_forecast_weather). Metric cells 90: 18 available and 72 unavailable with reason `no_eligible_target_prediction_pairs`. All cells are descriptive_only; test selection used: False. The available cells are train-only local-hour calendar diagnostics, not forecast-skill estimates, and no score was fabricated for an unavailable cell.

## Phase 9 model comparison

Model version phase9_ml_v4 (revision comparison_hardened), status limited_diagnostic (phase7_pm_history_unavailable, phase7_forecast_weather_unavailable, model_cells_unavailable).

| Item | Value |
| --- | --- |
| Feature sets | calendar_only, history_only, weather_only, history_weather |
| Families | ridge, bagged_tree |
| Target transforms | log1p, raw |
| Scopes | pooled, per_sensor |
| Model instances | 24 trained, 72 unavailable of 96 declared |
| Metric cells | 72 available, 216 unavailable of 288 |
| Prediction rows | 65424 |
| Comparison records | 360 |
| Selection | validation only; test scored once after the train-plus-validation refit |

The trained instances are calendar-only Ridge/tree diagnostics. Every history-only, weather-only and history_weather cell is unavailable with an explicit reason; no ERA5, CAMS, assumed-lag or target value entered a design matrix, and test was never used for selection.

## Why the artifacts are limited diagnostics

- The frozen historical window contains no evidence timestamp that predates a forecast origin, so captured PM-history and forecast-weather feature families are empty.
- Missing measured PM2.5 is never replaced with ERA5, CAMS or assumed-lag values.
- Calendar-only diagnostics can still train; no score is fabricated for an unavailable cell.
- A prospective collection period is required before captured-feature baseline or model evaluation exists.

Labels: Phase 8-9 metric outputs are descriptive_only; Phase 7-9 overall status is limited_diagnostic until a prospective captured collection period exists.
