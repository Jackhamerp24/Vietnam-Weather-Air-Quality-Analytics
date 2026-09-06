"""Explicitly synthetic intervals test audit arithmetic; no live API calls."""

import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPMessage
from io import BytesIO
from urllib.request import Request

from scripts.audit_openaq import summarize_hours
from scripts.probe_openaq import NoRedirects


class OpenAQAuditTests(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(hours=4)

    def row(self, hour, value: float | None = 1.0, flagged=False):
        return {
            "period": {
                "interval": "01:00:00",
                "datetimeFrom": {"utc": (self.start + timedelta(hours=hour - 1)).isoformat()},
                "datetimeTo": {"utc": (self.start + timedelta(hours=hour)).isoformat()},
            },
            "parameter": {"name": "pm25", "units": "\u00b5g/m\u00b3"},
            "flagInfo": {"hasFlags": flagged}, "value": value,
        }

    def test_complete_hourly_window(self):
        audit, _ = summarize_hours([self.row(i) for i in range(1, 5)], self.start, self.end)
        self.assertEqual(audit["present_percent"], 100)
        self.assertEqual(audit["expected_hours"], 4)

    def test_boundary_rows_excluded(self):
        audit, _ = summarize_hours([self.row(0), self.row(1), self.row(4), self.row(5)], self.start, self.end)
        self.assertEqual(audit["unique_present_hours"], 2)
        self.assertEqual(audit["rejection_counts"]["outside_window"], 2)

    def test_duplicates_do_not_inflate_coverage(self):
        audit, _ = summarize_hours([self.row(1), self.row(1), self.row(4)], self.start, self.end)
        self.assertEqual(audit["duplicate_periods"], 1)
        self.assertEqual(audit["missing_hours"], 2)
        self.assertEqual(audit["longest_missing_run_hours"], 2)
        self.assertEqual(audit["present_percent"], 50)

    def test_present_and_valid_are_separate(self):
        rows = [self.row(1, None), self.row(2, -999), self.row(3, flagged=True), self.row(4, 500)]
        audit, _ = summarize_hours(rows, self.start, self.end)
        self.assertEqual(audit["unique_present_hours"], 4)
        self.assertEqual(audit["finite_nonnegative_unflagged_hours"], 1)
        self.assertEqual(audit["provider_flagged_rows"], 1)

    def test_credential_redirects_blocked(self):
        self.assertIsNone(NoRedirects().redirect_request(
            Request("https://api.openaq.org/"), BytesIO(), 302,
            "redirect", HTTPMessage(), "https://other.invalid",
        ))


if __name__ == "__main__":
    unittest.main()
