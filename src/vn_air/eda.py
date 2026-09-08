"""Phase 5: frozen, source-separated descriptive exploration (no inference)."""

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median, stdev
from zoneinfo import ZoneInfo

from vn_air.ingestion.parsing import WEATHER, timestamp
from vn_air.quality import POLICY, digest, finite, hourly_end_grid, json_default, latest_revisions, select_captures, usable, validate_window
from vn_air.quality_store import extract_audit

EDA_VERSION = "phase5_eda_v1"
WEATHER_VARIABLES = WEATHER
EDA_POLICY = {
    "selection": POLICY,
    "analysis_quality": "accepted only; source values/status and absent hours remain in the dataset",
    "daily_mean": "Full 24-hour Vietnam date, at least 18 accepted hours; observed summaries retained for all dates",
    "percentiles": "Linear interpolation at (n-1)*p (type 7)",
    "lag_correlation": "Pearson of finite pairs separated by exact elapsed hours, no gap filling, no confidence bands",
    "weather_association": "Pairwise-complete Pearson per sensor, minimum 3 pairs, no p-values; raw wind direction excluded (circular)",
    "wind_sectors": "8 compass sectors, calm if wind speed <0.5 m/s; descriptive bins only",
    "scope": "Full audited window explored; no untouched modeling holdout is claimed",
}


def _percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def descriptive(values):
    values = [v for v in values if finite(v)]
    return {"n": len(values), "mean": mean(values) if values else None,
            "median": median(values) if values else None,
            **{f"p{p}": _percentile(values, p / 100) for p in (5, 25, 75, 95)},
            "minimum": min(values) if values else None, "maximum": max(values) if values else None,
            "stdev": stdev(values) if len(values) > 1 else None}


def descriptive_correlation(left, right):
    if len(left) != len(right):
        raise ValueError("Correlation inputs must align")
    pairs = [(a, b) for a, b in zip(left, right) if finite(a) and finite(b)]
    result = {"n": len(pairs), "pearson_r": None}
    if len(pairs) >= 3:
        xs, ys = zip(*pairs)
        mx, my = mean(xs), mean(ys)
        xx, yy = sum((x - mx) ** 2 for x in xs), sum((y - my) ** 2 for y in ys)
        if xx and yy:
            result["pearson_r"] = max(-1.0, min(1.0, sum((x - mx) * (y - my) for x, y in pairs) / math.sqrt(xx * yy)))
    return result


def local_parts(at, timezone_name):
    local = at.astimezone(ZoneInfo(timezone_name))
    return local.date().isoformat(), local.hour


def load_phase4(path, config, cutoff, start, end):
    validate_window(cutoff, start, end)
    if path.stat().st_size > 2_000_000:
        raise ValueError("Oversize Phase 4 artifact")
    artifact = json.loads(path.read_text(encoding="utf-8"))
    content = {k: v for k, v in artifact.items() if k != "result_sha256"}
    manifest = artifact["manifest"]
    if digest(content) != artifact["result_sha256"] or digest(manifest) != artifact["manifest_sha256"]:
        raise ValueError("Phase 4 artifact integrity mismatch")
    if manifest["audit_version"] != "phase4_quality_audit_v1" or manifest["policy"] != POLICY:
        raise ValueError("Unreviewed Phase 4 selection policy")
    if any(timestamp(manifest[k]) != v for k, v in (("cutoff", cutoff), ("start", start), ("end", end))):
        raise ValueError("EDA window must match Phase 4")
    if manifest["configuration_sha256"] != digest(config.model_dump(mode="json")):
        raise ValueError("EDA configuration differs from Phase 4")
    return artifact


def verify_inputs(data, artifact):
    manifest = artifact["manifest"]
    for key in ("schema_revision", "query_sha256", "implementation_sha256"):
        if data[key] != manifest[key]:
            raise ValueError("Phase 4 extraction implementation changed")
    for key, expected in manifest["input_sha256"].items():
        if digest(data[key]) != expected or len(data[key]) != manifest["input_counts"][key]:
            raise ValueError("Phase 4 input data changed")


def select_models(data, product, location, times, codes, cutoff):
    captures = [s for s in data["snapshots"] if s["product_id"] == product and s["location_id"] == location
                and s["purpose"] == "backfill" and s["recorded_at"] <= cutoff and s["retrieved_at"] <= cutoff]
    chosen = select_captures(captures, times)
    ids = {s["id"] for s in captures}
    indexed = {(v["snapshot_id"], v["variable_code"], v["valid_at"]): v for v in data["model_values"]
               if v["snapshot_id"] in ids and v["recorded_at"] <= cutoff}
    result = {}
    for at in sorted(times):
        capture = chosen[at]
        for code in codes:
            value = indexed.get((capture["id"], code, at)) if capture else None
            result[code, at] = {"value": value["value"] if usable(value) else None,
                "source_value": value["value"] if value else None,
                "quality": value["quality_status"] if value else "absent",
                "value_id": value["id"] if value else None,
                "snapshot_id": str(capture["id"]) if capture else None}
    return result


