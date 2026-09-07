"""Read-only extraction queries for the Phase 4 audit."""

import hashlib
from datetime import timezone
from pathlib import Path

from sqlalchemy import text

from vn_air.quality import digest, validate_window


MAX_ROWS_PER_TABLE = 250_000


MEASUREMENT_SQL = """
SELECT o.id, o.response_id, o.sensor_id, o.product_id, o.variable_code, o.canonical_unit,
       o.period_start, o.period_end, o.revision, o.value,
       o.quality_status, o.coverage_percent, o.source_flags,
       o.source_metadata, o.latitude, o.longitude, o.recorded_at,
       r.retrieved_at, run.purpose
FROM vn_air.air_quality_observations AS o
JOIN vn_air.source_responses AS r ON r.id = o.response_id
JOIN vn_air.ingestion_runs AS run ON run.id = r.run_id
WHERE o.period_end > :start AND o.period_end <= :end
  AND o.recorded_at <= :cutoff AND r.retrieved_at <= :cutoff
ORDER BY o.sensor_id, o.period_end, o.revision
"""

SNAPSHOT_SQL = """
SELECT s.id, s.response_id, s.product_id, s.location_id, s.model_key, s.data_kind,
       s.run_provenance, s.recorded_at, r.retrieved_at,
       run.purpose, run.window_start, run.window_end,
       s.requested_latitude, s.requested_longitude,
       s.grid_latitude, s.grid_longitude
FROM vn_air.model_snapshots AS s
JOIN vn_air.source_responses AS r ON r.id = s.response_id
JOIN vn_air.ingestion_runs AS run ON run.id = r.run_id
WHERE s.recorded_at <= :cutoff AND r.retrieved_at <= :cutoff
ORDER BY s.product_id, s.location_id, s.recorded_at, s.id
"""

MODEL_VALUE_SQL = """
SELECT v.id, v.snapshot_id, v.domain, v.variable_code, v.canonical_unit,
       v.valid_at, v.period_start, v.temporal_support,
       v.native_interval_seconds, v.value, v.quality_status,
       v.source_flags, v.recorded_at
FROM vn_air.modeled_values AS v
JOIN vn_air.model_snapshots AS s ON s.id = v.snapshot_id
JOIN vn_air.source_responses AS r ON r.id = s.response_id
WHERE v.recorded_at <= :cutoff AND s.recorded_at <= :cutoff
  AND r.retrieved_at <= :cutoff
ORDER BY v.snapshot_id, v.variable_code, v.valid_at
"""

RESPONSE_SQL = """
SELECT id, product_id, provider_group, http_status, error_code, requested_at,
       retrieved_at, body IS NOT NULL AS body_retained, body_sha256
FROM vn_air.source_responses
WHERE retrieved_at <= :cutoff
ORDER BY retrieved_at, id
"""

RUN_SQL = """
SELECT id, product_id, purpose, started_at, window_start, window_end,
       CASE WHEN finished_at <= :cutoff THEN status ELSE 'running' END AS status,
       CASE WHEN finished_at <= :cutoff THEN finished_at END AS finished_at,
       CASE WHEN finished_at <= :cutoff THEN error_code END AS error_code
FROM vn_air.ingestion_runs
WHERE started_at <= :cutoff
ORDER BY started_at, id
"""

ISSUE_SQL = """
SELECT issue_code, severity, detected_at
FROM vn_air.data_quality_issues
WHERE detected_at <= :cutoff
ORDER BY detected_at, id
"""

QUARANTINE_SQL = """
SELECT q.reason_code, q.recorded_at
FROM vn_air.quarantined_records AS q
JOIN vn_air.source_responses AS r ON r.id = q.response_id
WHERE q.recorded_at <= :cutoff AND r.retrieved_at <= :cutoff
ORDER BY q.recorded_at, q.id
"""


def extract_audit(engine, config, *, cutoff, start, end):
    """Extract only fields needed by the audit in one frozen read-only snapshot."""
    validate_window(cutoff, start, end)
    parameters = {"cutoff": cutoff, "start": start, "end": end}
    queries = dict(measurements=MEASUREMENT_SQL, snapshots=SNAPSHOT_SQL,
                   model_values=MODEL_VALUE_SQL, responses=RESPONSE_SQL,
                   runs=RUN_SQL, issues=ISSUE_SQL, quarantines=QUARANTINE_SQL)
    implementation = {name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
                      for name in ("quality.py", "quality_store.py", "config.py", "ingestion/parsing.py")}
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(text("SET LOCAL idle_in_transaction_session_timeout = '60s'"))
            schema_revision = connection.execute(text(
                "SELECT version_num FROM public.vn_air_schema_version"
            )).scalar_one()
            snapshot_at = connection.execute(text("SELECT transaction_timestamp()")).scalar_one()
            if cutoff > snapshot_at:
                raise ValueError("Audit cutoff cannot be in the future")
            if schema_revision != "0003_response_integrity":
                raise ValueError("Audit requires the reviewed schema revision 0003_response_integrity")
            document = config.model_dump(mode="json")
            stored = connection.execute(text("SELECT document FROM vn_air.reference_configs WHERE sha256=:sha AND recorded_at <= :cutoff"),
                                        {"sha": digest(document), "cutoff": cutoff}).scalar_one_or_none()
            if stored != document:
                raise ValueError("Audit configuration must match a stored configuration eligible at cutoff")

            def fetch(sql):
                rows = [dict(row) for row in connection.execute(text(sql + " LIMIT :row_limit"),
                        parameters | {"row_limit": MAX_ROWS_PER_TABLE + 1}).mappings()]
                if len(rows) > MAX_ROWS_PER_TABLE:
                    raise ValueError("Audit extraction exceeds the row budget; use a reviewed narrower extraction")
                return rows

            result = {
                **{name: fetch(sql) for name, sql in queries.items()},
                "schema_revision": schema_revision,
                "query_sha256": digest(queries),
                "implementation_sha256": digest(implementation),
                "extraction": {
                    "snapshot_at_utc": snapshot_at.astimezone(timezone.utc).isoformat(),
                    "isolation_level": "REPEATABLE READ",
                    "read_only": True,
                    "source_tables": [
                        "air_quality_observations", "source_responses", "ingestion_runs",
                        "model_snapshots", "modeled_values", "data_quality_issues",
                        "quarantined_records",
                    ],
                },
            }
    return result


def write_audit(path, report_text, engine=None):
    """Write a new local artifact; the database handle exists for call-site clarity."""
    del engine
    with path.open("x", encoding="utf-8") as handle:
        handle.write(report_text + "\n")
