# Phase 7 Correction Plan: Resolve Review Findings

Status: execution handoff for GLM 5.3 Flash
Date: 2026-09-09 UTC
Base implementation: Phase 7 worktree after the first GLM execution
Scope: correct the Phase 7 feature pipeline before prospective data or Phase 8 baselines are used

This document is the next execution plan for the same agent that implemented
Phase 7. Preserve the useful implementation and the current evidence, but do
not treat the first Phase 7 handoff as fully verified until every correction and
acceptance gate below is complete.

## 1. Review decision and evidence

Current review status: Request changes.

The current frozen diagnostic is internally consistent:

- input bundle:
  docs/verification/phase_7_input_bundle_2026-09-09.json
- current artifact:
  docs/verification/phase_7_features_2026-09-09_captured/
- current feature version: phase7_features_v1
- current artifact status: limited_diagnostic
- current manifest digest:
  86ebc5d81f98f3bb331eb99389b205a02b08c0f319a77a22bcc5892b406cf3d8
- current input bundle digest:
  9726689ba953b37ffb20b4e434f7236dd3008c0da3b3b0ac22cb9f31e37aa3bf
- current repository base:
  b850efaa45d0f4a03574074f3ad21f718d803729

Independent checks already completed:

- artifact SUCCESS hashes match every output file;
- replay was byte-identical for all six output files;
- offline suite passed 126 tests with 2 documented credential skips;
- git diff --check passed;
- all PM/weather value columns in the captured artifact are null, as expected;
- the current captured conclusion is correct: the frozen historical window has
  no prospectively captured PM/weather feature evidence.

The isolated PostgreSQL suite was reported as 51 passed by the prior execution.
A direct rerun in this runtime is blocked before tests by the operating system:
PostgreSQL initdb cannot create a shared-memory segment
(shmget: Operation not permitted). Report this limitation accurately if it
continues. Do not replace the isolated suite with a write against Supabase.

The review findings below are latent contract problems. They are not visible in
the current artifact because no captured PM/weather values were eligible.

## 2. Guardrails

- Preserve the existing captured artifact unchanged. Do not overwrite or delete
  docs/verification/phase_7_features_2026-09-09_captured/.
- Generate a new corrected artifact, for example:
  docs/verification/phase_7_features_2026-09-09_corrected/
- Do not silently change the target definition, 6h/24h horizons, source
  separation, quality policy, split fractions, purge rule or missingness policy.
- Do not generate an assumed-lag artifact unless the user explicitly authorizes
  that scenario. Synthetic assumed-mode tests are required and are sufficient
  for this correction pass.
- Do not poll providers, install a scheduler, add a database migration, train a
  model or insert predictions as part of this correction plan.
- Do not read, print, log, commit or paste values from .env.
- Do not commit or push unless the user separately authorizes it after review.
- Use apply_patch for manual edits.
- Keep Phase 8 baselines and Phase 9 ML out of this correction.

## 3. Pre-change correction addendum

Before generating the corrected artifact, append a dated section to
docs/verification/phase_7_plan.md, preserving the original plan text. Call it
"Phase 7 correction addendum — 2026-09-09".

State explicitly that the changes are mechanical contract corrections found
during review. They do not change the scientific target, horizons, source
policy, split policy or any model result, and no model result has been computed.

The addendum must predeclare:

1. A build can accept a new explicitly extracted window. The old frozen window is
   an optional verification boundary, not a permanent runtime constant.
2. A measurement warm-up interval of max(PM_LAG_HOURS, max(TRAILING_HOURS))
   hours is extracted before the origin start. The origin/target window remains
   unchanged.
3. Assumed-mode forecast values use the declared event-time policy and may have
   later backfill storage timestamps; they remain retrospective assumptions and
   never operational evidence.
4. Captured forecast selection requires product, data kind, purpose/model,
   location and coordinate checks.
5. Modeled-value timestamps and source metadata are part of feature lineage and
   leakage checks.
6. Unaccepted target values are represented as null labels with an explicit
   missing reason.
7. Temporal support validates both support class and period_start.
8. Replay binds the summary request to the exact input bundle digest and file
   digest.
9. Captured status is limited unless both required data families have captured
   evidence: accepted PM history and eligible forecast weather. Record separate
   PM and weather captured-origin counts.
10. The corrected frozen diagnostic is a new artifact and remains limited until
    prospective data exists.

Do not compute or regenerate the corrected artifact before this addendum is
written.

