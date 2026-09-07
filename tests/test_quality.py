"""Pure Phase 4 audit arithmetic; no database or provider traffic."""

import unittest
from datetime import datetime, timedelta, timezone

from vn_air.quality import gap_summary, hourly_end_grid, latest_revisions, select_captures


UTC = timezone.utc
START = datetime(2026, 6, 8, tzinfo=UTC)


class QualityAuditTests(unittest.TestCase):
    def test_hourly_grid_uses_period_ends(self):
        self.assertEqual(hourly_end_grid(START, START + timedelta(hours=3)), [
            START + timedelta(hours=1), START + timedelta(hours=2), START + timedelta(hours=3)
        ])

    def test_gap_summary_preserves_longest_run(self):
        expected = set(hourly_end_grid(START, START + timedelta(hours=6)))
        present = expected - {START + timedelta(hours=2), START + timedelta(hours=3), START + timedelta(hours=6)}
        summary = gap_summary(expected, present)
        self.assertEqual(summary["missing_hours"], 3)
        self.assertEqual(summary["longest_missing_run_hours"], 2)

    def test_latest_revision_is_as_of_cutoff(self):
        period = START + timedelta(hours=1)
        rows = [
            {"sensor_id": "s", "period_end": period, "revision": 1, "retrieved_at": START, "recorded_at": START},
            {"sensor_id": "s", "period_end": period, "revision": 2, "retrieved_at": START + timedelta(days=1), "recorded_at": START + timedelta(days=1)},
        ]
        selected = latest_revisions(rows, START + timedelta(hours=1))
        self.assertEqual(selected[("s", period)]["revision"], 1)

    def test_latest_invalid_revision_remains_selected(self):
        period = START + timedelta(hours=1)
        rows = [
            {"sensor_id": "s", "period_end": period, "revision": 1, "value": 10.0,
             "quality_status": "accepted", "retrieved_at": START, "recorded_at": START},
            {"sensor_id": "s", "period_end": period, "revision": 2, "value": None,
             "quality_status": "invalid", "retrieved_at": START + timedelta(hours=1),
             "recorded_at": START + timedelta(hours=1)},
        ]
        self.assertEqual(latest_revisions(rows, START + timedelta(hours=2))[("s", period)]["quality_status"], "invalid")

    def test_newer_capture_omission_does_not_fallback(self):
        old = {"id": "old", "retrieved_at": START, "recorded_at": START,
               "window_start": START, "window_end": START + timedelta(hours=3)}
        new = {"id": "new", "retrieved_at": START + timedelta(hours=1),
               "recorded_at": START + timedelta(hours=1), "window_start": START,
               "window_end": START + timedelta(hours=3)}
        chosen = select_captures([old, new], {START + timedelta(hours=1)})
        self.assertEqual(chosen[START + timedelta(hours=1)]["id"], "new")


if __name__ == "__main__":
    unittest.main()
