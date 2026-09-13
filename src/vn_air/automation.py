"""Phase 11 bounded ingestion automation with safe local evidence.

Planning never opens a database or network connection. The supervised cycle
locks one stable checkout-local lock file, preflights the schema, runs the
reviewed poll jobs as supervised ``sys.executable -B -m vn_air.cli`` children,
reaps every child before releasing the lock and writes allowlisted evidence.
Never reads ``.env``, prints credentials or constructs shell strings.

Exit categories: ``0`` succeeded, ``2`` partial, ``1`` failed, ``3`` invalid
request and ``4`` concurrent cycle excluded.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Callable, Literal
from urllib.parse import unquote

from pydantic import Field, ValidationError, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from vn_air.config import Identifier, Record, StudyConfig, load_config
from vn_air.automation_environment import ingestion_environment
from vn_air.database.setup import database_engine
from vn_air.ingestion.pipeline import PRODUCTS


AUTOMATION_VERSION = "phase11_automation_v1"
DEFAULT_AUTOMATION_CONFIG = Path("configs/automation.json")
DEFAULT_STUDY_CONFIG = Path("configs/study.json")
CYCLE_SUMMARY_NAME = "phase_11_cycle_summary.json"
CYCLE_ALERTS_NAME = "phase_11_alerts.json"
CYCLE_SUCCESS_NAME = "SUCCESS.json"

EXIT_SUCCEEDED = 0
EXIT_FAILED = 1
EXIT_PARTIAL = 2
EXIT_INVALID_REQUEST = 3
EXIT_ALREADY_RUNNING = 4

OPTIONAL_SECRET_NAMES = ("DATABASE_URL", "OPENAQ_API_KEY", "SUPABASE_SECRET_KEY", "SUPABASE_DB_URL")

OUTPUT_LIMIT_BYTES = 256 * 1024
MAX_EVENT_LINE_BYTES = 8192
READ_CHUNK_BYTES = 65536

WINDOW_POLICIES = {
    "openaq": "openaq_last_72_complete_utc_hours",
    "weather": "model_three_utc_calendar_days_including_forecast_valid_times",
    "cams": "model_three_utc_calendar_days_including_forecast_valid_times",
}
WINDOW_NOTES = {
    "openaq_last_72_complete_utc_hours": "The worker derives the last 72 complete UTC hours from its own clock.",
    "model_three_utc_calendar_days_including_forecast_valid_times": "The worker derives three UTC calendar days, including provider forecast valid times, from its own clock.",
}

UNRECOGNIZED_ERROR_CODE = "unrecognized_child_error"
SUPERVISION_ERROR_CODES = frozenset({
    "job_timeout", "child_failed", "partial_ingestion", "previous_job_not_successful",
    "cycle_deadline_exceeded", "internal_error", UNRECOGNIZED_ERROR_CODE,
})
INGESTION_ERROR_CODES = frozenset({
    "credential_echo", "credential_in_parameters", "database_session_lost", "database_size_budget_exhausted",
    "database_unavailable", "duplicate_or_unsorted_model_time", "era5_publication_delay",
    "explicit_utc_window_required", "future_backfill", "future_reanalysis", "incomplete_measurement",
    "incomplete_model_data", "ingestion_already_running", "instrument_metadata_changed", "interrupted",
    "internal_or_database_error", "invalid_coordinates", "invalid_hourly_interval", "invalid_json",
    "invalid_licence_metadata", "invalid_location_metadata", "invalid_measurement_payload",
    "invalid_model_response", "invalid_model_timestamps", "invalid_timestamp", "invalid_window",
    "licence_not_qualified", "location_identity_mismatch", "location_metadata_missing",
    "malformed_model_response", "migration_required", "model_array_mismatch",
    "model_backfill_requires_utc_midnights", "model_grid_too_distant", "model_window_mismatch",
    "network_error", "no_configured_targets", "openaq_key_missing", "pagination_budget_exhausted",
    "pagination_mismatch", "provider_budget_exhausted", "provider_cooldown", "quarantined_records",
    "redirect_blocked", "request_budget_exhausted", "response_deadline", "response_too_large",
    "retry_exhausted", "sensor_parameter_changed", "station_coordinates_changed",
    "station_timezone_changed", "timeout", "timezone_inconsistency", "unapproved_endpoint",
    "unapproved_parameters", "unapproved_product_options", "unconfigured_target", "unknown_source",
    "unsupported_poll_options", "weather_forecast_is_poll_only_use_era5_for_history", "worker_interrupted",
    "wrong_parameter",
})
KNOWN_ERROR_CODES = INGESTION_ERROR_CODES | SUPERVISION_ERROR_CODES
SOURCES = frozenset(PRODUCTS)
PRODUCT_IDS = frozenset(PRODUCTS.values())
STATUS_VALUES = frozenset({"failed", "partial", "skipped", "succeeded"})
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
HTTP_CODE_PATTERN = re.compile(r"^http_[1-5][0-9]{2}$")
SQLSTATE_PATTERN = re.compile(r"^[A-Z0-9]{5}$")
CALENDAR_DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
STDERR_CODE_PATTERNS = (
    re.compile(r"Ingestion stopped: ([a-z][a-z0-9_]*)"),
    re.compile(r"Database operation failed \(([A-Z0-9]{5})\)"),
)
CONNECTION_PATTERN = re.compile(r"postgres(?:ql)?(?:\+psycopg)?://[^\s\"']+", re.IGNORECASE)

MAX_CONFIG_BYTES = 1024 * 1024
STREAM_DRAIN_SECONDS = 5
GROUP_REAP_SECONDS = 5
INTERRUPTED_ERROR_CODE = "cycle_interrupted"


def _exact_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Expected an integer literal")
    return value


def _exact_str(value):
    if not isinstance(value, str):
        raise ValueError("Expected a string literal")
    return value


def _exact_bool(value):
    if not isinstance(value, bool):
        raise ValueError("Expected a boolean literal")
    return value


def normalize_error_code(value) -> str:
    if isinstance(value, str) and len(value) <= 64:
        if value in KNOWN_ERROR_CODES:
            return value
        if HTTP_CODE_PATTERN.fullmatch(value):
            return value
        if SQLSTATE_PATTERN.fullmatch(value):
            return "database_error_" + value
    return UNRECOGNIZED_ERROR_CODE


def _uuid_value(value, context):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Invalid run identifier")
    return str(uuid.UUID(value))


def _product_value(value, context):
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError("Invalid product identity")
    allowed = context.get("products")
    if value not in (allowed if allowed is not None else PRODUCT_IDS):
        raise ValueError("Unreviewed product identity")
    return value


def _target_value(value, context):
    if not isinstance(value, str) or not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError("Invalid target identity")
    allowed = context.get("targets")
    if allowed is not None and value not in allowed:
        raise ValueError("Unreviewed target identity")
    return value


def _source_value(value, context):
    if not isinstance(value, str) or value not in SOURCES:
        raise ValueError("Invalid source identity")
    return value


def _status_value(value, context):
    if not isinstance(value, str) or value not in STATUS_VALUES:
        raise ValueError("Invalid status value")
    return value


def _count_value(value, context):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Invalid count value")
    return value


def _http_status_value(value, context):
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        raise ValueError("Invalid HTTP status value")
    return value


def _timestamp_value(value, context):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("Invalid timestamp value")
    moment = datetime.fromisoformat(value)
    if moment.utcoffset() is None:
        raise ValueError("Timestamp requires an offset")
    return moment.astimezone(timezone.utc).isoformat()


def _window_value(value, context):
    if isinstance(value, str) and CALENDAR_DATE_PATTERN.fullmatch(value):
        return value
    return _timestamp_value(value, context)


def _code_value(value, context):
    if not isinstance(value, str):
        raise ValueError("Invalid error code value")
    return normalize_error_code(value)


EVENT_SCHEMAS = {
    "ingestion_started": {
        "run_id": _uuid_value, "product": _product_value, "target": _target_value,
        "start": _timestamp_value, "end": _timestamp_value,
    },
    "ingestion_finished": {
        "run_id": _uuid_value, "product": _product_value, "target": _target_value,
        "status": _status_value, "inserted": _count_value, "unchanged": _count_value,
        "quarantined": _count_value, "missing_hours": _count_value,
    },
    "ingestion_failed": {
        "run_id": _uuid_value, "product": _product_value, "target": _target_value,
        "error_code": _code_value,
    },
    "checkpoint_skipped": {
        "product": _product_value, "target": _target_value,
        "start": _timestamp_value, "end": _timestamp_value,
    },
    "orphaned_run_recovered": {"run_id": _uuid_value},
    "run_finalization_failed": {"run_id": _uuid_value, "error_code": _code_value},
    "ingestion_summary": {
        "source": _source_value, "chunks": _count_value, "requests": _count_value,
        "inserted": _count_value, "unchanged": _count_value, "quarantined": _count_value,
    },
    "http_attempt": {
        "run_id": _uuid_value, "product": _product_value, "attempt": _count_value,
        "http_status": _http_status_value, "error_code": _code_value, "elapsed_ms": _count_value,
        "page": _count_value, "window_start": _window_value,
    },
}

CYCLE_NOTES = (
    "Operational wall-clock timestamps; live cycles are not byte-identical analytics artifacts.",
    "Concurrent-cycle exclusion only; this is not exactly-once delivery or multi-host coordination.",
    "The Phase 3 worker retains the per-database advisory lock, reference seeding and lock-proven stale-run finalization.",
    "Only allowlisted JSON events with reviewed value contracts are persisted; raw stdout/stderr and response bodies are never stored.",
)


class AutomationError(Exception):
    """Stable machine-readable failure code; detail never carries credentials."""

    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code)


class CycleInterrupted(BaseException):
    """External SIGINT/SIGTERM asked the supervised cycle to stop."""


def _install_interrupt_handlers():
    previous = {}

    def handler(signum, frame):
        raise CycleInterrupted(signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, handler)
        except (ValueError, OSError):
            pass
    return previous


def _restore_interrupt_handlers(previous) -> None:
    for sig, handler in previous.items():
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):
            pass


class CycleSettings(Record):
    job_timeout_seconds: Annotated[int, Field(ge=10, le=7200)]
    cycle_timeout_seconds: Annotated[int, Field(ge=60, le=86400)]
    terminate_grace_seconds: Annotated[int, Field(ge=1, le=60)]
    expected_cadence_seconds: Annotated[int, Field(ge=60, le=86400)]
    stop_on_failure: bool

    @model_validator(mode="after")
    def consistent_timeouts(self):
        if self.cycle_timeout_seconds < self.job_timeout_seconds:
            raise ValueError("cycle timeout must not be shorter than the per-job timeout")
        return self


class Job(Record):
    id: Identifier
    source: Literal["openaq", "weather", "cams"]
    targets: list[Identifier] = Field(min_length=1)
    max_requests: Annotated[int, Field(ge=1, le=500)]
    timeout_seconds: Annotated[int, Field(ge=10, le=7200)]
    window: Literal[
        "openaq_last_72_complete_utc_hours",
        "model_three_utc_calendar_days_including_forecast_valid_times",
    ]

    @field_validator("source", "window", mode="before")
    @classmethod
    def string_literals(cls, value):
        return _exact_str(value)

    @model_validator(mode="after")
    def source_window_contract(self):
        if self.window != WINDOW_POLICIES[self.source]:
            raise ValueError("window policy does not match the job source")
        if len(set(self.targets)) != len(self.targets):
            raise ValueError("duplicate target in job")
        return self


class TargetOverrides(Record):
    fetch_success_age_seconds: Annotated[int, Field(ge=60, le=604800)] | None = None
    openaq_latest_period_age_seconds: Annotated[int, Field(ge=60, le=604800)] | None = None
    openaq_min_accepted_intervals: Annotated[int, Field(ge=1, le=168)] | None = None
    modeled_capture_age_seconds: Annotated[int, Field(ge=60, le=604800)] | None = None
    stale_running_age_seconds: Annotated[int, Field(ge=60, le=86400)] | None = None


class Readiness(Record):
    max_database_mib: Annotated[int, Field(ge=1, le=400)]
    schema_revision: Literal["0003_response_integrity"]
    fetch_success_age_seconds: Annotated[int, Field(ge=60, le=604800)]
    openaq_latest_period_age_seconds: Annotated[int, Field(ge=60, le=604800)]
    openaq_min_accepted_intervals: Annotated[int, Field(ge=1, le=168)]
    openaq_coverage_window_hours: Literal[24]
    modeled_capture_age_seconds: Annotated[int, Field(ge=60, le=604800)]
    stale_running_age_seconds: Annotated[int, Field(ge=60, le=86400)]
    backup_stale_after_seconds: Annotated[int, Field(ge=3600, le=2592000)]
    overrides: dict[Identifier, TargetOverrides] = Field(default_factory=dict)

    @field_validator("schema_revision", mode="before")
    @classmethod
    def revision_literal(cls, value):
        return _exact_str(value)

    @field_validator("openaq_coverage_window_hours", mode="before")
    @classmethod
    def coverage_literal(cls, value):
        return _exact_int(value)

    @model_validator(mode="after")
    def coverage_contract(self):
        if self.openaq_min_accepted_intervals > self.openaq_coverage_window_hours:
            raise ValueError("accepted-interval threshold exceeds the coverage window")
        for override in self.overrides.values():
            if (override.openaq_min_accepted_intervals is not None
                    and override.openaq_min_accepted_intervals > self.openaq_coverage_window_hours):
                raise ValueError("override accepted-interval threshold exceeds the coverage window")
        return self


class OutputSettings(Record):
    root: Annotated[str, Field(min_length=1, max_length=200)]

    @model_validator(mode="after")
    def repo_relative_root(self):
        path = Path(self.root)
        if path.is_absolute() or ".." in path.parts or self.root in {".", "/"}:
            raise ValueError("output root must be a repo-relative path without traversal")
        return self


class BackupPolicy(Record):
    scope: Literal["project_logical"]
    recommended_cadence_hours: Annotated[int, Field(ge=1, le=720)]
    automatic_deletion: Literal[False]
    retention_note: Annotated[str, Field(min_length=1, max_length=1000)]
    offsite_note: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("scope", mode="before")
    @classmethod
    def scope_literal(cls, value):
        return _exact_str(value)

    @field_validator("automatic_deletion", mode="before")
    @classmethod
    def deletion_literal(cls, value):
        return _exact_bool(value)


class AutomationConfig(Record):
    version: Literal[1]
    cycle: CycleSettings
    jobs: list[Job] = Field(min_length=1)
    readiness: Readiness
    output: OutputSettings
    backup: BackupPolicy

    @field_validator("version", mode="before")
    @classmethod
    def version_literal(cls, value):
        return _exact_int(value)

    @model_validator(mode="after")
    def unique_jobs(self):
        identifiers = set()
        work_items = set()
        assigned_targets = set()
        for job in self.jobs:
            if job.id in identifiers:
                raise ValueError("duplicate job id")
            identifiers.add(job.id)
            work = (job.source, tuple(sorted(job.targets)))
            if work in work_items:
                raise ValueError("duplicate job source/target work")
            work_items.add(work)
            overlap = assigned_targets & set(job.targets)
            if overlap:
                raise ValueError("target assigned to more than one job")
            assigned_targets |= set(job.targets)
        if any(job.timeout_seconds > self.cycle.job_timeout_seconds for job in self.jobs):
            raise ValueError("job timeout exceeds the cycle per-job limit")
        return self


def load_automation_config(path: Path) -> AutomationConfig:
    try:
        info = path.lstat()
    except OSError:
        raise AutomationError("automation_config_missing") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise AutomationError("automation_config_unsafe")
    if info.st_size > MAX_CONFIG_BYTES:
        raise AutomationError("automation_config_too_large")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise AutomationError("automation_config_unreadable") from None

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise AutomationError("automation_config_duplicate_key")
            result[key] = value
        return result

    try:
        json.loads(content, object_pairs_hook=unique_keys)
    except AutomationError:
        raise
    except (ValueError, UnicodeDecodeError):
        raise AutomationError("automation_config_invalid_json") from None
    try:
        return AutomationConfig.model_validate_json(content)
    except ValidationError:
        raise AutomationError("automation_config_invalid") from None


def load_study_config(path: Path) -> StudyConfig:
    try:
        return load_config(path)
    except (ValueError, OSError, ValidationError):
        raise AutomationError("automation_study_config_invalid") from None


def validate_config_targets(config: AutomationConfig, study: StudyConfig) -> None:
    measured_products = {product.id for product in study.products
                         if product.domain == "air_quality" and product.data_kind == "measurement"}
    sensors = {sensor.id for sensor in study.sensors if sensor.product_id in measured_products}
    stations = {location.id for location in study.locations if location.kind == "station"}
    cities = {location.id for location in study.locations if location.kind == "city"}
    allowed_by_source = {"openaq": sensors, "weather": stations, "cams": cities}
    known_targets = sensors | stations | cities
    for job in config.jobs:
        if set(job.targets) - allowed_by_source[job.source]:
            raise AutomationError("automation_target_unconfigured", f"job={job.id}")
    if set(config.readiness.overrides) - known_targets:
        raise AutomationError("automation_override_unknown_target")


def default_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd().resolve()


def default_lock_path() -> Path:
    return default_repo_root() / ".local" / "automation" / "cycle.lock"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def planned_windows(now: datetime) -> dict:
    current = now.astimezone(timezone.utc)
    openaq_end = current.replace(minute=0, second=0, microsecond=0)
    model_start = openaq_end.replace(hour=0)
    return {
        "openaq": {
            "start": iso(openaq_end - timedelta(hours=72)),
            "end": iso(openaq_end),
            "label": "planned_parent_preview",
        },
        "weather": {
            "start": iso(model_start),
            "end": iso(model_start + timedelta(days=3)),
            "label": "planned_parent_preview",
        },
        "cams": {
            "start": iso(model_start),
            "end": iso(model_start + timedelta(days=3)),
            "label": "planned_parent_preview",
        },
    }


def job_argv(job: Job, study_path: Path, executable: str) -> list[str]:
    argv = [executable, "-B", "-m", "vn_air.cli", "ingest", "poll",
            "--source", job.source, "--config", str(study_path),
            "--max-requests", str(job.max_requests)]
    for target in job.targets:
        argv += ["--target", target]
    return argv


def build_plan(config: AutomationConfig, study: StudyConfig, *, now: datetime,
               study_path: Path | None = None, automation_path: Path | None = None,
               executable: str | None = None, clock_label: str = "current clock") -> dict:
    validate_config_targets(config, study)
    executable = executable or sys.executable
    study_path = study_path or DEFAULT_STUDY_CONFIG
    windows = planned_windows(now)
    jobs = []
    for order, job in enumerate(config.jobs, start=1):
        jobs.append({
            "order": order,
            "id": job.id,
            "source": job.source,
            "targets": list(job.targets),
            "max_requests": job.max_requests,
            "timeout_seconds": job.timeout_seconds,
            "effective_timeout_seconds": min(job.timeout_seconds, config.cycle.job_timeout_seconds),
            "window_policy": job.window,
            "window_note": WINDOW_NOTES[job.window],
            "planned_window": windows[job.source],
            "argv": job_argv(job, study_path, executable),
        })
    return {
        "automation_version": AUTOMATION_VERSION,
        "command": "plan",
        "generated_at_utc": iso(now),
        "planning_clock": clock_label,
        "automation_config_sha256": sha256_file(automation_path) if automation_path and automation_path.is_file() else None,
        "study_config_sha256": sha256_file(study_path) if study_path and study_path.is_file() else None,
        "cycle": {
            "job_timeout_seconds": config.cycle.job_timeout_seconds,
            "cycle_timeout_seconds": config.cycle.cycle_timeout_seconds,
            "terminate_grace_seconds": config.cycle.terminate_grace_seconds,
            "cleanup_allowance_seconds": (2 * STREAM_DRAIN_SECONDS + GROUP_REAP_SECONDS
                                          + config.cycle.terminate_grace_seconds),
            "expected_cadence_seconds": config.cycle.expected_cadence_seconds,
            "stop_on_failure": config.cycle.stop_on_failure,
        },
        "jobs": jobs,
        "output_root": config.output.root,
        "backup": {
            "scope": config.backup.scope,
            "recommended_cadence_hours": config.backup.recommended_cadence_hours,
            "automatic_deletion": config.backup.automatic_deletion,
        },
        "preflight": {
            "status": "unperformed",
            "database_check": "unperformed",
            "schema_check": "unperformed",
            "role_check": "unperformed",
            "network_calls": 0,
        },
        "notes": [
            "Dry-run only: no database, credential or network access was performed.",
            "Child processes derive the executed poll window from their own clock; planned windows are a parent preview.",
            "Activation requires a reviewed grants/RLS design; this profile does not provision or assume a least-privilege role.",
        ],
    }


class CycleLock:
    """One stable checkout-local OS lock; the lock file is never unlinked."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fd: int | None = None

    def acquire(self) -> bool:
        parent = self.path.parent
        grandparent = parent.parent
        for candidate in (grandparent, parent):
            if candidate.exists() and candidate.is_symlink():
                raise AutomationError("automation_lock_unsafe")
        if parent.exists() and not parent.is_dir():
            raise AutomationError("automation_lock_unsafe")
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise AutomationError("automation_lock_unsafe")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError:
            raise AutomationError("automation_lock_unsafe") from None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(descriptor)
            return False
        try:
            os.fchmod(descriptor, 0o600)
        except OSError:
            pass
        self._fd = descriptor
        return True

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


