# Phase 6 Statistics: Assumptions and Limitations

Pre-registered sensor-level weather-PM2.5 association analysis replayed from the frozen
Phase 5 EDA bundle. No causal, city-wide exposure, operational forecast or health claim is supported.

## Frozen boundary

- Phase 5 bundle digest: `92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63` (file SHA-256 `00012495fd3fc455f5d9e43fdac18de9fd42ef686678f4ee843fa9ade82da18c`)
- Cutoff: 2026-09-06T20:59:00.669630+00:00; window: 2026-06-08T00:00:00+00:00 to 2026-09-06T00:00:00+00:00
- Seed 20260908; 2000 replicates per fit; block lengths [1, 2, 7] local calendar days
- Gate thresholds: >= 30 non-empty and >= 20 eligible independent partitions
- Reconciliation: {"absent_rows": 129, "accepted_cmt8": 2154, "accepted_oceanpark": 2037, "accepted_rows": 4191, "complete_weather_cmt8": 2033, "complete_weather_oceanpark": 1916, "shared_accepted_hours": 2035}
- Weather variables observed in the frozen bundle: apparent_temperature, cloud_cover, precipitation, relative_humidity_2m, shortwave_radiation, surface_pressure, temperature_2m, wind_direction_10m, wind_speed_10m

## Model

Each fit is ordinary least squares on accepted PM2.5 hours with sensor fixed effects (pooled and
shared fits), Vietnam local-hour fixed effects (reference hour 0), weekday fixed effects
(reference Monday) and a centered linear day trend. Exposures are standardized on each fit's
eligible rows; the estimand is the adjusted change in the response per one analysis-window
standard deviation of the exposure. H3 is the sensor contrast (OceanPark minus CMT8) on the
shared accepted-hour set and has no exposure term. Complete cases per fit; no imputation; CAMS
and provider forecasts are excluded.

Weather cases:

- `pairwise_complete`: accepted response plus a finite value of the fit's exposure only.
- `complete_weather`: additionally finite values for every weather variable observed in the
  bundle rows (listed above). Complete-weather OLS variants exist for the pooled H1, H2 and all
  five declared secondary log1p fits and are exploratory sensitivity output.
- `not_applicable`: H3, which has no weather exposure term.

Formulas per fit are recorded in the summary manifest.

## Uncertainty and inference

Uncertainty uses a moving-block bootstrap over Vietnam local calendar days. Moving windows are
resampling candidates only; they overlap and are not independent evidence units. Each replicate
draws `divmod(n_dates, block_days)` full-length windows plus one remainder-length window when
needed, so every replicate spans exactly 91 study dates (two-day blocks draw 45 two-day windows
plus one one-day window, never 92). Percentile 95% intervals; p-values are the two-sided
bootstrap tail statistic 2*min(P(beta<=0), P(beta>=0)) computed as (count+1)/(usable+1).

The inferential gate uses deterministic non-overlapping partitions of the ordered local calendar
dates anchored at the first frozen study date (chunks of at most block_days dates with a final
shorter chunk): at least 30 non-empty and at least 20 eligible independent partitions are
required. The frozen 91-date window yields 91, 46 and 13 independent partitions for one-, two-
and seven-day blocks, so seven-day sensitivity fits are expected to be descriptive-only under
the gate; this is a documented limitation, not a failure.

Inference labels: only the two Holm-adjusted primary pooled p-values and the five
Benjamini-Hochberg-adjusted secondary pooled p-values are `inferential`. Gate-passing but
unadjusted fits (site-specific, H3, raw-scale, block-length, complete-weather and
extreme-value) are `exploratory`. Gate-failing or descriptive outputs are `descriptive_only`.
Unadjusted p-values are exploratory diagnostics, not findings.

## Fit inventory

