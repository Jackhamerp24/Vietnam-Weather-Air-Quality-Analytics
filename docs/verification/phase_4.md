# Phase 4 Data-Quality Verification

Date: 2026-09-07 UTC. Scope: frozen structural audit of the stored Phase 3
dataset. This phase does not claim calibration, environmental truth, city-wide
exposure, causal relationships, statistical significance, predictive skill or
production monitoring.

## Implementation

The installed `vn-air data-quality audit` command performs a read-only extraction
from PostgreSQL and writes a new local JSON artifact. It uses:

- the stored reference configuration and schema head `0003_response_integrity`;
- one `REPEATABLE READ`, `READ ONLY` transaction;
- 30-second statement, 5-second lock and 60-second idle-transaction limits;
- a 250,000-row limit per extracted table;
- an explicit UTC cutoff and measurement window;
- SHA-256 hashes for the configuration, SQL, implementation inputs, extracted
  tables, manifest and result.

Source observations and model tables remain untouched. The output path refuses
to overwrite an existing file.

## Frozen Scope

| Item | Value |
| --- | --- |
| Extraction cutoff | 2026-09-06T20:59:00.669630Z |
| Measurement window | 2026-06-08T00:00:00Z through 2026-09-06T00:00:00Z |
| Measurement semantics | Complete hourly intervals with period end in `(start, end]` |
| Evidence artifact | [phase_4_quality_2026-09-07_final.json](phase_4_quality_2026-09-07_final.json) |

The audit selects the latest eligible measurement revision before applying
quality status. It selects a model capture before checking variables or values,
so a newer capture that omits a field does not silently fall back to an older
capture. ERA5, forecasts, CAMS and OpenAQ remain separate products.

## Findings

- CMT8 contains 2,154 of 2,160 expected hours: 99.7222% coverage and a longest
  gap of 3 hours.
- OceanPark contains 2,037 of 2,160 expected hours: 94.3056% coverage and a
  longest gap of 119 hours, from 2026-07-01T02:00Z through 2026-07-06T00:00Z.
- Every selected measured hour is provisionally `accepted`; no selected value
  violated the stored finite/nonnegative/unit/null checks, triggered the PM
  review threshold, matched the sentinel candidates, or carried a provider flag.
- CMT8 has 24 revised intervals. All 24 transitions changed source metadata
  only; none changed the PM2.5 value. OceanPark has no revised interval.
- No measured interval showed a duration, UTC-hour-boundary, coordinate-drift,
  or reviewed-licence-date violation.
- The stored run history contains 107 succeeded runs and one failed run at the
  cutoff. The failed run and one `station_timezone_changed` quarantine remain
  visible.
- The measured-to-ERA5 alignment diagnostic finds all nine weather variables at
  2,033 accepted CMT8 hours and 1,916 accepted OceanPark hours under the stated
  temporal-support policy. Weather joins remain a later analytical decision.
- The model audit reports source snapshots, valid-time gaps, overlapping captures,
  grid displacement, quality counts and unknown native cadence without averaging
  repeated vintages. Da Nang remains modeled-only.

## Verification

| Check | Result |
| --- | --- |
| Offline tests | 58 passed; 2 credential checks skipped because `.env` was not loaded |
| Isolated PostgreSQL tests | 45 passed |
| Installed CLI live audit | Passed; final artifact written |
| `git diff --check` | Passed |
| Database writes during audit | None; transaction was read-only |

## Limits

The artifact reports structural quality and provenance. It cannot establish
low-cost sensor calibration, outdoor siting, population exposure, causal weather
effects or historical provider availability. Backfilled retrieval age measures
collection lag, not the original reporting latency. ERA5 and CAMS values remain
model/reanalysis context, not measured ground truth. Missing values and gaps
remain visible; the audit performs no deletion or imputation.

The next phase can use this artifact to define a coverage-qualified analytical
dataset and EDA plan. It should preserve the frozen selection rules and disclose
the OceanPark outage, the shorter ERA5 history and the model-vintage limits.
