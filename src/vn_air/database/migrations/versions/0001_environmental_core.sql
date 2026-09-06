CREATE SCHEMA vn_air;
SET LOCAL search_path TO vn_air, pg_catalog;

CREATE DOMAIN finite_number AS double precision
    CHECK (VALUE > '-Infinity'::double precision AND VALUE < 'Infinity'::double precision);
CREATE DOMAIN latitude AS double precision CHECK (VALUE BETWEEN -90 AND 90);
CREATE DOMAIN longitude AS double precision CHECK (VALUE BETWEEN -180 AND 180);

CREATE TABLE reference_configs (
    sha256 text PRIMARY KEY CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    document jsonb NOT NULL CHECK (jsonb_typeof(document) = 'object'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE source_products (
    id text PRIMARY KEY,
    provider text NOT NULL,
    domain text NOT NULL CHECK (domain IN ('weather', 'air_quality')),
    data_kind text NOT NULL CHECK (data_kind IN ('measurement', 'reanalysis', 'forecast')),
    endpoint text NOT NULL CHECK (endpoint ~ '^https://[^/?@]+/[^?@#]*$'),
    attribution text NOT NULL,
    licence_url text NOT NULL CHECK (licence_url LIKE 'https://%'),
    configuration_sha256 text NOT NULL REFERENCES reference_configs(sha256),
    UNIQUE (id, domain, data_kind),
    UNIQUE (id, data_kind)
);

CREATE TABLE variables (
    code text PRIMARY KEY,
    domain text NOT NULL CHECK (domain IN ('weather', 'air_quality')),
    representation text NOT NULL CHECK (representation IN ('weather', 'concentration', 'index')),
    canonical_unit text NOT NULL,
    minimum finite_number,
    maximum finite_number,
    temporal_support text NOT NULL CHECK (temporal_support IN ('instant', 'preceding_hour_mean', 'preceding_hour_sum')),
    configuration_sha256 text NOT NULL REFERENCES reference_configs(sha256),
    CHECK (minimum IS NULL OR maximum IS NULL OR minimum < maximum),
    CHECK ((domain = 'weather') = (representation = 'weather')),
    UNIQUE (code, canonical_unit),
    UNIQUE (code, canonical_unit, domain, representation),
    UNIQUE (code, canonical_unit, domain, temporal_support)
);

CREATE TABLE locations (
    id text PRIMARY KEY,
    name text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('city', 'station')),
    parent_id text,
    parent_kind text GENERATED ALWAYS AS ('city'::text) STORED,
    country_code text NOT NULL CHECK (country_code = 'VN'),
    latitude latitude NOT NULL,
    longitude longitude NOT NULL,
    timezone text NOT NULL CHECK (timezone = 'Asia/Ho_Chi_Minh'),
    provider_timezone text NOT NULL,
    geonames_id bigint UNIQUE,
    configuration_sha256 text NOT NULL REFERENCES reference_configs(sha256),
    UNIQUE (id, kind),
    FOREIGN KEY (parent_id, parent_kind) REFERENCES locations(id, kind),
    CHECK ((kind = 'city' AND parent_id IS NULL) OR (kind = 'station' AND parent_id IS NOT NULL)),
    CHECK (parent_id IS DISTINCT FROM id),
    CHECK (geonames_id IS NULL OR (geonames_id > 0 AND kind = 'city'))
);

CREATE TABLE sensors (
    id text PRIMARY KEY,
    location_id text NOT NULL,
    location_kind text GENERATED ALWAYS AS ('station'::text) STORED,
    product_id text NOT NULL,
    data_kind text GENERATED ALWAYS AS ('measurement'::text) STORED,
    domain text GENERATED ALWAYS AS ('air_quality'::text) STORED,
    representation text GENERATED ALWAYS AS ('concentration'::text) STORED,
    external_sensor_id text NOT NULL,
    external_location_id text NOT NULL,
    variable_code text NOT NULL,
    canonical_unit text NOT NULL,
    instrument text NOT NULL,
    is_reference_monitor boolean NOT NULL,
    licence_url text NOT NULL CHECK (licence_url LIKE 'https://%'),
    licence_valid_from date NOT NULL,
    licence_valid_to date,
    attribution text NOT NULL,
    qualification_notes text NOT NULL,
    configuration_sha256 text NOT NULL REFERENCES reference_configs(sha256),
    UNIQUE (product_id, external_sensor_id),
    UNIQUE (id, product_id),
    UNIQUE (id, variable_code, canonical_unit),
    FOREIGN KEY (location_id, location_kind) REFERENCES locations(id, kind),
    FOREIGN KEY (product_id, domain, data_kind) REFERENCES source_products(id, domain, data_kind),
    FOREIGN KEY (variable_code, canonical_unit, domain, representation)
        REFERENCES variables(code, canonical_unit, domain, representation),
    CHECK (licence_valid_to IS NULL OR licence_valid_to >= licence_valid_from)
);

CREATE TABLE ingestion_runs (
    id uuid PRIMARY KEY,
    product_id text NOT NULL REFERENCES source_products(id),
    configuration_sha256 text NOT NULL REFERENCES reference_configs(sha256),
    pipeline_version text NOT NULL,
    purpose text NOT NULL CHECK (purpose IN ('poll', 'backfill', 'metadata')),
    status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    window_start timestamptz,
    window_end timestamptz,
    inserted_count integer NOT NULL DEFAULT 0 CHECK (inserted_count >= 0),
    unchanged_count integer NOT NULL DEFAULT 0 CHECK (unchanged_count >= 0),
    quarantined_count integer NOT NULL DEFAULT 0 CHECK (quarantined_count >= 0),
    error_code text,
    UNIQUE (id, product_id),
    CHECK ((window_start IS NULL AND window_end IS NULL) OR
           (window_start IS NOT NULL AND window_end IS NOT NULL AND window_end > window_start)),
    CHECK ((status = 'running' AND finished_at IS NULL) OR
           (status <> 'running' AND finished_at IS NOT NULL AND finished_at >= started_at)),
    CHECK (status NOT IN ('partial', 'failed') OR error_code IS NOT NULL)
);
CREATE INDEX ingestion_runs_product_time ON ingestion_runs(product_id, started_at DESC);

CREATE TABLE source_responses (
    id uuid PRIMARY KEY,
    run_id uuid NOT NULL,
    product_id text NOT NULL,
    requested_at timestamptz NOT NULL,
    retrieved_at timestamptz NOT NULL,
    request_parameters jsonb NOT NULL CHECK (jsonb_typeof(request_parameters) = 'object'),
    http_status integer CHECK (http_status BETWEEN 100 AND 599),
    error_code text,
    media_type text,
    body bytea,
    body_sha256 text GENERATED ALWAYS AS (encode(sha256(body), 'hex')) STORED,
    UNIQUE (id, product_id),
    FOREIGN KEY (run_id, product_id) REFERENCES ingestion_runs(id, product_id),
    CHECK (retrieved_at >= requested_at),
    CHECK (http_status IS NOT NULL OR error_code IS NOT NULL),
    CHECK (http_status IS NULL OR http_status <> 200 OR body IS NOT NULL),
    CHECK (NOT request_parameters ?| ARRAY['key', 'apikey', 'appid', 'token', 'X-API-Key', 'authorization', 'password'])
);
CREATE INDEX source_responses_run ON source_responses(run_id);

-- One immutable row per revision of a sensor's hourly interval. Equal values
-- can reappear in a later revision; do not deduplicate an entire history by value.
CREATE TABLE air_quality_observations (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_id text NOT NULL,
    product_id text NOT NULL,
    variable_code text NOT NULL,
    canonical_unit text NOT NULL,
    period_start timestamptz NOT NULL,
    period_end timestamptz NOT NULL,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    previous_revision integer GENERATED ALWAYS AS (nullif(revision - 1, 0)) STORED,
    response_id uuid NOT NULL,
    value finite_number CHECK (value >= 0),
    quality_status text NOT NULL CHECK (quality_status IN ('accepted', 'suspect', 'missing', 'invalid')),
    source_flags jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(source_flags) = 'object'),
    coverage_percent finite_number CHECK (coverage_percent BETWEEN 0 AND 100),
    latitude latitude NOT NULL,
    longitude longitude NOT NULL,
    source_metadata jsonb NOT NULL CHECK (jsonb_typeof(source_metadata) = 'object'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    source_published_at timestamptz,
    UNIQUE (sensor_id, period_start, period_end, revision),
    UNIQUE (sensor_id, period_start, period_end, response_id),
    FOREIGN KEY (sensor_id, product_id) REFERENCES sensors(id, product_id),
    FOREIGN KEY (sensor_id, variable_code, canonical_unit) REFERENCES sensors(id, variable_code, canonical_unit),
    FOREIGN KEY (response_id, product_id) REFERENCES source_responses(id, product_id),
    FOREIGN KEY (sensor_id, period_start, period_end, previous_revision)
        REFERENCES air_quality_observations(sensor_id, period_start, period_end, revision),
    CHECK (period_end = period_start + interval '1 hour'),
    CHECK (extract(epoch FROM period_end)::numeric % 3600 = 0),
    CHECK ((quality_status IN ('missing', 'invalid')) = (value IS NULL)),
    CHECK (source_published_at IS NULL OR source_published_at >= period_end)
);
CREATE INDEX air_quality_sensor_time ON air_quality_observations(sensor_id, period_end DESC, revision DESC);
CREATE INDEX air_quality_response ON air_quality_observations(response_id);

CREATE TABLE model_snapshots (
    id uuid PRIMARY KEY,
    product_id text NOT NULL,
    domain text NOT NULL,
    data_kind text NOT NULL CHECK (data_kind IN ('reanalysis', 'forecast')),
    location_id text NOT NULL REFERENCES locations(id),
    response_id uuid NOT NULL,
    model_key text NOT NULL,
    model_version text,
    run_initialized_at timestamptz,
    source_published_at timestamptz,
    run_provenance text NOT NULL CHECK (run_provenance IN ('unknown', 'operational', 'hindcast', 'reanalysis')),
    requested_latitude latitude NOT NULL,
    requested_longitude longitude NOT NULL,
    grid_latitude latitude NOT NULL,
    grid_longitude longitude NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (response_id, location_id, model_key),
    UNIQUE (id, domain),
    FOREIGN KEY (product_id, domain, data_kind) REFERENCES source_products(id, domain, data_kind),
    FOREIGN KEY (response_id, product_id) REFERENCES source_responses(id, product_id),
    CHECK ((data_kind = 'reanalysis' AND run_provenance = 'reanalysis' AND run_initialized_at IS NULL) OR
           (data_kind = 'forecast' AND run_provenance <> 'reanalysis')),
    CHECK (run_provenance NOT IN ('operational', 'hindcast') OR run_initialized_at IS NOT NULL),
    CHECK (source_published_at IS NULL OR run_initialized_at IS NULL OR source_published_at >= run_initialized_at)
);
CREATE INDEX model_snapshots_location ON model_snapshots(location_id, product_id, recorded_at DESC);

CREATE TABLE modeled_values (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    snapshot_id uuid NOT NULL,
    domain text NOT NULL,
    variable_code text NOT NULL,
    canonical_unit text NOT NULL,
    valid_at timestamptz NOT NULL,
    period_start timestamptz NOT NULL,
    temporal_support text NOT NULL,
    native_interval_seconds integer CHECK (native_interval_seconds > 0),
    value finite_number,
    quality_status text NOT NULL CHECK (quality_status IN ('accepted', 'suspect', 'missing', 'invalid')),
    source_flags jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(source_flags) = 'object'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (snapshot_id, variable_code, valid_at),
    FOREIGN KEY (snapshot_id, domain) REFERENCES model_snapshots(id, domain),
    FOREIGN KEY (variable_code, canonical_unit, domain, temporal_support)
        REFERENCES variables(code, canonical_unit, domain, temporal_support),
    CHECK ((temporal_support = 'instant' AND period_start = valid_at) OR
           (temporal_support IN ('preceding_hour_mean', 'preceding_hour_sum') AND period_start = valid_at - interval '1 hour')),
    CHECK ((quality_status IN ('missing', 'invalid')) = (value IS NULL))
);
CREATE INDEX modeled_values_time ON modeled_values(variable_code, valid_at);

CREATE TABLE quarantined_records (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    response_id uuid NOT NULL REFERENCES source_responses(id),
    record_locator text NOT NULL,
    reason_code text NOT NULL,
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (response_id, record_locator, reason_code)
);

CREATE TABLE data_quality_issues (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id uuid NOT NULL REFERENCES ingestion_runs(id),
    response_id uuid REFERENCES source_responses(id),
    observation_id bigint REFERENCES air_quality_observations(id),
    modeled_value_id bigint REFERENCES modeled_values(id),
    sensor_id text REFERENCES sensors(id),
    window_start timestamptz,
    window_end timestamptz,
    issue_code text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('info', 'warning', 'error')),
    details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object'),
    detected_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    resolved_at timestamptz,
    resolution text,
    CHECK (num_nonnulls(response_id, observation_id, modeled_value_id, sensor_id) = 1),
    CHECK ((window_start IS NULL AND window_end IS NULL) OR
           (window_start IS NOT NULL AND window_end IS NOT NULL AND window_end > window_start)),
    CHECK ((resolved_at IS NULL AND resolution IS NULL) OR
           (resolved_at IS NOT NULL AND resolution IS NOT NULL AND resolved_at >= detected_at))
);
CREATE INDEX data_quality_open_issues ON data_quality_issues(detected_at DESC) WHERE resolved_at IS NULL;