| fit | family | weather case | n | coverage % | independent blocks (non-empty/eligible) | estimate | CI | p | inference |
| H1_pooled_log1p_b1_pairwise_complete | primary | pairwise_complete | 3951 | 97.0138888889 | 91/86 | -0.207758555768 | [-0.256867070417, -0.166087269416] | 0.000999500249875 | inferential |
| H1_cmt8_log1p_b1_pairwise_complete | primary | pairwise_complete | 2034 | 99.7222222222 | 91/86 | -0.186727682782 | [-0.235237187037, -0.134995367249] | 0.000999500249875 | exploratory |
| H1_oceanpark_log1p_b1_pairwise_complete | primary | pairwise_complete | 1917 | 94.3055555556 | 87/82 | -0.22644271788 | [-0.303895857975, -0.147369588566] | 0.000999500249875 | exploratory |
| H2_pooled_log1p_b1_pairwise_complete | primary | pairwise_complete | 3951 | 97.0138888889 | 91/86 | 0.0986222781931 | [-0.00576113493793, 0.186298167368] | 0.0679660169915 | inferential |
| H2_cmt8_log1p_b1_pairwise_complete | primary | pairwise_complete | 2034 | 99.7222222222 | 91/86 | -0.075252705272 | [-0.13488347998, -0.00596744939865] | 0.0369815092454 | exploratory |
| H2_oceanpark_log1p_b1_pairwise_complete | primary | pairwise_complete | 1917 | 94.3055555556 | 87/82 | 0.178470295685 | [0.0250243457286, 0.322856663132] | 0.0259870064968 | exploratory |
| H3_shared_log1p_b1 | primary | not_applicable | 4070 | 100.0 | 87/87 | 0.179237904693 | [0.0596893954456, 0.296091871463] | 0.00299850074963 | exploratory |
| S_temperature_2m_pooled_log1p_b1_pairwise_complete | secondary | pairwise_complete | 3951 | 97.0138888889 | 91/86 | -0.0119795640857 | [-0.121071898142, 0.0924473856633] | 0.868565717141 | inferential |
| S_precipitation_pooled_log1p_b1_pairwise_complete | secondary | pairwise_complete | 3949 | 97.0138888889 | 91/86 | -0.0463695265032 | [-0.0822728027774, -0.00489393354705] | 0.0359820089955 | inferential |
| S_surface_pressure_pooled_log1p_b1_pairwise_complete | secondary | pairwise_complete | 3951 | 97.0138888889 | 91/86 | 0.116601348897 | [-0.0326559999346, 0.253788321096] | 0.139930034983 | inferential |
| S_cloud_cover_pooled_log1p_b1_pairwise_complete | secondary | pairwise_complete | 3951 | 97.0138888889 | 91/86 | -0.0900205188395 | [-0.127017383037, -0.0483079917918] | 0.00199900049975 | inferential |
| S_shortwave_radiation_pooled_log1p_b1_pairwise_complete | secondary | pairwise_complete | 3949 | 97.0138888889 | 91/86 | 0.0161320647126 | [-0.108787201821, 0.130387993032] | 0.87956021989 | inferential |
| H1_pooled_raw_b1_pairwise_complete | sensitivity | pairwise_complete | 3951 | 97.0138888889 | 91/86 | -4.50707727068 | [-5.48839739575, -3.54720543214] | 0.000999500249875 | exploratory |
| H2_pooled_raw_b1_pairwise_complete | sensitivity | pairwise_complete | 3951 | 97.0138888889 | 91/86 | 1.51053656597 | [-0.821705878263, 3.80582057982] | 0.178910544728 | exploratory |
| H3_shared_raw_b1 | sensitivity | not_applicable | 4070 | 100.0 | 87/87 | 8.9685995086 | [6.11667038938, 11.9207377908] | 0.000999500249875 | exploratory |
| H1_pooled_log1p_b2_pairwise_complete | sensitivity | pairwise_complete | 3951 | 97.0138888889 | 46/43 | -0.207758555768 | [-0.259026139528, -0.159253495991] | 0.000999500249875 | exploratory |
| H2_pooled_log1p_b2_pairwise_complete | sensitivity | pairwise_complete | 3951 | 97.0138888889 | 46/43 | 0.0986222781931 | [-0.0251575325498, 0.20901443185] | 0.118940529735 | exploratory |
| H3_shared_log1p_b2 | sensitivity | not_applicable | 4070 | 100.0 | 44/44 | 0.179237904693 | [0.0309496242275, 0.327939640791] | 0.0209895052474 | exploratory |
| H1_pooled_log1p_b7_pairwise_complete | sensitivity | pairwise_complete | 3951 | 97.0138888889 | 13/13 | -0.207758555768 | n/a | n/a | descriptive_only |
| H2_pooled_log1p_b7_pairwise_complete | sensitivity | pairwise_complete | 3951 | 97.0138888889 | 13/13 | 0.0986222781931 | n/a | n/a | descriptive_only |
| H3_shared_log1p_b7 | sensitivity | not_applicable | 4070 | 100.0 | 13/13 | 0.179237904693 | n/a | n/a | descriptive_only |
| H1_pooled_log1p_b1_pairwise_complete_excl_extreme | sensitivity | pairwise_complete | 3945 | 96.875 | 91/86 | -0.20708732678 | [-0.25555715149, -0.162165301651] | 0.000999500249875 | exploratory |
| H2_pooled_log1p_b1_pairwise_complete_excl_extreme | sensitivity | pairwise_complete | 3945 | 96.875 | 91/86 | 0.0996580556051 | [-0.00376580403511, 0.192125143575] | 0.0599700149925 | exploratory |
| H3_shared_log1p_b1_excl_extreme | sensitivity | not_applicable | 4064 | 99.8525798526 | 87/87 | 0.176395227716 | [0.0567583323564, 0.297905332498] | 0.00499750124938 | exploratory |
| H1_pooled_log1p_b1_complete_weather | sensitivity | complete_weather | 3949 | 97.0138888889 | 91/86 | -0.207808582517 | [-0.254242252792, -0.164853623147] | 0.000999500249875 | exploratory |
| H2_pooled_log1p_b1_complete_weather | sensitivity | complete_weather | 3949 | 97.0138888889 | 91/86 | 0.0987358546998 | [-0.00148072268653, 0.195322041217] | 0.055972013993 | exploratory |
| S_temperature_2m_pooled_log1p_b1_complete_weather | sensitivity | complete_weather | 3949 | 97.0138888889 | 91/86 | -0.0119482503975 | [-0.122188287791, 0.0942824805601] | 0.873563218391 | exploratory |
| S_precipitation_pooled_log1p_b1_complete_weather | sensitivity | complete_weather | 3949 | 97.0138888889 | 91/86 | -0.0463695265032 | [-0.0809874455422, -0.00525778582444] | 0.031984007996 | exploratory |
| S_surface_pressure_pooled_log1p_b1_complete_weather | sensitivity | complete_weather | 3949 | 97.0138888889 | 91/86 | 0.116725274809 | [-0.0300067074254, 0.252759020332] | 0.107946026987 | exploratory |
| S_cloud_cover_pooled_log1p_b1_complete_weather | sensitivity | complete_weather | 3949 | 97.0138888889 | 91/86 | -0.0900349439512 | [-0.128158297072, -0.0485844090533] | 0.000999500249875 | exploratory |
| S_shortwave_radiation_pooled_log1p_b1_complete_weather | sensitivity | complete_weather | 3949 | 97.0138888889 | 91/86 | 0.0161320647126 | [-0.114307591392, 0.131948505668] | 0.832583708146 | exploratory |

