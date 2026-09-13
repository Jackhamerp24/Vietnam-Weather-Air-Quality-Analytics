"""Phase 11 read-only health projection and recovery guidance.

Both commands open bounded read-only transactions, use parameterized SQL and
never write, migrate, seed or invoke the ingestion worker. Recovery emits
operator guidance only; it does not finalize runs, delete evidence or reconcile
checkpoints. Credentials, raw responses and connection identifiers never enter
the output.

Health exit mapping: ``0`` all configured checks healthy, ``2`` degraded
(partial/stale/low coverage/missing backup), ``1`` failed/unknown evidence/
schema/budget stop, ``3`` invalid configuration. Severity precedence is
``failed > degraded > healthy``; it is computed explicitly, never with
``max(code)``.
"""

from __future__ import annotations

import json
import stat
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from vn_air.automation import (
    AUTOMATION_VERSION,
    AutomationError,
    iso,
    normalize_error_code,
    utc_now,
)
from vn_air.database.setup import database_engine
from vn_air.ingestion.pipeline import PRODUCTS


HEALTH_EXIT_HEALTHY = 0
HEALTH_EXIT_FAILED = 1
HEALTH_EXIT_DEGRADED = 2
HEALTH_EXIT_INVALID = 3

HEALTH_VERSION = AUTOMATION_VERSION
HEALTH_LOOKBACK_SECONDS = 7 * 24 * 3600
HEALTH_QUALITY_LOOKBACK_SECONDS = 24 * 3600
HEALTH_STATEMENT_TIMEOUT_MS = 15000
HEALTH_CONNECT_TIMEOUT_SECONDS = 10
HEALTH_RUN_ROW_LIMIT = 200

SEVERITY_FAILED = "failed"
SEVERITY_DEGRADED = "degraded"
HEALTHY = "healthy"
EXIT_BY_SEVERITY = {SEVERITY_FAILED: HEALTH_EXIT_FAILED, SEVERITY_DEGRADED: HEALTH_EXIT_DEGRADED}

PROVIDER_GROUPS = {"openaq": "openaq", "weather": "open_meteo", "cams": "open_meteo"}
COOLDOWN_ERROR_CODES = frozenset({
    "provider_cooldown", "provider_budget_exhausted", "pagination_budget_exhausted",
    "request_budget_exhausted", "retry_exhausted", "response_deadline",
})
TRANSIENT_ERROR_CODES = frozenset({
    "network_error", "timeout", "database_unavailable", "database_session_lost",
    "worker_interrupted", "interrupted", "internal_or_database_error",
})
NON_RETRYABLE_ERROR_CODES = frozenset({
    "credential_echo", "future_backfill", "future_reanalysis", "invalid_coordinates",
    "invalid_licence_metadata", "invalid_location_metadata", "licence_not_qualified",
    "location_identity_mismatch", "migration_required", "model_backfill_requires_utc_midnights",
    "sensor_parameter_changed", "station_coordinates_changed", "station_timezone_changed",
    "unapproved_endpoint", "unapproved_parameters", "wrong_parameter",
    "weather_forecast_is_poll_only_use_era5_for_history",
})
OPENA_QUALITY_CODES = frozenset({"missing_hours", "incomplete_hour", "coverage_gap"})

HEALTH_NOTES = (
    "Read-only projection over bounded aggregate queries; no worker, migration, seed or write was performed.",
    "Run, fetch, coverage and modeled checks share a bounded 7-day lookback; older rows require direct inspection.",
    "Stale running rows are suspected stale, not proven orphaned; the Phase 3 worker keeps lock-proven finalization.",
    "OpenAQ success with missing hours is not complete coverage; fetch freshness is separate from accepted-data freshness.",
    "Modeled freshness uses capture/retrieval/recording timestamps, never future valid_at; invalid-only payloads are not healthy.",
    "Calendar-only limited diagnostic: this is not forecast skill, causal validity, city-wide coverage or production readiness.",
)

RECOVERY_NOTES = (
    "Guidance only: no run, checkpoint, response or observation was modified.",
    "Any retry is an explicit, bounded operator action and requires operator confirmation.",
    "A completed checkpoint with missing hours is retained as-is; coverage gaps are never silently reconciled.",
    "Unknown error codes are not auto-retryable.",
)

MODEL_SOURCES = ("weather", "cams")
OPENA_SOURCE = "openaq"