CREATE TABLE model_runs (
    id uuid PRIMARY KEY,
    model_name text NOT NULL,
    model_version text NOT NULL,
    horizon_hours integer NOT NULL CHECK (horizon_hours > 0 AND horizon_hours <= 168),
    training_started_at timestamptz NOT NULL,
    training_cutoff timestamptz NOT NULL,
    fitted_at timestamptz NOT NULL,
    feature_version text NOT NULL,
    code_revision text NOT NULL,
    data_manifest_sha256 text NOT NULL CHECK (data_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    parameters jsonb NOT NULL CHECK (jsonb_typeof(parameters) = 'object'),
    metrics jsonb CHECK (metrics IS NULL OR jsonb_typeof(metrics) = 'object'),
    artifact_uri text,
    UNIQUE (model_name, model_version, horizon_hours),
    UNIQUE (id, horizon_hours),
    CHECK (training_cutoff > training_started_at AND fitted_at >= training_cutoff)
);

CREATE TABLE model_predictions (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_run_id uuid NOT NULL,
    sensor_id text NOT NULL REFERENCES sensors(id),
    horizon_hours integer NOT NULL,
    forecast_origin timestamptz NOT NULL,
    target_start timestamptz NOT NULL,
    target_end timestamptz NOT NULL,
    prediction_kind text NOT NULL CHECK (prediction_kind IN ('retrospective', 'operational')),
    generated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    availability_basis text NOT NULL DEFAULT 'captured' CHECK (availability_basis IN ('captured', 'assumed')),
    availability_assumption text,
    feature_available_through timestamptz,
    predicted_pm2_5 finite_number NOT NULL CHECK (predicted_pm2_5 >= 0),
    lower_bound finite_number,
    upper_bound finite_number,
    interval_level finite_number,
    interval_method text,
    UNIQUE (model_run_id, sensor_id, forecast_origin),
    FOREIGN KEY (model_run_id, horizon_hours) REFERENCES model_runs(id, horizon_hours),
    CHECK (target_end = forecast_origin + make_interval(hours => horizon_hours)),
    CHECK (target_start = target_end - interval '1 hour' AND target_start >= forecast_origin),
    CHECK (feature_available_through <= forecast_origin),
    CHECK ((availability_basis = 'captured' AND feature_available_through IS NOT NULL AND availability_assumption IS NULL) OR
           (availability_basis = 'assumed' AND prediction_kind = 'retrospective' AND
            feature_available_through IS NULL AND availability_assumption IS NOT NULL)),
    CHECK (generated_at >= forecast_origin),
    CHECK (prediction_kind <> 'operational' OR generated_at <= target_start),
    CHECK ((num_nonnulls(lower_bound, upper_bound, interval_level, interval_method) = 0) OR
           (num_nonnulls(lower_bound, upper_bound, interval_level, interval_method) = 4 AND
            lower_bound >= 0 AND lower_bound <= upper_bound AND interval_level > 0 AND interval_level < 1))
);
CREATE INDEX model_predictions_target ON model_predictions(sensor_id, target_end DESC);

CREATE FUNCTION reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '% is append-only; retain provenance and create a new revision', TG_TABLE_NAME
        USING ERRCODE = '23514';
END;
$$;

CREATE FUNCTION check_observation() RETURNS trigger LANGUAGE plpgsql
    SET search_path = vn_air, pg_catalog AS $$
DECLARE
    fetched timestamptz;
    prior_recorded timestamptz;
    prior_fetched timestamptz;
    allowed_from date;
    allowed_to date;
BEGIN
    SELECT retrieved_at INTO fetched FROM source_responses WHERE id = NEW.response_id AND http_status = 200;
    IF fetched IS NULL OR NEW.recorded_at < fetched OR NEW.period_end > fetched OR
       (NEW.source_published_at IS NOT NULL AND NEW.source_published_at > fetched) THEN
        RAISE EXCEPTION 'Measurement must be complete and retrieved before storage' USING ERRCODE = '23514';
    END IF;
    SELECT licence_valid_from, licence_valid_to INTO allowed_from, allowed_to FROM sensors WHERE id = NEW.sensor_id;
    IF (NEW.period_start AT TIME ZONE 'Asia/Ho_Chi_Minh')::date < allowed_from OR
       (allowed_to IS NOT NULL AND (NEW.period_end AT TIME ZONE 'Asia/Ho_Chi_Minh') > (allowed_to + 1)::timestamp) THEN
        RAISE EXCEPTION 'Measurement interval outside reviewed licence dates' USING ERRCODE = '23514';
    END IF;
    IF NEW.revision > 1 THEN
        SELECT o.recorded_at, r.retrieved_at INTO prior_recorded, prior_fetched
        FROM air_quality_observations o JOIN source_responses r ON r.id = o.response_id
        WHERE o.sensor_id = NEW.sensor_id AND o.period_start = NEW.period_start AND
              o.period_end = NEW.period_end AND o.revision = NEW.revision - 1;
        IF NEW.recorded_at < prior_recorded OR fetched < prior_fetched THEN
            RAISE EXCEPTION 'Revision chronology cannot move backwards' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER observation_contract BEFORE INSERT ON air_quality_observations
    FOR EACH ROW EXECUTE FUNCTION check_observation();

CREATE FUNCTION check_modeled_value() RETURNS trigger LANGUAGE plpgsql
    SET search_path = vn_air, pg_catalog AS $$
DECLARE
    low finite_number;
    high finite_number;
    fetched timestamptz;
BEGIN
    IF TG_TABLE_NAME = 'model_snapshots' THEN
        SELECT retrieved_at INTO fetched FROM source_responses WHERE id = NEW.response_id AND http_status = 200;
        IF fetched IS NULL OR NEW.recorded_at < fetched OR NEW.run_initialized_at > fetched OR NEW.source_published_at > fetched THEN
            RAISE EXCEPTION 'Invalid snapshot retrieval/publication chronology' USING ERRCODE = '23514';
        END IF;
    ELSE
        IF EXISTS (SELECT 1 FROM model_snapshots WHERE id = NEW.snapshot_id AND recorded_at > NEW.recorded_at) THEN
            RAISE EXCEPTION 'Modeled value cannot precede its snapshot storage' USING ERRCODE = '23514';
        END IF;
        SELECT minimum, maximum INTO low, high FROM variables WHERE code = NEW.variable_code;
        IF NEW.value < low OR NEW.value > high THEN
            RAISE EXCEPTION 'Value violates canonical physical bounds; quarantine raw record' USING ERRCODE = '23514';
        END IF;
        IF EXISTS (SELECT 1 FROM model_snapshots s JOIN source_responses r ON r.id = s.response_id
                   WHERE s.id = NEW.snapshot_id AND s.data_kind = 'reanalysis' AND NEW.valid_at > r.retrieved_at) THEN
            RAISE EXCEPTION 'Reanalysis cannot have a future valid time' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER snapshot_contract BEFORE INSERT ON model_snapshots
    FOR EACH ROW EXECUTE FUNCTION check_modeled_value();
CREATE TRIGGER modeled_value_contract BEFORE INSERT ON modeled_values
    FOR EACH ROW EXECUTE FUNCTION check_modeled_value();

CREATE FUNCTION check_prediction() RETURNS trigger LANGUAGE plpgsql
    SET search_path = vn_air, pg_catalog AS $$
DECLARE
    model model_runs;
BEGIN
    SELECT * INTO model FROM model_runs WHERE id = NEW.model_run_id;
    IF model.training_cutoff > NEW.forecast_origin OR model.fitted_at > NEW.generated_at OR
       (NEW.prediction_kind = 'operational' AND model.fitted_at > NEW.forecast_origin) THEN
        RAISE EXCEPTION 'Model training/fitting occurred after its permissible cutoff' USING ERRCODE = '23514';
    END IF;
    IF EXISTS (SELECT 1 FROM sensors WHERE id = NEW.sensor_id AND variable_code <> 'pm2_5') THEN
        RAISE EXCEPTION 'PM2.5 predictions require a PM2.5 target sensor' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER prediction_contract BEFORE INSERT ON model_predictions
    FOR EACH ROW EXECUTE FUNCTION check_prediction();

DO $$
DECLARE relation text;
BEGIN
    FOREACH relation IN ARRAY ARRAY['reference_configs', 'source_products', 'variables', 'locations', 'sensors',
        'source_responses', 'air_quality_observations', 'model_snapshots', 'modeled_values',
        'quarantined_records', 'model_runs', 'model_predictions']
    LOOP
        EXECUTE format('CREATE TRIGGER immutable_rows BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION reject_mutation()', relation);
    END LOOP;
END;
$$;

-- Retrospective convenience only: latest must be selected before quality
-- filtering so a later missing/invalid revision cannot resurrect an older value.
CREATE VIEW latest_air_quality AS
    SELECT DISTINCT ON (o.sensor_id, o.period_start, o.period_end)
        o.*, r.retrieved_at
    FROM air_quality_observations o JOIN source_responses r ON r.id = o.response_id
    ORDER BY o.sensor_id, o.period_start, o.period_end, o.revision DESC;

CREATE VIEW weather_observations AS
    SELECT v.*, s.location_id, s.product_id, s.data_kind, s.model_key, s.run_initialized_at,
           s.run_provenance, s.recorded_at AS snapshot_recorded_at, r.retrieved_at
    FROM modeled_values v JOIN model_snapshots s ON s.id = v.snapshot_id
    JOIN source_responses r ON r.id = s.response_id WHERE v.domain = 'weather';

CREATE VIEW modeled_air_quality AS
    SELECT v.*, s.location_id, s.product_id, s.model_key, s.run_initialized_at,
           s.run_provenance, s.recorded_at AS snapshot_recorded_at, r.retrieved_at
    FROM modeled_values v JOIN model_snapshots s ON s.id = v.snapshot_id
    JOIN source_responses r ON r.id = s.response_id WHERE v.domain = 'air_quality';
