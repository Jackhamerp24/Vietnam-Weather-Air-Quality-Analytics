"""Deterministic quality screening; no database writes or automatic exclusions."""

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from uuid import UUID
from zoneinfo import ZoneInfo

from vn_air.ingestion.parsing import AIR, WEATHER, distance_km

AUDIT_VERSION = "phase4_quality_audit_v1"
HOUR = timedelta(hours=1)
POLICY = {
    "measurement_selection": "Latest eligible revision before quality; no fallback",
    "model_selection": "Within product/location/purpose, latest retrieved capture covering valid time before variable/quality selection; no fallback",
    "model_tie_break": "retrieved_at, snapshot recorded_at, UUID; deterministic, not provider run order",
    "alignment": "PM [t,t+1h): instantaneous weather at t; preceding-hour totals/means at t+1h",
    "pm_review_above_ug_m3": 500, "minimum_hour_coverage_percent": 75,
    "sentinel_candidates": [-999, -9999, 9999], "flatline_review_hours": 6,
    "use": "Retrospective screening only; thresholds are review prompts, not calibrated error detectors",
}


def json_default(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError("Unsupported audit JSON type")


def digest(value):
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), default=json_default, allow_nan=False)
    return hashlib.sha256(body.encode()).hexdigest()


def validate_window(cutoff, start, end):
    if any(not isinstance(t, datetime) or t.utcoffset() != timedelta(0) for t in (cutoff, start, end)):
        raise ValueError("Audit timestamps must be timezone-aware UTC")
    if not 0 < (end - start).total_seconds() <= 366 * 86400:
        raise ValueError("Audit window must be positive and at most 366 days")
    if start.timestamp() % 3600 or end.timestamp() % 3600:
        raise ValueError("Audit bounds must be on UTC hour boundaries")
    if end > cutoff:
        raise ValueError("Measurement window cannot end after cutoff")


def hourly_end_grid(start, end):
    """Complete measured intervals enclosed in [start,end), keyed by period end."""
    validate_window(end, start, end)
    return [start + i * HOUR for i in range(1, int((end - start) / HOUR) + 1)]


def gap_summary(expected, present):
    present = expected & present
    runs = []
    for at in sorted(expected - present):
        if runs and at == runs[-1]["last"] + HOUR:
            runs[-1]["last"] = at
            runs[-1]["hours"] += 1
        else:
            runs.append({"first": at, "last": at, "hours": 1})
    return {"expected_hours": len(expected), "present_hours": len(present),
            "missing_hours": len(expected - present),
            "completeness_percent": round(100 * len(present) / len(expected), 4) if expected else None,
            "longest_missing_run_hours": max((r["hours"] for r in runs), default=0), "missing_runs": runs}


def latest_revisions(rows, cutoff):
    selected = {}
    for row in rows:
        if row["retrieved_at"] <= cutoff and row["recorded_at"] <= cutoff:
            key = row["sensor_id"], row["period_end"]
            if key not in selected or row["revision"] > selected[key]["revision"]:
                selected[key] = row
    return selected


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def usable(row):
    return row is not None and row["quality_status"] == "accepted" and finite(row["value"])


def numeric_summary(values):
    values = [v for v in values if finite(v)]
    return {"count": len(values), "minimum": min(values) if values else None,
            "maximum": max(values) if values else None, "median": median(values) if values else None}


def value_checks(rows, variable):
    counts = Counter(dict.fromkeys(("unit_mismatch", "variable_mismatch", "quality_null_mismatch",
        "unknown_quality_status", "nonfinite_or_nonnumeric", "physical_range_violation",
        "sentinel_candidate", "pm_extreme_review"), 0))
    for row in rows:
        value = row["value"]
        counts["unit_mismatch"] += row["canonical_unit"] != variable.canonical_unit
        counts["variable_mismatch"] += row["variable_code"] != variable.code
        counts["quality_null_mismatch"] += (row["quality_status"] in {"missing", "invalid"}) != (value is None)
        counts["unknown_quality_status"] += row["quality_status"] not in {"accepted", "suspect", "missing", "invalid"}
        counts["nonfinite_or_nonnumeric"] += value is not None and not finite(value)
        if finite(value):
            counts["physical_range_violation"] += ((variable.minimum is not None and value < variable.minimum)
                                                    or (variable.maximum is not None and value > variable.maximum))
            counts["sentinel_candidate"] += value in POLICY["sentinel_candidates"]
            counts["pm_extreme_review"] += variable.code in {"pm2_5", "pm10"} and value > POLICY["pm_review_above_ug_m3"]
    return dict(sorted(counts.items()))


