# Phase 7 Plan: Availability-Aware Feature Engineering

Status: execution handoff for GLM 5.3 Flash or another coding agent
Date: 2026-09-09 UTC
Repository base: `b850efaa45d0f4a03574074f3ad21f718d803729`
Scope: define, implement and verify leakage-safe feature construction for future
6-hour and 24-hour PM2.5 prediction


## 1. Objective and phase boundary

Phase 7 makes the feature pipeline trustworthy and auditable. It does not train
models, compare model scores, create a dashboard or install a scheduler.

The behavior that must become true is:

> For every forecast origin, every feature is derived only from data whose
> availability is permitted by the declared policy at that origin; every target
> is aligned to the explicit horizon contract; missing periods remain missing;
> and the resulting feature rows can be replayed deterministically from a
> frozen input bundle.

The next phases depend on this contract:

- Phase 8: reproducible chronological baselines.
- Phase 9: ML comparisons and ablations.
- Phase 10: dashboard.
- Phase 11: automation.

Do not claim forecast skill, model performance, operational readiness or health
guidance in Phase 7.

## 2. Frozen project context

The project has completed Phases 1–6. The authoritative Phase 6 artifact is:

`docs/verification/phase_6_statistics_2026-09-09_corrected/`

The last pushed commit is:

`b850efaa45d0f4a03574074f3ad21f718d803729`

The current schema head is:

`0003_response_integrity`

The monitored measured sensors are:

- CMT8: sensor-level PM2.5 at the HCMC station location;
- OceanPark: sensor-level PM2.5 at the Hanoi urban-area station location.

Da Nang remains modeled-only. Do not present it as a measured target.

Read these files completely before editing:

1. `AGENTS.md`
2. `README.md`
3. `docs/architecture.md`
4. `docs/database.md`
5. `docs/source_contracts.md`
6. `docs/decisions/0001-data-sources.md`
7. `docs/ingestion.md`
8. `docs/verification/phase_4.md`
9. `docs/verification/phase_5.md`
10. `docs/verification/phase_6.md`
11. `docs/verification/phase_6_plan.md`
12. `src/vn_air/database/migrations/versions/0001_environmental_core.sql`
13. `src/vn_air/database/migrations/versions/0002_ingestion.sql`
14. `src/vn_air/database/migrations/versions/0003_response_integrity.py`
15. `src/vn_air/quality.py`
16. `src/vn_air/quality_store.py`
17. `src/vn_air/ingestion/pipeline.py`
18. `src/vn_air/ingestion/parsing.py`
19. `tests/test_ingestion.py`
20. `tests/integration/test_schema.py`
21. `tests/integration/test_ingestion_database.py`

Do not read, print, log, commit or paste values from `.env`. Do not expose
credentials, request headers, database URLs or raw secret-bearing exceptions.

## 3. Non-negotiable scientific rules

### 3.1 Separate analytical tracks

Implement two explicit availability modes:

1. `captured`: use only source records with evidence that they were received
   and stored before the origin under the documented conservative policy.
2. `assumed`: use historical records with a user-supplied, explicitly recorded
   lag assumption. This mode is retrospective sensitivity/mechanics output only
   and must never be called an operational backtest.

Never silently fall back from `captured` to `assumed`.

The existing Phase 3 historical backfill was retrieved after the historical
period. Its `retrieved_at` is not historical availability. Do not use those
backfill retrieval times to claim that an operational forecaster knew the data
at an earlier origin.

If the database does not contain enough genuinely captured prospective rows,
produce a diagnostic/limited artifact and state that a prospective collection
period is required. Do not fabricate availability timestamps.

### 3.2 Source separation

Use the following source policy:

- Measured OpenAQ PM2.5 is the target and historical PM feature source.
- Open-Meteo forecast snapshots are the only weather source eligible for the
  captured operational feature track.
- ERA5 reanalysis is retrospective context only. It must be excluded from the
  captured operational feature matrix.
- CAMS modeled air quality remains a separate optional benchmark/context stream.
  Exclude it from the primary measured-target feature matrix.
- Do not replace missing measured PM2.5 with CAMS or any other model output.

Every feature row must retain source/product/data-kind/provenance metadata.

### 3.3 Target contract

