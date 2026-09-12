# Phase 9 Machine Learning: Assumptions and Limitations

Deterministic, database-free chronological ML diagnostics over one Phase 7 captured
feature artifact with a Phase 8 v2 reference comparison. No operational forecast claim.

## Inputs and boundary

- Model version: `phase9_ml_v2`
- Phase 7 feature version: `phase7_features_v7`
- Phase 7 manifest SHA-256: `6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa`
- Phase 8 reference: `phase8_baselines_v2` (`ec651c4df04cb605f8849c1af96a3aea58f0902370e16ec39b9c48fdee22775e`)
- Availability basis: `captured`; horizons: `[6, 24]`
- Status: `limited_diagnostic`; reasons: `["phase7_pm_history_unavailable", "phase7_forecast_weather_unavailable", "model_cells_unavailable"]`
- Test used for selection: `False`

## Models and features

- Ridge with an unregularized intercept and train-partition-only standardization;
- 25 shallow bagged trees (depth 4, minimum leaf 10, 80% bootstrap) with SHA-256 seeds;
- Feature sets: calendar-only, history-only, weather-only and history+weather;
- Target transforms: log1p (primary) and raw (sensitivity), both with a non-negative reporting bound.

## Rules

- Only finite, accepted, non-purged targets are scored; no imputation of missing features;
- Every declared specification is reported; no model, feature set or transform is selected on test;
- Final test scoring uses a train-plus-validation refit after validation-only alpha selection;
- Predictions are descriptive and must not be presented as forecast skill.

## Limitations

- All metrics are descriptive diagnostics, not forecast-skill certification.
- The frozen Phase 7 captured artifact has no prospectively captured PM/weather features, so history and weather models are unavailable.
- The calendar diagnostic uses local calendar fields and training targets only; it is not an operational forecast.
- Pooled results are a descriptive combination of two non-reference sensor sites, not a city average.
- The final test period is scored once by a train-plus-validation refit and never used for selection.
