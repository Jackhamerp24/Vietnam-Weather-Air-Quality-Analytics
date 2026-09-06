"""Bounded, keyless Phase 1 probes. Not an ingestion or forecasting pipeline.

Captured response bodies are real provider data. Offline tests use explicitly
synthetic contract examples, which this script never includes in a live report.
"""

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


# Reviewed GeoNames matches from the initial research, not an application city list.
CITIES = (("Hanoi", 1581130), ("Ho Chi Minh City", 1566083), ("Da Nang", 1583992))
WEATHER_UNITS = {
    "temperature_2m": "\u00b0C",
    "relative_humidity_2m": "%",
    "precipitation": "mm",
    "wind_speed_10m": "m/s",
    "wind_direction_10m": "\u00b0",
    "surface_pressure": "hPa",
    "cloud_cover": "%",
    "shortwave_radiation": "W/m\u00b2",
}
AQ_UNITS: dict[str, str] = dict.fromkeys(
    ("pm2_5", "pm10", "nitrogen_dioxide", "sulphur_dioxide", "carbon_monoxide", "ozone"),
    "\u03bcg/m\u00b3",
)
AQ_UNITS["us_aqi"] = "USAQI"


def check_hourly(payload, units, count, locations):
    """Check the sampled contract, not sensor accuracy or long-term completeness."""
    if not isinstance(payload, list) or len(payload) != locations:
        raise ValueError("Unexpected number of location responses")
    summaries = []
    for row in payload:
        lat, lon = row["latitude"], row["longitude"]
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("Invalid returned coordinates")
        if row["utc_offset_seconds"] != 0:
            raise ValueError("UTC requested but response has a nonzero offset")
        hourly, returned_units = row["hourly"], row["hourly_units"]
        times = hourly["time"]
        if len(times) != count or any(type(t) is not int for t in times):
            raise ValueError("Unexpected timestamp count or epoch type")
        if any(right - left != 3600 for left, right in zip(times, times[1:])):
            raise ValueError("Duplicate, nonmonotonic, or missing hourly timestamp")
        if returned_units["time"] != "unixtime":
            raise ValueError("Unexpected timestamp unit")
        missing = {}
        for variable, expected in units.items():
            # Providers can use either Unicode micro sign for the same SI prefix.
            actual = returned_units[variable].replace("\u00b5", "\u03bc")
            if actual != expected:
                raise ValueError(f"Unexpected unit for {variable}: {actual!r}")
            values = hourly[variable]
            if len(values) != count:
                raise ValueError(f"Array length mismatch for {variable}")
            missing[variable] = sum(value is None for value in values)
            if missing[variable]:
                raise ValueError(f"Missing values in probe sample for {variable}")
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
                raise ValueError(f"Nonfinite or nonnumeric values for {variable}")
        summaries.append({
            "returned_coordinates": [lat, lon],
            "hour_count": count,
            "first_time_utc": datetime.fromtimestamp(times[0], timezone.utc).isoformat(),
            "last_time_utc": datetime.fromtimestamp(times[-1], timezone.utc).isoformat(),
            "missing_counts": missing,
            "current_interval_seconds": row.get("current", {}).get("interval"),
        })
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New JSON evidence file")
    args = parser.parse_args()
    if args.output.exists() or not args.output.parent.is_dir():
        parser.error("Output must not exist, and its parent directory must exist")

    report = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Phase 1 live API contract probes; not an analytical dataset",
        "historical_sample_date": "2023-01-01",
        "attribution": {
            "open_meteo": "https://open-meteo.com/",
            "geonames": "https://www.geonames.org/",
            "data_licence": "https://creativecommons.org/licenses/by/4.0/",
            "cams_global": "https://doi.org/10.24381/04a0b097",
            "era5": "https://doi.org/10.24381/cds.adbb2d47",
            "modifications": "Raw bodies unchanged; parsed copies and contract summaries added",
        },
        "requests": [],
        "checks": [],
    }

    def fetch(name, base, parameters):
        url = base + "?" + urlencode(parameters)
        entry: dict[str, Any] = {"name": name, "url": url, "requested_at_utc": datetime.now(timezone.utc).isoformat()}
        report["requests"].append(entry)
        # Eight requests at most, no automatic retries or account/credential access.
        time.sleep(1)
        request = Request(url, headers={"User-Agent": "VietnamEnvironmentalAnalytics-Research/0.1"})
        try:
            try:
                response = urlopen(request, timeout=30)
            except HTTPError as error:
                response = error
            with response:
                body = response.read()
                entry.update({
                    "http_status": response.status,
                    "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                    "body_sha256": hashlib.sha256(body).hexdigest(),
                    "body_utf8": body.decode("utf-8"),
                })
            payload = json.loads(entry["body_utf8"])
            json.dumps(payload, allow_nan=False)
            entry["response"] = payload
            return entry
        except (URLError, TimeoutError, OSError, ValueError) as error:
            entry["error"] = str(error)
            raise

    passed = False
    try:
        locations = []
        for name, geonames_id in CITIES:
            entry = fetch("geocoding_" + str(geonames_id), "https://geocoding-api.open-meteo.com/v1/search", {
                "name": name, "count": 10, "language": "en", "countryCode": "VN",
            })
            if entry["http_status"] != 200:
                raise ValueError(f"Geocoding failed for {name}")
            matches = [r for r in entry["response"].get("results", []) if r["id"] == geonames_id]
            if len(matches) != 1 or matches[0]["country_code"] != "VN":
                raise ValueError(f"Reviewed Vietnam location not returned for {name}")
            locations.append(matches[0])
        report["selected_locations"] = locations
        coordinates = {
            "latitude": ",".join(str(r["latitude"]) for r in locations),
            "longitude": ",".join(str(r["longitude"]) for r in locations),
            "timezone": "UTC", "timeformat": "unixtime",
        }
        history = {"start_date": "2023-01-01", "end_date": "2023-01-01"}
        probes = (
            ("weather_recent", "https://api.open-meteo.com/v1/forecast", WEATHER_UNITS,
             {"forecast_hours": 6, "current": "temperature_2m", "wind_speed_unit": "ms"}, 6),
            ("air_quality_recent", "https://air-quality-api.open-meteo.com/v1/air-quality", AQ_UNITS,
             {"forecast_hours": 6, "current": "pm2_5", "domains": "cams_global"}, 6),
            ("weather_era5_history", "https://archive-api.open-meteo.com/v1/archive", WEATHER_UNITS,
             {**history, "models": "era5", "wind_speed_unit": "ms"}, 24),
            ("air_quality_history", "https://air-quality-api.open-meteo.com/v1/air-quality", AQ_UNITS,
             {**history, "domains": "cams_global"}, 24),
        )
        for name, base, units, options, count in probes:
            entry = fetch(name, base, {**coordinates, "hourly": ",".join(units), **options})
            if entry["http_status"] != 200:
                raise ValueError(f"{name} returned HTTP {entry['http_status']}")
            report["checks"].append({"probe": name, "locations": check_hourly(entry["response"], units, count, len(locations))})
        entry = fetch("invalid_latitude", "https://api.open-meteo.com/v1/forecast", {
            "latitude": 91, "longitude": 105.84, "hourly": "temperature_2m",
        })
        if entry["http_status"] != 400 or entry["response"].get("error") is not True:
            raise ValueError("Invalid-coordinate request did not return the documented error")
        passed = True
    except (KeyError, TypeError, ValueError, URLError, TimeoutError, OSError) as error:
        report["failure"] = f"{type(error).__name__}: {error}"
    finally:
        report["passed"] = passed
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
            output.write("\n")
    print(f"{'PASS' if passed else 'FAIL'}: {len(report['requests'])} requests; evidence: {args.output}")
    if not passed:
        print(report.get("failure", "Probe failed"), file=sys.stderr)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
