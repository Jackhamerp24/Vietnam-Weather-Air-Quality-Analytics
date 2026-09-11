# Phase 8 Baselines: Assumptions and Limitations

Reproducible chronological baseline diagnostics generated from a Phase 7 artifact.
No database access, no imputation and no operational forecast claim.

## Input and boundary

- Phase 7 feature version: `phase7_features_v7`
- Input summary SHA-256: `7fd1bfd725c5bec6df0088adf52af1f6e34f08d7d2244bb95b6172f7896e4d0b`
- Input features SHA-256: `2e2829e8cd14444ce4da322dc4f288ebb49baa05dba14423529bea2c866e092c`
- Input targets SHA-256: `d3e5198ccba3814259e5c9e8cfe647f481d58481b1bb8d774997e982e0f51073`
- Availability basis: `captured`; horizons: `[6, 24]`
- Phase 8 status: `limited_diagnostic`; reasons: `["input_phase7_missing_pm_history", "input_phase7_missing_forecast_weather"]`
- Test metrics are reported but `test_selection_used = False`.

## Baselines

- `persistence_last_available` uses only Phase 7 `pm25_last_available`.
- `persistence_lag_1h` uses only the exact Phase 7 `pm25_lag_1h` feature.
- `trailing_mean_24h` requires the strict complete Phase 7 24-hour window.
- `local_hour_climatology` is fit by sensor and Vietnam local hour on non-purged training targets only.
- `weather_augmented_climatology` is a diagnostic training climatology stratified by a finite captured-weather availability indicator; it is unavailable when no finite captured weather feature exists.

## Metrics

Metrics are computed only when the target is accepted/finite, the prediction is finite and the row is not purged.
MASE uses the non-purged training one-hour naive denominator without bridging time gaps. sMAPE skips zero denominators and is null if all denominators are zero.

## Limitations

- Metrics are descriptive baseline diagnostics, not forecast-skill certification.
- The Phase 7 captured artifact has no prospectively captured PM/weather feature evidence; feature-based baselines are therefore unavailable.
- The local-hour climatology uses training targets and calendar hour only; it is not an operational feature baseline.
- Two non-reference sensor sites are not a city average or population estimate.
- The final test period is reported but never used for baseline selection or fitting.
