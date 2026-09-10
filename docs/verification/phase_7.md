# Phase 7 Feature Engineering Verification

Date: 2026-09-10 UTC. Scope: availability-aware, leakage-safe feature construction
for future 6-hour and 24-hour PM2.5 prediction, with a read-only extractor, a
pure deterministic builder, chronological split/purge metadata and a captured
availability artifact. No model was trained, no prediction was inserted, no
schedule was installed and no database migration or write occurred. No
forecast-skill, causal, city-wide, operational or health claim is supported.

**Authoritative artifact: `phase_7_features_2026-09-10_structural_hardened/`**
(`phase7_features_v7`). The earlier artifacts are preserved unchanged and
superseded for verification: `phase_7_features_2026-09-09_captured/`
(`phase7_features_v1`), `phase_7_features_2026-09-09_corrected/`
(`phase7_features_v2`) and `phase_7_features_2026-09-09_final/`
(`phase7_features_v3`), plus the intermediate
`phase_7_features_2026-09-10_final/` (`phase7_features_v4`) and
`phase_7_features_2026-09-10_hardened/` (`phase7_features_v5`) and
`phase_7_features_2026-09-10_snapshot_hardened/` (`phase7_features_v6`). The v2 review (Corrections A–J of
[phase_7_correction_plan.md](phase_7_correction_plan.md)) fixed ten latent
contract gaps, and the final fix
([phase_7_final_fix_plan.md](phase_7_final_fix_plan.md)) corrected two v2
findings: (P1-A) status counts now measure usable accepted feature evidence —
`pm_available_origin_count` requires a finite accepted PM2.5 row and
`weather_available_origin_count` requires a finite accepted, identity-valid,
availability-passing, alignment-passing weather value per location/origin — so
invalid-only input can no longer produce `status = ok`; and (P1-B) the declared
input-table hashes (`measurements`, `snapshots`, `model_values`) are recomputed
and verified before every build, with re-signed tampered bundles rejected and
the verified hashes recorded in an `input_integrity` manifest section.
`availability_basis` is restricted to `captured`/`assumed` at the API boundary.
The v3 review also found a registry-boundary gap: a re-signed bundle could alter
the variable registry while retaining the reviewed configuration digest. The
2026-09-10 correction validates the complete reviewed variable, sensor and
location registries, modeled-value identity/support consistency and duplicate
modeled-value keys before construction. It is recorded in the
[registry-boundary correction plan](phase_7_registry_fix_plan.md) and the dated
addendum in [phase_7_plan.md](phase_7_plan.md).
The subsequent hardening review found that extracted sensor `name` and
`timezone` were not bound to the reviewed station registry. The v5 correction
binds both fields to the referenced reviewed station; its execution is recorded
in [phase_7_registry_hardening_plan.md](phase_7_registry_hardening_plan.md).
The final adversarial pass found that malformed or unknown snapshot product
identity could be ignored or raise a raw key error. The v6 correction binds
every snapshot to the reviewed product domain/data kind, validates required
identity fields and modeled-value/snapshot domain consistency, and records the
work in
[phase_7_snapshot_boundary_hardening_plan.md](phase_7_snapshot_boundary_hardening_plan.md).
The final structural review found malformed rows that could raise raw Python
exceptions. The v7 correction validates JSON shapes and required table fields
before timestamp conversion; its execution is recorded in
[phase_7_structural_schema_hardening_plan.md](phase_7_structural_schema_hardening_plan.md).

## Contract

The implementation follows [phase_7_plan.md](phase_7_plan.md) and its correction
addendum: the target contract (`target_end = origin + h`, target row
`[target_end − 1h, target_end)`, targets stored separately from features,
unaccepted targets as null labels with reasons), the captured/assumed
availability policy (evidence timestamps strictly before the origin; assumed lag
applied to declared event times — `period_end + lag` for measurements,
`run_initialized_at + lag` for forecast snapshots — with later backfill storage
timestamps allowed only under the assumed basis), source separation (measured
OpenAQ PM2.5 for targets/history; Open-Meteo forecast snapshots as the only
captured weather source with product/domain/data-kind/purpose/model-key/
location/requested-coordinate checks; ERA5 and CAMS excluded), revision-before-
quality selection with a deterministic composite tie-break, exact-timestamp
lags, strict trailing windows, 72-hour warm-up extraction
(`history_start = start − 72h`, inclusive), wind direction as sin/cos only,
temporal support plus period_start validation, one shared 60/20/20
chronological split with horizon purge, config/bundle boundary checks
(`--config` required from the CLI; frozen boundary optional via
`--require-frozen-boundary`), summary-bound replay bound to the exact input
bundle digest, file digest, feature version, horizons, availability basis and
lag, and deterministic replay.

