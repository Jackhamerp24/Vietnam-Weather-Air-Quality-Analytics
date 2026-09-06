SET LOCAL search_path TO vn_air, pg_catalog;

ALTER TABLE ingestion_runs
    ADD COLUMN target_location_id text REFERENCES locations(id),
    ADD COLUMN target_sensor_id text REFERENCES sensors(id);

ALTER TABLE source_responses
    ADD COLUMN provider_group text CHECK (provider_group IN ('openaq', 'open_meteo')),
    ADD COLUMN request_path text,
    ADD COLUMN attempt integer CHECK (attempt BETWEEN 1 AND 4),
    ADD COLUMN elapsed_ms integer CHECK (elapsed_ms >= 0),
    ADD COLUMN retry_after_seconds finite_number CHECK (retry_after_seconds >= 0);
ALTER TABLE source_responses DROP CONSTRAINT source_responses_check2;
ALTER TABLE source_responses ADD CONSTRAINT source_responses_check2
    CHECK (http_status IS NULL OR http_status <> 200 OR body IS NOT NULL OR
           error_code IN ('credential_echo', 'response_too_large', 'response_deadline', 'network_error', 'timeout'));
CREATE INDEX source_responses_provider_time ON source_responses(provider_group, requested_at DESC);

ALTER TABLE model_snapshots
    ADD COLUMN content_sha256 text CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    ADD COLUMN query_sha256 text CHECK (query_sha256 ~ '^[0-9a-f]{64}$');
CREATE INDEX model_snapshots_query ON model_snapshots(product_id, location_id, query_sha256, recorded_at DESC);

CREATE TABLE ingestion_checkpoints (
    id text PRIMARY KEY CHECK (id ~ '^[0-9a-f]{64}$'),
    run_id uuid NOT NULL REFERENCES ingestion_runs(id),
    completed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX ingestion_checkpoints_run ON ingestion_checkpoints(run_id);

ALTER FUNCTION reject_mutation() SET search_path = pg_catalog;
ALTER VIEW latest_air_quality SET (security_invoker = true);
ALTER VIEW weather_observations SET (security_invoker = true);
ALTER VIEW modeled_air_quality SET (security_invoker = true);

-- Owner/bypass-RLS backend access only. No browser access is needed for ingestion.
ALTER TABLE public.vn_air_schema_version ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.vn_air_schema_version FROM PUBLIC;
REVOKE ALL ON SCHEMA vn_air FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA vn_air FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA vn_air FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA vn_air FROM PUBLIC;
DO $$
DECLARE item record;
BEGIN
    FOR item IN SELECT tablename FROM pg_tables WHERE schemaname = 'vn_air' LOOP
        EXECUTE format('ALTER TABLE vn_air.%I ENABLE ROW LEVEL SECURITY', item.tablename);
    END LOOP;
    FOR item IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') LOOP
        EXECUTE format('REVOKE ALL ON public.vn_air_schema_version FROM %I', item.rolname);
        EXECUTE format('REVOKE ALL ON SCHEMA vn_air FROM %I', item.rolname);
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA vn_air FROM %I', item.rolname);
        EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA vn_air FROM %I', item.rolname);
        EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA vn_air FROM %I', item.rolname);
    END LOOP;
END;
$$;