Use the database contract already recorded in `docs/database.md`:

For an origin `o` and horizon `h` hours:

- `target_end = o + h hours`
- `target_start = target_end - 1 hour`
- target PM2.5 is the measured hourly interval
  `[target_start, target_end)`, represented by the observation whose
  `period_end = target_end`.

The initial horizons are exactly:

- `6` hours;
- `24` hours.

Origins must be UTC hour boundaries. Derive Vietnam calendar fields with
`Asia/Ho_Chi_Minh`, but do not change the UTC storage/join semantics.

Target labels are not features. A target may be looked up from the eventual
quality-qualified record for evaluation, but its value and its retrieval/storage
timestamps must never enter the feature lineage for the earlier origin.

Keep the target value physically separate from model-ready features: write it to
phase_7_targets.csv, not to phase_7_features.csv. A feature row may carry target
identity, target timestamps, target quality and target-availability flags for
auditing, but it must not carry target_pm25 in the model-ready feature columns.

A target with no eligible measured PM2.5 record remains unavailable. Never
interpolate, carry forward, replace or silently drop it without recording the
reason.

### 3.4 Revision and quality rules

For measured history:

1. Select the latest eligible revision for each sensor and period **within the
   origin availability cutoff**.
2. Filter quality after revision selection.
3. Use `accepted` rows for the primary feature track.
4. Keep missing, invalid, suspect and excluded rows visible in coverage and
   reason counts. Do not resurrect an older accepted revision when a newer
   missing/invalid revision is already eligible.
5. Use actual timestamps to align lags and windows. Never use row position as a
   proxy for elapsed hours.

For model weather values:

- use only finite values with accepted/eligible quality;
- preserve `valid_at`, `period_start`, `temporal_support`,
  `snapshot_id`, `response_id`, `retrieved_at`, `recorded_at`,
  `run_provenance` and `data_kind`;
- choose one eligible forecast vintage per location/origin/target variable;
- never average overlapping snapshots or silently mix vintages.

## 4. Availability policy

Add this policy to the Phase 7 plan/report before generating a real artifact.

### 4.1 Captured mode

A source value is eligible at origin `o` only if all relevant evidence
timestamps are strictly before the origin:

- source response `retrieved_at < o`;
- canonical row `recorded_at < o`;
- for modeled values, snapshot `recorded_at < o` and modeled-value
  `recorded_at < o`;
- non-null `source_published_at` and `run_initialized_at`, when present,
  must also be `< o`;
- the source response is a retained successful response and the row is not
  withheld by the Phase 3 integrity contract.

Because the schema does not record an exact PostgreSQL transaction commit time,
the feature manifest must call this a conservative captured-timestamp policy.
Do not describe it as proof of as-issued provider availability when
`run_provenance=unknown`.

Record:

- `availability_basis = "captured"`;
- `feature_available_through`: the maximum applicable evidence timestamp;
- `availability_safety_note`: the commit-timestamp limitation;
- the full source lineage for every feature.

If a future implementation adds a reviewed commit/availability timestamp, it may
tighten this policy. Do not invent such a column in Phase 7.

### 4.2 Assumed mode

Assumed mode is allowed only when the command explicitly receives a lag
parameter, for example:

```text
--availability assumed --assumed-lag-hours 6
```

The output must record:

- `availability_basis = "assumed"`;
- the exact lag and its unit;
- the affected source/product;
- `availability_assumption`;
- that no operational forecast claim is permitted.

Never use the historical `retrieved_at` of a later backfill as if it were the
historical lag. The assumption is a declared scenario, not observed evidence.

Apply the assumed lag to a declared source event time, not to the later
backfill retrieval time. Use this table and record it in the manifest:

| Source record | Assumed event time | Eligibility rule |
| --- | --- | --- |
| Measured PM2.5 observation | `period_end` | `period_end + assumed_lag < origin` |
| Reanalysis/model value used only in an explicitly retrospective scenario | `valid_at` | `valid_at + assumed_lag < origin` |
| Forecast snapshot with known initialization | `run_initialized_at` | `run_initialized_at + assumed_lag < origin` |
| Forecast snapshot with unknown initialization | none | reject as ambiguous; do not invent an event time |

