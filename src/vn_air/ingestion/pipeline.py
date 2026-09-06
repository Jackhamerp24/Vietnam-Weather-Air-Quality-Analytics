"""Serial, resumable ingestion with committed raw evidence and atomic chunks."""

import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote
from uuid import uuid4

from sqlalchemy import event, text

from vn_air.database.setup import seed_reference_data
from vn_air.ingestion import PIPELINE_VERSION, IngestionError
from vn_air.ingestion.http import HTTPSource, decode_json
from vn_air.ingestion.parsing import AIR, WEATHER, HOUR, Parsed, check_licence, check_location, parse_meteo, parse_openaq


LOCK_ID = 86750301
PRODUCTS = {
    "openaq": "openaq_airgradient_hourly",
    "era5": "open_meteo_era5",
    "weather": "open_meteo_weather_forecast",
    "cams": "open_meteo_cams_global",
}
ENDPOINTS = {
    "openaq": "https://api.openaq.org/v3/sensors/{sensors_id}/hours",
    "era5": "https://archive-api.open-meteo.com/v1/archive",
    "weather": "https://api.open-meteo.com/v1/forecast",
    "cams": "https://air-quality-api.open-meteo.com/v1/air-quality",
}


def serialized(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False,
                      default=lambda item: item.isoformat())


def fingerprint(value):
    return hashlib.sha256(serialized(value).encode()).hexdigest()


def emit(event, **values):
    print(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(), "event": event, **values}, default=str), flush=True)


def insert_many(connection, table, rows):
    if not rows:
        return
    # Column/table names are internal constants, never taken from provider input.
    columns = list(rows[0])
    query = text(f"INSERT INTO vn_air.{table} ({', '.join(columns)}) VALUES ({', '.join(':' + name for name in columns)})")
    prepared = [{key: serialized(value) if isinstance(value, (dict, list)) else value for key, value in row.items()} for row in rows]
    for index in range(0, len(prepared), 500):
        connection.execute(query, prepared[index:index + 500])


