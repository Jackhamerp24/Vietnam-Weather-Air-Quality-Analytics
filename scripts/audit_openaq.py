"""Summarize local OpenAQ captures without trusting provider completeness totals.

This is a source-qualification audit, not EDA or a production data validator.
It writes only selected CC BY 4.0 station metadata, small samples, derived audit
counts and retrieval provenance. Full captures stay in ignored local staging.
"""

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path


def parse_time(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Timestamp lacks timezone")
    return parsed


def summarize_hours(rows, start, end):
    """Count fully enclosed hourly periods, keeping gaps distinct from bad values."""
    hour = timedelta(hours=1)
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("Audit bounds must be timezone-aware")
    if end <= start or (end - start) % hour:
        raise ValueError("Audit window must contain a positive whole number of hours")
    expected = {start + i * hour for i in range(1, int((end - start) / hour) + 1)}
    periods = []
    usable = set()
    rejected = Counter()
    flags = 0
    partial = 0
    in_window = []
    for row in rows:
        period = row["period"]
        left = parse_time(period["datetimeFrom"]["utc"])
        right = parse_time(period["datetimeTo"]["utc"])
        if left < start or right > end:
            rejected["outside_window"] += 1
            continue
        if right - left != hour or right not in expected or period["interval"] != "01:00:00":
            rejected["invalid_interval"] += 1
            continue
        periods.append(right)
        in_window.append(row)
        flagged = row.get("flagInfo", {}).get("hasFlags") is True
        flags += flagged
        coverage = row.get("coverage") or {}
        completeness = coverage.get("percentComplete")
        partial += completeness is not None and completeness < 100
        if row["parameter"]["name"] != "pm25" or row["parameter"]["units"].replace("\u00b5", "\u03bc") != "\u03bcg/m\u00b3":
            rejected["wrong_parameter_or_unit"] += 1
            continue
        value = row["value"]
        if type(value) not in (int, float) or not math.isfinite(value):
            rejected["missing_or_nonfinite"] += 1
            continue
        if value < 0:
            rejected["negative_concentration"] += 1
            continue
        if not flagged:
            usable.add(right)
    present = set(periods)
    gaps = sorted(expected - present)
    longest_gap = 0
    current_gap = 0
    previous = None
    for missing in gaps:
        current_gap = current_gap + 1 if previous is not None and missing - previous == hour else 1
        longest_gap = max(longest_gap, current_gap)
        previous = missing
    summary = {
        "expected_hours": len(expected), "received_rows": len(rows),
        "enclosed_rows": len(periods), "unique_present_hours": len(present),
        "duplicate_periods": len(periods) - len(present),
        "missing_hours": len(gaps), "longest_missing_run_hours": longest_gap,
        "present_percent": round(100 * len(present) / len(expected), 4),
        "finite_nonnegative_unflagged_hours": len(usable),
        "finite_nonnegative_unflagged_percent": round(100 * len(usable) / len(expected), 4),
        "provider_flagged_rows": flags, "partially_complete_rows": partial,
        "rejection_counts": dict(rejected),
        "first_period_end_utc": min(present).isoformat() if present else None,
        "last_period_end_utc": max(present).isoformat() if present else None,
        "first_missing_period_ends_utc": [value.isoformat() for value in gaps[:10]],
    }
    return summary, sorted(in_window, key=lambda r: r["period"]["datetimeTo"]["utc"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not args.output.parent.is_dir():
        parser.error("Output must be new and its parent must exist")
    captures = {}
    for label in ("inventory", "metadata", "samples"):
        with getattr(args, label).open(encoding="utf-8") as file:
            capture = json.load(file)
        if not capture["passed"]:
            raise ValueError(f"Incomplete {label} capture")
        for request in capture["requests"]:
            if hashlib.sha256(request["body_utf8"].encode("utf-8")).hexdigest() != request["body_sha256"]:
                raise ValueError("Response checksum mismatch")
            if json.loads(request["body_utf8"]) != request["response"]:
                raise ValueError("Parsed response differs from raw evidence")
        captures[label] = capture
    inventory = captures["inventory"]["locations"]
    if any(location["country"]["code"] != "VN" for location in inventory):
        raise ValueError("Country filter mismatch")
    if len({location["id"] for location in inventory}) != len(inventory):
        raise ValueError("Duplicate location identifiers")
    if inventory != [row for request in captures["inventory"]["requests"] for row in request["response"]["results"]]:
        raise ValueError("Inventory differs from captured response")
    report = {
        "purpose": "Phase 1 measured-source qualification, not scientific findings",
        "attribution": {
            "access": "OpenAQ: https://openaq.org/",
            "provider": "AirGradient: https://www.airgradient.com/",
            "licence": "https://creativecommons.org/licenses/by/4.0/",
            "modifications": "Selected records and first 24 enclosed hourly rows; completeness recalculated",
        },
        "inventory": {"location_count": len(inventory), "captured_at_utc": captures["inventory"]["finished_at_utc"]},
        "stations": [],
        "provenance": [{
            "capture": label, "requests": [{
                key: request[key] for key in ("url", "http_status", "retrieved_at_utc", "body_sha256")
            } for request in capture["requests"]],
        } for label, capture in captures.items()],
    }
    # Check a stated geographic neighborhood, not all of Da Nang's administrative area.
    nearby = []
    distances = []
    for location in inventory:
        lat, lon = location["coordinates"].get("latitude"), location["coordinates"].get("longitude")
        if lat is None or lon is None:
            continue
        dlat, dlon = math.radians(lat - 16.06778), math.radians(lon - 108.22083)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(16.06778)) * math.cos(math.radians(lat)) * math.sin(dlon / 2) ** 2
        distance = 6371.0 * 2 * math.asin(min(1, math.sqrt(a)))
        distances.append(distance)
        if distance <= 25:
            nearby.append(location["id"])
    report["inventory"].update({
        "da_nang_search_center": [16.06778, 108.22083], "search_radius_km": 25,
        "locations_within_radius": len(nearby),
        "nearest_inventory_location_km": round(min(distances), 2),
    })
    licences = [row for request in captures["metadata"]["requests"] if "/licenses/" in request["url"] for row in request["response"]["results"]]
    licence = next(row for row in licences if row["id"] == 41)
    if licence["sourceUrl"] != "https://creativecommons.org/licenses/by/4.0/" or not licence["redistributionAllowed"]:
        raise ValueError("Reviewed licence metadata changed")
    report["licence_metadata"] = licence
    for sample in captures["samples"]["samples"]:
        sensor_id = sample["sensor_id"]
        path = f"/v3/sensors/{sensor_id}/hours?"
        raw_rows = [row for request in captures["samples"]["requests"] if path in request["url"] for row in request["response"]["results"]]
        if raw_rows != sample["rows"]:
            raise ValueError("Sample rows differ from captured pages")
        location = next(row for row in inventory if any(sensor["id"] == sensor_id for sensor in row["sensors"]))
        if location["provider"]["id"] != 66 or not location["licenses"]:
            raise ValueError("Sample is not from a reviewed AirGradient location")
        start, end = parse_time(sample["from"]), parse_time(sample["to"])
        eligible = [license for license in location["licenses"] if license["id"] == 41
                    and license["dateFrom"] is not None and license["dateFrom"] <= start.date().isoformat()
                    and (license["dateTo"] is None or license["dateTo"] >= end.date().isoformat())]
        if not eligible:
            raise ValueError("No reviewed licence covering the sample window")
        summary, rows = summarize_hours(sample["rows"], start, end)
        report["stations"].append({
            "location_id": location["id"], "name": location["name"],
            "sensor_id": sensor_id, "provider": location["provider"],
            "coordinates": location["coordinates"], "timezone": location["timezone"],
            "isMonitor": location["isMonitor"], "instruments": location["instruments"],
            "licenses": eligible, "window_from": sample["from"], "window_to": sample["to"],
            "audit": summary, "first_24_enclosed_rows": rows[:24],
        })
        print(f"{location['name']}:", json.dumps(summary))
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
        output.write("\n")
    print("Inventory:", json.dumps(report["inventory"]))
    print("Evidence:", args.output)


if __name__ == "__main__":
    main()