def environment_secrets(environ: dict | None = None) -> tuple[str, ...]:
    values: list[str] = []
    environment = os.environ if environ is None else environ
    for name in OPTIONAL_SECRET_NAMES:
        value = environment.get(name)
        if value:
            values.append(value)
            decoded = unquote(value)
            if decoded != value:
                values.append(decoded)
    try:
        parsed = make_url(environment["DATABASE_URL"])
        if parsed.password:
            values.append(parsed.password)
            values.append(unquote(parsed.password))
    except Exception:
        pass
    return tuple(dict.fromkeys(value for value in values if value))


def scrub_text(value, secrets: tuple[str, ...] = ()) -> str:
    text_value = str(value)
    for secret in secrets:
        if secret:
            text_value = text_value.replace(secret, "[redacted]")
    return CONNECTION_PATTERN.sub("[redacted-connection]", text_value)


def extract_event(line: bytes, secrets: tuple[str, ...] = (), context: dict | None = None) -> dict | None:
    if not line or len(line) > MAX_EVENT_LINE_BYTES:
        return None
    try:
        record = json.loads(line)
    except (ValueError, UnicodeDecodeError):
        return None
    return sanitize_event(record, secrets, context)


def sanitize_event(record, secrets: tuple[str, ...] = (), context: dict | None = None) -> dict | None:
    if not isinstance(record, dict):
        return None
    event_name = record.get("event")
    if not isinstance(event_name, str):
        return None
    schema = EVENT_SCHEMAS.get(event_name)
    if schema is None:
        return None
    context = context or {}
    safe = {"event": event_name}
    for field_name, validator in schema.items():
        value = record.get(field_name)
        if value is None:
            continue
        if field_name == "error_code":
            try:
                safe[field_name] = validator(value, context)
            except (ValueError, TypeError):
                safe[field_name] = UNRECOGNIZED_ERROR_CODE
            continue
        try:
            safe[field_name] = validator(value, context)
        except (ValueError, TypeError, OverflowError):
            return None
    for field_name, value in safe.items():
        if isinstance(value, str):
            safe[field_name] = scrub_text(value, secrets)
    return safe


