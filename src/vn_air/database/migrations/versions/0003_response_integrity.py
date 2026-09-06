"""Require retained successful evidence for all canonical rows."""

from alembic import op

revision = "0003_response_integrity"
down_revision = "0002_ingestion"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE vn_air.source_responses DROP CONSTRAINT source_responses_check2")
    op.execute("""
        ALTER TABLE vn_air.source_responses ADD CONSTRAINT source_responses_check2
        CHECK (http_status IS NULL OR http_status <> 200 OR body IS NOT NULL OR
               (error_code IS NOT NULL AND error_code IN
                ('credential_echo', 'response_too_large', 'response_deadline', 'network_error', 'timeout')))
    """)
    op.execute("""
        CREATE FUNCTION vn_air.require_usable_response() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, vn_air AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM vn_air.source_responses
                           WHERE id=NEW.response_id AND http_status=200 AND error_code IS NULL AND body IS NOT NULL) THEN
                RAISE EXCEPTION 'Canonical rows require retained successful response evidence' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END;
        $$;
        REVOKE ALL ON FUNCTION vn_air.require_usable_response() FROM PUBLIC;
        CREATE TRIGGER usable_response BEFORE INSERT ON vn_air.air_quality_observations
            FOR EACH ROW EXECUTE FUNCTION vn_air.require_usable_response();
        CREATE TRIGGER usable_response BEFORE INSERT ON vn_air.model_snapshots
            FOR EACH ROW EXECUTE FUNCTION vn_air.require_usable_response();
    """)


def downgrade():
    op.execute("DROP TRIGGER usable_response ON vn_air.air_quality_observations")
    op.execute("DROP TRIGGER usable_response ON vn_air.model_snapshots")
    op.execute("DROP FUNCTION vn_air.require_usable_response()")
    # Keep the stronger null-safe response constraint rather than restoring a gap.