def build_dataset(config, data, *, cutoff, start, end):
    validate_window(cutoff, start, end)
    ends = hourly_end_grid(start, end)
    times = {at - timedelta(hours=1) for at in ends}
    latest = latest_revisions(data["measurements"], cutoff)
    locations = {l.id: l for l in config.locations}
    variables = {v.code: v for v in config.variables}
    rows, cams = [], []
    for sensor in config.sensors:
        location = locations[sensor.location_id]
        # Same valid-time window as Phase 4, including its final accumulation boundary limit.
        weather = select_models(data, "open_meteo_era5", location.id, times | set(ends), WEATHER, cutoff)
        for at in ends:
            left = at - timedelta(hours=1)
            local = left.astimezone(ZoneInfo(location.timezone))
            source = latest.get((sensor.id, at))
            values = {}
            for code in WEATHER:
                weather_at = left if variables[code].temporal_support == "instant" else at
                values[code] = weather.get((code, weather_at), {"value": None, "source_value": None,
                    "quality": "absent", "value_id": None, "snapshot_id": None})
            rows.append({"sensor_id": sensor.id, "location_id": location.id,
                "period_start": left.isoformat(), "period_end": at.isoformat(),
                "local_date": local.date().isoformat(), "local_hour": local.hour, "weekday": local.weekday(),
                "measurement_id": source["id"] if source else None, "revision": source["revision"] if source else None,
                "response_id": str(source["response_id"]) if source else None,
                "quality": source["quality_status"] if source else "absent",
                "source_pm25": source["value"] if source else None,
                "pm25": source["value"] if usable(source) else None, "weather": values})
    for location in config.locations:
        if location.kind != "city":
            continue
        modeled = select_models(data, "open_meteo_cams_global", location.id, times, ("pm2_5",), cutoff)
        for at in sorted(times):
            cams.append({"location_id": location.id, "valid_at": at.isoformat(),
                         "local_date": at.astimezone(ZoneInfo(location.timezone)).date().isoformat(),
                         **modeled["pm2_5", at]})
    provenance = {str(s["id"]): s for s in data["snapshots"]}
    return {"rows": rows, "cams_modeled_pm25": cams, "snapshot_provenance": provenance,
            "sensors": {s.id: {"name": locations[s.location_id].name, "location_id": s.location_id,
                "attribution": s.attribution, "licence_url": s.licence_url} for s in config.sensors},
            "weather_variables": {code: {"unit": variables[code].canonical_unit,
                "temporal_support": variables[code].temporal_support} for code in WEATHER},
            "forecast_captures_not_analyzed": sum(s["purpose"] == "poll" for s in data["snapshots"])}


def grouped(rows, key, value_key="pm25"):
    bins = defaultdict(list)
    for row in rows:
        bins[row[key]].append(row)
    output = []
    for label, group in sorted(bins.items()):
        stats = descriptive(r[value_key] for r in group)
        item = {key: label, "expected_hours": len(group), "accepted_hours": stats["n"],
                "coverage_percent": 100 * stats["n"] / len(group), **stats}
        if key == "local_date":
            item["full_local_day"] = len(group) == 24
            item["qualified_mean"] = stats["mean"] if len(group) == 24 and stats["n"] >= 18 else None
        output.append(item)
    return output


def lag_correlations(rows, lags=tuple(range(1, 49)) + (72, 168)):
    at = {timestamp(r["period_end"]): r["pm25"] for r in rows}
    results = []
    for lag in lags:
        pairs = [(value, at.get(t - timedelta(hours=lag))) for t, value in sorted(at.items())]
        results.append({"lag_hours": lag, **descriptive_correlation([p[0] for p in pairs], [p[1] for p in pairs])})
    return results