def extract_stderr_codes(line: bytes) -> list[str]:
    try:
        decoded = line.decode("utf-8", errors="ignore")
    except Exception:
        return []
    codes = []
    for pattern in STDERR_CODE_PATTERNS:
        codes.extend(normalize_error_code(code) for code in pattern.findall(decoded))
    return codes


class _StreamCollector:
    def __init__(self, *, limit: int, secrets: tuple[str, ...], parse_events: bool):
        self.events: list[dict] = []
        self.error_codes: list[str] = []
        self.total_bytes = 0
        self.stored_bytes = 0
        self.invalid_lines = 0
        self._limit = limit
        self._secrets = secrets
        self._parse_events = parse_events
        self._buffer = b""

    def feed(self, chunk: bytes) -> None:
        self.total_bytes += len(chunk)
        remaining = self._limit - self.stored_bytes
        if remaining <= 0:
            return
        chunk = chunk[:remaining]
        self.stored_bytes += len(chunk)
        self._buffer += chunk
        lines = self._buffer.split(b"\n")
        self._buffer = lines.pop()
        for line in lines:
            self._consume(line)
        if len(self._buffer) > MAX_EVENT_LINE_BYTES:
            self.invalid_lines += 1
            self._buffer = b""

    def finish(self) -> None:
        if self._buffer:
            self._consume(self._buffer)
            self._buffer = b""

    def _consume(self, line: bytes) -> None:
        if not line.strip():
            return
        if self._parse_events:
            event = extract_event(line, self._secrets)
            if event is None:
                self.invalid_lines += 1
            else:
                self.events.append(event)
        else:
            codes = extract_stderr_codes(line)
            if codes:
                self.error_codes.extend(codes)
            else:
                self.invalid_lines += 1


