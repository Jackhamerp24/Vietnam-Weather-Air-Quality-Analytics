"""Pure Phase 4 audit arithmetic; no database or provider traffic."""

import unittest
from datetime import datetime, timedelta, timezone

from vn_air.quality import gap_summary, hourly_end_grid, latest_revisions, select_captures
from vn_air.eda import descriptive, descriptive_correlation, lag_correlations


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

    def test_descriptive_summary_has_no_inferential_claims(self):
        summary = descriptive([1.0, 2.0, 3.0])
        self.assertEqual(summary["n"], 3)
        self.assertEqual(summary["median"], 2.0)
        self.assertNotIn("p_value", summary)

    def test_descriptive_correlation_ignores_missing_pairs(self):
        result = descriptive_correlation([1.0, None, 3.0, 4.0], [2.0, 4.0, 6.0, 8.0])
        self.assertEqual(result["n"], 3)
        self.assertEqual(result["pearson_r"], 1.0)

    def test_lag_correlation_respects_elapsed_hours_across_gaps(self):
        rows = [
            {"period_end": "2026-06-08T01:00:00+00:00", "pm25": 1.0},
            {"period_end": "2026-06-08T03:00:00+00:00", "pm25": 3.0},
        ]
        result = lag_correlations(rows, lags=(1, 2))
        self.assertEqual(result[0]["n"], 0)
        self.assertEqual(result[1]["n"], 1)


if __name__ == "__main__":
    unittest.main()
