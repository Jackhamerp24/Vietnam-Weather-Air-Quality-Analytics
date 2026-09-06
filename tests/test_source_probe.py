"""Synthetic contract examples only. No study data or external API calls."""

import copy
import unittest

from scripts.probe_sources import check_hourly


class HourlyProbeTests(unittest.TestCase):
    def setUp(self):
        self.units = {"pm2_5": "\u03bcg/m\u00b3"}
        self.payload = [{
            "latitude": 21.0, "longitude": 105.8, "utc_offset_seconds": 0,
            "hourly_units": {"time": "unixtime", "pm2_5": "\u03bcg/m\u00b3"},
            "hourly": {"time": [0, 3600], "pm2_5": [1.0, 2.0]},
        }]

    def test_valid_contract(self):
        result = check_hourly(self.payload, self.units, 2, 1)
        self.assertEqual(result[0]["missing_counts"], {"pm2_5": 0})
        self.assertEqual(result[0]["first_time_utc"], "1970-01-01T00:00:00+00:00")

    def test_micro_sign_alias(self):
        self.payload[0]["hourly_units"]["pm2_5"] = "\u00b5g/m\u00b3"
        check_hourly(self.payload, self.units, 2, 1)

    def test_wrong_units_rejected(self):
        self.payload[0]["hourly_units"]["pm2_5"] = "mg/m3"
        with self.assertRaisesRegex(ValueError, "Unexpected unit"):
            check_hourly(self.payload, self.units, 2, 1)

    def test_missing_and_invalid_values_rejected(self):
        for value in (None, float("nan"), float("inf"), "1", True):
            with self.subTest(value=value):
                payload = copy.deepcopy(self.payload)
                payload[0]["hourly"]["pm2_5"][0] = value
                with self.assertRaises(ValueError):
                    check_hourly(payload, self.units, 2, 1)

    def test_duplicate_gap_and_reversed_times_rejected(self):
        for times in ([0, 0], [0, 7200], [3600, 0], [0, "3600"]):
            with self.subTest(times=times):
                self.payload[0]["hourly"]["time"] = times
                with self.assertRaises(ValueError):
                    check_hourly(self.payload, self.units, 2, 1)

    def test_mismatched_array_rejected(self):
        self.payload[0]["hourly"]["pm2_5"] = [1.0]
        with self.assertRaisesRegex(ValueError, "Array length mismatch"):
            check_hourly(self.payload, self.units, 2, 1)

    def test_non_utc_rejected(self):
        self.payload[0]["utc_offset_seconds"] = 25200
        with self.assertRaisesRegex(ValueError, "nonzero offset"):
            check_hourly(self.payload, self.units, 2, 1)

    def test_wrong_location_count_rejected(self):
        with self.assertRaisesRegex(ValueError, "location responses"):
            check_hourly(self.payload, self.units, 2, 3)

    def test_invalid_coordinates_rejected(self):
        self.payload[0]["latitude"] = 91
        with self.assertRaisesRegex(ValueError, "Invalid returned coordinates"):
            check_hourly(self.payload, self.units, 2, 1)


if __name__ == "__main__":
    unittest.main()