def _parse_moment(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _age_seconds(value, as_of: datetime) -> float | None:
    moment = _parse_moment(value)
    if moment is None:
        return None
    return round((as_of - moment).total_seconds(), 3)


def configured_health_targets(config, study) -> list[dict]:
    measured_products = {product.id for product in study.products
                         if product.domain == "air_quality" and product.data_kind == "measurement"}
    sensors = {sensor.id for sensor in study.sensors if sensor.product_id in measured_products}
    stations = {location.id for location in study.locations if location.kind == "station"}
    cities = {location.id for location in study.locations if location.kind == "city"}
    allowed_by_source = {"openaq": sensors, "weather": stations, "cams": cities}
    targets = []
    for job in config.jobs:
        for target in job.targets:
            if target not in allowed_by_source[job.source]:
                raise AutomationError("automation_target_unconfigured", f"job={job.id}")
            targets.append({
                "source": job.source,
                "product": PRODUCTS[job.source],
                "target": target,
                "target_kind": "sensor" if job.source == OPENA_SOURCE else "location",
            })
    return targets


def _rows(connection, sql: str, parameters: dict | None = None) -> list[dict]:
    return [dict(row) for row in connection.execute(text(sql), parameters or {}).mappings()]


def _scalar(connection, sql: str, parameters: dict | None = None):
    return connection.execute(text(sql), parameters or {}).scalar_one_or_none()


def _threshold(config, target, name):
    override = config.readiness.overrides.get(target)
    value = getattr(override, name, None) if override is not None else None
    return getattr(config.readiness, name) if value is None else value


def collect_health_facts(connection, config, study, *, as_of: datetime) -> dict:
    targets = configured_health_targets(config, study)
    run_since = as_of - timedelta(seconds=HEALTH_LOOKBACK_SECONDS)
    stale_before = as_of - timedelta(seconds=config.readiness.stale_running_age_seconds)
    coverage_end = as_of.replace(minute=0, second=0, microsecond=0)
    coverage_start = coverage_end - timedelta(hours=config.readiness.openaq_coverage_window_hours)
    install_table = _scalar(connection, "SELECT to_regclass('public.vn_air_schema_version')")
    revision = None
    if install_table is not None:
        revision = _scalar(connection, "SELECT version_num FROM public.vn_air_schema_version")
    facts = {
        "server_version_num": int(_scalar(connection, "SELECT current_setting('server_version_num')")),
        "schema": {"installed": install_table is not None, "revision": revision,
                   "expected": config.readiness.schema_revision},
        "database_bytes": int(_scalar(connection, "SELECT pg_database_size(current_database())")),
        "targets": [],
        "fetch": [],
        "openaq": [],
        "modeled": [],
        "stale_running": [],
        "quality_issues": [],
    }
    if install_table is None or revision != config.readiness.schema_revision:
        return facts

    run_sql = """
        SELECT status, error_code, started_at, finished_at, window_start, window_end
        FROM vn_air.ingestion_runs
        WHERE product_id = :product AND started_at >= :since AND started_at <= :as_of
          AND ((:target_kind = 'sensor' AND target_sensor_id = :target)
               OR (:target_kind = 'location' AND target_location_id = :target))
        ORDER BY started_at DESC
        LIMIT :limit
    """
    for target in targets:
        rows = _rows(connection, run_sql, {
            "product": target["product"], "since": run_since, "target": target["target"],
            "target_kind": target["target_kind"], "limit": HEALTH_RUN_ROW_LIMIT, "as_of": as_of,
        })
        record = dict(target)
        record["runs"] = _summarize_runs(rows, as_of=as_of)
        facts["targets"].append(record)

    fetch_sql = """
        SELECT max(sr.retrieved_at) AS latest_success_at, count(*) AS successes
        FROM vn_air.source_responses AS sr
        JOIN vn_air.ingestion_runs AS ir ON ir.id = sr.run_id
        WHERE sr.provider_group = :provider_group AND sr.product_id = :product
          AND ir.product_id = :product
          AND sr.http_status = 200 AND sr.error_code IS NULL AND sr.body IS NOT NULL
          AND sr.requested_at BETWEEN :since AND :as_of
          AND sr.retrieved_at BETWEEN :since AND :as_of
          AND ((:target_kind = 'sensor' AND ir.target_sensor_id = :target)
               OR (:target_kind = 'location' AND ir.target_location_id = :target))
    """
    for target in targets:
        fetch_rows = _rows(connection, fetch_sql, {
            "provider_group": PROVIDER_GROUPS[target["source"]],
            "product": target["product"], "since": run_since,
            "target": target["target"], "target_kind": target["target_kind"], "as_of": as_of,
        })
        facts["fetch"].append({
            **target,
            "provider_group": PROVIDER_GROUPS[target["source"]],
            **fetch_rows[0],
        })

    latest_revision_sql = """
        SELECT latest.period_end, latest.quality_status
        FROM (
            SELECT DISTINCT ON (period_start, period_end)
                period_start, period_end, revision, quality_status, value
            FROM vn_air.air_quality_observations
            WHERE sensor_id = :sensor AND period_end > :since AND period_end <= :coverage_end
            ORDER BY period_start, period_end, revision DESC
        ) AS latest
        ORDER BY latest.period_end DESC
        LIMIT 1
    """
    coverage_sql = """
        SELECT count(*) FILTER (WHERE quality_status = 'accepted' AND value IS NOT NULL) AS accepted_intervals,
               max(period_end) FILTER (WHERE quality_status = 'accepted' AND value IS NOT NULL) AS latest_accepted_end
        FROM (
            SELECT DISTINCT ON (period_start, period_end)
                period_start, period_end, quality_status, value
            FROM vn_air.air_quality_observations
            WHERE sensor_id = :sensor AND period_end > :coverage_start AND period_end <= :coverage_end
            ORDER BY period_start, period_end, revision DESC
        ) AS latest
    """
    accepted_sql = """
        SELECT max(period_end) AS latest_accepted_end
        FROM (
            SELECT DISTINCT ON (period_start, period_end) period_end, quality_status, value
            FROM vn_air.air_quality_observations
            WHERE sensor_id = :sensor AND period_end > :since AND period_end <= :coverage_end
            ORDER BY period_start, period_end, revision DESC
        ) AS latest
        WHERE quality_status = 'accepted' AND value IS NOT NULL
    """
    for target in targets:
        if target["source"] != OPENA_SOURCE:
            continue
        sensor = target["target"]
        coverage = _rows(connection, coverage_sql, {
            "sensor": sensor, "coverage_start": coverage_start, "coverage_end": coverage_end,
        })[0]
        latest_accepted = _scalar(connection, accepted_sql, {"sensor": sensor, "since": run_since,
                                                             "coverage_end": coverage_end})
        latest_revision = None
        revision_rows = _rows(connection, latest_revision_sql, {"sensor": sensor, "since": run_since,
                                                                "coverage_end": coverage_end})
        if revision_rows:
            latest_revision = revision_rows[0]
        facts["openaq"].append({
            "sensor": sensor,
            "accepted_intervals": int(coverage.get("accepted_intervals") or 0),
            "latest_accepted_end": coverage.get("latest_accepted_end"),
            "latest_accepted_within_lookback": latest_accepted,
            "latest_revision_period_end": latest_revision.get("period_end") if latest_revision else None,
            "latest_revision_status": latest_revision.get("quality_status") if latest_revision else None,
        })

    modeled_sql = """
        SELECT s.recorded_at, s.data_kind, r.retrieved_at,
               (SELECT count(*) FROM vn_air.modeled_values v
                WHERE v.snapshot_id = s.id AND v.quality_status = 'accepted' AND v.value IS NOT NULL)
                   AS accepted_values
        FROM vn_air.model_snapshots s
        JOIN vn_air.source_responses r ON r.id = s.response_id
        WHERE s.product_id = :product AND s.location_id = :location AND s.recorded_at >= :since
        ORDER BY s.recorded_at DESC
        LIMIT 1
    """
    for target in targets:
        if target["source"] not in MODEL_SOURCES:
            continue
        rows = _rows(connection, modeled_sql, {"product": target["product"], "location": target["target"],
                                               "since": run_since})
        snapshot = rows[0] if rows else None
        if snapshot is not None:
            snapshot["accepted_values"] = int(snapshot.get("accepted_values") or 0)
        facts["modeled"].append({**target, "latest_snapshot": snapshot})

    facts["stale_running"] = _rows(connection, """
        SELECT product_id, target_sensor_id, target_location_id, started_at
        FROM vn_air.ingestion_runs
        WHERE status = 'running' AND started_at >= :since AND started_at < :stale_before
        ORDER BY started_at DESC
        LIMIT 20
    """, {"since": run_since, "stale_before": stale_before})

    facts["quality_issues"] = _rows(connection, """
        SELECT issue_code, severity, count(*) AS open_count
        FROM vn_air.data_quality_issues
        WHERE detected_at >= :since AND resolved_at IS NULL
        GROUP BY issue_code, severity
        ORDER BY issue_code, severity
    """, {"since": as_of - timedelta(seconds=HEALTH_QUALITY_LOOKBACK_SECONDS)})
    return facts


def _summarize_runs(rows: list[dict], *, as_of: datetime) -> dict:
    if not rows:
        return {"count": 0, "latest_status": None, "latest_error_code": None,
                "latest_started_at": None, "latest_finished_at": None,
                "last_success_at": None, "last_partial_at": None, "last_failure_at": None,
                "latest_age_seconds": None}
    latest = rows[0]
    success = next((row["finished_at"] for row in rows if row["status"] == "succeeded"), None)
    partial = next((row["finished_at"] for row in rows if row["status"] == "partial"), None)
    failure = next((row["finished_at"] for row in rows if row["status"] == "failed"), None)
    return {
        "count": len(rows),
        "latest_status": latest.get("status"),
        "latest_error_code": normalize_error_code(latest.get("error_code")) if latest.get("error_code") else None,
        "latest_started_at": latest.get("started_at"),
        "latest_finished_at": latest.get("finished_at"),
        "last_success_at": success,
        "last_partial_at": partial,
        "last_failure_at": failure,
        "latest_age_seconds": _age_seconds(latest.get("started_at"), as_of),
    }


def inspect_backup_evidence(backup_dir: Path, *, as_of: datetime, stale_after_seconds: int) -> dict:
    from vn_air.automation_backup import (
        BACKUP_MANIFEST_NAME,
        validate_manifest_document,
    )

    directory = Path(backup_dir)
    result = {"directory": str(directory), "manifests_found": 0, "latest_manifest": None,
              "age_seconds": None, "status": "missing", "checksum_verified": False,
              "note": "Health checks manifest validity, declared file sizes and age; only backup-verify claims checksum or restore verification."}
    if directory.is_symlink() or not directory.is_dir():
        result["status"] = "missing"
        return result
    candidates = []
    direct = directory / BACKUP_MANIFEST_NAME
    if direct.is_file() and not direct.is_symlink():
        candidates.append(direct)
    else:
        for child in sorted(directory.iterdir()):
            if child.is_symlink() or not child.is_dir():
                continue
            manifest = child / BACKUP_MANIFEST_NAME
            if manifest.is_file() and not manifest.is_symlink():
                candidates.append(manifest)
    parsed = []
    for manifest in candidates:
        try:
            if manifest.stat().st_size > 1024 * 1024:
                continue
            document = json.loads(manifest.read_text(encoding="utf-8"))
            validate_manifest_document(document)
            created = _parse_moment(document["created_at_utc"])
            parsed.append((created, manifest.parent, document))
        except (OSError, ValueError, UnicodeDecodeError, AutomationError):
            parsed.append((None, manifest.parent, None))
    result["manifests_found"] = len(parsed)
    if not parsed:
        result["status"] = "missing"
        return result
    parsed.sort(key=lambda item: item[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    created, parent, document = parsed[0]
    if document is None or created is None:
        result["status"] = "invalid"
        result["latest_manifest"] = parent.name
        return result
    result["latest_manifest"] = parent.name
    if not _backup_files_consistent(parent, document):
        result["status"] = "invalid"
        return result
    age = round((as_of - created).total_seconds(), 3)
    result["age_seconds"] = age
    result["status"] = "stale" if age > stale_after_seconds else "current"
    return result


def _backup_files_consistent(parent: Path, document: dict) -> bool:
    for entry in document["archives"]:
        path = parent / entry["file"]
        try:
            info = path.lstat()
        except OSError:
            return False
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            return False
        if info.st_size != entry["bytes"]:
            return False
    return True


def _json_safe(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def assess_health(config, facts: dict, *, as_of: datetime, backup_facts: dict | None = None) -> dict:
    findings: list[dict] = []

    def add(severity: str, code: str, status: str, detail: str, *, source=None, target=None):
        findings.append({"severity": severity, "code": code, "status": status, "detail": detail,
                         "source": source, "target": target})

    schema = facts["schema"]
    if not schema["installed"]:
        add(SEVERITY_FAILED, "schema_revision_missing", "schema_mismatch",
            "Migration table public.vn_air_schema_version is absent")
    elif schema["revision"] != schema["expected"]:
        add(SEVERITY_FAILED, "schema_revision_mismatch", "schema_mismatch",
            f"Installed schema revision differs from the reviewed {schema['expected']}")

    budget_bytes = config.readiness.max_database_mib * 1024 * 1024
    if facts["database_bytes"] >= budget_bytes:
        add(SEVERITY_FAILED, "database_size_budget_exhausted", "budget_exhausted",
            f"Database size {facts['database_bytes']} bytes reached the {config.readiness.max_database_mib} MiB stop")
    elif facts["database_bytes"] >= budget_bytes * 0.8:
        add(SEVERITY_DEGRADED, "database_size_near_budget", "stale",
            f"Database size {facts['database_bytes']} bytes is above 80% of the worker stop")

    schema_ready = schema["installed"] and schema["revision"] == schema["expected"]
    if schema_ready:
        for target in facts["targets"]:
            runs = target["runs"]
            identity = {"source": target["source"], "target": target["target"]}
            if runs["count"] == 0:
                add(SEVERITY_FAILED, "run_evidence_missing", "unknown",
                    "No ingestion run recorded in the bounded lookback window", **identity)
                continue
            if runs["latest_status"] == "failed":
                add(SEVERITY_FAILED, "run_failed", "failed",
                    f"Latest run failed ({runs['latest_error_code']})", **identity)
            elif runs["latest_status"] == "partial":
                add(SEVERITY_DEGRADED, "run_partial", "partial", "Latest run was partial", **identity)
            elif runs["latest_status"] == "running":
                if runs["latest_age_seconds"] is not None and runs["latest_age_seconds"] > \
                        _threshold(config, target["target"], "stale_running_age_seconds"):
                    add(SEVERITY_DEGRADED, "run_stale", "stale",
                        "Latest run is still running past the stale threshold; suspected stale, not proven orphaned",
                        **identity)
            if runs["latest_error_code"] in COOLDOWN_ERROR_CODES:
                add(SEVERITY_DEGRADED, "provider_cooldown_indicator", "stale",
                    f"Latest run recorded {runs['latest_error_code']}", **identity)

        for target in facts["targets"]:
            if not any(fetch.get("source") == target["source"]
                       and fetch.get("target") == target["target"] for fetch in facts["fetch"]):
                add(SEVERITY_FAILED, "fetch_evidence_missing", "unknown",
                    "No retained successful HTTP receipt in the bounded lookback window",
                    source=target["source"], target=target["target"])
        for target in facts["targets"]:
            if target["source"] == OPENA_SOURCE and not any(
                    record["sensor"] == target["target"] for record in facts["openaq"]):
                add(SEVERITY_FAILED, "openaq_accepted_evidence_missing", "unknown",
                    "No accepted PM2.5 interval in the bounded lookback window",
                    source=OPENA_SOURCE, target=target["target"])
            if target["source"] in MODEL_SOURCES and not any(
                    record["target"] == target["target"] for record in facts["modeled"]):
                add(SEVERITY_FAILED, "modeled_capture_evidence_missing", "unknown",
                    "No modeled snapshot captured in the bounded lookback window",
                    source=target["source"], target=target["target"])

        for fetch in facts["fetch"]:
            identity = {"source": fetch["source"], "target": fetch.get("target")}
            age = _age_seconds(fetch.get("latest_success_at"), as_of)
            if age is None:
                add(SEVERITY_FAILED, "fetch_evidence_missing", "unknown",
                    "No retained successful HTTP receipt in the bounded lookback window", **identity)
            elif age < 0:
                add(SEVERITY_FAILED, "fetch_timestamp_invalid", "unknown",
                    "Receipt is later than the health cutoff", **identity)
            elif age > _threshold(config, fetch.get("target"), "fetch_success_age_seconds"):
                add(SEVERITY_DEGRADED, "fetch_stale", "stale",
                    f"Latest retained successful receipt is {age:.0f}s old", **identity)

        for record in facts["openaq"]:
            identity = {"source": OPENA_SOURCE, "target": record["sensor"]}
            if record["latest_accepted_within_lookback"] is None:
                add(SEVERITY_FAILED, "openaq_accepted_evidence_missing", "unknown",
                    "No accepted PM2.5 interval in the bounded lookback window", **identity)
            else:
                age = _age_seconds(record["latest_accepted_within_lookback"], as_of)
                if age is not None and age > _threshold(config, record["sensor"], "openaq_latest_period_age_seconds"):
                    add(SEVERITY_DEGRADED, "openaq_period_stale", "stale",
                        f"Latest accepted interval is {age:.0f}s old", **identity)
            if record["accepted_intervals"] < _threshold(config, record["sensor"], "openaq_min_accepted_intervals"):
                add(SEVERITY_DEGRADED, "openaq_low_coverage", "partial",
                    f"{record['accepted_intervals']}/{config.readiness.openaq_coverage_window_hours} accepted complete UTC intervals",
                    **identity)
            revision_moment = _parse_moment(record["latest_revision_period_end"])
            accepted_moment = _parse_moment(record["latest_accepted_within_lookback"])
            if (record["latest_revision_status"] not in (None, "accepted")
                    and revision_moment is not None
                    and (accepted_moment is None or revision_moment >= accepted_moment)):
                add(SEVERITY_DEGRADED, "openaq_recent_revision_not_accepted", "stale",
                    "The latest revision of a recent interval is missing or invalid; an older accepted value is retained",
                    **identity)

        for record in facts["modeled"]:
            identity = {"source": record["source"], "target": record["target"]}
            snapshot = record["latest_snapshot"]
            if snapshot is None:
                add(SEVERITY_FAILED, "modeled_capture_evidence_missing", "unknown",
                    "No modeled snapshot captured in the bounded lookback window", **identity)
                continue
            capture = max([moment for moment in (_parse_moment(snapshot.get("recorded_at")),
                                                 _parse_moment(snapshot.get("retrieved_at"))) if moment],
                          default=None)
            age = (as_of - capture).total_seconds() if capture else None
            if age is not None and age > _threshold(config, record["target"], "modeled_capture_age_seconds"):
                add(SEVERITY_DEGRADED, "modeled_capture_stale", "stale",
                    f"Latest snapshot capture is {age:.0f}s old", **identity)
            if snapshot["accepted_values"] == 0:
                add(SEVERITY_FAILED, "modeled_snapshot_invalid_only", "unknown",
                    "Latest snapshot has no accepted finite canonical values", **identity)

        if facts["stale_running"]:
            add(SEVERITY_DEGRADED, "stale_running_runs", "stale",
                f"{len(facts['stale_running'])} running row(s) exceed the stale threshold; suspected stale, not proven orphaned")

        for issue in facts["quality_issues"]:
            if issue["severity"] == "error":
                add(SEVERITY_DEGRADED, "open_quality_issues", "partial",
                    f"{issue['open_count']} unresolved error issue(s) with code {issue['issue_code']}")
            elif issue["issue_code"] in OPENA_QUALITY_CODES:
                add(SEVERITY_DEGRADED, "missing_hour_issues", "partial",
                    f"{issue['open_count']} unresolved {issue['issue_code']} issue(s)")

    if backup_facts is not None:
        status = backup_facts["status"]
        if status == "missing":
            add(SEVERITY_DEGRADED, "backup_missing", "backup_stale",
                "No backup manifest was found in the supplied backup directory")
        elif status == "invalid":
            add(SEVERITY_FAILED, "backup_manifest_invalid", "unknown",
                "The most recent backup manifest or its declared files failed strict validation")
        elif status == "stale":
            add(SEVERITY_DEGRADED, "backup_stale", "backup_stale",
                f"Latest backup is {backup_facts['age_seconds']:.0f}s old, beyond the configured threshold")

    overall = HEALTHY
    if any(finding["severity"] == SEVERITY_FAILED for finding in findings):
        overall = SEVERITY_FAILED
    elif any(finding["severity"] == SEVERITY_DEGRADED for finding in findings):
        overall = SEVERITY_DEGRADED
    rank = {HEALTHY: 0, SEVERITY_DEGRADED: 1, SEVERITY_FAILED: 2}
    findings.sort(key=lambda finding: (-rank[finding["severity"]], finding["code"],
                                       finding["target"] or "", finding["source"] or ""))
    document = {
        "automation_version": HEALTH_VERSION,
        "command": "health",
        "as_of_utc": iso(as_of),
        "schema": facts["schema"],
        "database_bytes": facts["database_bytes"],
        "database_budget_bytes": budget_bytes,
        "server_version_num": facts["server_version_num"],
        "severity_precedence": ["failed", "degraded", "healthy"],
        "status": overall,
        "exit_code": EXIT_BY_SEVERITY.get(overall, HEALTH_EXIT_HEALTHY),
        "targets": _json_safe(facts["targets"]),
        "fetch": _json_safe(facts["fetch"]),
        "openaq": _json_safe(facts["openaq"]),
        "modeled": _json_safe(facts["modeled"]),
        "stale_running_count": len(facts["stale_running"]),
        "quality_issues": _json_safe(facts["quality_issues"]),
        "backup": backup_facts,
        "findings": findings,
        "notes": [
            *HEALTH_NOTES,
            "Backup checksum/restore verification is not claimed by health; use automation backup-verify.",
        ],
    }
    return document


def health_snapshot(config, study, *, engine_factory: Callable | None = None, as_of: datetime | None = None,
                    backup_dir: Path | None = None) -> dict:
    as_of = (as_of or utc_now()).astimezone(timezone.utc)
    factory = engine_factory or (lambda: database_engine(
        connect_timeout=HEALTH_CONNECT_TIMEOUT_SECONDS))
    try:
        engine = factory()
    except ValueError:
        raise AutomationError("database_url_missing") from None
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SELECT set_config('statement_timeout', :ms, true)"),
                               {"ms": str(HEALTH_STATEMENT_TIMEOUT_MS)})
            facts = collect_health_facts(connection, config, study, as_of=as_of)
    except SQLAlchemyError:
        raise AutomationError("database_unavailable") from None
    finally:
        engine.dispose()
    backup_facts = None
    if backup_dir is not None:
        backup_facts = inspect_backup_evidence(backup_dir, as_of=as_of,
                                               stale_after_seconds=config.readiness.backup_stale_after_seconds)
    return assess_health(config, facts, as_of=as_of, backup_facts=backup_facts)


def print_health_summary(document: dict) -> None:
    backup = document.get("backup") or {}
    print(f"automation health: status={document['status']} exit={document['exit_code']} "
          f"as_of={document['as_of_utc']} findings={len(document['findings'])} "
          f"backup={backup.get('status', 'not_requested')}", file=sys.stderr)
    for finding in document["findings"]:
        location = " ".join(part for part in (finding.get("source"), finding.get("target")) if part)
        detail = f" {location}" if location else ""
        print(f"automation health: {finding['severity']} {finding['code']}{detail}: {finding['detail']}",
              file=sys.stderr)


def _write_exclusive_json(path: Path, document: dict) -> None:
    if path.exists() or path.is_symlink():
        raise AutomationError("automation_output_exists")
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise AutomationError("automation_output_parent_invalid")
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
        handle.write("\n")


def health_command(config, study, *, output: Path | None = None, backup_dir: Path | None = None,
                   engine_factory: Callable | None = None, as_of: datetime | None = None) -> int:
    try:
        document = health_snapshot(config, study, engine_factory=engine_factory, as_of=as_of,
                                   backup_dir=backup_dir)
    except AutomationError as error:
        print(f"automation: {error.code}", file=sys.stderr)
        return HEALTH_EXIT_FAILED
    except Exception:
        print("automation: internal_error", file=sys.stderr)
        return HEALTH_EXIT_FAILED
    if output is not None:
        try:
            _write_exclusive_json(Path(output), document)
        except AutomationError as error:
            print(f"automation: {error.code}", file=sys.stderr)
            return HEALTH_EXIT_INVALID
    print(json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False))
    print_health_summary(document)
    return document["exit_code"]


def _bounded_retry_window(run: dict, as_of: datetime) -> dict | None:
    start = _parse_moment(run.get("window_start"))
    end = _parse_moment(run.get("window_end"))
    if start is None or end is None or end <= start:
        return None
    floor = as_of.replace(minute=0, second=0, microsecond=0)
    latest_end = min(end, floor)
    bounded_start = max(start, latest_end - timedelta(hours=72))
    if bounded_start >= latest_end:
        return None
    return {"start": bounded_start, "end": latest_end}


def _retry_class(source: str, error_code: str | None) -> str:
    if error_code in NON_RETRYABLE_ERROR_CODES or error_code in {"unrecognized_child_error"}:
        return "not_retryable"
    if error_code in COOLDOWN_ERROR_CODES:
        return "cooldown"
    if error_code in TRANSIENT_ERROR_CODES:
        return "transient"
    return "not_retryable"


def _guidance_for(source: str, error_code: str | None, retry_class: str) -> tuple[str, bool, bool]:
    """Returns (guidance, retryable, poll_only)."""
    if source != OPENA_SOURCE:
        if retry_class == "cooldown":
            return ("Provider cooldown or budget stop is persisted by the worker; wait for the "
                    "documented cooldown and the next scheduled poll. Historical model backfill is "
                    "unsupported.", True, True)
        if retry_class == "transient":
            return ("Transient model-source error: wait for the next scheduled poll; historical model "
                    "backfill is unsupported.", True, True)
        return ("Error code is not automatically retryable; do not backfill model history. Review the "
                "evidence and wait for or restart a supervised poll.", False, True)
    if retry_class == "cooldown":
        return ("Provider cooldown or budget stop is persisted by the worker; retry only after the "
                "documented cooldown and keep the window bounded.", True, False)
    if retry_class == "transient":
        return ("Transient source error: a bounded explicit OpenAQ backfill may be appropriate "
                "after operator review.", True, False)
    return ("Error code is not automatically retryable; review the run, window and evidence before "
            "any explicit bounded backfill.", False, False)


def collect_recovery_facts(connection, config, *, as_of: datetime) -> dict:
    run_since = as_of - timedelta(seconds=HEALTH_LOOKBACK_SECONDS)
    stale_before = as_of - timedelta(seconds=config.readiness.stale_running_age_seconds)
    install_table = _scalar(connection, "SELECT to_regclass('public.vn_air_schema_version')")
    revision = None
    if install_table is not None:
        revision = _scalar(connection, "SELECT version_num FROM public.vn_air_schema_version")
    if install_table is None or revision != config.readiness.schema_revision:
        raise AutomationError("schema_revision_mismatch" if install_table is not None else "schema_revision_missing")
    stale = _rows(connection, """
        SELECT product_id, target_sensor_id, target_location_id, started_at
        FROM vn_air.ingestion_runs
        WHERE status = 'running' AND started_at >= :since AND started_at < :stale_before
        ORDER BY started_at DESC
        LIMIT 20
    """, {"since": run_since, "stale_before": stale_before})
    problem_sql = """
        SELECT r.product_id, r.target_sensor_id, r.target_location_id, r.status, r.error_code,
               r.started_at, r.finished_at, r.window_start, r.window_end,
               EXISTS (SELECT 1 FROM vn_air.ingestion_checkpoints c WHERE c.run_id = r.id)
                   AS checkpoint_completed
        FROM vn_air.ingestion_runs r
        WHERE r.product_id = :product AND r.started_at >= :since AND r.status IN ('failed', 'partial')
        ORDER BY r.started_at DESC
        LIMIT 50
    """
    products = sorted({PRODUCTS[job.source] for job in config.jobs})
    problems = []
    for product in products:
        problems.extend(_rows(connection, problem_sql, {"product": product, "since": run_since}))
    problems.sort(key=lambda row: row.get("started_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return {"stale_running": stale, "problems": problems[:50]}


def _iso_or_none(value) -> str | None:
    moment = _parse_moment(value)
    return iso(moment) if moment is not None else None


def build_recovery_guidance(config, study, facts: dict, *, as_of: datetime) -> dict:
    targets = configured_health_targets(config, study)
    by_product = {}
    for target in targets:
        by_product.setdefault(target["product"], []).append(target)
    findings = []
    for row in facts["stale_running"]:
        target = _target_label(row, by_product)
        findings.append({
            "kind": "stale_running",
            "source": _source_for_product(row["product_id"]),
            "product": row["product_id"],
            "target": target,
            "status": "stale",
            "error_code": None,
            "retryable": False,
            "retry_class": "operator_review",
            "operator_confirmation_required": True,
            "last_attempt_utc": iso(_parse_moment(row["started_at"]) or as_of),
            "window": {"start": _iso_or_none(row.get("window_start")),
                       "end": _iso_or_none(row.get("window_end"))},
            "checkpoint_completed": False,
            "guidance": ("Suspected stale, not proven orphaned. The Phase 3 worker finalizes lock-proven stale "
                         "runs at the start of the next supervised cycle. Do not mark it failed from inspection "
                         "and do not delete raw evidence."),
            "suggested_command": None,
            "poll_only": False,
        })
    for row in facts["problems"]:
        source = _source_for_product(row["product_id"]) or ""
        target = _target_label(row, by_product)
        error_code = normalize_error_code(row.get("error_code")) if row.get("error_code") else None
        retry_class = _retry_class(source, error_code)
        guidance, retryable, poll_only = _guidance_for(source, error_code, retry_class)
        window = _bounded_retry_window(row, as_of)
        suggested = None
        if retryable and not poll_only and source == OPENA_SOURCE and window is not None:
            suggested = ["vn-air", "ingest", "backfill", "--source", "openaq",
                         "--target", target, "--start", iso(window["start"]), "--end", iso(window["end"]),
                         "--max-requests", "10"]
        if row.get("checkpoint_completed"):
            guidance += (" A completed checkpoint exists for this run; coverage gaps are retained and the "
                         "checkpoint is never deleted or silently reconciled.")
        if retryable and not poll_only and window is None:
            guidance += " No explicit bounded window is recorded; supply one before any retry."
        openaq_ready = retryable and not poll_only and source == OPENA_SOURCE and window is not None
        model_ready = retryable and not poll_only and source != OPENA_SOURCE
        findings.append({
            "kind": "failed_or_partial_run",
            "source": source,
            "product": row["product_id"],
            "target": target,
            "status": row["status"],
            "error_code": error_code,
            "retryable": bool(openaq_ready or model_ready),
            "retry_class": retry_class,
            "operator_confirmation_required": True,
            "last_attempt_utc": iso(_parse_moment(row.get("finished_at") or row.get("started_at")) or as_of),
            "window": {"start": _iso_or_none(row.get("window_start")),
                       "end": _iso_or_none(row.get("window_end"))},
            "checkpoint_completed": bool(row.get("checkpoint_completed")),
            "guidance": guidance,
            "suggested_command": suggested,
            "poll_only": poll_only,
        })
    findings.sort(key=lambda finding: (finding["kind"], finding["source"] or "", finding["target"] or ""))
    return {
        "automation_version": HEALTH_VERSION,
        "command": "recover",
        "as_of_utc": iso(as_of),
        "read_only": True,
        "findings": findings,
        "counts": {"stale_running": len(facts["stale_running"]),
                   "failed_or_partial": len(facts["problems"])},
        "notes": list(RECOVERY_NOTES),
    }


def _target_label(row: dict, by_product: dict) -> str | None:
    for target in by_product.get(row["product_id"], []):
        if target["target_kind"] == "sensor" and target["target"] == row.get("target_sensor_id"):
            return target["target"]
        if target["target_kind"] == "location" and target["target"] == row.get("target_location_id"):
            return target["target"]
    return row.get("target_sensor_id") or row.get("target_location_id")


def _source_for_product(product: str) -> str | None:
    for source, source_product in PRODUCTS.items():
        if source_product == product:
            return source
    return None


def recover_command(config, study, *, engine_factory: Callable | None = None,
                    as_of: datetime | None = None, output: Path | None = None) -> int:
    as_of = (as_of or utc_now()).astimezone(timezone.utc)
    factory = engine_factory or (lambda: database_engine(
        connect_timeout=HEALTH_CONNECT_TIMEOUT_SECONDS))
    try:
        engine = factory()
    except ValueError:
        print("automation: database_url_missing", file=sys.stderr)
        return HEALTH_EXIT_FAILED
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SELECT set_config('statement_timeout', :ms, true)"),
                               {"ms": str(HEALTH_STATEMENT_TIMEOUT_MS)})
            facts = collect_recovery_facts(connection, config, as_of=as_of)
    except AutomationError as error:
        print(f"automation: {error.code}", file=sys.stderr)
        return HEALTH_EXIT_FAILED
    except SQLAlchemyError:
        print("automation: database_unavailable", file=sys.stderr)
        return HEALTH_EXIT_FAILED
    except Exception:
        print("automation: internal_error", file=sys.stderr)
        return HEALTH_EXIT_FAILED
    finally:
        engine.dispose()
    document = build_recovery_guidance(config, study, facts, as_of=as_of)
    if output is not None:
        try:
            _write_exclusive_json(Path(output), document)
        except AutomationError as error:
            print(f"automation: {error.code}", file=sys.stderr)
            return HEALTH_EXIT_INVALID
    print(json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False))
    print(f"automation recover: stale_running={document['counts']['stale_running']} "
          f"failed_or_partial={document['counts']['failed_or_partial']} read_only=true", file=sys.stderr)
    for finding in document["findings"]:
        print(f"automation recover: {finding['kind']} {finding['source']} {finding['target']} "
              f"retryable={finding['retryable']} poll_only={finding['poll_only']}",
              file=sys.stderr)
    return HEALTH_EXIT_HEALTHY


__all__ = [
    "HEALTH_EXIT_HEALTHY", "HEALTH_EXIT_FAILED", "HEALTH_EXIT_DEGRADED", "HEALTH_EXIT_INVALID",
    "assess_health", "build_recovery_guidance", "collect_health_facts", "collect_recovery_facts",
    "configured_health_targets", "health_command", "health_snapshot", "inspect_backup_evidence",
    "recover_command",
]