def _pump(stream, collector: _StreamCollector) -> None:
    try:
        while True:
            chunk = stream.read(READ_CHUNK_BYTES)
            if not chunk:
                break
            collector.feed(chunk)
    except (OSError, ValueError):
        pass
    finally:
        collector.finish()
        try:
            stream.close()
        except (OSError, ValueError):
            pass


def _group_alive(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _signal_group(process_group: int, sig: int) -> None:
    try:
        os.killpg(process_group, sig)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _reap_group(process_group: int, deadline_seconds: float = GROUP_REAP_SECONDS) -> bool:
    limit = time.monotonic() + deadline_seconds
    while time.monotonic() < limit:
        if not _group_alive(process_group):
            return True
        time.sleep(0.05)
    return not _group_alive(process_group)


class SubprocessSupervisor:
    """Bounded child supervision: shell-free argv arrays, monotonic deadlines,
    retained process-group terminate/kill/reap, allowlisted JSON evidence."""

    def __init__(self, *, executable: str | None = None, cwd: Path | None = None,
                 output_limit_bytes: int = OUTPUT_LIMIT_BYTES,
                 secrets: tuple[str, ...] | None = None):
        self.executable = executable or sys.executable
        self.cwd = Path(cwd) if cwd is not None else default_repo_root()
        self.output_limit_bytes = output_limit_bytes
        self.secrets = tuple(secrets) if secrets is not None else environment_secrets()

    def child_environment(self, env: dict | None = None) -> dict:
        return ingestion_environment(os.environ if env is None else env,
                                     default_repo_root() / "src")

    def run(self, argv: list[str], *, env: dict | None = None, timeout_seconds: float,
            grace_seconds: float) -> dict:
        if (not isinstance(argv, (list, tuple)) or not argv
                or not all(isinstance(argument, str) for argument in argv)):
            raise AutomationError("automation_argv_invalid")
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=self.child_environment(env), cwd=str(self.cwd),
                start_new_session=True, close_fds=True)
        except OSError:
            raise AutomationError("automation_child_spawn_failed") from None
        process_group = os.getpgid(process.pid)
        stdout = _StreamCollector(limit=self.output_limit_bytes, secrets=self.secrets, parse_events=True)
        stderr = _StreamCollector(limit=self.output_limit_bytes, secrets=self.secrets, parse_events=False)
        threads = [
            threading.Thread(target=_pump, args=(process.stdout, stdout), daemon=True),
            threading.Thread(target=_pump, args=(process.stderr, stderr), daemon=True),
        ]
        for thread in threads:
            thread.start()
        timed_out = False
        interrupted = False
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except (CycleInterrupted, KeyboardInterrupt):
            interrupted = True
            exit_code = None
        except subprocess.TimeoutExpired:
            timed_out = True
            _signal_group(process_group, signal.SIGTERM)
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                _signal_group(process_group, signal.SIGKILL)
        finally:
            if process.poll() is None:
                _signal_group(process_group, signal.SIGKILL)
                try:
                    process.wait(timeout=STREAM_DRAIN_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
            if _group_alive(process_group):
                _signal_group(process_group, signal.SIGKILL)
                _reap_group(process_group)
            if process.poll() is None:
                process.wait()
            for thread in threads:
                thread.join(timeout=STREAM_DRAIN_SECONDS)
        return {
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "interrupted": interrupted,
            "group_reaped": not _group_alive(process_group),
            "duration_seconds": round(time.monotonic() - started, 3),
            "events": stdout.events,
            "stderr_error_codes": stderr.error_codes,
            "stdout_bytes": stdout.total_bytes,
            "stderr_bytes": stderr.total_bytes,
            "invalid_stdout_lines": stdout.invalid_lines,
            "invalid_stderr_lines": stderr.invalid_lines,
        }


def database_preflight(config: AutomationConfig, *, engine_factory: Callable | None = None,
                       remaining_seconds: float | None = None) -> dict:
    if remaining_seconds is not None and remaining_seconds <= 0:
        raise AutomationError("cycle_deadline_exceeded")
    connect_timeout = 10
    statement_timeout_ms = 15000
    if remaining_seconds is not None:
        connect_timeout = min(10, max(1, int(remaining_seconds)))
        statement_timeout_ms = min(15000, max(1000, int(remaining_seconds * 1000)))
    if engine_factory is None:
        engine_factory = lambda: database_engine(connect_timeout=connect_timeout)
    try:
        engine = engine_factory()
    except ValueError:
        raise AutomationError("database_url_missing") from None
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SELECT set_config('statement_timeout', :ms, true)"),
                               {"ms": str(statement_timeout_ms)})
            server_version = int(connection.execute(text("SELECT current_setting('server_version_num')")).scalar_one())
            installed = connection.execute(text("SELECT to_regclass('public.vn_air_schema_version')")).scalar_one()
            revision = None
            if installed is not None:
                revision = connection.execute(text("SELECT version_num FROM public.vn_air_schema_version")).scalar_one_or_none()
            size = int(connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one())
    except SQLAlchemyError:
        raise AutomationError("database_unavailable") from None
    finally:
        engine.dispose()
    if server_version < 150000:
        raise AutomationError("database_version_unsupported")
    if revision is None:
        raise AutomationError("schema_revision_missing")
    if revision != config.readiness.schema_revision:
        raise AutomationError("schema_revision_mismatch")
    if size >= config.readiness.max_database_mib * 1024 * 1024:
        raise AutomationError("database_size_budget_exhausted")
    return {"status": "ok", "schema_revision": revision, "database_bytes": size,
            "server_version_num": server_version}


