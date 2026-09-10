# Phase 7 Features: Assumptions and Limitations

Availability-aware, leakage-safe feature construction replayed from a frozen input bundle.
No model is trained; no forecast-skill, causal, city-wide, operational or health claim is supported.

## Frozen boundary

- Input bundle digest: `9726689ba953b37ffb20b4e434f7236dd3008c0da3b3b0ac22cb9f31e37aa3bf` (file SHA-256 `ba6ce5362a7ce6f55d87002b4101a880ab8d00f5569a1d34863055d75e961878`)
- Cutoff 2026-09-06T20:59:00.669630+00:00; measurement window 2026-06-08T00:00:00+00:00 to 2026-09-06T00:00:00+00:00
- Feature version `phase7_features_v1`; availability basis `captured`
- Horizons [6, 24] hours; origins 2026-06-08T00:00:00+00:00 to 2026-09-05T00:00:00+00:00 (2137 hourly origins)
- Status: `limited_diagnostic`; a prospective collection period is required before captured availability exists

## Availability policy

- Captured: A source value is eligible at origin o only when every applicable evidence timestamp (response retrieved_at, row recorded_at, snapshot recorded_at, run_initialized_at and source_published_at when present) is strictly before o, the response is a retained successful response, and the row is not withheld. Conservative captured-timestamp policy: the schema has no exact transaction commit time, so this is not proof of as-issued provider availability when run_provenance is unknown.
- Assumed: Declared lag scenario only; retrospective sensitivity/mechanics output, never an operational backtest. Measured observations use event time period_end with period_end + lag < origin. Forecast snapshots use run_initialized_at + lag < origin and are rejected as ambiguous when run_initialized_at is unknown.
- Never silently fall back from captured to assumed.
- The Phase 3 historical backfill was retrieved after the historical period; its retrieved_at is not historical availability.

## Source policy

- Target and PM history: Measured OpenAQ PM2.5 (latest eligible revision before quality filtering; accepted rows for the primary track).
- Captured weather: Open-Meteo forecast snapshots only; one deterministic vintage per location/origin.
- Excluded from the captured matrix: ERA5 reanalysis (retrospective context only) and CAMS modeled air quality (separate benchmark stream).
- Missing measured PM2.5 is never replaced with CAMS or any model output.

## Target contract

- origin + horizon hours; target_end - 1 hour
- measured hourly interval [target_start, target_end), represented by the observation with period_end = target_end
- eventual quality-qualified record at the extraction cutoff, for evaluation only; never a feature input
- target values are written to phase_7_targets.csv only

## Catalog

- PM lags (hours): [1, 3, 6, 12, 24, 48, 72]
- Trailing windows (hours): [3, 6, 12, 24]; strict: null unless every expected hourly observation is accepted; sample standard deviation over the strict 24h window
- Weather features use the `weather_forecast_` prefix over variables apparent_temperature, cloud_cover, precipitation, relative_humidity_2m, shortwave_radiation, surface_pressure, temperature_2m, wind_direction_10m, wind_speed_10m; sin/cos components only
- Calendar features (origin and target local date/hour/weekday, Asia/Ho_Chi_Minh) are deterministic facts, not measurements.

## Chronological split

- Shared across both sensors and both horizons: train 60%, validation 20%, untouched test 20%.
- Validation starts 2026-07-31T10:00:00+00:00; test starts 2026-08-18T05:00:00+00:00.
- Purged origins (target interval reaches the next period): 112 of 8548 rows; reasons {"target_reaches_test": 56, "target_reaches_validation": 56}.
- Test rows are never purged and test-derived statistics are not used for feature decisions.

## Row accounting

- Feature rows: 8548; by split {"test": 1712, "train": 5128, "validation": 1708}
- Targets available: 8290; reasons {"ok": 8290, "target_absent": 258}
- PM history reasons {"no_eligible_accepted_values": 4274}
- Weather reasons {"no_eligible_vintage": 8548}
- Weather values missing or not accepted: 76932; alignment mismatches rejected: 0
- Measurement rows never eligible at any origin: 4215
- Forecast snapshots never eligible at any origin: 2
- Ambiguous-vintage rejections (assumed mode, unknown run initialization): 0
- Rows rejected for future evidence: 0 (the builder stops the run on any violation)

## Assumptions

- Captured eligibility is a conservative evidence-timestamp policy; the schema has no exact transaction commit time.
- Overlapping forecast snapshots are never averaged; one deterministic vintage is selected per location/origin.
- Wind direction enters only as sin/cos components; raw direction is not a linear feature.
- Gaps are never bridged: exact lags require exact timestamps, strict trailing windows require every expected hour, and row position is never a proxy for elapsed time.
- Floating-point feature values are rounded to 12 significant digits for deterministic replay; leakage checks run on unrounded values.

## Limitations

- Feature availability uses evidence timestamps; the schema has no exact transaction commit time, so captured eligibility is a conservative policy, not proof of as-issued provider availability.
- The Phase 3 historical backfill was retrieved after the historical period; captured mode therefore yields a limited diagnostic artifact until a prospective collection period exists.
- ERA5 reanalysis and CAMS modeled air quality are excluded from the captured measured-target feature matrix.
- Targets are evaluation labels stored separately; they never enter feature lineage.
- No model is trained here; no forecast-skill, causal, city-wide or operational claim is supported.

## Attribution

OpenAQ; AirGradient; Thomas Versteeg (CMT8); Open-Meteo. See docs/verification/phase_7.md for the
verification record and phase_7_plan.md for the contract.