## Pairwise-complete versus complete-weather descriptive correlations

Descriptive per-sensor Pearson correlations using the Phase 5 convention. `pairwise_complete`
rows have finite accepted PM2.5 and a finite exposure value; `complete_weather` rows also have
every bundle weather variable finite. These are coverage/descriptive sensitivity output only:
no bootstrap interval, p-value, adjustment or inferential label applies, and no new hypothesis
is created. Wind direction is circular and stays excluded; Phase 5 wind sectors remain the
descriptive wind-direction output.

| sensor | exposure | weather case | n | Pearson r |
| cmt8 | cloud_cover | pairwise_complete | 2034 | -0.123027461832 |
| cmt8 | cloud_cover | complete_weather | 2033 | -0.123083383985 |
| cmt8 | precipitation | pairwise_complete | 2033 | -0.108296307893 |
| cmt8 | precipitation | complete_weather | 2033 | -0.108296307893 |
| cmt8 | relative_humidity_2m | pairwise_complete | 2034 | 0.0430368096669 |
| cmt8 | relative_humidity_2m | complete_weather | 2033 | 0.0429983518369 |
| cmt8 | shortwave_radiation | pairwise_complete | 2033 | -0.0614250905007 |
| cmt8 | shortwave_radiation | complete_weather | 2033 | -0.0614250905007 |
| cmt8 | surface_pressure | pairwise_complete | 2034 | 0.175534147984 |
| cmt8 | surface_pressure | complete_weather | 2033 | 0.175518314203 |
| cmt8 | temperature_2m | pairwise_complete | 2034 | -0.0262887374078 |
| cmt8 | temperature_2m | complete_weather | 2033 | -0.0262489610935 |
| cmt8 | wind_speed_10m | pairwise_complete | 2034 | -0.338661434979 |
| cmt8 | wind_speed_10m | complete_weather | 2033 | -0.338669909233 |
| oceanpark | cloud_cover | pairwise_complete | 1917 | -0.15030553805 |
| oceanpark | cloud_cover | complete_weather | 1916 | -0.150310689147 |
| oceanpark | precipitation | pairwise_complete | 1916 | -0.137928733746 |
| oceanpark | precipitation | complete_weather | 1916 | -0.137928733746 |
| oceanpark | relative_humidity_2m | pairwise_complete | 1917 | 0.201211257217 |
| oceanpark | relative_humidity_2m | complete_weather | 1916 | 0.201212161584 |
| oceanpark | shortwave_radiation | pairwise_complete | 1916 | -0.127564047289 |
| oceanpark | shortwave_radiation | complete_weather | 1916 | -0.127564047289 |
| oceanpark | surface_pressure | pairwise_complete | 1917 | 0.12239246625 |
| oceanpark | surface_pressure | complete_weather | 1916 | 0.122400031337 |
| oceanpark | temperature_2m | pairwise_complete | 1917 | -0.136579001926 |
| oceanpark | temperature_2m | complete_weather | 1916 | -0.136608392481 |
| oceanpark | wind_speed_10m | pairwise_complete | 1917 | -0.310362864395 |
| oceanpark | wind_speed_10m | complete_weather | 1916 | -0.310367660106 |

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
- Overlapping moving windows are resampling candidates, not independent evidence units; the gate uses non-overlapping date partitions.
- Seven-day block sensitivity fits have 13 independent partitions and are descriptive-only under the 30-partition gate by construction.
- Site-specific, raw-scale, block-length, complete-weather and extreme-value results are unadjusted exploratory sensitivity output.
- No causal effect, forecast skill, health guidance or model-performance claim is supported.

## Attribution

OpenAQ; AirGradient; Thomas Versteeg (CMT8); Open-Meteo; ERA5/Copernicus C3S. CC BY 4.0.
See docs/verification/phase_6.md for the verification record, phase_6_plan.md for the
pre-registration and its 2026-09-09 correction addendum.
