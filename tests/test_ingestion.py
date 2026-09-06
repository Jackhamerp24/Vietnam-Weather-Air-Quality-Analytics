"""Pure parser and mocked transport tests; no provider traffic."""

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from ingestion_fixtures import aq_row, licence_payload, location_payload, meteo_payload
from vn_air.config import load_config
from vn_air.ingestion import IngestionError
from vn_air.ingestion.http import HTTPSource, decode_json
from vn_air.ingestion.parsing import HOUR, check_licence, check_location, parse_meteo, parse_openaq, timestamp


CONFIG = load_config(Path(__file__).resolve().parents[1] / "configs/study.json")
T = datetime(2026, 6, 8, tzinfo=timezone.utc)
SENSOR = CONFIG.sensors[0]
LOCATION = next(row for row in CONFIG.locations if row.id == SENSOR.location_id)


class ParserTests(unittest.TestCase):
    def aq(self, rows):
        return parse_openaq({"results": rows}, SENSOR, LOCATION, {}, T, T + timedelta(days=1), T + timedelta(days=2))

    def test_timezone_offset_and_naive_rejection(self):
        self.assertEqual(timestamp("2026-06-08T07:00:00+07:00"), T)
        with self.assertRaises(IngestionError):
            timestamp("2026-06-08T07:00:00")

    def test_hourly_mean_end_is_preserved(self):
        result = self.aq([aq_row(T)])
        self.assertEqual(result.rows[0]["period_end"], T + HOUR)
        self.assertEqual(result.rows[0]["canonical_unit"], "ug/m3")

    def test_both_micro_unit_spellings(self):
        for unit in ("\u00b5g/m\u00b3", "\u03bcg/m\u00b3"):
            row = aq_row(T)
            row["parameter"]["units"] = unit
            self.assertEqual(self.aq([row]).rows[0]["value"], 10)

    def test_negative_nonfinite_and_bool_are_invalid_markers(self):
        for value in (-999, float("nan"), float("inf"), True, "10"):
            with self.subTest(value=value):
                result = self.aq([aq_row(T, value)])
                self.assertIsNone(result.rows[0]["value"])
                self.assertEqual(result.rows[0]["quality_status"], "invalid")
                self.assertTrue(result.issues[0]["quarantine"])

    def test_missing_and_extreme_are_distinct(self):
        self.assertEqual(self.aq([aq_row(T, None)]).rows[0]["quality_status"], "missing")
        row = self.aq([aq_row(T, 800)]).rows[0]
        self.assertEqual((row["value"], row["quality_status"]), (800, "suspect"))

    def test_inconsistent_local_timestamp_quarantined(self):
        row = aq_row(T)
        row["period"]["datetimeTo"]["local"] = T.isoformat()
        result = self.aq([row])
        self.assertEqual(result.rows, [])
        self.assertEqual(result.issues[0]["code"], "timezone_inconsistency")

    def test_bad_interval_and_wrong_variable_are_not_pm25(self):
        for change in ("time", "parameter"):
            row = aq_row(T)
            if change == "time":
                row["period"]["interval"] = "00:05:00"
            else:
                row["parameter"]["name"] = "o3"
            self.assertFalse(self.aq([row]).rows)

    def test_bad_coverage_does_not_erase_value(self):
        row = aq_row(T)
        row["coverage"]["percentComplete"] = 1435100.0
        value = self.aq([row]).rows[0]
        self.assertEqual(value["value"], 10)
        self.assertIsNone(value["coverage_percent"])
        self.assertEqual(value["quality_status"], "suspect")

    def test_openaq_invalid_unit_keeps_identifiable_interval(self):
        row = aq_row(T)
        row["parameter"]["units"] = "AQI"
        result = self.aq([row])
        self.assertEqual(result.rows[0]["period_end"], T + HOUR)
        self.assertEqual(result.rows[0]["quality_status"], "invalid")

    def test_metadata_identity_licence_and_movement(self):
        payload = location_payload(SENSOR, LOCATION)
        check_location(payload, SENSOR, LOCATION, T, T + HOUR)
        check_licence(licence_payload())
        for key, value in (("id", 1), ("isMobile", True), ("licenses", []), ("coordinates", {"latitude": 15, "longitude": 108})):
            bad = copy.deepcopy(payload)
            bad["results"][0][key] = value
            with self.subTest(key=key), self.assertRaises(IngestionError):
                check_location(bad, SENSOR, LOCATION, T, T + HOUR)

    def test_precipitation_model_interval(self):
        variables = [v for v in CONFIG.variables if v.code == "precipitation"]
        payload = meteo_payload(LOCATION, variables, T)
        result = parse_meteo(payload, variables, LOCATION, T, T + timedelta(days=1), T + timedelta(days=2), "reanalysis")
        self.assertEqual(result.rows[0]["period_start"], T - HOUR)

    def test_reviewed_unknown_instrument_enrichment(self):
        payload = location_payload(SENSOR, LOCATION)
        payload["results"][0]["instruments"] = [{"name": "AirGradient Open Air Generation 1 (O-1PST)"}]
        result = check_location(payload, SENSOR, LOCATION, T, T + HOUR)
        self.assertEqual(result["instrument"], "AirGradient Open Air Generation 1 (O-1PST)")
        payload["results"][0]["instruments"] = [{"name": "Unreviewed new sensor"}]
        with self.assertRaises(IngestionError):
            check_location(payload, SENSOR, LOCATION, T, T + HOUR)

    def test_modern_timezone_alias_keeps_original_metadata(self):
        payload = location_payload(SENSOR, LOCATION)
        payload["results"][0]["timezone"] = "Asia/Bangkok"
        result = check_location(payload, SENSOR, LOCATION, T, T + HOUR)
        self.assertEqual(result["provider_timezone"], "Asia/Bangkok")
        payload["results"][0]["timezone"] = "Asia/Tokyo"
        with self.assertRaisesRegex(IngestionError, "station_timezone_changed"):
            check_location(payload, SENSOR, LOCATION, T, T + HOUR)

    def test_missing_model_variable_not_zero(self):
        variables = [v for v in CONFIG.variables if v.code in ("temperature_2m", "precipitation")]
        payload = meteo_payload(LOCATION, variables, T)
        del payload["hourly"]["precipitation"]
        result = parse_meteo(payload, variables, LOCATION, T, T + timedelta(days=1), T + timedelta(days=2), "reanalysis")
        missing = [row for row in result.rows if row["variable_code"] == "precipitation"]
        self.assertTrue(all(row["value"] is None and row["quality_status"] == "missing" for row in missing))

    def test_model_array_mismatch_and_bad_units(self):
        variables = [v for v in CONFIG.variables if v.code == "temperature_2m"]
        payload = meteo_payload(LOCATION, variables, T)
        payload["hourly_units"]["temperature_2m"] = "F"
        result = parse_meteo(payload, variables, LOCATION, T, T + timedelta(days=1), T + timedelta(days=2), "reanalysis")
        self.assertTrue(all(row["quality_status"] == "invalid" for row in result.rows))
        payload["hourly"]["temperature_2m"].pop()
        with self.assertRaises(IngestionError):
            parse_meteo(payload, variables, LOCATION, T, T + timedelta(days=1), T + timedelta(days=2), "reanalysis")