def missingness(expected, rows):
    """Local bins use interval START, not the exclusive period end."""
    result = {}
    for name, zone in (("utc_day", timezone.utc), ("vietnam_day", ZoneInfo("Asia/Ho_Chi_Minh")),
                       ("vietnam_hour", ZoneInfo("Asia/Ho_Chi_Minh"))):
        bins = defaultdict(Counter)
        for end in sorted(expected):
            left = (end - HOUR).astimezone(zone)
            label = f"{left.hour:02}" if name.endswith("hour") else left.date().isoformat()
            bins[label]["expected"] += 1
            bins[label]["present"] += end in rows
            bins[label]["accepted"] += usable(rows.get(end))
        result[name] = {label: dict(counts) for label, counts in sorted(bins.items())}
    return result


def flatlines(rows):
    runs, previous = [], None
    for row in sorted(rows, key=lambda r: r["period_end"]):
        if not finite(row["value"]):
            previous = None
            continue
        if previous and row["period_end"] == previous["period_end"] + HOUR and row["value"] == previous["value"]:
            length += 1
        else:
            first, length = row["period_end"], 1
        if length == POLICY["flatline_review_hours"]:
            runs.append({"first_period_end": first, "last_period_end": row["period_end"], "hours": length})
        elif length > POLICY["flatline_review_hours"]:
            runs[-1].update(last_period_end=row["period_end"], hours=length)
        previous = row
    return runs


def revision_changes(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["period_end"]].append(row)
    counts, changed = Counter(), Counter()
    fields = ("value", "quality_status", "coverage_percent", "source_flags", "source_metadata", "latitude", "longitude")
    for versions in groups.values():
        versions.sort(key=lambda r: r["revision"])
        counts["chain_errors"] += [r["revision"] for r in versions] != list(range(1, len(versions) + 1))
        for old, new in zip(versions, versions[1:]):
            differences = {f for f in fields if old[f] != new[f]}
            changed.update(differences)
            counts["metadata_only_transitions"] += bool(differences) and differences <= {"source_metadata", "latitude", "longitude"}
            counts["value_changing_transitions"] += "value" in differences
            counts["unchanged_transitions"] += not differences
    return {"revision_rows": len(rows), "distinct_intervals": len(groups),
            "extra_revision_rows": len(rows) - len(groups), "revised_intervals": sum(len(v) > 1 for v in groups.values()),
            "transitions": dict(sorted(counts.items())), "changed_fields": dict(sorted(changed.items()))}


def measurement_audit(config, rows, cutoff, start, end):
    selected = latest_revisions(rows, cutoff)
    expected, result = set(hourly_end_grid(start, end)), {}
    for sensor in config.sensors:
        location = next(l for l in config.locations if l.id == sensor.location_id)
        variable = next(v for v in config.variables if v.code == sensor.variable_code)
        all_rows = [r for r in rows if r["sensor_id"] == sensor.id and r["recorded_at"] <= cutoff and r["retrieved_at"] <= cutoff]
        current = {at: r for (sid, at), r in selected.items() if sid == sensor.id}
        values = list(current.values())
        metadata = {f: len({digest(r["source_metadata"].get(f)) for r in all_rows})
                    for f in ("instrument", "provider_timezone", "licences", "provider_id", "external_location_id")}
        result[sensor.id] = {
            "location_id": sensor.location_id, "coverage": gap_summary(expected, set(current)),
            "accepted_coverage": gap_summary(expected, {at for at, r in current.items() if usable(r)}),
            "quality_status_counts": dict(sorted(Counter(r["quality_status"] for r in values).items())),
            "value_screening": value_checks(values, variable), "value_summary_ug_m3": numeric_summary(r["value"] for r in values),
            "all_revision_screening": value_checks(all_rows, variable), "revision_handling": revision_changes(all_rows),
            "interval_errors": sum(r["period_end"] - r["period_start"] != HOUR or r["period_end"].timestamp() % 3600 != 0 for r in all_rows),
            "metadata_distinct_counts": metadata,
            "coordinate_drift_rows_over_100m": sum(distance_km(r["latitude"], r["longitude"], location) > 0.1 for r in all_rows),
            "licence_interval_violations": sum(r["period_start"].astimezone(ZoneInfo(location.timezone)).date() < sensor.licence_valid_from
                or (sensor.licence_valid_to is not None and (r["period_end"] - timedelta(microseconds=1)).astimezone(ZoneInfo(location.timezone)).date() > sensor.licence_valid_to) for r in all_rows),
            "provider_flagged_hours": sum(r["source_flags"].get("hasFlags") is True for r in values),
            "provider_flag_unknown_hours": sum(type(r["source_flags"].get("hasFlags")) is not bool for r in values),
            "unknown_or_low_hour_coverage": sum(not finite(r["coverage_percent"]) or r["coverage_percent"] < 75 for r in values),
            "missingness": missingness(expected, current), "flatline_candidates": flatlines(values),
            "retrieval_age_hours_by_purpose": {purpose: numeric_summary((r["retrieved_at"] - r["period_end"]).total_seconds() / 3600
                for r in all_rows if r["purpose"] == purpose) for purpose in sorted({r["purpose"] for r in all_rows})},
        }
    return result, selected