def summarize(dataset):
    all_rows = dataset["rows"]
    sensors = {}
    accepted_sets = [{r["period_end"] for r in all_rows if r["sensor_id"] == sid and finite(r["pm25"])} for sid in dataset["sensors"]]
    common = set.intersection(*accepted_sets) if accepted_sets else set()
    for sid, metadata in dataset["sensors"].items():
        rows = [r for r in all_rows if r["sensor_id"] == sid]
        associations, wind = [], defaultdict(list)
        for code in WEATHER:
            if code == "wind_direction_10m":
                continue  # Degrees wrap at north, making ordinary linear correlation misleading.
            associations.append({"variable": code, **descriptive_correlation(
                [r["pm25"] for r in rows], [r["weather"][code]["value"] for r in rows])})
        for r in rows:
            speed, direction = (r["weather"][c]["value"] for c in ("wind_speed_10m", "wind_direction_10m"))
            if finite(speed) and finite(direction) and finite(r["pm25"]):
                sector = "calm" if speed < .5 else ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int((direction + 22.5) % 360 // 45)]
                wind[sector].append(r["pm25"])
        complete = [r for r in rows if finite(r["pm25"]) and all(finite(w["value"]) for w in r["weather"].values())]
        sensors[sid] = {**metadata, "expected_hours": len(rows), "quality_counts": dict(Counter(r["quality"] for r in rows)),
            "pm25": descriptive(r["pm25"] for r in rows),
            "common_sensor_hours": descriptive(r["pm25"] for r in rows if r["period_end"] in common),
            "complete_weather_hours": len(complete), "pm25_complete_weather": descriptive(r["pm25"] for r in complete),
            "daily": grouped(rows, "local_date"), "diurnal": grouped(rows, "local_hour"),
            "weekday": grouped(rows, "weekday"), "lag_correlations": lag_correlations(rows),
            "weather_associations": associations, "wind_sectors": {k: descriptive(v) for k, v in sorted(wind.items())},
            "highest_hours": sorted((r for r in rows if finite(r["pm25"])), key=lambda r: (-r["pm25"], r["period_end"]))[:5]}
    cams = {}
    for lid in sorted({r["location_id"] for r in dataset["cams_modeled_pm25"]}):
        rows = [r for r in dataset["cams_modeled_pm25"] if r["location_id"] == lid]
        cams[lid] = {"product": "open_meteo_cams_global", "data_kind": "modeled, retrospective capture",
                     "pm25": descriptive(r["value"] for r in rows), "daily": grouped(rows, "local_date", "value")}
    return {"sensors": sensors, "common_accepted_sensor_hours": len(common), "cams_modeled_context": cams,
            "forecast_captures_not_analyzed": dataset["forecast_captures_not_analyzed"]}


def prepare_bundle(config, data, artifact, artifact_hash, cutoff, start, end):
    verify_inputs(data, artifact)
    dataset = build_dataset(config, data, cutoff=cutoff, start=start, end=end)
    summary = summarize(dataset)
    for sid, stats in summary["sensors"].items():
        if stats["pm25"]["n"] != artifact["measurements"][sid]["accepted_coverage"]["present_hours"]:
            raise ValueError("EDA measured selection differs from Phase 4")
        if stats["complete_weather_hours"] != artifact["sensor_model_alignment"][sid]["accepted_hours_with_all_nine_era5_variables"]:
            raise ValueError("EDA weather alignment differs from Phase 4")
    root = Path(__file__).parent
    manifest = {"eda_version": EDA_VERSION, "cutoff": cutoff, "start": start, "end": end,
        "phase4_artifact_sha256": artifact_hash, "phase4_manifest_sha256": artifact["manifest_sha256"],
        "input_sha256": artifact["manifest"]["input_sha256"], "policy": EDA_POLICY,
        "implementation_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ("eda.py", "eda_output.py")}}
    bundle = {"manifest": manifest, "summary": summary, "dataset": dataset}
    # Normalize timestamps/UUIDs before persisting so replay hashes match.
    bundle = json.loads(json.dumps(bundle, default=json_default, allow_nan=False))
    bundle["bundle_sha256"] = digest(bundle)
    return bundle


def run_eda(engine, config, *, cutoff, start, end, phase4_artifact, output_dir):
    from vn_air.eda_output import write_outputs
    if output_dir.exists() or not output_dir.parent.is_dir():
        raise ValueError("EDA output directory must be new with an existing parent")
    artifact = load_phase4(phase4_artifact, config, cutoff, start, end)
    data = extract_audit(engine, config, cutoff=cutoff, start=start, end=end)
    bundle = prepare_bundle(config, data, artifact, hashlib.sha256(phase4_artifact.read_bytes()).hexdigest(), cutoff, start, end)
    return write_outputs(output_dir, bundle)


def replay_eda(bundle_path, output_dir):
    from vn_air.eda_output import write_outputs
    if bundle_path.stat().st_size > 40_000_000:
        raise ValueError("Oversize EDA bundle")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if bundle["bundle_sha256"] != digest({k: v for k, v in bundle.items() if k != "bundle_sha256"}):
        raise ValueError("EDA bundle integrity mismatch")
    if bundle["manifest"]["eda_version"] != EDA_VERSION or bundle["manifest"]["policy"] != EDA_POLICY:
        raise ValueError("Unreviewed EDA policy")
    for name, expected in bundle["manifest"]["implementation_sha256"].items():
        if name not in {"eda.py", "eda_output.py"} or hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest() != expected:
            raise ValueError("EDA replay implementation differs")
    return write_outputs(output_dir, bundle)
