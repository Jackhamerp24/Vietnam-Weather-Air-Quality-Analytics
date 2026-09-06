"""Pure source contracts: no HTTP, database access, interpolation or imputation."""

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from vn_air.ingestion import IngestionError


HOUR = timedelta(hours=1)
WEATHER = ("temperature_2m", "apparent_temperature", "relative_humidity_2m", "precipitation",
           "wind_speed_10m", "wind_direction_10m", "surface_pressure", "cloud_cover", "shortwave_radiation")
AIR = ("pm2_5", "pm10", "nitrogen_dioxide", "sulphur_dioxide", "carbon_monoxide", "ozone", "us_aqi")
UNITS = {"degC": {"\u00b0C"}, "%": {"%"}, "mm": {"mm"}, "m/s": {"m/s"}, "degree": {"\u00b0"},
         "hPa": {"hPa"}, "W/m2": {"W/m\u00b2"}, "ug/m3": {"\u03bcg/m\u00b3", "\u00b5g/m\u00b3"}, "USAQI": {"USAQI"}}


@dataclass
class Parsed:
    rows: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    grid: tuple | None = None

    def issue(self, code, locator, *, quarantine=False, severity="warning", details=None):
        self.issues.append(dict(code=code, locator=locator, quarantine=quarantine, severity=severity, details=details or {}))


def timestamp(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise IngestionError("invalid_timestamp") from None


def date_pair(value):
    if not isinstance(value, dict) or "utc" not in value:
        raise IngestionError("invalid_timestamp")
    result = timestamp(value["utc"])
    if "local" in value and timestamp(value["local"]) != result:
        raise IngestionError("timezone_inconsistency")
    return result


def distance_km(latitude, longitude, location):
    if (type(latitude) not in (int, float) or type(longitude) not in (int, float)
            or not -90 <= latitude <= 90 or not -180 <= longitude <= 180):
        raise IngestionError("invalid_coordinates")
    a = math.sin(math.radians(latitude - location.latitude) / 2) ** 2
    a += math.cos(math.radians(latitude)) * math.cos(math.radians(location.latitude)) * math.sin(math.radians(longitude - location.longitude) / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(a)))


def check_location(payload, sensor, location, start, end):
    try:
        records = payload["results"]
        if len(records) != 1:
            raise IngestionError("location_metadata_missing")
        item = records[0]
        if str(item["id"]) != sensor.external_location_id or item["country"]["code"] != "VN":
            raise IngestionError("location_identity_mismatch")
        if item["isMobile"] or item["isMonitor"] != sensor.is_reference_monitor:
            raise IngestionError("instrument_metadata_changed")
        instruments = sorted(i["name"] for i in item["instruments"])
        enriched = sensor.instrument == "Unknown AirGradient Sensor" and instruments == ["AirGradient Open Air Generation 1 (O-1PST)"]
        if item["provider"]["id"] != 66 or (sensor.instrument not in instruments and not enriched):
            raise IngestionError("instrument_metadata_changed")
        coordinates = item["coordinates"]
        if distance_km(coordinates["latitude"], coordinates["longitude"], location) > 0.1:
            raise IngestionError("station_coordinates_changed")
        provider_zone = ZoneInfo(item["timezone"])
        canonical_zone = ZoneInfo(location.timezone)
        if item["timezone"] not in {location.provider_timezone, "Asia/Bangkok", "Asia/Ho_Chi_Minh"}:
            raise IngestionError("station_timezone_changed")
        # These IANA zones differ historically. Accept the known metadata alias
        # only when their offsets agree throughout this actual query window.
        if any((start + i * HOUR).astimezone(provider_zone).utcoffset() != (start + i * HOUR).astimezone(canonical_zone).utcoffset()
               for i in range(int((end - start) / HOUR) + 1)):
            raise IngestionError("station_timezone_changed")
        match = next((s for s in item["sensors"] if str(s["id"]) == sensor.external_sensor_id), None)
        if match is None or match["parameter"]["name"] != "pm25" or match["parameter"]["units"] not in UNITS["ug/m3"]:
            raise IngestionError("sensor_parameter_changed")
        local_start = start.astimezone(ZoneInfo(location.timezone)).date().isoformat()
        local_end = (end - timedelta(microseconds=1)).astimezone(ZoneInfo(location.timezone)).date().isoformat()
        licences = [lic for lic in (item["licenses"] or []) if lic["id"] == 41
                    and lic.get("dateFrom") and lic["dateFrom"] <= local_start
                    and (lic.get("dateTo") is None or lic["dateTo"] >= local_end)]
        if not licences:
            raise IngestionError("licence_not_qualified")
        return {"instrument": ", ".join(instruments), "configured_instrument": sensor.instrument,
                "is_reference_monitor": item["isMonitor"],
                "provider_timezone": item["timezone"],
                "licences": licences, "provider_id": 66, "external_location_id": sensor.external_location_id}
    except (KeyError, TypeError, ValueError, IndexError):
        raise IngestionError("invalid_location_metadata") from None


