"""Deliberately synthetic API payloads for edge-case tests, never study data."""

from datetime import timedelta
from typing import Any

from vn_air.ingestion.parsing import HOUR, UNITS


def location_payload(sensor, location):
    return {"results": [{"id": int(sensor.external_location_id), "country": {"code": "VN"}, "isMobile": False,
                         "isMonitor": False, "provider": {"id": 66}, "instruments": [{"name": sensor.instrument}],
                         "coordinates": {"latitude": location.latitude, "longitude": location.longitude},
                         "timezone": "Asia/Ho_Chi_Minh",
                         "sensors": [{"id": int(sensor.external_sensor_id), "parameter": {"name": "pm25", "units": "\u00b5g/m\u00b3"}}],
                         "licenses": [{"id": 41, "dateFrom": "2023-07-15", "dateTo": None,
                                       "attribution": {"name": "Synthetic contributor"}}]}]}


def licence_payload():
    return {"results": [{"id": 41, "sourceUrl": "https://creativecommons.org/licenses/by/4.0/",
                         "redistributionAllowed": True, "modificationAllowed": True}]}


def aq_row(start, value: Any = 10.0):
    return {"value": value, "flagInfo": {"hasFlags": False}, "parameter": {"name": "pm25", "units": "\u00b5g/m\u00b3"},
            "period": {"interval": "01:00:00", "datetimeFrom": {"utc": start.isoformat()},
                       "datetimeTo": {"utc": (start + HOUR).isoformat()}}, "coordinates": None,
            "coverage": {"percentComplete": 100.0}}


def meteo_payload(location, variables, start, hours=24):
    return {"latitude": location.latitude, "longitude": location.longitude, "utc_offset_seconds": 0,
            "hourly_units": {"time": "unixtime", **{v.code: sorted(UNITS[v.canonical_unit])[0] for v in variables}},
            "hourly": {"time": [int((start + timedelta(hours=i)).timestamp()) for i in range(hours)],
                       **{v.code: [10.0] * hours for v in variables}}}