def reserve_output_dir(path: Path) -> Path:
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise AutomationError("automation_output_exists")
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise AutomationError("automation_output_parent_invalid")
    resolved = path.resolve()
    broad = {Path("/"), Path.home().resolve(), default_repo_root()}
    if resolved in broad or resolved.parent == Path("/") or len(resolved.parts) < 2:
        raise AutomationError("automation_output_broad")
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        raise AutomationError("automation_output_exists") from None
    except OSError:
        raise AutomationError("automation_output_parent_invalid") from None
    if path.is_symlink():
        raise AutomationError("automation_output_unsafe")
    return path


def write_exclusive_json(path: Path, document: dict) -> str:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
        handle.write("\n")
    return path.name


def _job_record(job: Job, order: int, outcome: dict, argv: list[str], secrets: tuple[str, ...] = (),
                effective_timeout: float | None = None) -> dict:
    if outcome.get("timed_out") or outcome.get("interrupted"):
        status = "failed"
    elif outcome.get("exit_code") == EXIT_SUCCEEDED:
        status = "succeeded"
    elif outcome.get("exit_code") == EXIT_PARTIAL:
        status = "partial"
    else:
        status = "failed"
    context = {"targets": frozenset(job.targets), "products": frozenset({PRODUCTS[job.source]})}
    events = []
    for event in outcome.get("events", []):
        sanitized = sanitize_event(event, secrets, context)
        if sanitized is not None:
            events.append(sanitized)
    codes = [event.get("error_code") for event in events
             if event.get("event") == "ingestion_failed" and event.get("error_code")]
    if not codes:
        codes = [normalize_error_code(code) for code in outcome.get("stderr_error_codes", [])]
    primary = codes[-1] if codes else None
    if outcome.get("timed_out"):
        primary = "job_timeout"
    elif outcome.get("interrupted"):
        primary = INTERRUPTED_ERROR_CODE
    elif primary is None and status == "failed":
        primary = "child_failed"
    elif primary is None and status == "partial":
        primary = "partial_ingestion"
    return {
        "order": order,
        "id": job.id,
        "source": job.source,
        "targets": list(job.targets),
        "max_requests": job.max_requests,
        "configured_timeout_seconds": job.timeout_seconds,
        "effective_timeout_seconds": effective_timeout,
        "attempted": True,
        "status": status,
        "error_code": primary,
        "exit_code": outcome.get("exit_code"),
        "timed_out": bool(outcome.get("timed_out")),
        "interrupted": bool(outcome.get("interrupted")),
        "duration_seconds": outcome.get("duration_seconds"),
        "stdout_bytes": outcome.get("stdout_bytes", 0),
        "stderr_bytes": outcome.get("stderr_bytes", 0),
        "events": events,
        "argv_allowlisted": True,
        "child_argument_count": len(argv),
    }