## 4. Correction A — support prospective windows without weakening frozen checks

### Problem

src/vn_air/features.py currently hardcodes:

- FROZEN_CUTOFF;
- FROZEN_START;
- FROZEN_END;

and load_bundle rejects any bundle whose manifest differs from those values.
That makes the required future prospective collection period impossible to
process through the implemented CLI.

### Required implementation

Refactor boundary validation as follows:

1. Remove unconditional runtime rejection against FROZEN_START/FROZEN_END/
   FROZEN_CUTOFF.
2. Always validate the input manifest with validate_window:
   - UTC-aware cutoff/start/end;
   - hour-aligned bounds;
   - positive window;
   - end <= cutoff.
3. Keep the old frozen constants only as a named verification fixture or
   optional expected-boundary policy.
4. Add an optional CLI flag to build/replay:
   --require-frozen-boundary
5. When the flag is supplied, require the current Phase 4/Phase 7 boundary.
   When omitted, accept a new valid input bundle.
6. Record in the output manifest:
   - boundary_mode: frozen or explicit;
   - boundary values;
   - input origin window;
   - whether the frozen-boundary assertion was applied.
7. The corrected frozen artifact must be built with
   --require-frozen-boundary.
8. A future prospective bundle must be buildable without that flag and must
   retain its own explicit cutoff/window in the manifest.

Update CLI help and documentation. Do not infer a prospective window from
system time.

### Required tests

Add tests that prove:

- the existing frozen bundle succeeds with --require-frozen-boundary;
- a shifted synthetic input window succeeds without the flag;
- the same shifted bundle is rejected with the flag;
- invalid UTC/window boundaries still stop the build;
- replay preserves the selected boundary mode.

## 5. Correction B — extract warm-up history for 72-hour features

### Problem

features_store.py currently extracts measurements only where:

period_end > start AND period_end <= end

The feature catalog requires exact PM lags up to 72 hours and trailing windows
ending at the origin. The first 72 hours of a new origin window therefore cannot
use otherwise available history.

### Required implementation

1. Define:
   max_history_hours = max(max(PM_LAG_HOURS), max(TRAILING_HOURS)).
2. Add history_start = start - max_history_hours.
3. Query measured observations with:
   period_end > history_start AND period_end <= end.
4. Keep manifest start/end as the origin/target window, and add:
   history_start and warmup_hours.
5. Keep target lookup limited to target periods in the origin/target window.
6. Do not allow pre-window history to create origins before start.
7. Include warm-up counts and whether each origin had sufficient history in the
   manifest and assumptions report.
8. Keep revision selection and quality filtering unchanged:
   latest eligible revision first, quality second.
9. The same warm-up behavior must work for captured and assumed modes.

Do not solve this by shifting the first origin forward silently. If an origin
lacks warm-up rows, emit null features and an explicit reason.

### Required tests

Add synthetic rows before start and prove:

- lag_72h is populated when the exact pre-start row exists;
- lag_72h is null when it is absent;
- trailing windows use exact timestamps;
- the first origin remains at start;
- the warm-up rows are not included as target candidates;
- input counts and warm-up metadata are deterministic.

## 6. Correction C — implement assumed forecast availability according to the plan

### Problem

The plan declares that assumed forecast availability is based on
run_initialized_at + assumed_lag_hours. The builder currently filters modeled
values by recorded_at < origin for every availability mode. That silently
rejects a valid assumed historical forecast value merely because it was
retrieved/stored later during backfill.

The current code path is in features.py around the usable_values construction.

### Required implementation

Split value eligibility by availability basis:

Captured mode:

- snapshot evidence must precede origin;
- modeled-value recorded_at must precede origin;
- successful response and quality checks remain required;
- future evidence raises a hard error.

Assumed mode:

- snapshot must have known run_initialized_at;
- run_initialized_at + assumed_lag_hours < origin;
- modeled values from that selected snapshot may be used despite later
  backfill recorded_at;
- the output must label the row and every affected lineage record as assumed;
- no operational/as-issued claim is allowed;
- unknown run initialization remains rejected as ambiguous.

Do not use retrieved_at as the assumed historical event time. Do not make
assumed mode bypass source/product/model/location/quality validation.

Add to lineage:

- value_id;
- variable_code;
- valid_at;
- period_start;
- temporal_support;
- value quality;
- value recorded_at;
- snapshot_id;
- product_id;
- data_kind;
- model_key/model_version;
- run_initialized_at;
- source_published_at;
- response retrieved_at;
- availability_basis.