def select_captures(snapshots, times):
    """Select a capture first, even when it omits a variable or hour."""
    ordered = sorted(snapshots, key=lambda s: (s["retrieved_at"], s["recorded_at"], str(s["id"])), reverse=True)
    return {at: next((s for s in ordered if s["window_start"] <= at < s["window_end"]), None) for at in times}


def model_audit(config, rows, snapshots, start, end):
    indexed = {(r["snapshot_id"], r["variable_code"], r["valid_at"]): r for r in rows}
    series, selected_history = {}, {}
    variable_map = {v.code: v for v in config.variables}
    by_snapshot_variable = defaultdict(list)
    for row in rows:
        by_snapshot_variable[row["snapshot_id"], row["variable_code"]].append(row)
    for product in config.products:
        if product.data_kind == "measurement":
            continue
        purposes = ("poll",) if product.id == "open_meteo_weather_forecast" else (("backfill",) if product.data_kind == "reanalysis" else ("backfill", "poll"))
        locations = [l for l in config.locations if l.kind == ("station" if product.domain == "weather" else "city")]
        for location in locations:
            for purpose in purposes:
                captures = [s for s in snapshots if (s["product_id"], s["location_id"], s["purpose"]) == (product.id, location.id, purpose)]
                requested = set()
                for capture in captures:
                    requested.update(at - HOUR for at in hourly_end_grid(capture["window_start"], capture["window_end"]))
                times = {at - HOUR for at in hourly_end_grid(start, end)} if purpose == "backfill" else requested
                chosen, variables = select_captures(captures, times), {}
                for code in (WEATHER if product.domain == "weather" else AIR):
                    variable = variable_map[code]
                    candidates = [r for s in captures for r in by_snapshot_variable[s["id"], code] if r["valid_at"] in times]
                    current = {at: indexed[s["id"], code, at] for at, s in chosen.items() if s and (s["id"], code, at) in indexed}
                    if purpose == "backfill":
                        selected_history[product.id, location.id, code] = current
                    variables[code] = {
                        "coverage": gap_summary(times, set(current)), "not_requested_hours": len(times - requested),
                        "requested_but_absent_hours": len((times & requested) - set(current)),
                        "accepted_hours": sum(usable(r) for r in current.values()),
                        "quality_status_counts": dict(sorted(Counter(r["quality_status"] for r in current.values()).items())),
                        "capture_value_rows": len(candidates),
                        "overlapping_value_rows": len(candidates) - len({r["valid_at"] for r in candidates}),
                        "selected_value_screening": value_checks(list(current.values()), variable),
                        "all_capture_value_screening": value_checks(candidates, variable),
                        "interval_errors": sum(r["period_start"] != (r["valid_at"] if variable.temporal_support == "instant" else r["valid_at"] - HOUR)
                            or r["temporal_support"] != variable.temporal_support or r["valid_at"].timestamp() % 3600 != 0 for r in candidates),
                        "native_cadence_unknown_values": sum(r["native_interval_seconds"] is None for r in current.values()),
                    }
                series[f"{product.id}/{location.id}/{purpose}"] = {
                    "snapshots": len(captures), "requested_hours": len(requested), "variables": variables,
                    "grid_displacement_km": numeric_summary(distance_km(s["grid_latitude"], s["grid_longitude"], location) for s in captures),
                    "distinct_grids": len({(s["grid_latitude"], s["grid_longitude"]) for s in captures}),
                    "run_provenance_counts": dict(sorted(Counter(s["run_provenance"] for s in captures).items()))}
    return series, selected_history