Captured mode uses the actual evidence timestamps instead of this table. A
forecast value with `valid_at > origin` is allowed in captured mode only when
its forecast snapshot passed the captured evidence checks; `valid_at` is the
future target time, not the receipt time. Reanalysis values with `valid_at >
origin` are never allowed in an operational/captured matrix.

### 4.3 Forecast-vintage selection

For captured forecast weather, eligible snapshots must satisfy the origin
availability policy and match:

- product: `open_meteo_weather_forecast`;
- `data_kind = forecast`;
- the requested station location;
- the requested model key/configuration.

Select a single snapshot deterministically. Use this ranking, documented in the
manifest:

1. latest known `run_initialized_at` when available;
2. latest known `source_published_at` when available;
3. latest `retrieved_at`;
4. latest snapshot `recorded_at`;
5. stable snapshot UUID as final tie-break.

If provenance is unknown, preserve that fact and label the selected vintage
unknown-provenance. Do not call it an as-issued operational run.

### 4.4 Temporal-support alignment

For a target interval `[target_start, target_end)`:

- instantaneous weather variables join at `target_start`;
- `preceding_hour_mean` and `preceding_hour_sum` variables join at
  `target_end`, because they describe the preceding target hour;
- PM2.5 target joins at `target_end`;
- historical PM features use their actual `period_end` timestamps.

The implementation must read `variables.temporal_support`/the reviewed config
rather than inferring support from variable names.

## 5. Feature catalog

Implement the following minimum catalog. Additional features require a written
manifest entry and tests.

### 5.1 Known-at-origin calendar features

For each origin/horizon:

- origin UTC timestamp;
- origin Vietnam local date/hour/weekday;
- target local date/hour/weekday;
- horizon hours;
- sensor/location identifiers.

These are deterministic calendar facts, not measured observations.

### 5.2 PM2.5 history features

Use accepted measured PM2.5 only:

- exact lags: `pm25_lag_1h`, `pm25_lag_3h`,
  `pm25_lag_6h`, `pm25_lag_12h`, `pm25_lag_24h`,
  `pm25_lag_48h`, `pm25_lag_72h`;
- latest available value at or before origin:
  `pm25_last_available`;
- its age in hours: `pm25_last_age_hours`;
- trailing statistics ending at origin:
  `pm25_trailing_mean_3h`, `pm25_trailing_mean_6h`,
  `pm25_trailing_mean_12h`, `pm25_trailing_mean_24h`,
  `pm25_trailing_std_24h`;
- observation counts for every trailing window.

Rules:

- exact lags require the exact expected period-end timestamp;
- trailing windows use timestamp bounds, not list positions. For a window of
  `w` hours ending at origin `o`, include period ends in `(o - w hours, o]`;
  the strict complete-window count is exactly `w`;
- the strict feature variant requires every expected hourly observation in its
  window; otherwise the value is null and the count is still reported;
- no centered windows, backward fills, interpolation or zero filling;
- `pm25_last_age_hours` must expose staleness rather than hiding it.

Do not decide model eligibility by silently deleting rows in the feature builder.
Emit reason/coverage fields; later baseline/model phases may predeclare their own
eligibility masks.

### 5.3 Forecast-weather features

For each horizon and target interval, expose the reviewed weather variables:

- temperature;
- apparent temperature;
- relative humidity;
- precipitation;
- surface pressure;
- cloud cover;
- shortwave radiation;
- wind speed;
- wind direction represented only as `sin`/`cos` components.

Do not expose raw wind direction as an ordinary linear feature.

Use explicit names such as:

- `weather_forecast_temperature_2m`;
- `weather_forecast_relative_humidity_2m`;
- `weather_forecast_wind_speed_10m`;
- `weather_forecast_wind_direction_sin`;
- `weather_forecast_wind_direction_cos`.

Each weather feature must have corresponding lineage and missingness metadata.
Do not add ERA5 fields to the captured matrix under a forecast-looking name.

### 5.4 Availability and lineage fields

Every feature row must include:

- `sensor_id`, `location_id`, `origin`, `horizon_hours`;
- `target_start`, `target_end`;
- target identity/timestamps, `target_quality` and `target_available` flags;
- `feature_available_through`;
- `availability_basis`;
- `availability_assumption` when applicable;
- `feature_version`;
- `input_manifest_sha256`;
- `lineage` or a separately keyed lineage table containing source IDs,
  timestamps, snapshot/vintage IDs, quality and data-kind;
- feature missingness/reason fields.

The target value belongs only in `phase_7_targets.csv`; it must not be copied
into `phase_7_features.csv` or the feature lineage. Do not include raw response
bodies in feature artifacts.

## 6. Required implementation shape

Keep the feature computation pure and replayable. Use the existing package
style and standard-library-compatible data structures; do not add a modeling
library in Phase 7.

Add these components:

### 6.1 Read-only input extraction

Add a small read-only extractor, preferably:

- `src/vn_air/features_store.py`

It must execute bounded queries in a `REPEATABLE READ`, read-only transaction
and verify:

- schema revision `0003_response_integrity`;
- stored configuration hash matches the requested config;
- explicit UTC cutoff/window;
- row budgets;
- no writes or migrations.

The extracted input bundle must include only the fields needed for features:

- selected/revisioned measured observations and source-response timing;
- model snapshots, source-response timing, run purpose/provenance and coordinates;
- modeled values, temporal support, quality and storage timing;
- reference/config manifest and query/code hashes.

Do not reuse the retrospective `latest_air_quality` or
`weather_observations` views as if they were origin-as-of views. Add explicit
as-of selection logic.

### 6.2 Pure feature builder

Add:

- `src/vn_air/features.py`

The module must:

- validate the input-bundle hash and schema/config boundary;
- construct the origin grid;
- construct both target horizons;
- select as-of measured revisions;
- select eligible forecast vintages;
- align temporal support;
- construct features and lineage;
- construct shared chronological split metadata;
- refuse future evidence;
- produce deterministic JSON-serializable output.

Use deterministic sorting and stable tie-breakers everywhere. Round only
presentation fields; do not round timestamps or values before leakage checks.

### 6.3 Output writer

Add:

- `src/vn_air/features_output.py`

Write only to a new directory and refuse overwrite. Required files:

- `phase_7_feature_summary.json`;
- `phase_7_features.csv`;
- `phase_7_targets.csv`;
- `phase_7_assumptions.md`;
- `SUCCESS.json`.

If lineage is too wide for the feature CSV, write
`phase_7_lineage.csv` as an additional hashed file and keep a stable
`lineage_id` in the feature rows.

`phase_7_targets.csv` must contain one row per sensor/origin/horizon target
candidate, including target PM2.5 when available, target quality, target
observation/revision identifiers, target retrieval/storage timestamps and the
reason when unavailable. It is an evaluation-label artifact, never a feature
input.

The summary manifest must include:

- input bundle digest/file hash;
- configuration/schema/query/code hashes;
- feature version and catalog;
- availability mode and assumption;
- source/product/data-kind policy;
- target/horizon contract;
- origin range and split boundaries;
- row counts by sensor/horizon/availability basis;
- missingness and exclusion reasons;
- number of rows rejected for future evidence;
- number of rows rejected for ambiguous vintage;
- output implementation hashes.

### 6.4 CLI

Add a `features` command group to `src/vn_air/cli.py`:

```bash
vn-air features extract \\
  --cutoff <UTC> --start <UTC> --end <UTC> \\
  --config configs/study.json --output <new-input-bundle.json>

vn-air features build \\
  --bundle <input-bundle.json> \\
  --output-dir <new-output-directory> \\
  --horizons 6 24 --availability captured

vn-air features build \\
  --bundle <input-bundle.json> \\
  --output-dir <new-output-directory> \\
  --horizons 6 24 --availability assumed \\
  --assumed-lag-hours <positive-number>

vn-air features replay \\
  --bundle <input-bundle.json> \\
  --output-dir <new-output-directory>
```

Requirements:

- all output paths must be new;
- `build` and `replay` must not access the database;
- `extract` is read-only and must not migrate or write source data;
- `--assumed-lag-hours` is mandatory for assumed mode and forbidden for
  captured mode;
- no implicit default from captured to assumed;
- no model training or prediction insertion.

## 7. Chronological split and purge contract

