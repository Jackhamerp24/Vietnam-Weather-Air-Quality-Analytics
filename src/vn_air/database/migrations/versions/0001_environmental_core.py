"""Source-aware environmental data, immutable revisions and forecast vintages."""

from pathlib import Path

from alembic import op


revision = "0001_environmental_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().exec_driver_sql(
        Path(__file__).with_suffix(".sql").read_text(encoding="utf-8"),
        execution_options={"no_parameters": True},
    )


def downgrade():
    # Explicit dependency order; never CASCADE into unowned objects.
    for view in ("latest_air_quality", "weather_observations", "modeled_air_quality"):
        op.execute(f"DROP VIEW vn_air.{view}")
    for table in (
        "model_predictions", "model_runs", "data_quality_issues",
        "quarantined_records", "modeled_values", "model_snapshots",
        "air_quality_observations", "source_responses", "ingestion_runs",
        "sensors", "locations", "variables", "source_products", "reference_configs",
    ):
        op.execute(f"DROP TABLE vn_air.{table}")
    for function in ("reject_mutation", "check_observation", "check_modeled_value", "check_prediction"):
        op.execute(f"DROP FUNCTION vn_air.{function}()")
    for domain in ("latitude", "longitude", "finite_number"):
        op.execute(f"DROP DOMAIN vn_air.{domain}")
    op.execute("DROP SCHEMA vn_air")
