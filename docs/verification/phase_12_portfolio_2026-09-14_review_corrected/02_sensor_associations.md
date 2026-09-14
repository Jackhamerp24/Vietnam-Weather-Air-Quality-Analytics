# Walkthrough 02: Pre-registered weather-PM2.5 sensor associations

Command: `python3 -B reports/portfolio/walkthrough_02_sensor_associations.py --output-dir <output-dir>`

Pre-registration: hypotheses, estimands, adjustment set, block policy, seed, multiple-testing rules and the extreme-value review rule were fixed before any estimate was computed (Phase 6 plan and the 2026-09-09 correction addendum). The corrected artifact is `phase_6_statistics_2026-09-09_corrected/`.

## H1/H2 primary family and H3 exploratory contrast (log1p, 1-day blocks)

| Hypothesis | Question | n (sensor-hours) | Estimate | 95% interval | Raw p | Holm-adjusted p | Label |
| --- | --- | --- | --- | --- | --- | --- | --- |
| H1 | Within-sensor PM2.5 vs wind speed (adjusted) | 3951 | -0.207759 | [-0.256867, -0.166087] | 0.0009995 | 0.001999 | inferential |
| H2 | Within-sensor PM2.5 vs relative humidity (adjusted) | 3951 | 0.0986223 | [-0.00576113, 0.186298] | 0.067966 | 0.067966 | inferential |
| H3 | OceanPark minus CMT8 on shared accepted hours | 4070 | 0.179238 | [0.0596894, 0.296092] | 0.0029985 | not applicable | exploratory |

H1/H2 use pairwise-complete weather rows and report the adjusted change in log1p(PM2.5) per one analysis-window standard deviation of the exposure. Holm adjustment covers H1 and H2; H1 remains significant at 0.05 and H2 does not. H3 compares OceanPark minus CMT8 on 2,035 shared hours (4,070 sensor-hours), with temporal adjustment but no weather exposure or multiple-testing adjustment. Its p-value and interval remain exploratory.

## Secondary family (pooled, BH-adjusted)

| Exposure | Estimate | 95% interval | Raw p | BH-adjusted p |
| --- | --- | --- | --- | --- |
| cloud_cover | -0.0900205 | [-0.127017, -0.048308] | 0.001999 | 0.009995 |
| precipitation | -0.0463695 | [-0.0822728, -0.00489393] | 0.035982 | 0.089955 |
| shortwave_radiation | 0.0161321 | [-0.108787, 0.130388] | 0.87956 | 0.87956 |
| surface_pressure | 0.116601 | [-0.032656, 0.253788] | 0.13993 | 0.233217 |
| temperature_2m | -0.0119796 | [-0.121072, 0.0924474] | 0.868566 | 0.87956 |

Only cloud cover survives Benjamini-Hochberg FDR at 0.05. These are pre-declared family members labelled inferential after adjustment; the raw p-values alone are not findings.

## Declared sensitivities (exploratory unless noted)

| Sensitivity | Estimate | 95% interval | Label |
| --- | --- | --- | --- |
| complete_weather_h1 | -0.207809 | [-0.254242, -0.164854] | exploratory |
| complete_weather_h2 | 0.0987359 | [-0.00148072, 0.195322] | exploratory |
| extreme_rule_h1 | -0.207087 | [-0.255557, -0.162165] | exploratory |
| raw_scale_humidity | 1.51054 | [-0.821706, 3.80582] | exploratory |
| raw_scale_primary | -4.50708 | [-5.4884, -3.54721] | exploratory |
| seven_day_blocks_h1 | -0.207759 | point estimate only (gate) | descriptive_only |
| two_day_blocks_h1 | -0.207759 | [-0.259026, -0.159253] | exploratory |
| two_day_blocks_h2 | 0.0986223 | [-0.0251575, 0.209014] | exploratory |

Seven-day blocks are descriptive-only by the pre-declared gate (13 non-overlapping partitions < 30 non-empty / 20 eligible).

## Uncertainty design

- Moving-block bootstrap over Vietnam local calendar days: 2000 replicates, seed 20260908, block lengths [1, 2, 7] days.
- H1 pooled bootstrap: 2000 usable replicates, 0 skipped, 91 sampled dates per replicate.
- Gate: at least 30 non-empty and 20 eligible non-overlapping partitions; one-day blocks give 91/86 non-empty/eligible partitions.
- Adjustments: Holm over the two primary p-values; Benjamini-Hochberg over the five secondary p-values.

Scope: Sensor-level associations over one frozen 90-day window at two non-reference low-cost sites; not city-wide exposure, causal effects or forecast skill.
