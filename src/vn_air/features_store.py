"""Phase 7: bounded read-only extraction for availability-aware features.

One REPEATABLE READ, READ ONLY transaction with verified schema and stored
configuration. Never writes, never migrates, never reads credentials.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

from vn_air.config import load_config
from vn_air.quality import digest, json_default, validate_window

MAX_ROWS_PER_TABLE = 250_000
EXTRACT_VERSION = "phase7_extract_v3"
SCHEMA_REVISION = "0003_response_integrity"
WARMUP_HOURS = max(max((1, 3, 6, 12, 24, 48, 72)), max((3, 6, 12, 24)))
EXTRACT_POLICY = {
    "extraction": "Bounded read-only extraction in one REPEATABLE READ transaction; cutoff-filtered evidence; no writes and no migrations",
    "measurement_window": "Complete hourly intervals with period end in [history_start, end] where history_start = start - warmup_hours; the inclusive lower bound supports the exact 72h lag at the first origin; warm-up rows never create origins or targets before start",
    "warmup_hours": WARMUP_HOURS,
    "evidence_filter": "Rows kept only when recorded_at, retrieved_at and non-null source_published_at are at or before the cutoff; availability at an origin is decided later by the feature builder",
    "model_values_scope": "Open-Meteo forecast snapshot values only; ERA5 and CAMS values are counted for separation diagnostics but not extracted into the feature bundle",
    "row_budget": f"At most {MAX_ROWS_PER_TABLE} rows per extracted table; a larger requirement stops the run",
}
MEASUREMENT_SQL = """
SELECT o.id, o.sensor_id, o.product_id, o.variable_code, o.canonical_unit,
       o.period_start, o.period_end, o.revision, o.value, o.quality_status,
       o.coverage_percent, o.source_published_at, o.recorded_at, o.response_id,
       r.retrieved_at, run.purpose
FROM vn_air.air_quality_observations AS o
JOIN vn_air.source_responses AS r ON r.id = o.response_id
JOIN vn_air.ingestion_runs AS run ON run.id = r.run_id
WHERE o.period_end >= :history_start AND o.period_end <= :end
  AND o.recorded_at <= :cutoff AND r.retrieved_at <= :cutoff
  AND (o.source_published_at IS NULL OR o.source_published_at <= :cutoff)
ORDER BY o.sensor_id, o.period_end, o.revision
"""
SNAPSHOT_SQL = """
SELECT s.id, s.product_id, s.domain, s.data_kind, s.location_id, s.response_id,
       s.model_key, s.model_version, s.run_initialized_at, s.source_published_at,
       s.run_provenance, s.requested_latitude, s.requested_longitude,
       s.grid_latitude, s.grid_longitude, s.recorded_at,
       r.retrieved_at, r.http_status, r.error_code, run.purpose,
       run.window_start, run.window_end
FROM vn_air.model_snapshots AS s
JOIN vn_air.source_responses AS r ON r.id = s.response_id
JOIN vn_air.ingestion_runs AS run ON run.id = r.run_id
WHERE s.recorded_at <= :cutoff AND r.retrieved_at <= :cutoff
ORDER BY s.product_id, s.location_id, s.recorded_at, s.id
"""
MODEL_VALUE_SQL = """
SELECT v.id, v.snapshot_id, v.domain, v.variable_code, v.canonical_unit, v.valid_at,
       v.period_start, v.temporal_support, v.native_interval_seconds,
       v.value, v.quality_status, v.recorded_at
FROM vn_air.modeled_values AS v
JOIN vn_air.model_snapshots AS s ON s.id = v.snapshot_id
JOIN vn_air.source_responses AS r ON r.id = s.response_id
WHERE s.product_id = 'open_meteo_weather_forecast'
  AND v.recorded_at <= :cutoff AND s.recorded_at <= :cutoff AND r.retrieved_at <= :cutoff
