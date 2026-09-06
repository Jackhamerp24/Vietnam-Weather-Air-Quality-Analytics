"""Alembic uses the explicit connection supplied by the project CLI/tests."""

from alembic import context


connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    version_table="vn_air_schema_version",
    version_table_schema="public",
    transactional_ddl=True,
)
with context.begin_transaction():
    context.run_migrations()