### Required tests

Add a synthetic test where:

- snapshot initialization is before origin;
- assumed lag is satisfied;
- model values are recorded after origin;
- assumed mode includes the values;
- captured mode excludes the values;
- lineage clearly records the assumed basis and later storage timestamp.

Retain the existing unknown-initialization rejection test.

## 7. Correction D — enforce forecast source/vintage identity

### Problem

The current builder filters only product/data_kind and can select an
unexpected model key, purpose or location-coordinate combination. This is
unobservable in the limited artifact because no snapshot is eligible.

### Required extraction changes

Extend snapshot extraction to include:

- requested_latitude;
- requested_longitude;
- grid_latitude;
- grid_longitude;
- model_key;
- model_version;
- purpose;
- product/data_kind/domain;
- response status/error;
- retrieved_at and snapshot recorded_at.

The current query already includes some of these; verify every required field is
retained in the bundle and manifest.

### Required builder checks

For captured forecast weather, accept a snapshot only when:

- product_id is open_meteo_weather_forecast;
- domain is weather;
- data_kind is forecast;
- purpose is poll;
- model_key equals the reviewed configured model key (ecmwf_ifs);
- location_id is the configured sensor station location;
- requested coordinates match the configured station coordinates within a
  documented tolerance (use exact config values or <= 1e-6 degrees);
- response is successful and not error-bearing;
- availability timestamps pass the captured policy.

For assumed mode, preserve the same source/product/model/location checks. Only
the availability timing differs.

Never select by grid coordinates alone. Preserve grid coordinates for
diagnostics. Never average snapshots.

### Required tests

Add tests for:

- wrong model key;
- wrong purpose;
- wrong location;
- requested-coordinate mismatch;
- wrong product/data kind;
- duplicate/overlapping snapshots;
- deterministic ranking after invalid candidates are removed.

## 8. Correction E — complete lineage and leakage checks

### Problem

The current lineage records model value IDs but not enough metadata to audit each
feature's source. The leakage guard checks snapshot timestamps but not the
timestamps of the modeled values actually used.

### Required implementation

For each weather feature used, build a deterministic per-variable lineage map.
Store it as JSON in the lineage CSV or as normalized rows in an additional
lineage CSV. At minimum record:

- feature name;
- value id;
- variable code;
- valid_at;
- period_start;
- temporal_support;
- quality_status;
- value recorded_at;
- snapshot id;
- product id;
- data_kind;
- model key/version;
- requested/grid coordinates;
- response id/retrieved_at;
- snapshot recorded_at;
- run_initialized_at;
- source_published_at;
- availability basis.

Add value-level max timestamps to the lineage summary:

- weather_max_value_recorded_at;
- weather_max_value_retrieved_at if applicable.

Captured leakage checks must include these value-level timestamps and fail when
any is >= origin.

Assumed leakage checks must validate the declared event-time rule while
preserving later storage timestamps as an explicit limitation.

Update feature_available_through to be the maximum relevant timestamp under the
selected availability policy, and document whether it is evidence time or
assumed event time.

### Required tests

- a used model value recorded at/after origin fails captured mode;
- the same value can be represented in assumed mode only when event-time lag
  passes;
- lineage contains every required field;
- feature-to-lineage mapping is one-to-one and deterministic;
- no target value or target source timestamp appears in feature lineage.

## 9. Correction F — make target quality semantics safe

### Problem

The target CSV currently copies final.value even when the final revision is
not accepted. That exposes invalid/suspect target values alongside
target_available=false.

### Required implementation

When final target quality is not accepted or value is non-finite:

- target_available = false;
- target_pm25 = null;
- target_missing_reason identifies target_absent or target_not_accepted_<status>;
- preserve target observation/revision identity for audit;
- preserve quality/status and source timestamps in the target file;
- do not copy the rejected numerical value into the target label.

Accepted target values remain unchanged.

### Required tests

Add invalid, missing and suspect target revisions and assert:

- target_pm25 is null;
- target_available is false;
- reason and revision metadata remain present;
- an older accepted target is not resurrected.

## 10. Correction G — validate temporal support completely

### Problem

weather_feature_set currently checks only the temporal_support string. It
does not verify period_start against valid_at.

### Required implementation

For each weather value:

- instant: require period_start == valid_at;
- preceding_hour_mean: require period_start == valid_at - 1 hour;
- preceding_hour_sum: require period_start == valid_at - 1 hour;
- otherwise mark alignment mismatch and do not use the value.