def alignment_audit(config, measured, weather, start, end):
    result = {}
    variables = [v for v in config.variables if v.code in WEATHER]
    for sensor in config.sensors:
        eligible = {at: r for (sid, at), r in measured.items() if sid == sensor.id and usable(r)}
        matched = {}
        for variable in variables:
            stream = weather.get(("open_meteo_era5", sensor.location_id, variable.code), {})
            matched[variable.code] = {at for at, r in eligible.items()
                if usable(stream.get(r["period_start"] if variable.temporal_support == "instant" else r["period_end"]))}
        all_weather = set.intersection(*matched.values()) if matched else set()
        result[sensor.id] = {"expected_sensor_hours": len(hourly_end_grid(start, end)), "accepted_sensor_hours": len(eligible),
            "matched_by_variable": {code: len(at) for code, at in matched.items()},
            "accepted_hours_with_all_nine_era5_variables": len(all_weather),
            "accepted_hours_without_all_weather": len(eligible) - len(all_weather)}
    return result


def build_audit(config, data, *, cutoff, start, end):
    validate_window(cutoff, start, end)
    measurements, selected = measurement_audit(config, data["measurements"], cutoff, start, end)
    models, history = model_audit(config, data["model_values"], data["snapshots"], start, end)
    keys = ("measurements", "snapshots", "model_values", "responses", "runs", "issues", "quarantines")
    manifest = {"audit_version": AUDIT_VERSION, "cutoff": cutoff, "start": start, "end": end, "policy": POLICY,
        "configuration_sha256": digest(config.model_dump(mode="json")), "schema_revision": data["schema_revision"],
        "query_sha256": data["query_sha256"], "implementation_sha256": data["implementation_sha256"],
        "input_sha256": {key: digest(data[key]) for key in keys}, "input_counts": {key: len(data[key]) for key in keys}}
    known_sensors = {s.id for s in config.sensors}
    if any(r["sensor_id"] not in known_sensors for r in data["measurements"]):
        raise ValueError("Unconfigured measured sensor in audit extraction")
    report = {
        "purpose": "Phase 4 structural screening of sensor measurements and separate modeled context",
        "manifest": manifest, "manifest_sha256": digest(manifest), "measurements": measurements, "models": models,
        "sensor_model_alignment": alignment_audit(config, selected, history, start, end),
        "source_response_statuses": dict(sorted(Counter(f'{r["provider_group"]}/{r["http_status"]}/{r["error_code"] or "none"}' for r in data["responses"]).items())),
        "ingestion_run_statuses_at_cutoff": dict(sorted(Counter(r["status"] for r in data["runs"]).items())),
        "preexisting_quality_issues": dict(sorted(Counter(r["issue_code"] for r in data["issues"]).items())),
        "quarantine_reasons": dict(sorted(Counter(r["reason_code"] for r in data["quarantines"]).items())),
        "limitations": [
            "Accepted means provisional ingestion screening, not verified calibration, outdoor siting or city-wide representativeness.",
            "Retrieval ages include backfill/revision lag; they do not estimate historical publication latency or availability.",
            "Snapshot selection is retrospective. Unknown model run provenance stays unknown. CAMS and ERA5 are not measured ground truth.",
            "Extraction sees rows committed now and eligible by stored timestamps; historical commit visibility cannot be reconstructed.",
            "Raw bodies stay in PostgreSQL. Sentinel checks inspect canonical values and retained quarantine reasons, not an exhaustive raw reparse.",
            "Flatlines, sentinel candidates and high PM prompt review only. No deletion, imputation or automatic relabeling occurs.",
            "Input hashes detect replay changes; the aggregate artifact cannot restore source rows if the source database is lost.",
        ]}
    return report


def audit_database(engine, config, *, cutoff, start, end):
    from vn_air.quality_store import extract_audit
    validate_window(cutoff, start, end)
    data = extract_audit(engine, config, cutoff=cutoff, start=start, end=end)
    report = build_audit(config, data, cutoff=cutoff, start=start, end=end)
    report["extraction"] = data["extraction"]
    report["result_sha256"] = digest(report)
    return report