## Implementation

- `src/vn_air/features.py` (`phase7_features_v7`): pure builder with reviewed
  variable/sensor/location registry validation, modeled-value identity checks,
  duplicate-key rejection, derived sensor name/timezone binding, reviewed
  snapshot-product identity and embedded-ID checks, structural row/type and
  required-field checks that normalize malformed input to `FeatureError`,
  boundary-mode handling, warm-up metadata, truthful
  two-family status over usable accepted evidence, per-value weather lineage,
  value-level leakage guards, and input-table hash verification.
- `src/vn_air/features_store.py` (`phase7_extract_v3`): bounded read-only
  extraction in one `REPEATABLE READ`, `READ ONLY` transaction; schema
  revision, stored-configuration, cutoff/window and 250,000-row budget checks;
  warm-up measurement window `[start − 72h, end]`; forecast-only model values;
  full snapshot identity fields (requested/grid coordinates, model key/version,
  purpose, response status).
- `src/vn_air/features_output.py`: writers for the six output files; refuses
  existing directories.
- `src/vn_air/cli.py`: `features extract|build|replay`; `build`/`replay` never
  touch the database; `--assumed-lag-hours` mandatory for assumed and forbidden
  for captured; `--config` required for build/replay;
  `--require-frozen-boundary` optional; summary-bound replay rejects any
  bundle/file/request mismatch and inherits the recorded boundary mode; an
  explicit-parameter replay is recorded as `replay_request_mode: explicit` in
  the CLI result and never claims summary-bound status.

## Final captured artifact (limited diagnostic)

The frozen window still contains no prospectively captured evidence, so the
final artifact reports `status = limited_diagnostic` with BOTH families missing
(`status_missing_families: ["pm_history", "forecast_weather"]`),
`pm_available_origin_count = 0`, `weather_available_origin_count = 0`,
`rows_with_any_data_feature = 0` and `prospective_collection_period_required =
true`. The final run was built with `--require-frozen-boundary` and the reviewed
configuration (`config_validation.mode = reviewed_config`, forecast model key
`ecmwf_ifs`), from the registry-validated input bundle whose declared table hashes were
verified before the build (`input_integrity.verified = true`).

Registry-validated input bundle: `phase_7_input_bundle_2026-09-10_registry.json`
(bundle digest `4cf5e9537758308a67c09e00cc9af3931946bab8ea64c6520cac36f1d3ed3c4e`,
file SHA-256 `c797e03a21f45d00fc5dd92647a0c37106476860cae2d47b19a3a8757c530894`;
4,215 measurements, 72 snapshots, 1,296 forecast model values; warm-up window
from 2026-06-05T00:00Z with 0 pre-window rows — the Phase 3 backfill starts at
the window edge).

Normal CLI invocation (environment-blocked for v7 by the local dataless
`.venv` package stall):

```bash
PYTHONPATH=src .venv/bin/python -B -m vn_air.cli features build \
  --bundle docs/verification/phase_7_input_bundle_2026-09-10_registry.json \
  --config configs/study.json \
  --output-dir docs/verification/phase_7_features_2026-09-10_structural_hardened \
  --horizons 6 24 --availability captured --require-frozen-boundary

PYTHONPATH=src .venv/bin/python -B -m vn_air.cli features replay \
  --bundle docs/verification/phase_7_input_bundle_2026-09-10_registry.json \
  --config configs/study.json \
  --summary docs/verification/phase_7_features_2026-09-10_structural_hardened/phase_7_feature_summary.json \
  --output-dir <new-replay-directory>
```

Output directory: `phase_7_features_2026-09-10_structural_hardened/`
(manifest SHA-256 `6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa`,
`feature_version phase7_features_v7`; the input bundle's declared table hashes,
complete reviewed registries, derived sensor metadata, snapshot/product
identity and structural schema were verified before the build).