Use UTC-aware exact timestamp comparisons. Keep the existing target-start/
target-end valid_at policy.

### Required tests

Add a value with correct support but incorrect period_start and assert it is
rejected. Retain the existing wrong-support test.

## 11. Correction H — bind replay to the exact input bundle

### Problem

features replay with --summary reads the request fields from the summary but
does not verify that the supplied input bundle is the same bundle used for the
summary.

### Required implementation

When --summary is supplied:

- load the summary manifest;
- compare summary.bundle_sha256 with the loaded input bundle digest;
- compare summary.bundle_file_sha256 with the current input file SHA-256;
- compare feature_version, horizons, availability_basis and assumed lag;
- reject any mismatch before building.

When explicit replay parameters are supplied without --summary, record that
the request was explicitly reconstructed and do not claim summary-bound replay.

### Required tests

- summary + different bundle rejects;
- summary + same semantic content but different file bytes rejects if the
  recorded file digest differs;
- summary + changed horizons/availability rejects;
- same summary/bundle remains byte-identical.

## 12. Correction I — validate configuration and input-bundle boundary

### Problem

load_bundle verifies only a self-consistent bundle hash and schema revision.
A modified bundle whose contents and self-reported hash are both recomputed can
pass. The builder also does not verify that the bundle configuration digest
matches the reviewed config used by the CLI.

### Required implementation

Add an optional expected-config validation path:

- build/replay accept --config configs/study.json;
- load the reviewed config;
- compare digest(config.model_dump(mode="json")) to
  bundle.manifest.configuration_sha256;
- verify configured sensors, station locations, timezone and forecast model key;
- reject mismatch.

Keep pure unit tests able to use synthetic bundles by making config validation
optional at the Python function boundary, but require it from the real CLI.

Record config validation mode and config digest in the output manifest.

Add required-bundle structural checks:

- required manifest keys;
- input table hashes/counts;
- sensor IDs and location IDs;
- variables/domain/temporal-support schema;
- snapshot/value foreign-key consistency.

### Required tests

- recomputed bundle hash with changed configuration is rejected when --config
  is supplied;
- missing required manifest fields reject;
- value referencing an absent snapshot rejects;
- changed model key/config rejects;
- valid synthetic bundle remains usable without external config only in unit
  tests.

## 13. Correction J — make limited status truthful

### Problem

The current status becomes ok when either PM history or weather snapshots have
some eligible rows:

captured_possible = PM availability OR weather availability.

That can label a matrix as okay even though one required feature family is
entirely unavailable.

### Required implementation

Track separately:

- pm_captured_origin_count;
- weather_captured_origin_count;
- rows_with_any_captured_feature;
- rows_with_complete_captured_feature_set.

Set status:

- ok only when both required families have captured evidence for at least one
  origin and the artifact is not otherwise blocked;
- limited_diagnostic when either required family has zero captured origins;
- include a reason map identifying which family is missing.

Keep calendar-only rows distinguishable from data-feature rows. Do not claim
operational readiness merely because calendar features exist.

Add tests for:

- PM only;
- weather only;
- both;
- neither.

## 14. Implementation files

Expected changes:

- src/vn_air/features.py
- src/vn_air/features_store.py
- src/vn_air/features_output.py
- src/vn_air/cli.py
- tests/test_features.py
- tests/integration/test_features_database.py
- docs/verification/phase_7_plan.md
- docs/verification/phase_7.md
- AGENTS.md and README.md only after all gates pass

Do not add a migration. The current schema is sufficient for this correction.
If a schema limitation genuinely blocks the contract, stop and report it
instead of silently changing the database.

## 15. Execution order

### Step 0 — Baseline

Run:

~~~bash
git status --short
git log -1 --oneline
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -q
git diff --check
~~~

Record the baseline. Preserve the original diagnostic artifact.

### Step 1 — Write the correction addendum

Update phase_7_plan.md with the predeclared addendum in section 3. Do this
before regenerating any corrected artifact.

### Step 2 — Implement pure code corrections

Implement Corrections A–J in small patches. Keep code stdlib-only and deterministic.
Do not run live extraction while the focused synthetic tests are failing.

### Step 3 — Expand synthetic tests first

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_features -v
~~~

The focused suite must cover every required test in Corrections A–J, including
at least one synthetic prospective window and one assumed late-backfill
forecast-value case.

### Step 4 — Update integration tests

Update/add integration tests for:

- warm-up extraction window;
- source/model/purpose/coordinate filters;
- read-only behavior;
- config/bundle boundary;
- input counts and hashes;
- no database writes.

Run the isolated suite when the environment permits it:

~~~bash
PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
~~~

If initdb is blocked by OS shared memory, retain the exact error and do not
claim an independently rerun integration suite.

### Step 5 — Regenerate corrected frozen diagnostic

Use a new input bundle path and output directory. Do not overwrite the old
artifact:

~~~bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli features extract \
  --cutoff 2026-09-06T20:59:00.669630Z \
  --start 2026-06-08T00:00:00Z \
  --end 2026-09-06T00:00:00Z \
  --config configs/study.json \
  --output docs/verification/phase_7_input_bundle_2026-09-09_corrected.json

PYTHONPATH=src .venv/bin/python -B -m vn_air.cli features build \
  --bundle docs/verification/phase_7_input_bundle_2026-09-09_corrected.json \
  --config configs/study.json \
  --output-dir docs/verification/phase_7_features_2026-09-09_corrected \
  --horizons 6 24 \
  --availability captured \
  --require-frozen-boundary
~~~

Use the actual CLI flags after implementing them, but preserve the semantics.
Do not generate assumed output without user authorization.

### Step 6 — Replay

Run replay into a separate new directory or a temporary directory. Use the
summary-bound invocation and verify all output file hashes, not only the
manifest:

~~~bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli features replay \
  --bundle docs/verification/phase_7_input_bundle_2026-09-09_corrected.json \
  --summary docs/verification/phase_7_features_2026-09-09_corrected/phase_7_feature_summary.json \
  --output-dir <new-replay-directory> \
  --config configs/study.json
~~~

### Step 7 — Full verification

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
git diff --check
~~~

Confirm:

- corrected artifact hashes;
- all six output files;
- corrected input bundle hash;
- no feature value lineage timestamp violates captured origin;
- no target value appears in feature CSV/lineage;
- no invalid/suspect target value appears in target_pm25;
- warm-up metadata is present;
- prospective boundary mode is supported;
- PM/weather status counts are truthful;
- replay is byte-identical.

### Step 8 — Update documents

Only after all applicable gates pass:

1. Update docs/verification/phase_7.md with the correction addendum, corrected
   artifact hash, actual counts, tests and replay result.
2. Mark the original 2026-09-09 captured artifact preserved but superseded for
   verification if the corrected artifact changes the implementation contract.
3. Update AGENTS.md and README.md to point to the corrected artifact.
4. Keep the prospective-collection blocker explicit.
5. Keep Phase 8 baselines marked blocked/next until captured data exists.
6. Do not commit or push without separate authorization.

## 16. Acceptance criteria

Phase 7 correction is complete only when:

- a new valid prospective input window can be extracted and built without
  editing Python constants;
- frozen-boundary mode still protects the original diagnostic;
- warm-up rows support the full 72h lag catalog;
- assumed forecast values follow event-time lag and captured values follow
  storage/evidence-time policy;
- forecast product/data kind/model/purpose/location/coordinate checks pass;
- no snapshots are averaged;
- modeled-value lineage is complete and value-level leakage is checked;
- invalid/suspect targets have null target_pm25;
- temporal support and period_start are both validated;
- summary-bound replay rejects a mismatched bundle/config/request;
- configuration and input-bundle boundaries are checked;
- status requires both PM and weather captured families;
- corrected artifact is deterministic and non-overwriting;
- focused synthetic tests pass;
- offline suite passes;
- isolated PostgreSQL suite passes or its environment blocker is documented;
- git diff --check passes;
- no migration, database write, scheduler, model training or secret exposure
  occurred.

Do not mark Phase 7 verified if only the frozen all-null diagnostic passes while
the prospective/assumed contracts remain untested.

## 17. Final handoff format

After execution, report:

1. corrected input bundle and artifact paths;
2. old artifact preservation status;
3. corrected manifest/file hashes;
4. boundary mode and prospective-window test result;
5. warm-up hours and first-origin history coverage;
6. captured/assumed PM and weather origin counts;
7. source/vintage rejection counts;
8. target missing/invalid/suspect counts;
9. lineage completeness and leakage-test results;
10. exact test commands/results;
11. replay hash comparison;
12. PostgreSQL verification result or exact OS blocker;
13. whether Phase 8 remains blocked by lack of prospective captured data.

Do not claim forecast skill, operational readiness, causal effects, city-wide
exposure or model performance from this phase.
