# Phase 6 Statistics: Assumptions and Limitations

Pre-registered sensor-level weather-PM2.5 association analysis replayed from the frozen
Phase 5 EDA bundle. No causal, city-wide exposure, operational forecast or health claim is supported.

## Frozen boundary

- Phase 5 bundle digest: `92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63` (file SHA-256 `00012495fd3fc455f5d9e43fdac18de9fd42ef686678f4ee843fa9ade82da18c`)
- Cutoff: 2026-09-06T20:59:00.669630+00:00; window: 2026-06-08T00:00:00+00:00 to 2026-09-06T00:00:00+00:00
- Seed 20260908; 2000 replicates per fit; block lengths [1, 2, 7] local calendar days
- Gate thresholds: >= 30 non-empty blocks and >= 20 eligible blocks
- Reconciliation: {"absent_rows": 129, "accepted_cmt8": 2154, "accepted_oceanpark": 2037, "accepted_rows": 4191, "complete_weather_cmt8": 2033, "complete_weather_oceanpark": 1916, "shared_accepted_hours": 2035}

## Model

Each fit is ordinary least squares on accepted PM2.5 hours with sensor fixed effects (pooled and
shared fits), Vietnam local-hour fixed effects (reference hour 0), weekday fixed effects
(reference Monday) and a centered linear day trend. Exposures are standardized on each fit's
eligible rows; the estimand is the adjusted change in the response per one analysis-window
standard deviation of the exposure. H3 is the sensor contrast (OceanPark minus CMT8) on the
shared accepted-hour set. Complete cases per exposure model; no imputation; CAMS and provider
forecasts are excluded.

Formulas per fit are recorded in the summary manifest.

## Uncertainty and inference

Uncertainty uses a moving-block bootstrap over Vietnam local calendar days: blocks are contiguous
spans of 1, 2 or 7 local dates drawn with replacement from every contiguous window, keeping the
observed hours and gaps inside each sampled block. Percentile 95% intervals; p-values are the
two-sided bootstrap tail statistic 2*min(P(beta<=0), P(beta>=0)) computed as (count+1)/(usable+1),
emitted only when the block gates pass. Holm adjusts the two primary p-values; Benjamini-Hochberg
adjusts the five declared secondary exposures. Site-specific, sensitivity and exploratory p-values
are unadjusted. Rank-deficient replicates are discarded and reported; the full-sample fit must be
full rank or the run stops.

## Fit inventory