def _not_attempted_record(job: Job, order: int, reason: str) -> dict:
    return {
        "order": order,
        "id": job.id,
        "source": job.source,
        "targets": list(job.targets),
        "max_requests": job.max_requests,
        "configured_timeout_seconds": job.timeout_seconds,
        "attempted": False,
        "status": "not_attempted",
        "error_code": reason,
        "exit_code": None,
        "timed_out": False,
        "duration_seconds": None,
        "events": [],
    }


def _alerts_for(record: dict) -> list[dict]:
    if record["status"] == "succeeded":
        return []
    severity = "error" if record["status"] in {"failed", "not_attempted"} else "warning"
    return [{
        "severity": severity,
        "code": record.get("error_code") or "unknown",
        "job_id": record["id"],
        "source": record["source"],
    }]


def _cycle_outcome(summary: dict) -> tuple[str, int]:
    if summary.get("error_code"):
        return "failed", EXIT_FAILED
    statuses = [job["status"] for job in summary["jobs"]]
    if any(status == "failed" for status in statuses):
        return "failed", EXIT_FAILED
    if any(status == "partial" for status in statuses):
        return "partial", EXIT_PARTIAL
    if any(status == "not_attempted" for status in statuses):
        return "failed", EXIT_FAILED
    return "succeeded", EXIT_SUCCEEDED