def check_licence(payload):
    try:
        item = payload["results"][0]
        if (item["id"] != 41 or item["sourceUrl"] != "https://creativecommons.org/licenses/by/4.0/"
                or item["redistributionAllowed"] is not True or item["modificationAllowed"] is not True):
            raise IngestionError("licence_not_qualified")
    except (KeyError, TypeError, IndexError):
        raise IngestionError("invalid_licence_metadata") from None


def parse_openaq(payload, sensor, location, metadata, start, end, retrieved):
    if not isinstance(payload.get("results"), list):
        raise IngestionError("invalid_measurement_payload")
    result = Parsed()
    for index, item in enumerate(payload["results"]):
        locator = f"results/{index}"
        try:
            period = item["period"]
            left, right = date_pair(period["datetimeFrom"]), date_pair(period["datetimeTo"])
            if right - left != HOUR or right.timestamp() % 3600 or period["interval"] != "01:00:00":
                raise IngestionError("invalid_hourly_interval")
            if left < start or right > end:
                result.issue("outside_requested_window", locator, severity="info")
                continue
            if right > retrieved:
                raise IngestionError("incomplete_measurement")
            if item.get("coordinates") is not None:
                if distance_km(item["coordinates"]["latitude"], item["coordinates"]["longitude"], location) > 0.1:
                    raise IngestionError("station_coordinates_changed")
            if item["parameter"]["name"] != "pm25":
                raise IngestionError("wrong_parameter")
            value = item.get("value")
            status, codes = "accepted", []
            if item["parameter"].get("units") not in UNITS["ug/m3"]:
                status, value = "invalid", None
                codes.append("unexpected_unit")
            elif "value" not in item:
                status, value = "invalid", None
                codes.append("missing_value_field")
            elif value is None:
                status = "missing"
                codes.append("source_missing_value")
            elif type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                status, value = "invalid", None
                codes.append("invalid_concentration")
            elif value > 500:
                status = "suspect"
                codes.append("extreme_concentration_review")
            coverage = (item.get("coverage") or {}).get("percentComplete")
            if coverage is not None and (type(coverage) not in (int, float) or not 0 <= coverage <= 100):
                coverage = None
                codes.append("invalid_coverage_metadata")
            flag = (item.get("flagInfo") or {}).get("hasFlags")
            if flag is not False:
                codes.append("provider_flag" if flag is True else "provider_flag_unknown")
            if coverage is None or coverage < 75:
                codes.append("insufficient_hour_coverage")
            if codes and status == "accepted":
                status = "suspect"
            for code in codes:
                result.issue(code, locator, quarantine=status == "invalid", severity="error" if status == "invalid" else "warning")
            result.rows.append(dict(sensor_id=sensor.id, product_id=sensor.product_id, variable_code=sensor.variable_code,
                                    canonical_unit=sensor.canonical_unit, period_start=left, period_end=right,
                                    value=value, quality_status=status, coverage_percent=coverage,
                                    source_flags={"hasFlags": flag if type(flag) is bool else None, "codes": codes},
                                    latitude=location.latitude, longitude=location.longitude, source_metadata=metadata,
                                    _locator=locator))
        except IngestionError as error:
            result.issue(error.code, locator, quarantine=True, severity="error")
        except (KeyError, TypeError, ValueError, OverflowError):
            result.issue("malformed_measurement", locator, quarantine=True, severity="error")
    return result