| fit | family | n | coverage % | blocks (non-empty/eligible) | estimate | CI | p |
| H1_pooled_log1p_b1 | primary | 3951 | 97.0138888889 | 91/86 | -0.207758555768 | [-0.256867070417, -0.166087269416] | 0.000999500249875 |
| H1_cmt8_log1p_b1 | primary | 2034 | 99.7222222222 | 91/86 | -0.186727682782 | [-0.235237187037, -0.134995367249] | 0.000999500249875 |
| H1_oceanpark_log1p_b1 | primary | 1917 | 94.3055555556 | 87/82 | -0.22644271788 | [-0.303895857975, -0.147369588566] | 0.000999500249875 |
| H2_pooled_log1p_b1 | primary | 3951 | 97.0138888889 | 91/86 | 0.0986222781931 | [-0.00576113493793, 0.186298167368] | 0.0679660169915 |
| H2_cmt8_log1p_b1 | primary | 2034 | 99.7222222222 | 91/86 | -0.075252705272 | [-0.13488347998, -0.00596744939865] | 0.0369815092454 |
| H2_oceanpark_log1p_b1 | primary | 1917 | 94.3055555556 | 87/82 | 0.178470295685 | [0.0250243457286, 0.322856663132] | 0.0259870064968 |
| H3_shared_log1p_b1 | primary | 4070 | 100.0 | 87/87 | 0.179237904693 | [0.0596893954456, 0.296091871463] | 0.00299850074963 |
| S_temperature_2m_pooled_log1p_b1 | secondary | 3951 | 97.0138888889 | 91/86 | -0.0119795640857 | [-0.121071898142, 0.0924473856633] | 0.868565717141 |
| S_precipitation_pooled_log1p_b1 | secondary | 3949 | 97.0138888889 | 91/86 | -0.0463695265032 | [-0.0822728027774, -0.00489393354705] | 0.0359820089955 |
| S_surface_pressure_pooled_log1p_b1 | secondary | 3951 | 97.0138888889 | 91/86 | 0.116601348897 | [-0.0326559999346, 0.253788321096] | 0.139930034983 |
| S_cloud_cover_pooled_log1p_b1 | secondary | 3951 | 97.0138888889 | 91/86 | -0.0900205188395 | [-0.127017383037, -0.0483079917918] | 0.00199900049975 |
| S_shortwave_radiation_pooled_log1p_b1 | secondary | 3949 | 97.0138888889 | 91/86 | 0.0161320647126 | [-0.108787201821, 0.130387993032] | 0.87956021989 |
| H1_pooled_raw_b1 | sensitivity | 3951 | 97.0138888889 | 91/86 | -4.50707727068 | [-5.48839739575, -3.54720543214] | 0.000999500249875 |
| H2_pooled_raw_b1 | sensitivity | 3951 | 97.0138888889 | 91/86 | 1.51053656597 | [-0.821705878263, 3.80582057982] | 0.178910544728 |
| H3_shared_raw_b1 | sensitivity | 4070 | 100.0 | 87/87 | 8.9685995086 | [6.11667038938, 11.9207377908] | 0.000999500249875 |
| H1_pooled_log1p_b2 | sensitivity | 3951 | 97.0138888889 | 90/86 | -0.207758555768 | [-0.258418809142, -0.158014288809] | 0.000999500249875 |
| H2_pooled_log1p_b2 | sensitivity | 3951 | 97.0138888889 | 90/86 | 0.0986222781931 | [-0.0265217488063, 0.204825514482] | 0.116941529235 |
| H3_shared_log1p_b2 | sensitivity | 4070 | 100.0 | 87/87 | 0.179237904693 | [0.0314386666024, 0.329307712471] | 0.0209895052474 |
| H1_pooled_log1p_b7 | sensitivity | 3951 | 97.0138888889 | 85/85 | -0.207758555768 | [-0.264302146977, -0.150879154647] | 0.000999500249875 |
| H2_pooled_log1p_b7 | sensitivity | 3951 | 97.0138888889 | 85/85 | 0.0986222781931 | [-0.0741841381529, 0.220005257549] | 0.260869565217 |
| H3_shared_log1p_b7 | sensitivity | 4070 | 100.0 | 85/85 | 0.179237904693 | [0.0442950803131, 0.346063881518] | 0.00899550224888 |
| H1_pooled_log1p_b1_excl_extreme | sensitivity | 3945 | 96.875 | 91/86 | -0.20708732678 | [-0.25516303298, -0.165962913842] | 0.000999500249875 |
| H2_pooled_log1p_b1_excl_extreme | sensitivity | 3945 | 96.875 | 91/86 | 0.0996580556051 | [0.00157875383459, 0.189665684208] | 0.0489755122439 |
| H3_shared_log1p_b1_excl_extreme | sensitivity | 4064 | 99.8525798526 | 87/87 | 0.176395227716 | [0.0532078448397, 0.296602990144] | 0.00999500249875 |

## Extreme-value review rule (sensitivity only)

- cmt8: Q1 15.2, Q3 28.9, fence Q3+3*IQR = 70.0 ug/m3, 1 accepted hours flagged; flagged rows keep Phase 4 labels and stay in primary fits
- oceanpark: Q1 19.8, Q3 41.8, fence Q3+3*IQR = 107.8 ug/m3, 5 accepted hours flagged; flagged rows keep Phase 4 labels and stay in primary fits

## Assumptions

- Accepted OpenAQ values are provisional screening labels, not calibration certification.
- ERA5 reanalysis at station coordinates represents site weather; it is retrospective and its retrieval time is not historical availability.
- Within-block serial dependence is preserved by design; across-block independence is approximate.
- Effects are linear on the fitted scale over the observed range; log1p and raw scales are both reported.
- Fixed effects for hour, weekday and a linear trend absorb major temporal structure, not all confounding.
- Bootstrap p-values are exact only under the resampling model; they are not parametric p-values.
- Floating-point outputs are rounded to 12 significant digits for deterministic replay.

## Limitations

- Two non-reference low-cost sensor sites over one 90-day window; no city-wide exposure, seasonal or population inference.
- Associations are adjusted for temporal structure only; residual confounding, sensor bias and calibration uncertainty remain.
- ERA5 is retrospective reanalysis at model resolution; it is not a site measurement and its retrieval time is not historical availability.
- CAMS and provider forecasts are excluded from these measured-target models.
- Bootstrap blocks are approximately independent; serial dependence beyond the block length may remain.
- Site-specific, raw-scale, block-length, extreme-value and complete-weather results are unadjusted sensitivity output.
- No causal effect, forecast skill, health guidance or model-performance claim is supported.

## Attribution

OpenAQ; AirGradient; Thomas Versteeg (CMT8); Open-Meteo; ERA5/Copernicus C3S. CC BY 4.0.
See docs/verification/phase_6.md for the verification record and phase_6_plan.md for the pre-registration.
