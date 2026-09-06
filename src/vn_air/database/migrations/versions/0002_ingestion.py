"""Resumable ingestion provenance and private-by-default database access."""

from pathlib import Path

from alembic import op

revision = "0002_ingestion"
down_revision = "0001_environmental_core"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().exec_driver_sql(
        Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"),
        execution_options={"no_parameters": True},
    )


def downgrade():
    # Security hardening is intentionally retained on downgrade.
    op.execute("DROP TABLE vn_air.ingestion_checkpoints")
    op.execute("ALTER TABLE vn_air.model_snapshots DROP COLUMN content_sha256, DROP COLUMN query_sha256")
    op.execute("ALTER TABLE vn_air.source_responses DROP CONSTRAINT source_responses_check2")
    op.execute("ALTER TABLE vn_air.source_responses ADD CONSTRAINT source_responses_check2 CHECK (http_status IS NULL OR http_status <> 200 OR body IS NOT NULL) NOT VALID")
    op.execute("ALTER TABLE vn_air.source_responses DROP COLUMN provider_group, DROP COLUMN request_path, DROP COLUMN attempt, DROP COLUMN elapsed_ms, DROP COLUMN retry_after_seconds")
    op.execute("ALTER TABLE vn_air.ingestion_runs DROP COLUMN target_location_id, DROP COLUMN target_sensor_id")