class TransportTests(unittest.TestCase):
    def request(self, handler, *, key="synthetic_test_token", max_bytes=2048):
        attempts, waits = [], []
        source = HTTPSource(key=key, transport=httpx.MockTransport(handler), sleep=waits.append, max_bytes=max_bytes)
        try:
            value = source.get("https://api.openaq.org/v3/licenses/41", {}, before_attempt=lambda group: None,
                               save_attempt=lambda attempt, number, group: attempts.append(attempt) or number)
            return value, attempts, waits
        finally:
            source.close()

    def test_auth_header_not_url(self):
        def handler(request):
            self.assertEqual(request.headers["X-API-Key"], "synthetic_test_token")
            self.assertNotIn("synthetic_test_token", str(request.url))
            return httpx.Response(200, json={"results": []})
        self.assertEqual(self.request(handler)[0][0], 1)

    def test_retry_after_and_transient_success(self):
        calls = []
        def handler(request):
            calls.append(1)
            return httpx.Response(429, headers={"Retry-After": "5"}, json={}) if len(calls) == 1 else httpx.Response(200, json={})
        _, attempts, waits = self.request(handler)
        self.assertEqual(len(attempts), 2)
        self.assertGreaterEqual(waits[0], 5)

    def test_401_not_retried(self):
        calls = []
        def handler(request):
            calls.append(1)
            return httpx.Response(401, json={})
        with self.assertRaisesRegex(IngestionError, "http_401"):
            self.request(handler)
        self.assertEqual(len(calls), 1)

    def test_long_cooldown_stops_without_early_retry(self):
        calls = []
        def handler(request):
            calls.append(1)
            return httpx.Response(429, headers={"Retry-After": "3600"}, json={})
        with self.assertRaisesRegex(IngestionError, "provider_cooldown"):
            self.request(handler)
        self.assertEqual(len(calls), 1)

    def test_unicode_escaped_secret_is_withheld(self):
        body = ('{"echo":"' + ''.join('\\u%04x' % ord(char) for char in "synthetic_test_token") + '"}').encode()
        with self.assertRaisesRegex(IngestionError, "credential_echo"):
            self.request(lambda request: httpx.Response(200, content=body))

    def test_timeout_bounded(self):
        calls = []
        def handler(request):
            calls.append(1)
            raise httpx.ReadTimeout("Synthetic timeout with sensitive request", request=request)
        with self.assertRaisesRegex(IngestionError, "timeout"):
            self.request(handler)
        self.assertEqual(len(calls), 4)

    def test_redirect_blocked(self):
        with self.assertRaisesRegex(IngestionError, "redirect_blocked"):
            self.request(lambda request: httpx.Response(302, headers={"Location": "https://evil.invalid"}))

    def test_secret_echo_and_size_are_withheld(self):
        for body, error in ((b'{"value":"synthetic_test_token"}', "credential_echo"), (b'x' * 3000, "response_too_large")):
            attempts = []
            source = HTTPSource(key="synthetic_test_token", transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body)), sleep=lambda s: None, max_bytes=2048)
            try:
                with self.assertRaisesRegex(IngestionError, error):
                    source.get("https://api.openaq.org/v3/licenses/41", {}, before_attempt=lambda group: None,
                               save_attempt=lambda attempt, number, group: attempts.append(attempt))
                self.assertIsNone(attempts[0].body)
            finally:
                source.close()

    def test_invalid_json_and_unapproved_host(self):
        with self.assertRaisesRegex(IngestionError, "invalid_json"):
            decode_json(b'{"a":1,"a":2}')
        source = HTTPSource(key="test")
        try:
            with self.assertRaisesRegex(IngestionError, "unapproved_endpoint"):
                source.validate("https://api.openaq.org.evil.invalid/v3/locations/1", {})
            with self.assertRaisesRegex(IngestionError, "unapproved_parameters"):
                source.validate("https://api.openaq.org/v3/locations/1", {"token": "test"})
        finally:
            source.close()