ORDER BY v.snapshot_id, v.variable_code, v.valid_at
"""
PRODUCT_VALUE_COUNT_SQL = """
SELECT s.product_id, s.data_kind, count(*) AS value_rows
FROM vn_air.modeled_values AS v
JOIN vn_air.model_snapshots AS s ON s.id = v.snapshot_id
WHERE v.recorded_at <= :cutoff AND s.recorded_at <= :cutoff
GROUP BY s.product_id, s.data_kind
ORDER BY s.product_id
"""


def extract_features(engine, config, *, cutoff, start, end):
    validate_window(cutoff, start, end)
    history_start = start - timedelta(hours=WARMUP_HOURS)
    parameters = {"cutoff": cutoff, "start": start, "end": end, "history_start": history_start}
    queries = dict(measurements=MEASUREMENT_SQL, snapshots=SNAPSHOT_SQL,
                   model_values=MODEL_VALUE_SQL, product_value_counts=PRODUCT_VALUE_COUNT_SQL)
    implementation = {"features_store.py": hashlib.sha256((Path(__file__).parent / "features_store.py").read_bytes()).hexdigest()}
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = '60s'"))
            schema_revision = connection.execute(text(
                "SELECT version_num FROM public.vn_air_schema_version")).scalar_one_or_none()
            if schema_revision != SCHEMA_REVISION:
                raise ValueError("Feature extraction requires schema revision 0003_response_integrity")
            document = config.model_dump(mode="json")
            stored = connection.execute(text(
                "SELECT document FROM vn_air.reference_configs WHERE sha256=:sha AND recorded_at <= :cutoff"),
                {"sha": digest(document), "cutoff": cutoff}).scalar_one_or_none()
            if stored != document:
                raise ValueError("Feature extraction configuration must match a stored configuration eligible at cutoff")
            snapshot_at = connection.execute(text("SELECT transaction_timestamp()")).scalar_one()
            if cutoff > snapshot_at:
                raise ValueError("Extraction cutoff cannot be in the future")

            def fetch(sql):
                rows = [dict(row) for row in connection.execute(text(sql + " LIMIT :row_limit"),
                        parameters | {"row_limit": MAX_ROWS_PER_TABLE + 1}).mappings()]
                if len(rows) > MAX_ROWS_PER_TABLE:
                    raise ValueError("Feature extraction exceeds the row budget; use a reviewed narrower extraction")
                return rows

            measurements = fetch(queries["measurements"])
            snapshots = fetch(queries["snapshots"])
            model_values = fetch(queries["model_values"])
            product_counts = [dict(row) for row in connection.execute(
                text(queries["product_value_counts"] + " LIMIT 100"), parameters).mappings()]
    forecast_ids = {s["id"] for s in snapshots if s["product_id"] == "open_meteo_weather_forecast"}
    excluded = {row["product_id"]: row["value_rows"] for row in product_counts
                if row["product_id"] != "open_meteo_weather_forecast"}
    locations = {location.id: location.model_dump(mode="json") for location in config.locations}
    sensors = {sensor.id: {**sensor.model_dump(mode="json"),
                           "name": locations[sensor.location_id]["name"],
                           "timezone": locations[sensor.location_id]["timezone"]}
               for sensor in config.sensors}
    variables = {variable.code: {"canonical_unit": variable.canonical_unit,
                                 "temporal_support": variable.temporal_support,
                                 "domain": variable.domain,
                                 "representation": variable.representation,
                                 "minimum": variable.minimum,
                                 "maximum": variable.maximum}
                 for variable in config.variables}
    manifest = {"extract_version": EXTRACT_VERSION, "cutoff": cutoff, "start": start, "end": end,
        "history_start": history_start, "warmup_hours": WARMUP_HOURS,
        "configuration_sha256": digest(config.model_dump(mode="json")), "schema_revision": schema_revision,
        "query_sha256": digest(queries), "implementation_sha256": implementation,
        "input_sha256": {"measurements": digest(measurements), "snapshots": digest(snapshots),
                         "model_values": digest(model_values)},
        "input_counts": {"measurements": len(measurements), "snapshots": len(snapshots),
                         "model_values": len(model_values)},
        "excluded_modeled_values_by_product": excluded,
        "policy": EXTRACT_POLICY,
        "extraction": {"snapshot_at_utc": snapshot_at.astimezone(timezone.utc).isoformat(),
                       "isolation_level": "REPEATABLE READ", "read_only": True}}
    dataset = {"sensors": sensors, "locations": locations, "variables": variables,
               "measurements": measurements,
               "snapshots": snapshots,
               "model_values": [row for row in model_values if row["snapshot_id"] in forecast_ids]}
    bundle = json.loads(json.dumps({"manifest": manifest, "dataset": dataset},
                                   default=json_default, allow_nan=False, sort_keys=True))
    bundle["bundle_sha256"] = digest(bundle)
    return bundle
