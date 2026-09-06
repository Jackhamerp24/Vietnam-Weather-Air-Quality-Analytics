"""Safe aggregate evidence without response bodies, connection URIs or secrets."""

from sqlalchemy import text
from datetime import datetime, timezone


def ingestion_report(engine):
    queries = {
        "database": "SELECT current_setting('server_version') AS server_version, pg_database_size(current_database()) AS bytes",
        "revision": "SELECT version_num FROM public.vn_air_schema_version",
        "runs": "SELECT product_id, status, count(*) AS runs, sum(inserted_count) AS inserted, sum(unchanged_count) AS unchanged, sum(quarantined_count) AS quarantined FROM vn_air.ingestion_runs GROUP BY product_id, status ORDER BY product_id, status",
        "measurements": "SELECT sensor_id, count(*) AS revisions, count(DISTINCT period_end) AS distinct_hours, min(period_start) AS first_start, max(period_end) AS last_end, max(revision) AS max_revision FROM vn_air.air_quality_observations GROUP BY sensor_id ORDER BY sensor_id",
        "measurement_quality": "SELECT sensor_id, quality_status, count(*) AS hours FROM vn_air.latest_air_quality GROUP BY sensor_id, quality_status ORDER BY sensor_id, quality_status",
        "modeled": "SELECT s.product_id, s.location_id, count(DISTINCT s.id) AS snapshots, count(*) AS values, min(v.valid_at) AS first_valid, max(v.valid_at) AS last_valid FROM vn_air.model_snapshots s JOIN vn_air.modeled_values v ON v.snapshot_id=s.id GROUP BY s.product_id, s.location_id ORDER BY s.product_id, s.location_id",
        "model_quality": "SELECT s.product_id, v.quality_status, count(*) AS values FROM vn_air.modeled_values v JOIN vn_air.model_snapshots s ON s.id=v.snapshot_id GROUP BY s.product_id, v.quality_status ORDER BY s.product_id, v.quality_status",
        "responses": "SELECT provider_group, http_status, error_code, count(*) AS requests, sum(octet_length(body)) AS body_bytes FROM vn_air.source_responses GROUP BY provider_group, http_status, error_code ORDER BY provider_group, http_status",
        "quality_issues": "SELECT issue_code, severity, count(*) AS issues FROM vn_air.data_quality_issues GROUP BY issue_code, severity ORDER BY issue_code",
        "checkpoints": "SELECT count(*) AS completed_chunks FROM vn_air.ingestion_checkpoints",
        "predictions": "SELECT count(*) AS predictions FROM vn_air.model_predictions",
        "recent_runs": "SELECT id, product_id, target_sensor_id, target_location_id, status, window_start, window_end, inserted_count, unchanged_count, quarantined_count, error_code FROM vn_air.ingestion_runs ORDER BY started_at DESC LIMIT 12",
    }
    with engine.begin() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        return {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "purpose": "Aggregate ingestion verification, not model results or a released observation dataset",
                **{name: [dict(row) for row in connection.execute(text(sql)).mappings()] for name, sql in queries.items()}}