def _finalize(output_dir: Path, summary: dict, alerts: list[dict], *, now: datetime, duration: float) -> dict:
    summary["finished_at_utc"] = iso(now)
    summary["duration_seconds"] = round(duration, 3)
    summary["status"], summary["exit_code"] = _cycle_outcome(summary)
    summary["alerts"] = alerts
    write_exclusive_json(output_dir / CYCLE_SUMMARY_NAME, summary)
    write_exclusive_json(output_dir / CYCLE_ALERTS_NAME, {
        "automation_version": AUTOMATION_VERSION,
        "generated_at_utc": iso(now),
        "alerts": alerts,
    })
    if summary["status"] == "succeeded":
        files = {name: sha256_file(output_dir / name) for name in (CYCLE_SUMMARY_NAME, CYCLE_ALERTS_NAME)}
        write_exclusive_json(output_dir / CYCLE_SUCCESS_NAME, {
            "automation_version": AUTOMATION_VERSION,
            "status": "succeeded",
            "summary_sha256": files[CYCLE_SUMMARY_NAME],
            "files_sha256": files,
        })
    return {"status": summary["status"], "exit_code": summary["exit_code"],
            "summary_path": str(output_dir / CYCLE_SUMMARY_NAME)}


def run_cycle(config: AutomationConfig, study: StudyConfig, *, output_dir: Path | None, execute: bool,
              automation_path: Path | None = None, study_path: Path | None = None,
              lock_path: Path | None = None, supervisor=None, preflight: Callable | None = None,
              argv_builder: Callable | None = None, clock: Callable = time.monotonic,
              now: Callable = utc_now, cycle_id: str | None = None,
              secrets: tuple[str, ...] | None = None) -> dict:
    if not execute:
        raise AutomationError("automation_execute_required")
    if output_dir is None:
        raise AutomationError("automation_output_required")
    validate_config_targets(config, study)
    secrets = environment_secrets() if secrets is None else tuple(secrets)
    lock = CycleLock(lock_path or default_lock_path())
    if not lock.acquire():
        return {"status": "already_running", "exit_code": EXIT_ALREADY_RUNNING, "summary_path": None}
    previous_handlers = None
    cycle_start = None
    summary = None
    alerts: list[dict] = []
    resolved_output = Path(output_dir)
    try:
        previous_handlers = _install_interrupt_handlers()
        cycle_start = clock()
        started = now()
        deadline = cycle_start + config.cycle.cycle_timeout_seconds
        cleanup_allowance = (2 * STREAM_DRAIN_SECONDS + GROUP_REAP_SECONDS
                             + config.cycle.terminate_grace_seconds)
        summary = {
            "automation_version": AUTOMATION_VERSION,
            "command": "run",
            "cycle_id": str(cycle_id or uuid.uuid4()),
            "operational_timestamps": True,
            "config_sha256": sha256_file(automation_path) if automation_path and automation_path.is_file() else None,
            "study_config_sha256": sha256_file(study_path) if study_path and study_path.is_file() else None,
            "schema_revision": config.readiness.schema_revision,
            "started_at_utc": iso(started),
            "deadline_policy": {
                "cycle_timeout_seconds": config.cycle.cycle_timeout_seconds,
                "cleanup_allowance_seconds": cleanup_allowance,
                "includes_preflight": True,
                "child_cleanup_bounded_seconds": cleanup_allowance,
            },
            "planned_windows_note": "Child processes derive the executed window from their own clock.",
            "jobs": [],
            "notes": list(CYCLE_NOTES),
        }
        supervisor = supervisor or SubprocessSupervisor()
        study_path = study_path or DEFAULT_STUDY_CONFIG
        argv_builder = argv_builder or (lambda job, path: job_argv(job, path, supervisor.executable
                                                                   if hasattr(supervisor, "executable") else sys.executable))
        resolved_output = reserve_output_dir(resolved_output)
        try:
            preflight_remaining = deadline - clock()
            if preflight_remaining <= 0:
                raise AutomationError("cycle_deadline_exceeded")
            preflight_callable = preflight or (lambda remaining: database_preflight(config, remaining_seconds=remaining))
            summary["preflight"] = preflight_callable(preflight_remaining)
        except AutomationError as error:
            summary["error_code"] = error.code
            summary["preflight"] = {"status": "failed", "error_code": error.code}
            alerts.append({"severity": "error", "code": error.code, "job_id": None, "source": None})
            return _finalize(resolved_output, summary, alerts, now=now(), duration=clock() - cycle_start)
        except Exception:
            summary["error_code"] = "internal_error"
            summary["preflight"] = {"status": "failed", "error_code": "internal_error"}
            alerts.append({"severity": "error", "code": "internal_error", "job_id": None, "source": None})
            return _finalize(resolved_output, summary, alerts, now=now(), duration=clock() - cycle_start)
        stopped = False
        try:
            for order, job in enumerate(config.jobs, start=1):
                if stopped:
                    record = _not_attempted_record(job, order, "previous_job_not_successful")
                else:
                    remaining = deadline - clock()
                    if remaining <= cleanup_allowance:
                        record = _not_attempted_record(job, order, "cycle_deadline_exceeded")
                        stopped = True
                    else:
                        timeout = min(job.timeout_seconds, config.cycle.job_timeout_seconds,
                                      remaining - cleanup_allowance)
                        argv = argv_builder(job, study_path)
                        outcome = supervisor.run(argv, timeout_seconds=timeout,
                                                 grace_seconds=config.cycle.terminate_grace_seconds)
                        record = _job_record(job, order, outcome, argv, secrets, timeout)
                        if record["status"] != "succeeded" and config.cycle.stop_on_failure:
                            stopped = True
                        if outcome.get("interrupted"):
                            summary["jobs"].append(record)
                            alerts.extend(_alerts_for(record))
                            raise CycleInterrupted(0)
                summary["jobs"].append(record)
                alerts.extend(_alerts_for(record))
        except AutomationError as error:
            summary["error_code"] = error.code
            alerts.append({"severity": "error", "code": error.code, "job_id": None, "source": None})
        except Exception:
            summary["error_code"] = "internal_error"
            alerts.append({"severity": "error", "code": "internal_error", "job_id": None, "source": None})
        return _finalize(resolved_output, summary, alerts, now=now(), duration=clock() - cycle_start)
    except (CycleInterrupted, KeyboardInterrupt):
        if summary is None:
            summary = {
                "automation_version": AUTOMATION_VERSION,
                "command": "run",
                "cycle_id": str(cycle_id or uuid.uuid4()),
                "operational_timestamps": True,
                "started_at_utc": iso(now()),
                "jobs": [],
                "notes": list(CYCLE_NOTES),
            }
        summary["error_code"] = INTERRUPTED_ERROR_CODE
        alerts.append({"severity": "error", "code": INTERRUPTED_ERROR_CODE, "job_id": None, "source": None})
        elapsed = (clock() - cycle_start) if cycle_start is not None else 0.0
        try:
            if resolved_output.is_dir() and not resolved_output.is_symlink():
                return _finalize(resolved_output, summary, alerts, now=now(), duration=elapsed)
        except OSError:
            pass
        return {"status": "failed", "exit_code": EXIT_FAILED, "summary_path": None}
    finally:
        if previous_handlers is not None:
            _restore_interrupt_handlers(previous_handlers)
        lock.release()


