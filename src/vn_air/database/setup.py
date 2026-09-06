"""Small migration and reference-data boundary; no live ingestion."""

import hashlib
import json
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from vn_air.config import StudyConfig


def database_engine(url: str | None = None):
    value = url or os.environ.get("DATABASE_URL")
    if not value:
        raise ValueError("Set DATABASE_URL explicitly; no database is selected by default")
    try:
        parsed = make_url(value)
    except Exception:
        raise ValueError("Invalid DATABASE_URL") from None
    if parsed.drivername not in {"postgresql", "postgresql+psycopg"} or not parsed.database:
        raise ValueError("Use a PostgreSQL database URL with an explicit database name")
    if parsed.database in {"template0", "template1"}:
        raise ValueError("Template databases are not valid project targets")
    if parsed.database == "postgres":
        host = (parsed.host or "").lower()
        is_supabase = host.endswith((".supabase.co", ".supabase.com"))
        if not is_supabase:
            raise ValueError("Use a dedicated local database; Supabase projects are the supported exception for database 'postgres'")
        sslmode = parsed.query.get("sslmode")
        if sslmode is None:
            parsed = parsed.update_query_dict({"sslmode": "require"})
        elif sslmode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError("Supabase connections require TLS")
        if host.endswith(".pooler.supabase.com") and parsed.port != 5432:
            raise ValueError("Use the session pooler on port 5432; ingestion holds a session lock")
    return create_engine(
        parsed.set(drivername="postgresql+psycopg"),
        hide_parameters=True,
        connect_args={"connect_timeout": 10, "options": "-c timezone=UTC"},
    )


def migrate(connection, target: str = "head", *, downgrade: bool = False):
    if int(connection.execute(text("SHOW server_version_num")).scalar_one()) < 150000:
        raise ValueError("PostgreSQL 15 or newer is required")
    connection.execute(text("SELECT pg_advisory_xact_lock(86750201)"))
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.attributes["connection"] = connection
    operation = command.downgrade if downgrade else command.upgrade
    operation(config, target)


def seed_reference_data(connection, config: StudyConfig):
    """New metadata is append-only; conflicting identities roll back the seed."""
    connection.execute(text("SELECT pg_advisory_xact_lock(86750201)"))
    document = config.model_dump(mode="json")
    serialized = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(serialized.encode()).hexdigest()
    connection.execute(text("INSERT INTO vn_air.reference_configs(sha256, document) VALUES (:sha, CAST(:document AS jsonb)) ON CONFLICT DO NOTHING"), {"sha": digest, "document": serialized})
    counts = {}
    groups = (
        ("source_products", "id", config.products),
        ("variables", "code", config.variables),
        ("locations", "id", sorted(config.locations, key=lambda row: row.kind != "city")),
        ("sensors", "id", config.sensors),
    )
    for table, key, records in groups:
        inserted = 0
        for record in records:
            values = record.model_dump(mode="python")
            # API options live in the immutable config, not duplicated SQL columns.
            values.pop("options", None)
            existing = connection.execute(text(f"SELECT * FROM vn_air.{table} WHERE {key} = :identity"), {"identity": values[key]}).mappings().first()
            if existing is not None:
                if any(existing[name] != value for name, value in values.items()):
                    raise ValueError(f"Reference conflict in {table}: {values[key]}; use a reviewed metadata migration/version")
                if table == "source_products":
                    old = connection.execute(text("SELECT document FROM vn_air.reference_configs WHERE sha256 = :sha"), {"sha": existing["configuration_sha256"]}).scalar_one()
                    old_product = next(row for row in old["products"] if row["id"] == values[key])
                    if old_product.get("options", {}) != record.model_dump(mode="json")["options"]:
                        raise ValueError(f"Product options changed for {values[key]}; create a new product version")
                continue
            values["configuration_sha256"] = digest
            columns = ", ".join(values)
            bindings = ", ".join(f":{name}" for name in values)
            connection.execute(text(f"INSERT INTO vn_air.{table} ({columns}) VALUES ({bindings})"), values)
            inserted += 1
        counts[table] = inserted
    return counts