Phase 7 does not fit a model, but it must emit a split manifest for Phase 8/9.

Use one shared UTC time split for both sensors and both horizons. Do not choose
different cutoffs because one sensor has better coverage.

Unless a reviewed data-window decision changes it before execution, use:

- first 60% of the origin range: train;
- next 20%: validation;
- final 20%: untouched test.

Round boundaries to UTC hour boundaries and record exact timestamps in the
manifest before any baseline/model fitting.

Purging rules:

- remove a train origin when its target interval reaches into validation or
  later;
- remove a validation origin when its target interval reaches into test or
  later;
- do not use test targets, test-derived statistics or test coverage to choose
  features;
- preserve the final test period even if it has low coverage;
- report the number of purged origins separately from missing-feature rows.

Feature transformations, scaling, feature selection and climatology statistics
must be fitted on training rows only in later phases. Phase 7 may define their
interfaces but must not fit them globally.

If the available origin range is too short to support all three periods, stop
with a documented `insufficient_time_window` status. Do not shrink the test
period silently.

## 8. Tests

Add `tests/test_features.py` with deterministic synthetic input bundles.

Required unit tests:

1. Target alignment:
   - 6h and 24h target start/end satisfy the exact contract;
   - origins are UTC-hour aligned.
2. Revision selection:
   - latest eligible revision is chosen before quality filtering;
   - a later invalid/missing revision prevents resurrection of an older value.
3. Availability:
   - any response/storage timestamp after origin is rejected;
   - captured mode never uses a later backfill retrieval;
   - assumed mode requires and records its lag;
   - captured and assumed rows cannot be mixed silently.
4. Source separation:
   - ERA5 is rejected from the captured forecast feature matrix;
   - CAMS is excluded from the primary measured-target matrix;
   - Open-Meteo forecast values retain snapshot/vintage lineage.
5. Forecast-vintage selection:
   - one deterministic snapshot is selected;
   - ties resolve by the documented ranking;
   - overlapping snapshots are not averaged.
6. Temporal support:
   - instant variables join at target start;
   - preceding-hour mean/sum variables join at target end;
   - wrong interval alignment is rejected.
7. PM history:
   - exact timestamp lags do not bridge gaps;
   - row order cannot create a false lag;
   - strict trailing windows become null when an expected hour is missing;
   - age and observation counts are correct.
8. Wind direction:
   - sine/cosine encoding is correct;
   - raw direction is absent from model-ready feature columns.
9. Sensor isolation:
   - CMT8 values never enter OceanPark features and vice versa.
10. Leakage:
    - no feature lineage timestamp exceeds origin;
    - target values/target timestamps do not appear in feature inputs;
    - future forecast values are allowed only when their snapshot was available
      before origin.
11. Split/purge:
    - shared cutoffs are identical across sensors;
    - horizon-overlapping origins are purged;
    - final test rows remain untouched.
12. Determinism:
    - same input bundle and policy produce byte-identical output;
    - tampered input/hash mismatch stops the build;
    - existing output directories are rejected.

Add integration coverage in
`tests/integration/test_features_database.py` if the extractor is added:

- read-only transaction is enforced;
- schema/config boundary checks work;
- as-of revision/vintage selection matches the synthetic database;
- no database rows are inserted or modified;
- isolated PostgreSQL schema tests continue to pass.

## 9. Execution sequence

Follow this order exactly.

### Step 0 — Inspect and establish the policy

Run:

```bash
git status --short
git log -1 --oneline
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -q
```

Write `docs/verification/phase_7_plan.md` (this document) before generating
features or evaluating any model. Do not modify Phase 4–6 frozen artifacts.

### Step 1 — Implement synthetic core first

Implement the pure feature builder and synthetic tests before connecting it to a
database. Make the synthetic bundle contain:

- both sensors;
- multiple revisions;
- missing hours;
- an invalid later revision;
- forecast snapshots with overlapping vintages;
- ERA5 and CAMS rows;
- captured and assumed timing cases;
- all temporal-support classes.