def print_cycle_status(result: dict) -> None:
    if result["status"] == "already_running":
        print("automation: already_running", file=sys.stderr)
        return
    print(f"automation cycle status={result['status']} exit={result['exit_code']} summary={result['summary_path']}",
          file=sys.stderr)


def automation_command(*, action: str, automation_config: Path | None = None,
                       study_config: Path | None = None, output_dir: Path | None = None,
                       execute: bool = False, now: datetime | None = None,
                       output: Path | None = None, backup_dir: Path | None = None,
                       restore_drill: bool = False) -> int:
    automation_config = automation_config or DEFAULT_AUTOMATION_CONFIG
    study_config = study_config or DEFAULT_STUDY_CONFIG
    if action == "run":
        if not execute:
            print("automation: automation_execute_required", file=sys.stderr)
            return EXIT_INVALID_REQUEST
        if output_dir is None:
            print("automation: automation_output_required", file=sys.stderr)
            return EXIT_INVALID_REQUEST
    try:
        config = load_automation_config(automation_config)
        study = load_study_config(study_config)
        validate_config_targets(config, study)
    except AutomationError as error:
        print(f"automation: {error.code}", file=sys.stderr)
        return EXIT_INVALID_REQUEST
    if action == "plan":
        plan = build_plan(config, study, now=now or utc_now(), study_path=study_config,
                          automation_path=automation_config,
                          clock_label="explicit --now" if now is not None else "current clock")
        print(json.dumps(plan, sort_keys=True))
        return EXIT_SUCCEEDED
    if action == "run":
        try:
            result = run_cycle(config, study, output_dir=output_dir, execute=True,
                               automation_path=automation_config, study_path=study_config)
        except AutomationError as error:
            print(f"automation: {error.code}", file=sys.stderr)
            return EXIT_INVALID_REQUEST
        print_cycle_status(result)
        return result["exit_code"]
    if action == "health":
        from vn_air.automation_health import health_command
        return health_command(config, study, output=output, backup_dir=backup_dir)
    if action == "recover":
        from vn_air.automation_health import recover_command
        return recover_command(config, study, output=output)
    if action == "backup":
        from vn_air.automation_backup import backup_command
        return backup_command(config, study, output_dir=output_dir, execute=execute)
    if action == "backup-verify":
        from vn_air.automation_backup import backup_verify_command
        return backup_verify_command(config, study, backup_dir=backup_dir, restore_drill=restore_drill)
    print(f"automation: unsupported_action_{action}", file=sys.stderr)
    return EXIT_INVALID_REQUEST
