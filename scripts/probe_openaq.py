"""Bounded authenticated OpenAQ research, with no credentials in saved evidence.

Provide OPENAQ_API_KEY through the process environment. This script does not
load .env, create a database, schedule polling, or establish source-data rights.
Stage responses locally until the relevant licences have been reviewed.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward the authentication header to another host.
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="New local evidence file")
    parser.add_argument("--sensor-id", type=int, action="append", default=[])
    parser.add_argument("--license-id", type=int, action="append", default=[])
    parser.add_argument("--from-utc", help="Inclusive query bound with UTC offset")
    parser.add_argument("--to-utc", help="Query upper bound with UTC offset")
    args = parser.parse_args()
    if args.output.exists() or not args.output.parent.is_dir():
        parser.error("Output must not exist and its parent must exist")
    key = os.environ.get("OPENAQ_API_KEY", "").strip()
    if not key:
        parser.error("OPENAQ_API_KEY is required")
    if bool(args.from_utc) != bool(args.to_utc):
        parser.error("Supply both time bounds or neither")
    if args.from_utc:
        start = datetime.fromisoformat(args.from_utc.replace("Z", "+00:00"))
        end = datetime.fromisoformat(args.to_utc.replace("Z", "+00:00"))
        if start.utcoffset() is None or end.utcoffset() is None:
            parser.error("Time bounds must include offsets")
        if not 0 < (end - start).total_seconds() <= 366 * 86400:
            parser.error("Probe windows must be positive and at most 366 days")
    if len(args.sensor_id) > 12 or len(args.license_id) > 12:
        parser.error("Use at most 12 sensors and 12 licences per probe")
    report = {
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Authenticated OpenAQ source qualification, not model evaluation",
        "requests": [],
        "passed": False,
    }
    opener = build_opener(NoRedirects())

    def fetch(path, parameters=None):
        if len(report["requests"]) >= 120:
            raise ValueError("Research request budget exhausted")
        url = "https://api.openaq.org/v3/" + path
        if parameters:
            url += "?" + urlencode(parameters)
        request = Request(url, headers={"X-API-Key": key, "User-Agent": "VietnamEnvironmentalAnalytics-Research/0.1"})
        entry = {"url": url, "requested_at_utc": datetime.now(timezone.utc).isoformat()}
        report["requests"].append(entry)
        time.sleep(3)
        try:
            response = opener.open(request, timeout=45)
        except HTTPError as error:
            response = error
        with response:
            body = response.read()
            text = body.decode("utf-8")
            if key in text:
                raise ValueError("Server echoed a credential; response not retained")
            entry.update({
                "http_status": response.status,
                "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
                "body_utf8": text,
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "rate_headers": {k: v for k, v in response.headers.items() if k.lower().startswith("x-ratelimit")},
            })
        if entry["http_status"] != 200:
            raise ValueError(f"OpenAQ HTTP {entry['http_status']}; stopped without retry")
        payload = json.loads(text)
        if key in json.dumps(payload, allow_nan=False):
            raise ValueError("Decoded response echoed a credential; processing stopped")
        entry["response"] = payload
        return payload

    try:
        if not args.sensor_id and not args.license_id:
            locations = []
            for page in range(1, 6):
                data = fetch("locations", {"iso": "VN", "limit": 1000, "page": page})
                rows = data["results"]
                locations.extend(rows)
                if len(rows) < 1000:
                    break
            else:
                raise ValueError("Inventory pagination budget reached; completeness unknown")
            report["locations"] = locations
            print(f"Vietnam inventory: {len(locations)} locations")
            for location in locations:
                sensors = [s for s in location["sensors"] if s["parameter"]["name"] == "pm25"]
                if sensors:
                    print(json.dumps({
                        "id": location["id"], "name": location["name"],
                        "coordinates": location["coordinates"], "provider": location["provider"],
                        "isMonitor": location["isMonitor"], "datetimeLast": location["datetimeLast"],
                        "pm25_sensor_ids": [s["id"] for s in sensors],
                        "licenses": location["licenses"],
                    }, ensure_ascii=True))
        for license_id in args.license_id:
            data = fetch(f"licenses/{license_id}")
            print("Licence:", json.dumps(data["results"], ensure_ascii=True))
        for sensor_id in args.sensor_id:
            sensor = fetch(f"sensors/{sensor_id}")
            print("Sensor:", json.dumps(sensor["results"], ensure_ascii=True))
            if args.from_utc:
                rows = []
                for page in range(1, 11):
                    data = fetch(f"sensors/{sensor_id}/hours", {
                        "datetime_from": args.from_utc, "datetime_to": args.to_utc,
                        "limit": 1000, "page": page,
                    })
                    rows.extend(data["results"])
                    if len(data["results"]) < 1000:
                        break
                else:
                    raise ValueError("Measurement pagination budget reached; completeness unknown")
                report.setdefault("samples", []).append({
                    "sensor_id": sensor_id, "from": args.from_utc, "to": args.to_utc, "rows": rows,
                })
                print(f"Sensor {sensor_id}: {len(rows)} hourly rows in requested window")
        report["passed"] = True
    except (ValueError, KeyError, TypeError, URLError, TimeoutError, OSError) as error:
        report["failure"] = f"{type(error).__name__}: {error}".replace(key, "[REDACTED]")
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        serialized = json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False)
        if key in serialized:
            raise ValueError("Refusing to write evidence containing a credential")
        with args.output.open("x", encoding="utf-8") as output:
            output.write(serialized + "\n")
    print(f"{'PASS' if report['passed'] else 'FAIL'}: {len(report['requests'])} requests; evidence: {args.output}")
    if not report["passed"]:
        print(report["failure"], file=sys.stderr)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