def parse_meteo(payload, variables, location, start, end, retrieved, kind):
    result = Parsed()
    try:
        if payload.get("error") or payload["utc_offset_seconds"] != 0:
            raise IngestionError("invalid_model_response")
        lat, lon = payload["latitude"], payload["longitude"]
        if distance_km(lat, lon, location) > 60:
            raise IngestionError("model_grid_too_distant")
        result.grid = (lat, lon)
        hourly, units = payload["hourly"], payload["hourly_units"]
        if units["time"] != "unixtime" or not isinstance(hourly["time"], list):
            raise IngestionError("invalid_model_timestamps")
        times = hourly["time"]
        if not times or any(type(t) is not int or t % 3600 for t in times):
            raise IngestionError("invalid_model_timestamps")
        if any(b <= a for a, b in zip(times, times[1:])):
            raise IngestionError("duplicate_or_unsorted_model_time")
        moments = [datetime.fromtimestamp(t, timezone.utc) for t in times]
        if len(times) > 14 * 24 or any(t < start or t >= end for t in moments):
            raise IngestionError("model_window_mismatch")
        if kind == "reanalysis" and any(t > retrieved for t in moments):
            raise IngestionError("future_reanalysis")
        expected = {start + i * HOUR for i in range(int((end - start) / HOUR))}
        if len(expected - set(moments)):
            result.issue("missing_model_hours", "hourly/time", details={"missing_hours": len(expected - set(moments))})
        for key, values in hourly.items():
            if key != "time" and (not isinstance(values, list) or len(values) != len(times)):
                raise IngestionError("model_array_mismatch")
        selected = {variable.code for variable in variables}
        if set(hourly) - selected - {"time"}:
            result.issue("unexpected_model_variables", "hourly", details={"count": len(set(hourly) - selected - {"time"})})
        for variable in variables:
            missing_variable = variable.code not in hourly
            unit_bad = units.get(variable.code) not in UNITS[variable.canonical_unit]
            if missing_variable or unit_bad:
                result.issue("variable_unavailable" if missing_variable else "unexpected_unit", f"hourly/{variable.code}", quarantine=not missing_variable, severity="warning" if missing_variable else "error")
            values = hourly.get(variable.code, [None] * len(times))
            counts = Counter()
            for i, (at, value) in enumerate(zip(moments, values)):
                status, code = "accepted", None
                if missing_variable:
                    status, code = "missing", "variable_unavailable"
                elif unit_bad:
                    value, status, code = None, "invalid", "unexpected_unit"
                elif value is None:
                    status, code = "missing", "source_missing_value"
                elif (type(value) not in (int, float) or not math.isfinite(value)
                      or (variable.minimum is not None and value < variable.minimum)
                      or (variable.maximum is not None and value > variable.maximum)):
                    value, status, code = None, "invalid", "invalid_model_value"
                    result.issue(code, f"hourly/{variable.code}/{i}", quarantine=True, severity="error")
                elif variable.code in ("pm2_5", "pm10") and value > 500:
                    status, code = "suspect", "extreme_concentration_review"
                if code:
                    counts[code] += 1
                result.rows.append(dict(domain=variable.domain, variable_code=variable.code, canonical_unit=variable.canonical_unit,
                                        valid_at=at, period_start=at if variable.temporal_support == "instant" else at - HOUR,
                                        temporal_support=variable.temporal_support, native_interval_seconds=3600 if kind == "reanalysis" else None,
                                        value=value, quality_status=status, source_flags={"codes": [code] if code else []}))
            if counts:
                result.issue("model_value_quality_summary", f"hourly/{variable.code}", details=dict(counts))
        return result
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        raise IngestionError("malformed_model_response") from None