Run:

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_features -v
```

Fix all failures before any live extraction.

### Step 2 — Implement the read-only extractor

Add the bounded extraction command and tests. Use a new input-bundle filename;
never overwrite an existing evidence file.

The extractor must not read `.env` itself, print secrets, write source tables,
run migrations or use the Phase 5 EDA bundle as a substitute for availability
metadata.

If no current database rows meet captured availability for historical origins,
report that fact in the artifact. Do not convert the result into an operational
dataset.

### Step 3 — Build a captured artifact if evidence exists

Use a new dated output directory, for example:

`docs/verification/phase_7_features_2026-09-09_captured/`

Run the exact command documented by the implemented CLI. Confirm:

- no feature lineage timestamp is after its origin;
- no ERA5/CAMS value appears in the primary captured matrix;
- each forecast target has one selected vintage or an explicit missing reason;
- target alignment is exact;
- both sensors use shared split boundaries;
- all missingness/purge/rejection counts are reported;
- output hashes are present.

If captured evidence is insufficient, stop at a limited diagnostic artifact and
state that a prospective collection period is required. Do not use assumed mode
without an explicit user-authorized scenario.

### Step 4 — Optional assumed mechanics artifact

Only when explicitly authorized, build a separate assumed-lag artifact with a
new directory, for example:

`docs/verification/phase_7_features_2026-09-09_assumed_lag6h/`

Keep it visibly separate from captured output. It is useful for testing feature
assembly, but it cannot support operational forecast claims or model skill.

### Step 5 — Deterministic replay

Run `features replay` into a different new directory or a temporary directory.
Compare SHA-256 hashes for every output file, not only the summary manifest.

### Step 6 — Verification gates

Run:

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
git diff --check
```

The isolated PostgreSQL suite must use its own disposable cluster. If the
runtime blocks PostgreSQL shared memory, report the exact environment blocker;
do not substitute a live Supabase write or the project database.

If a live Supabase extraction is performed, use the project-scoped read-only
workflow and the Supabase skill first. Never use the live database as a write
target for feature generation.

### Step 7 — Documentation update after gates

Only after the implementation and evidence gates pass:

1. Write `docs/verification/phase_7.md` with actual commands, hashes, counts,
   availability limitations and replay results.
2. Update `AGENTS.md` to state the verified Phase 7 artifact and preserve the
   Phase 8 boundary.
3. Update the README roadmap/status only with evidence-backed claims.
4. Keep Phase 8 baselines, Phase 9 ML, dashboard work and scheduling marked
   planned.
5. Do not commit or push unless separately authorized.

## 10. Stop conditions

Stop and report the exact reason if any of the following occurs:

- schema revision is not `0003_response_integrity`;
- configuration or input-bundle hash does not match;
- a feature uses a source timestamp after origin;
- a target value enters feature lineage;
- latest revision is selected after quality filtering;
- multiple forecast vintages are averaged or mixed;
- ERA5 is used in the captured operational matrix;
- CAMS is treated as measured truth;
- a gap is bridged by row position, interpolation or fill;
- shared chronological cutoffs cannot be established;
- the time window cannot support train/validation/test and purge;
- availability is unknown but the output is labelled operational;
- an existing artifact would be overwritten;
- a database write, migration or secret exposure would be required.

Do not “fix” a stop condition by weakening the policy.

## 11. Acceptance criteria

Phase 7 is complete only when all applicable criteria are true:

- `docs/verification/phase_7_plan.md` exists and records the target,
  availability, source, temporal-support, missingness and split contracts.
- A pure, deterministic feature builder exists with a versioned catalog.
- A bounded read-only input extractor exists, or a documented blocker explains
  why captured extraction cannot yet be produced.
- Captured and assumed availability are separate and explicit.
- The target contract is enforced for 6h and 24h.
- Latest revisions are selected before quality filtering.
- No feature is available after its origin.
- No feature crosses a timestamp gap incorrectly.
- Forecast vintages are selected deterministically without averaging.
- ERA5/CAMS are excluded from the captured primary feature matrix.
- Wind direction is encoded circularly; raw direction is not a linear feature.
- Shared chronological split and horizon purge metadata are emitted.
- Required synthetic leakage/time-alignment/source-separation tests pass.
- Offline tests pass.
- Isolated PostgreSQL tests pass, or the exact environment limitation is
  documented without overstating verification.