class Ingestor:
    def __init__(self, engine, config, *, transport=None, sleep=time.sleep, max_requests=250, max_database_mb=400, key=None):
        self.engine, self.config = engine, config
        self.sleep = sleep
        self.max_requests = max_requests
        self.max_database_bytes = max_database_mb * 1024 * 1024
        self.requests = 0
        self.key = key if key is not None else os.environ.get("OPENAQ_API_KEY")
        credentials = [engine.url.password, os.environ.get("DATABASE_URL"), os.environ.get("SUPABASE_SECRET_KEY")]
        credentials += [unquote(value) for value in credentials if value]
        self.http = HTTPSource(key=self.key, secrets=credentials, transport=transport, sleep=sleep)
        self.metadata = {}
        self.licence_checked = False
        self.config_hash = fingerprint(config.model_dump(mode="json"))

    def close(self):
        self.http.close()

    def before_attempt(self, group):
        if self.requests >= self.max_requests:
            raise IngestionError("request_budget_exhausted")
        with self.connection.begin():
            usage = self.connection.execute(text("""
                SELECT count(*) FILTER (WHERE requested_at > clock_timestamp() - interval '1 hour') AS hourly,
                       count(*) FILTER (WHERE requested_at > clock_timestamp() - interval '1 day') AS daily,
                       count(*) AS monthly, max(retrieved_at) AS last,
                       max(retrieved_at + make_interval(secs => retry_after_seconds)) AS cooldown_until
                FROM vn_air.source_responses
                WHERE provider_group=:provider AND requested_at > clock_timestamp() - interval '31 days'
            """), {"provider": group}).mappings().one()
            if usage["hourly"] >= (1000 if group == "openaq" else 2000) or (group == "open_meteo" and (usage["daily"] >= 3000 or usage["monthly"] >= 80000)):
                raise IngestionError("provider_budget_exhausted")
            size = self.connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
            if size >= self.max_database_bytes:
                raise IngestionError("database_size_budget_exhausted")
        spacing = 3.7 if group == "openaq" else 1.1
        if usage["cooldown_until"] is not None:
            cooldown = (usage["cooldown_until"] - datetime.now(timezone.utc)).total_seconds()
            if cooldown > 300:
                raise IngestionError("provider_cooldown")
            if cooldown > 0:
                self.sleep(cooldown)
        if usage["last"] is not None:
            delay = max(0.0, spacing - (datetime.now(timezone.utc) - usage["last"]).total_seconds())
            if delay:
                self.sleep(delay)
        self.requests += 1

    def fetch(self, url, parameters, run_id, product):
        def save(attempt, number, group):
            response_id = uuid4()
            row = dict(id=response_id, run_id=run_id, product_id=product.id, request_parameters=parameters,
                       request_path=url, provider_group=group, attempt=number,
                       **vars(attempt))
            with self.connection.begin():
                insert_many(self.connection, "source_responses", [row])
            emit("http_attempt", run_id=run_id, product=product.id, attempt=number,
                 http_status=attempt.http_status, error_code=attempt.error_code, elapsed_ms=attempt.elapsed_ms,
                 page=parameters.get("page"), window_start=parameters.get("datetime_from", parameters.get("start_date")))
            return response_id

        return self.http.get(url, parameters, before_attempt=self.before_attempt, save_attempt=save)

    def issue_rows(self, result, run_id, response_id):
        issues, quarantines = [], []
        seen = set()
        for item in result.issues:
            issues.append(dict(run_id=run_id, response_id=response_id, issue_code=item["code"], severity=item["severity"],
                               details={"locator": item["locator"], **item["details"]}))
            key = item["locator"], item["code"]
            if item["quarantine"] and key not in seen:
                seen.add(key)
                quarantines.append(dict(response_id=response_id, record_locator=item["locator"], reason_code=item["code"], details=item["details"]))
        return issues, quarantines

    def store_observations(self, batches, sensor, start, end, run_id):
        all_rows, issues, quarantines = [], [], []
        for response_id, result in batches:
            extra_issues, extra_quarantines = self.issue_rows(result, run_id, response_id)
            issues.extend(extra_issues)
            quarantines.extend(extra_quarantines)
            all_rows.extend({**row, "response_id": response_id} for row in result.rows)
        # Never choose the first/last conflicting duplicate arbitrarily. Invalidate
        # identifiable intervals, preserving every original record in raw responses.
        unique = {}
        for item in all_rows:
            interval = item["period_end"]
            row = {key: value for key, value in item.items() if key != "_locator"}
            if interval in unique:
                earlier = unique[interval]
                comparable = {k: v for k, v in row.items() if k != "response_id"}
                old = {k: v for k, v in earlier.items() if k != "response_id"}
                conflicting = comparable != old
                code = "conflicting_duplicate_period" if conflicting else "duplicate_period"
                issues.append(dict(run_id=run_id, response_id=row["response_id"], issue_code=code,
                                   severity="error" if conflicting else "warning", details={"period_end": interval.isoformat()}))
                if conflicting:
                    earlier.update(value=None, quality_status="invalid", source_flags={"codes": [code]})
                    quarantines.append(dict(response_id=row["response_id"], record_locator=item["_locator"], reason_code=code, details={}))
                continue
            unique[interval] = row
        present = set(unique)
        expected = {start + i * HOUR for i in range(1, int((end - start) / HOUR) + 1)}
        missing = expected - present
        if missing:
            issues.append(dict(run_id=run_id, sensor_id=sensor.id, window_start=start, window_end=end,
                               issue_code="missing_hours", severity="warning", details={"expected_hours": len(expected), "missing_hours": len(missing)}))
        with self.connection.begin():
            existing = {row["period_end"]: dict(row) for row in self.connection.execute(text("""
                SELECT * FROM vn_air.latest_air_quality WHERE sensor_id=:sensor
                AND period_end > :start AND period_end <= :end
            """), {"sensor": sensor.id, "start": start, "end": end}).mappings()}
            inserts, unchanged = [], 0
            for at, row in sorted(unique.items()):
                old = existing.get(at)
                if old and all(old[key] == value for key, value in row.items() if key != "response_id"):
                    unchanged += 1
                else:
                    row["revision"] = old["revision"] + 1 if old else 1
                    inserts.append(row)
            insert_many(self.connection, "air_quality_observations", inserts)
            self.store_issues(issues, quarantines)
            self.update_counts(run_id, len(inserts), unchanged, len(quarantines))
        return len(inserts), unchanged, len(quarantines), len(missing)

    def store_issues(self, issues, quarantines):
        # Different issue scopes use distinct column sets for executemany.
        for rows in ([i for i in issues if "response_id" in i], [i for i in issues if "sensor_id" in i]):
            insert_many(self.connection, "data_quality_issues", rows)
        unique = {(r["response_id"], r["record_locator"], r["reason_code"]): r for r in quarantines}
        insert_many(self.connection, "quarantined_records", list(unique.values()))

    def update_counts(self, run_id, inserted, unchanged, quarantined):
        self.connection.execute(text("""
            UPDATE vn_air.ingestion_runs SET inserted_count=:inserted, unchanged_count=:unchanged,
            quarantined_count=:quarantined WHERE id=:id
        """), dict(id=run_id, inserted=inserted, unchanged=unchanged, quarantined=quarantined))

    def store_model(self, result, response_id, product, location, parameters, run_id):
        query_hash = fingerprint(parameters)
        content_hash = fingerprint({"grid": result.grid, "rows": result.rows})
        issues, quarantines = self.issue_rows(result, run_id, response_id)
        with self.connection.begin():
            old = self.connection.execute(text("""
                SELECT content_sha256 FROM vn_air.model_snapshots WHERE product_id=:product
                AND location_id=:location AND query_sha256=:query ORDER BY recorded_at DESC, id DESC LIMIT 1
            """), dict(product=product.id, location=location.id, query=query_hash)).scalar_one_or_none()
            inserted, unchanged = 0, 0
            if old == content_hash:
                unchanged = len(result.rows)
            else:
                snapshot_id = uuid4()
                snapshot = dict(id=snapshot_id, product_id=product.id, domain=product.domain, data_kind=product.data_kind,
                                location_id=location.id, response_id=response_id,
                                model_key=product.options.get("models", product.options.get("domains")),
                                run_provenance="reanalysis" if product.data_kind == "reanalysis" else "unknown",
                                requested_latitude=location.latitude, requested_longitude=location.longitude,
                                grid_latitude=result.grid[0], grid_longitude=result.grid[1],
                                query_sha256=query_hash, content_sha256=content_hash)
                insert_many(self.connection, "model_snapshots", [snapshot])
                insert_many(self.connection, "modeled_values", [{"snapshot_id": snapshot_id, **row} for row in result.rows])
                inserted = len(result.rows)
            self.store_issues(issues, quarantines)
            self.update_counts(run_id, inserted, unchanged, len(quarantines))
        return inserted, unchanged, len(quarantines), 0

    def run_chunk(self, source, product, target, start, end, purpose, resume):
        sensor = target if source == "openaq" else None
        location = next(row for row in self.config.locations if row.id == sensor.location_id) if sensor else target
        checkpoint = fingerprint(dict(product=product.id, target=target.id, start=start, end=end,
                                      config=self.config_hash, pipeline=PIPELINE_VERSION))
        with self.connection.begin():
            if resume and self.connection.execute(text("SELECT 1 FROM vn_air.ingestion_checkpoints WHERE id=:id"), {"id": checkpoint}).scalar_one_or_none():
                emit("checkpoint_skipped", product=product.id, target=target.id, start=start, end=end)
                return {"status": "skipped", "inserted": 0, "unchanged": 0, "quarantined": 0}
            run_id = uuid4()
            if purpose == "backfill":
                # An explicit refresh supersedes its earlier completion marker.
                # If this attempt fails/partially parses, resume must retry it.
                self.connection.execute(text("DELETE FROM vn_air.ingestion_checkpoints WHERE id=:id"), {"id": checkpoint})
            insert_many(self.connection, "ingestion_runs", [dict(id=run_id, product_id=product.id,
                        configuration_sha256=self.config_hash, pipeline_version=PIPELINE_VERSION, purpose=purpose,
                        window_start=start, window_end=end, target_location_id=location.id,
                        target_sensor_id=sensor.id if sensor else None)])
        emit("ingestion_started", run_id=run_id, product=product.id, target=target.id, start=start, end=end)
        last_response = None
        stage = "request"
        degraded = False
        try:
            if sensor:
                if not self.licence_checked:
                    last_response, attempt = self.fetch("https://api.openaq.org/v3/licenses/41", {}, run_id, product)
                    stage = "parse"
                    check_licence(decode_json(attempt.body))
                    self.licence_checked = True
                if sensor.id not in self.metadata:
                    stage = "request"
                    last_response, attempt = self.fetch(f"https://api.openaq.org/v3/locations/{sensor.external_location_id}", {}, run_id, product)
                    stage = "parse"
                    self.metadata[sensor.id] = decode_json(attempt.body)
                metadata = check_location(self.metadata[sensor.id], sensor, location, start, end)
                with self.connection.begin():
                    known_instrument = self.connection.execute(text("""
                        SELECT source_metadata->>'instrument' FROM vn_air.air_quality_observations
                        WHERE sensor_id=:sensor ORDER BY recorded_at DESC, id DESC LIMIT 1
                    """), {"sensor": sensor.id}).scalar_one_or_none()
                if known_instrument and known_instrument != "Unknown AirGradient Sensor" and known_instrument != metadata["instrument"]:
                    raise IngestionError("instrument_metadata_changed")
                batches = []
                for page in range(1, 11):
                    stage = "request"
                    parameters = {"datetime_from": start.isoformat(), "datetime_to": end.isoformat(), "limit": 1000, "page": page}
                    last_response, attempt = self.fetch(product.endpoint.format(sensors_id=sensor.external_sensor_id), parameters, run_id, product)
                    stage = "parse"
                    payload = decode_json(attempt.body)
                    if payload.get("meta", {}).get("page") != page:
                        raise IngestionError("pagination_mismatch")
                    parsed = parse_openaq(payload, sensor, location, metadata, start, end, attempt.retrieved_at)
                    batches.append((last_response, parsed))
                    if len(payload["results"]) < 1000:
                        break
                else:
                    raise IngestionError("pagination_budget_exhausted")
                stage = "database"
                counts = self.store_observations(batches, sensor, start, end, run_id)
                invalid_payload = any(issue["quarantine"] for _, result in batches for issue in result.issues)
            else:
                codes = WEATHER if product.domain == "weather" else AIR
                variables = [next(row for row in self.config.variables if row.code == code) for code in codes]
                parameters = {"latitude": location.latitude, "longitude": location.longitude,
                              "start_date": start.date().isoformat(), "end_date": (end - HOUR).date().isoformat(),
                              "hourly": ",".join(codes), **product.options}
                last_response, attempt = self.fetch(product.endpoint, parameters, run_id, product)
                stage = "parse"
                parsed = parse_meteo(decode_json(attempt.body), variables, location, start, end, attempt.retrieved_at, product.data_kind)
                stage = "database"
                counts = self.store_model(parsed, last_response, product, location, parameters, run_id)
                degraded = any(issue["code"] in {"variable_unavailable", "missing_model_hours", "model_value_quality_summary"} for issue in parsed.issues)
                invalid_payload = any(row["quality_status"] == "invalid" for row in parsed.rows)
            inserted, unchanged, quarantined, missing = counts
            status = "partial" if quarantined or invalid_payload or (not sensor and degraded) else "succeeded"
            with self.connection.begin():
                self.connection.execute(text("UPDATE vn_air.ingestion_runs SET status=:status, finished_at=clock_timestamp(), error_code=:error WHERE id=:id"),
                                        {"id": run_id, "status": status, "error": "quarantined_records" if quarantined else ("incomplete_model_data" if status == "partial" else None)})
                if status == "succeeded" and purpose == "backfill":
                    self.connection.execute(text("INSERT INTO vn_air.ingestion_checkpoints(id, run_id) VALUES (:id, :run) ON CONFLICT (id) DO UPDATE SET run_id=EXCLUDED.run_id, completed_at=clock_timestamp()"),
                                            {"id": checkpoint, "run": run_id})
            emit("ingestion_finished", run_id=run_id, product=product.id, target=target.id, status=status,
                 inserted=inserted, unchanged=unchanged, quarantined=quarantined, missing_hours=missing)
            return dict(run_id=str(run_id), status=status, inserted=inserted, unchanged=unchanged, quarantined=quarantined)
        except BaseException as error:
            code = error.code if isinstance(error, IngestionError) else ("interrupted" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "internal_or_database_error")
            # Never stringify arbitrary exceptions or payloads into logs/database.
            try:
                if self.connection.in_transaction():
                    self.connection.rollback()
                with self.connection.begin():
                    if last_response is not None and stage == "parse":
                        result = Parsed()
                        result.issue(code, "$", quarantine=True, severity="error")
                        issues, quarantines = self.issue_rows(result, run_id, last_response)
                        self.store_issues(issues, quarantines)
                    self.connection.execute(text("""
                        UPDATE vn_air.ingestion_runs SET status=CASE WHEN inserted_count > 0 THEN 'partial' ELSE 'failed' END,
                        finished_at=clock_timestamp(), error_code=:code,
                        quarantined_count=(SELECT count(*) FROM vn_air.quarantined_records q
                          JOIN vn_air.source_responses r ON r.id=q.response_id WHERE r.run_id=:id)
                        WHERE id=:id
                    """), {"id": run_id, "code": code})
            except Exception:
                emit("run_finalization_failed", run_id=run_id, error_code="database_unavailable")
            emit("ingestion_failed", run_id=run_id, product=product.id, target=target.id, error_code=code)
            raise IngestionError(code) from None

    def run(self, source, start=None, end=None, *, poll=False, resume=False, target_ids=()):
        if source not in PRODUCTS:
            raise IngestionError("unknown_source")
        product = next(row for row in self.config.products if row.id == PRODUCTS[source])
        if product.endpoint != ENDPOINTS[source]:
            raise IngestionError("unapproved_endpoint")
        required = {"openaq": {}, "era5": {"models": "era5"}, "weather": {"models": "ecmwf_ifs"}, "cams": {"domains": "cams_global"}}[source]
        if source != "openaq":
            required |= {"timezone": "UTC", "timeformat": "unixtime"}
        if product.domain == "weather":
            required |= {"wind_speed_unit": "ms", "temperature_unit": "celsius", "precipitation_unit": "mm"}
        if product.options != required:
            raise IngestionError("unapproved_product_options")
        current = datetime.now(timezone.utc)
        if poll:
            if resume or source == "era5":
                raise IngestionError("unsupported_poll_options")
            if source == "openaq":
                end = current.replace(minute=0, second=0, microsecond=0)
                start = end - timedelta(hours=72)
            else:
                start = current.replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=3)
        if start is None or end is None or start.utcoffset() is None or end.utcoffset() is None:
            raise IngestionError("explicit_utc_window_required")
        start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        if start.timestamp() % 3600 or end.timestamp() % 3600 or not 0 < (end - start).total_seconds() <= 366 * 86400:
            raise IngestionError("invalid_window")
        if source != "openaq" and (start.hour != 0 or end.hour != 0):
            raise IngestionError("model_backfill_requires_utc_midnights")
        if not poll and end > current:
            raise IngestionError("future_backfill")
        if source == "weather" and not poll:
            raise IngestionError("weather_forecast_is_poll_only_use_era5_for_history")
        if source == "era5" and end > current.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=5):
            raise IngestionError("era5_publication_delay")
        targets = [s for s in self.config.sensors if s.product_id == product.id] if source == "openaq" else [l for l in self.config.locations if l.kind == ("city" if source == "cams" else "station")]
        if target_ids:
            if set(target_ids) - {target.id for target in targets}:
                raise IngestionError("unconfigured_target")
            targets = [target for target in targets if target.id in target_ids]
        if not targets:
            raise IngestionError("no_configured_targets")
        if source == "openaq" and not self.key:
            raise IngestionError("openaq_key_missing")
        results = []
        with self.engine.connect() as connection:
            self.connection = connection
            with connection.begin():
                acquired = connection.execute(text("SELECT pg_try_advisory_lock(:lock)"), {"lock": LOCK_ID}).scalar_one()
            if not acquired:
                raise IngestionError("ingestion_already_running")
            def reject_reconnect(conn):
                # Losing the session loses its lock. Never reconnect and write as
                # though the old lock were still held; next invocation recovers runs.
                if conn.invalidated:
                    raise IngestionError("database_session_lost")
            event.listen(connection, "begin", reject_reconnect)
            try:
                with connection.begin():
                    version = connection.execute(text("SELECT version_num FROM public.vn_air_schema_version")).scalar_one()
                    if version != "0003_response_integrity":
                        raise IngestionError("migration_required")
                    seed_reference_data(connection, self.config)
                    # The exclusive session lock proves any old run from this worker
                    # version has lost its worker. Never resume a still-active worker.
                    recovered = connection.execute(text("""
                        UPDATE vn_air.ingestion_runs SET status='failed', finished_at=clock_timestamp(), error_code='worker_interrupted'
                        WHERE status='running' AND pipeline_version=:version RETURNING id
                    """), {"version": PIPELINE_VERSION}).scalars().all()
                for run_id in recovered:
                    emit("orphaned_run_recovered", run_id=run_id)
                for target in targets:
                    cursor = start
                    while cursor < end:
                        stop = min(cursor + timedelta(days=7), end)
                        results.append(self.run_chunk(source, product, target, cursor, stop, "poll" if poll else "backfill", resume))
                        cursor = stop
            finally:
                event.remove(connection, "begin", reject_reconnect)
                if connection.in_transaction():
                    connection.rollback()
                if not connection.invalidated:
                    try:
                        with connection.begin():
                            connection.execute(text("SELECT pg_advisory_unlock(:lock)"), {"lock": LOCK_ID})
                    except Exception:
                        # A pooled connection must never keep a session lock.
                        connection.invalidate()
        emit("ingestion_summary", source=source, chunks=len(results), requests=self.requests,
             inserted=sum(r["inserted"] for r in results), unchanged=sum(r["unchanged"] for r in results),
             quarantined=sum(r["quarantined"] for r in results))
        return results