For v7, the equivalent pure-builder/output-writer path was used to materialize
the artifact because importing the CLI was blocked by the local macOS dataless
`.venv` SQLAlchemy/Pydantic files. The request, reviewed configuration digest,
input bundle and builder checks are identical to the CLI path; no database
connection was opened.

## Counts

| Item | Value |
| --- | --- |
| Boundary | mode `frozen`; frozen-boundary assertion applied |
| Origins | 2,137 hourly UTC origins, 2026-06-08T00:00Z to 2026-09-05T00:00Z (end − max horizon) |
| Warm-up | `history_start` 2026-06-05T00:00Z (72h); 0 selected pre-window rows per sensor |
| Feature rows | 8,548 = 2 sensors × 2,137 origins × 2 horizons |
| Split (shared) | train 5,128; validation 1,708; test 1,712; boundaries 2026-07-31T10:00Z and 2026-08-18T05:00Z |
| Purged rows | 112 (56 target-reaches-validation, 56 target-reaches-test); test untouched |
| Targets | 8,290 accepted; 258 absent (129 grid gaps × 2 horizons); unaccepted values stored as null labels with reasons |
| PM/weather available origins | 0 / 0 (truthful two-family status; limited diagnostic) |
| Rows with any / complete data features | 0 / 0; rows with full 72h lag coverage 0 (no pre-window history exists) |
| Registry validation | variable, sensor and location registries verified; reviewed config SHA-256 `296be9aad8aa2f1ffdaf908333c247de042d9ee69f6523857a865f7b2f2c5570` |
| Derived sensor metadata | bundle `name` and `timezone` are bound to the referenced reviewed station |
| Snapshot/product boundary | required snapshot identity, reviewed product domain/data kind, modeled-value domain and embedded IDs verified |
| Structural schema | required row shapes/fields validated; malformed input raises `FeatureError` |
| Snapshot identity rejections | none required (both poll snapshots fail on availability, not identity); 2 snapshots never eligible |
| Future-evidence rejections / ambiguous vintages | 0 / 0 (captured mode; the leakage guard would stop the run) |

No target value appears in the feature CSV or lineage; no feature lineage
timestamp violates its origin; weather lineage now records, per used value,
the feature names, value id, variable code, valid_at, period_start, temporal
support, quality, value recorded_at, snapshot identity, coordinates, response
and snapshot/run timestamps and the availability basis.

## Tests and verification

| Check | Result |
| --- | --- |
| `tests/test_features.py` (synthetic, v7) | 85 non-CLI builder/regression tests passed, including malformed row/type/required-field rejection; the five CLI replay tests remain environment-blocked. |
| `tests/integration/test_features_database.py` (isolated PostgreSQL) | Prior v5 gate: 7 Phase 7 integration tests passed; v7 changed no database code and its rerun was blocked by the same local package hydration stall |
| Offline suite | Full v7 rerun blocked by the local dataless `.venv` package stall; all non-CLI v7 offline classes passed (85 tests). The prior v5 full run was 180 passed, 2 credential skips. |
| Isolated PostgreSQL suite | Prior v5 disposable-cluster run: 52 passed. The v7 rerun was blocked by the same local package hydration stall; v7 changed no database code. |
| `git diff --check` | Clean |
| Deterministic replay | Pure-builder replay byte-identical for all six output files including SUCCESS.json; final manifest SHA-256 `6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa` |
| Database writes | None; the recorded live extraction ran in a READ ONLY transaction against Supabase; no migration |
| Secrets | `.env` sourced only for the documented live extract; no credential values read into tool output |

## Limits and next-phase boundary

Captured availability does not exist for the frozen historical window; a
prospective collection period is required before any captured operational
feature matrix or Phase 8 baseline can run on real data. The assumed-lag
mechanics are implemented and tested but no assumed artifact was generated —
that requires an explicitly user-authorized scenario (for example
`--availability assumed --assumed-lag-hours 6`), and it would remain a declared
scenario, never an operational backtest. Feature transformations, scaling,
feature selection and climatology statistics are not fitted here; Phase 8
baselines and Phase 9 ML must fit them on training rows only. The Phase 6
statistics boundary is unchanged; Phase 6 claims nothing about forecast skill.