- Deterministic replay is byte-identical.
- `git diff --check` is clean.
- No model was trained, no prediction was inserted, no schedule was installed,
  no migration was added without separate review, and no secret was exposed.
- The final report makes no forecast-skill, causal, city-wide or operational
  claim unsupported by captured availability evidence.

## 12. Final handoff format

After execution, report:

1. artifact and input-bundle paths;
2. feature version and availability mode;
3. exact target/horizon and split contracts;
4. row counts by sensor, horizon, source and eligibility reason;
5. number of captured versus assumed rows;
6. number of future-evidence, missing-target, missing-feature and purged rows;
7. selected forecast-vintage counts and unknown-provenance counts;
8. changed files and implementation hashes;
9. test commands/results;
10. deterministic replay hash comparison;
11. database write/migration status;
12. remaining blocker before Phase 8 baselines.

Do not report a model score because Phase 7 does not train or evaluate a model.

## Phase 7 correction addendum — 2026-09-09

This addendum is a dated amendment to the plan above. It records mechanical
contract corrections found during review of the first Phase 7 implementation.
They do not change the scientific target definition, the 6h/24h horizons, the
source policy, the split fractions, the purge rule, the missingness policy or any
model result — no model result has been computed. The original captured artifact
(`phase_7_features_2026-09-09_captured/`) is preserved unchanged; a corrected
artifact supersedes it for verification only. The following decisions are
predeclared before the corrected artifact is generated:

1. A build can accept a new explicitly extracted window. The old frozen
   2026-06-08/2026-09-06 boundary is an optional verification fixture, not a
   permanent runtime constant. Every input manifest is still validated with the
   standard UTC/hour-boundary/window rules; a `--require-frozen-boundary` flag
   re-enables the frozen assertion for the historical diagnostic.
2. A measurement warm-up interval of `max(max(PM_LAG_HOURS), max(TRAILING_HOURS))`
   hours (= 72 here) before the origin start is extracted so the full lag and
   trailing catalog is available at the first origins. The origin/target window
   is unchanged; pre-window rows are never target candidates and never create
   origins before `start`. Origins lacking warm-up rows emit null features with
   explicit reasons and coverage metadata.
3. Assumed-mode forecast values follow the declared event-time policy
   (`run_initialized_at + assumed_lag < origin`); they may carry later backfill
   storage timestamps, remain retrospective assumptions, and are never
   operational evidence. Captured mode keeps the storage/evidence-time policy.
4. Captured forecast selection requires product, domain, data kind, purpose
   (`poll`), the reviewed configured model key (`ecmwf_ifs`), the configured
   station location, requested coordinates matching the configured station
   coordinates (tolerance <= 1e-6 degrees), a successful non-error response and
   the captured availability policy. Grid coordinates are diagnostics only.
   Snapshots are never averaged.
5. Modeled-value timestamps and source metadata are part of feature lineage and
   leakage checks; captured leakage fails when any used value's storage
   timestamp is not strictly before the origin.
6. Unaccepted target values are represented as null labels with an explicit
   missing reason; identity, quality and source timestamps remain in the target
   file for audit but the rejected numerical value is never copied.
7. Temporal support validates both the support class and the period_start
   alignment (instant: `period_start == valid_at`; preceding-hour classes:
   `period_start == valid_at − 1h`).
8. Summary-bound replay binds the recorded request to the exact input bundle
   digest, input file digest, feature version, horizons, availability basis and
   lag; explicit-parameter replay records that it was reconstructed and does not
   claim summary-bound status.
9. Status is `limited_diagnostic` unless BOTH required data families have
   available evidence at at least one origin: accepted PM history and eligible
   forecast weather. Separate PM and weather available-origin counts, plus
   any-feature and complete-feature-set row counts, are recorded; under the
   captured basis these are the captured-origin counts.
10. The corrected frozen diagnostic is a new artifact and remains limited until
    prospective data exists.

## Phase 7 final-fix note — 2026-09-09 (v2 review)

This note records a mechanical correction to status accounting and input-table
integrity found during the v2 review. It does not change the target definition,
availability policy, source policy, split policy, purge rule, missingness policy
or any model result; no model result has been computed. Predeclared before the
final artifact is generated:

1. `pm_available_origin_count` counts sensor/origin states with at least one
   finite accepted PM2.5 row eligible under the selected availability policy;
   raw revisions, invalid, missing, suspect or non-finite rows never count as
   usable feature evidence.
2. `weather_available_origin_count` counts location/origin states with at least
   one finite accepted weather value from an identity-valid selected snapshot
   that passes availability and temporal-support/period-start alignment for at
   least one requested horizon; each location/origin counts once, not once per
   horizon. Partial but valid weather evidence counts as family availability
   even when no row has a complete feature set.
3. Status is `ok` only when both required families have at least one usable
   origin; otherwise `limited_diagnostic` with `status_missing_families` naming
   the missing families.
4. `load_bundle` and the builder verify the declared input-table hashes
   (`measurements`, `snapshots`, `model_values`) by recomputing them with the
   project digest helper and comparing to `manifest.input_sha256`; a re-signed
   bundle with altered table content is rejected. The output manifest records
   the verified hashes in an `input_integrity` section.
5. `availability_basis` is restricted to `captured` and `assumed` at the Python
   API boundary; descriptive policy keys are not accepted values.

## Phase 7 registry-boundary correction addendum — 2026-09-10

This is a mechanical registry-boundary correction found during review. It does
not change the scientific target, horizons, availability modes, source policy,
split/purge rules or any model result. The complete reviewed variable, sensor
and location registries are now validated before feature construction, and
modeled-value identity/support consistency is enforced. Synthetic unit tests
may use an explicit fixture-only reviewed configuration path; real CLI build and
replay require reviewed configuration validation. No corrected artifact is
generated before this addendum is recorded.

## Phase 7 derived-sensor-metadata hardening addendum — 2026-09-10

The registry-boundary review found one additional mechanical gap after the v4
correction: a re-signed bundle could mutate the extracted sensor `name` or
`timezone` fields while leaving the reviewed location registry and configuration
digest unchanged. The builder uses the sensor timezone for Vietnam-local
calendar features, so these derived fields are part of the effective boundary.

The standalone execution plan
(`docs/verification/phase_7_registry_hardening_plan.md`) was recorded before
the hardened artifact was generated. The v5 correction therefore validates
sensor `name` and `timezone` against the reviewed sensor's referenced station
location, rejects non-station sensor references, and preserves every prior
variable, sensor, location, identity, duplicate-key, table-hash, availability,
target, lineage and split/purge rule. It changes no scientific estimand or
result. The v4 artifact remains preserved unchanged and is superseded by the
hardened v5 artifact for verification.

## Phase 7 snapshot-boundary hardening addendum — 2026-09-10

Adversarial review of the v5 path found that malformed or unknown snapshot
identity could be ignored or surface as an unhelpful raw exception: snapshot
`domain`, `data_kind` and `product_id` were not fully bound to the reviewed
product registry, and modeled-value domain was not checked against its snapshot.

The standalone execution plan
(`docs/verification/phase_7_snapshot_boundary_hardening_plan.md`) was recorded
before the next artifact was generated. The v6 correction now validates required
snapshot identity fields, reviewed product domain/kind for every snapshot,
modeled-value/snapshot domain consistency, embedded registry IDs and safe
missing-location rejection handling. It preserves all prior registry, table
hash, availability, source, target, lineage and split/purge contracts. It does
not change any scientific estimand or result. The v5 artifact remains preserved
unchanged and is superseded by the v6 snapshot-hardened artifact for
verification.

## Phase 7 structural-schema hardening addendum — 2026-09-10

Adversarial fuzzing after the v6 snapshot-boundary correction found malformed
rows that could raise raw `KeyError`, `TypeError` or `AttributeError`, or omit a
required modeled-value field without a deterministic structural rejection. The
standalone plan
(`docs/verification/phase_7_structural_schema_hardening_plan.md`) was recorded
before the next artifact. The v7 correction validates mapping/list/object
shapes and required measurement, snapshot and modeled-value fields before any
timestamp conversion or feature construction. Every malformed case now raises
`FeatureError`; no data is repaired or filled. All v6 registry, hash,
availability, source, target, lineage and split/purge contracts remain
unchanged. The v6 artifact remains preserved and is superseded by the v7
structural-hardened artifact for verification.
