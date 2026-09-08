"""Phase 6 statistics on synthetic data; no database, no network, no real bundle dependency."""

import json
import random
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from vn_air import statistics as st
from vn_air.eda import EDA_POLICY
from vn_air.quality import digest

WEATHER_CODES = ("apparent_temperature", "cloud_cover", "precipitation", "relative_humidity_2m",
                 "shortwave_radiation", "surface_pressure", "temperature_2m", "wind_direction_10m",
                 "wind_speed_10m")
START = datetime(2026, 6, 8, tzinfo=timezone.utc)
EXTREME_DAYS = (50, 60)
GAP_DAYS = (40, 41)
WEATHER_GAP_DAYS = (30,)
PRIMARY_IDS = ("H1_pooled_log1p_b1_pairwise_complete", "H2_pooled_log1p_b1_pairwise_complete")


def synthetic_bundle(days=91, seed=7, hours=tuple(range(24)), weather_gap_days=WEATHER_GAP_DAYS):
    rng = random.Random(seed)
    rows = []
    for day_offset in range(days):
        day = date(2026, 6, 8) + timedelta(days=day_offset)
        for hour in hours:
            end = START + timedelta(days=day_offset, hours=hour + 1)
            for sensor_id, location in (("openaq_11357424", "cmt8"), ("openaq_14581375", "oceanpark")):
                absent = location == "oceanpark" and day_offset in GAP_DAYS
                wind = 2.0 + 0.02 * hour + rng.gauss(0, 0.3)
                humidity = 60 + 0.1 * hour + rng.gauss(0, 2.0)
                weather = {code: {"value": wind if code == "wind_speed_10m" else humidity} for code in WEATHER_CODES}
                pm25 = 30 - 3 * wind + 0.05 * humidity + rng.gauss(0, 1.5)
                if location == "oceanpark" and day_offset in EXTREME_DAYS and hour in (10, 11):
                    pm25 += 90
                if location == "oceanpark" and day_offset in weather_gap_days:
                    weather["cloud_cover"]["value"] = None
                rows.append({"sensor_id": sensor_id, "location_id": location,
                    "period_end": end.isoformat(), "period_start": (end - timedelta(hours=1)).isoformat(),
                    "local_date": day.isoformat(), "local_hour": hour, "weekday": day.weekday(),
                    "pm25": None if absent else pm25, "source_pm25": pm25,
                    "quality": "absent" if absent else "accepted", "weather": weather})
    manifest = {"eda_version": "phase5_eda_v1", "policy": EDA_POLICY,
        "cutoff": "2026-09-06T20:59:00.669630+00:00", "start": "2026-06-08T00:00:00+00:00",
        "end": "2026-09-06T00:00:00+00:00", "phase4_artifact_sha256": "0" * 64,
        "phase4_manifest_sha256": "0" * 64, "input_sha256": {}}
    dataset = {"rows": rows, "sensors": {"openaq_11357424": {"name": "CMT8", "location_id": "cmt8"},
               "openaq_14581375": {"name": "OceanPark", "location_id": "oceanpark"}}}
    return {"bundle_sha256": "0" * 64, "manifest": manifest, "dataset": dataset}


def counts_from_bundle(bundle):
    rows = bundle["dataset"]["rows"]
    accepted = [r for r in rows if r["pm25"] is not None]
    ends = {}
    for row in accepted:
        ends.setdefault(row["location_id"], set()).add(row["period_end"])
    complete = lambda r: all(w["value"] is not None for w in r["weather"].values())
    return {"accepted_rows": len(accepted), "absent_rows": len(rows) - len(accepted),
            "accepted_cmt8": sum(r["location_id"] == "cmt8" for r in accepted),
            "accepted_oceanpark": sum(r["location_id"] == "oceanpark" for r in accepted),
            "complete_weather_cmt8": sum(r["location_id"] == "cmt8" and complete(r) for r in accepted),
            "complete_weather_oceanpark": sum(r["location_id"] == "oceanpark" and complete(r) for r in accepted),
            "shared_accepted_hours": len(set.intersection(*ends.values()))}


def absent_hours(days=91, gap_days=GAP_DAYS):
    return sum(24 for offset in range(days) if offset in gap_days)


def study_dates(count=91):
    return [(date(2026, 6, 8) + timedelta(days=offset)).isoformat() for offset in range(count)]


class ArithmeticTests(unittest.TestCase):
    def test_percentile_is_type_7(self):
        self.assertEqual(st.percentile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(st.percentile([10, 20, 30, 40], 0.25), 17.5)
        self.assertEqual(st.percentile([5], 0.975), 5)

    def test_sig_rounds_to_12_significant_digits(self):
        self.assertEqual(st.sig(1 / 3), float(f"{1 / 3:.12g}"))
        self.assertIsNone(st.sig(None))

    def test_holm_matches_hand_computation(self):
        self.assertEqual(st.holm([0.03, 0.01]), [0.03, 0.02])
        self.assertEqual(st.holm([0.6, 0.7]), [1.0, 1.0])
        self.assertEqual(st.holm([0.0]), [0.0])

    def test_benjamini_hochberg_matches_hand_computation(self):
        self.assertEqual(st.benjamini_hochberg([0.01, 0.03]), [0.02, 0.03])
        self.assertEqual(st.benjamini_hochberg([0.04, 0.02, 0.03]), [0.04, 0.04, 0.04])
        self.assertEqual(st.benjamini_hochberg([0.5]), [0.5])
        self.assertEqual(st.benjamini_hochberg([2.0]), [1.0])

    def test_solve_normal_recovers_exact_coefficients(self):
        beta = st.solve_normal([3.0, 6.0, 14.0], [12.0, 28.0], 2)
        self.assertAlmostEqual(beta[0], 0.0, places=10)
        self.assertAlmostEqual(beta[1], 2.0, places=10)

    def test_solve_normal_detects_rank_deficiency(self):
        with self.assertRaises(st.RankDeficient):
            st.solve_normal([3.0, 6.0, 12.0], [12.0, 24.0], 2)
        with self.assertRaises(st.RankDeficient):
            st.solve_normal([0.0, 0.0, 0.0], [0.0, 0.0], 2)

    def test_pair_indices_cover_upper_triangle(self):
        p = 4
        pairs = st.pair_indices(p)
        self.assertEqual(len(pairs), p * (p + 1) // 2)
        self.assertEqual(sorted(k for _, _, k in pairs), list(range(p * (p + 1) // 2)))
        self.assertTrue(all(i <= j for i, j, _ in pairs))

    def test_draw_plan_spans_exactly_n_dates(self):
        self.assertEqual(st.draw_plan(91, 1), (91, 0))
        self.assertEqual(st.draw_plan(91, 2), (45, 1))
        self.assertEqual(st.draw_plan(91, 7), (13, 0))
        for n_dates, block_days in ((91, 1), (91, 2), (91, 7), (10, 3), (12, 3), (12, 4)):
            full, remainder = st.draw_plan(n_dates, block_days)
            lengths = [block_days] * full + ([remainder] if remainder else [])
            self.assertEqual(sum(lengths), n_dates)
            self.assertLessEqual(max(lengths, default=0), block_days)

    def test_partition_chunks_are_non_overlapping_and_anchored(self):
        dates = study_dates()
        for block_days, expected in ((1, 91), (2, 46), (7, 13)):
            chunks = st.partition_chunks(dates, block_days)
            self.assertEqual(len(chunks), expected)
            self.assertEqual(sorted(day for chunk in chunks for day in chunk), dates)
        self.assertEqual([len(chunk) for chunk in st.partition_chunks(dates, 2)], [2] * 45 + [1])
        self.assertEqual([len(chunk) for chunk in st.partition_chunks(dates, 7)], [7] * 13)

    def test_inference_label_classification(self):
        self.assertEqual(st.inference_label(True, True), "inferential")
        self.assertEqual(st.inference_label(True, False), "exploratory")
        self.assertEqual(st.inference_label(False, True), "descriptive_only")
        self.assertEqual(st.inference_label(False, False), "descriptive_only")

    def test_enumerate_fits_exposes_weather_cases(self):
        fits = st.enumerate_fits()
        self.assertEqual(len(fits), 31)
        self.assertEqual(len({f["fit_id"] for f in fits}), 31)
        by_id = {f["fit_id"]: f for f in fits}
        self.assertEqual([f["fit_id"] for f in fits[:3]],
                         ["H1_pooled_log1p_b1_pairwise_complete", "H1_cmt8_log1p_b1_pairwise_complete",
                          "H1_oceanpark_log1p_b1_pairwise_complete"])
        self.assertEqual(sum(f["role"] == "secondary" for f in fits), 5)
        self.assertEqual(sum(f["role"] == "primary" for f in fits), 7)
        for fit_id in ("H1_pooled_log1p_b1_complete_weather", "H2_pooled_log1p_b1_complete_weather",
                       "S_temperature_2m_pooled_log1p_b1_complete_weather",
                       "S_precipitation_pooled_log1p_b1_complete_weather",
                       "S_surface_pressure_pooled_log1p_b1_complete_weather",
                       "S_cloud_cover_pooled_log1p_b1_complete_weather",
                       "S_shortwave_radiation_pooled_log1p_b1_complete_weather"):
            self.assertEqual(by_id[fit_id]["weather_case"], "complete_weather")
            self.assertEqual(by_id[fit_id]["role"], "sensitivity")
        self.assertEqual(by_id["H3_shared_log1p_b1"]["weather_case"], "not_applicable")
        self.assertTrue(all(f["weather_case"] in st.WEATHER_CASES for f in fits))


class ExtremeReviewTests(unittest.TestCase):
    def accepted(self, values):
        return [{"location": "cmt8", "end": f"end{i}", "pm25": value} for i, value in enumerate(values)]

    def test_fence_flags_only_extreme_values(self):
        fences, flagged = st.extreme_review(self.accepted([10.0] * 99 + [100.0]))
        self.assertEqual(fences["cmt8"]["fence"], 10.0)
        self.assertEqual(fences["cmt8"]["flagged_hours"], 1)
        self.assertEqual(flagged, {("cmt8", "end99")})

    def test_no_flags_without_extremes(self):
        fences, flagged = st.extreme_review(self.accepted([float(v) for v in range(1, 101)]))
        self.assertEqual(fences["cmt8"]["flagged_hours"], 0)
        self.assertEqual(flagged, set())


class FitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = synthetic_bundle()
        cls.counts = counts_from_bundle(cls.bundle)
        with patch.object(st, "FROZEN_COUNTS", cls.counts):
            cls.analysis = st.build_analysis(cls.bundle)
        cls.date_index = {day: i for i, day in enumerate(cls.analysis["dates"])}
        cls.fences, cls.flagged = st.extreme_review(cls.analysis["accepted"])

    def spec(self, fit_id="H1_pooled_raw_b1_pairwise_complete"):
        return next(f for f in st.enumerate_fits() if f["fit_id"] == fit_id)

    def fit(self, fit_id="H1_pooled_raw_b1_pairwise_complete", seed=st.SEED, replicates=50, **overrides):
        spec = {**self.spec(fit_id), **overrides}
        return st.fit_model(random.Random(seed), spec, self.analysis, self.date_index, self.flagged), spec

    def test_frozen_counts_match_synthetic(self):
        self.assertEqual(self.analysis["reconciliation"], self.counts)

    def test_exact_linear_effect_recovered(self):
        result, _ = self.fit()
        _, eligible, _ = st.fit_rows(self.analysis, self.spec(), self.flagged)
        _, sd = st.mean_stdev([r["exposure"]["wind_speed_10m"] for r in eligible])
        self.assertAlmostEqual(result["estimate"], -3 * sd, delta=0.15)
        self.assertTrue(result["gate_pass"])
        self.assertEqual(result["inference"], "exploratory")
        self.assertLess(result["p_value"], 0.05)
        self.assertLessEqual(result["ci_low"], result["estimate"])
        self.assertLessEqual(result["estimate"], result["ci_high"])
        self.assertEqual(result["n"], 91 * 48 - absent_hours())
        self.assertEqual(result["nonempty_independent_blocks"], 91)
        self.assertEqual(result["eligible_independent_blocks"], 91)
        self.assertEqual(result["candidate_windows"], 91)
        self.assertEqual(result["sampled_dates_per_replicate"], 91)

    def test_gate_uses_independent_partitions_not_moving_windows(self):
        result, _ = self.fit("H1_pooled_log1p_b1_pairwise_complete", block_days=2)
        self.assertEqual(result["candidate_windows"], 90)
        self.assertEqual(result["nonempty_independent_blocks"], 46)
        self.assertEqual(result["eligible_independent_blocks"], 46)
        self.assertTrue(result["gate_pass"])
        with patch.object(st, "GATE_MIN_ELIGIBLE", 50):
            failed, _ = self.fit("H1_pooled_log1p_b1_pairwise_complete", block_days=2)
        self.assertEqual(failed["candidate_windows"], 90)
        self.assertGreater(failed["candidate_windows"], 50)
        self.assertLess(failed["eligible_independent_blocks"], 50)
        self.assertFalse(failed["gate_pass"])
        self.assertEqual(failed["inference"], "descriptive_only")

    def test_exact_bootstrap_length_with_two_day_blocks(self):
        result, _ = self.fit("H1_pooled_log1p_b1_pairwise_complete", block_days=2)
        self.assertEqual(result["full_draws"], 45)
        self.assertEqual(result["remainder_draws"], 1)
        self.assertEqual(result["draws_per_replicate"], 46)
        self.assertEqual(result["sampled_dates_per_replicate"], 91)
        seven, _ = self.fit("H1_pooled_log1p_b1_pairwise_complete", block_days=7)
        self.assertEqual((seven["full_draws"], seven["remainder_draws"], seven["draws_per_replicate"]), (13, 0, 13))
        self.assertEqual(seven["sampled_dates_per_replicate"], 91)

    def test_bootstrap_deterministic_for_fixed_seed(self):
        first, _ = self.fit(seed=123)
        second, _ = self.fit(seed=123)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        other, _ = self.fit(seed=124)
        self.assertNotEqual(first["bootstrap_mean"], other["bootstrap_mean"])

    def test_gate_failure_reports_descriptive_only(self):
        with patch.object(st, "GATE_MIN_NONEMPTY", 200):
            result, _ = self.fit()
        self.assertFalse(result["gate_pass"])
        self.assertEqual(result["inference"], "descriptive_only")
        self.assertNotIn("p_value", result)
        self.assertNotIn("ci_low", result)

    def test_missing_hours_are_not_imputed(self):
        result, _ = self.fit()
        self.assertEqual(result["coverage"]["absent_hours"], absent_hours())
        self.assertEqual(result["coverage"]["accepted_hours"], 91 * 48 - absent_hours())
        self.assertEqual(result["n"], result["coverage"]["accepted_hours"])

    def test_block_length_changes_partitions_and_gate(self):
        one, _ = self.fit("H1_pooled_log1p_b1_pairwise_complete", block_days=1)
        seven, _ = self.fit("H1_pooled_log1p_b1_pairwise_complete", block_days=7)
        self.assertEqual(one["draws_per_replicate"], 91)
        self.assertEqual(seven["draws_per_replicate"], 13)
        self.assertEqual(one["eligible_independent_blocks"], 91)
        self.assertEqual(seven["eligible_independent_blocks"], 13)
        self.assertTrue(one["gate_pass"])
        self.assertFalse(seven["gate_pass"])
        self.assertEqual(seven["inference"], "descriptive_only")

    def test_full_sample_rank_deficiency_stops(self):
        analysis = {"rows": self.analysis["rows"][:3], "dates": self.analysis["dates"],
                    "shared": self.analysis["shared"], "accepted": self.analysis["accepted"]}
        with self.assertRaises(ValueError):
            st.fit_model(random.Random(1), self.spec(), analysis, self.date_index, set())

    def test_constant_exposure_stops(self):
        rows = [{**row, "exposure": {**row["exposure"], "wind_speed_10m": 5.0}}
                for row in self.analysis["rows"][:200]]
        analysis = {"rows": rows, "dates": self.analysis["dates"], "shared": self.analysis["shared"],
                    "accepted": rows}
        with self.assertRaises(ValueError):
            st.fit_model(random.Random(1), self.spec(), analysis, self.date_index, set())

    def test_extreme_exclusion_removes_only_flagged_rows(self):
        result, _ = self.fit("H1_pooled_log1p_b1_pairwise_complete_excl_extreme")
        base, _ = self.fit("H1_pooled_log1p_b1_pairwise_complete")
        self.assertGreater(self.flagged, set())
        self.assertLess(result["n"], base["n"])
        self.assertGreater(result["coverage"]["extreme_flagged_hours"], 0)
        self.assertEqual(result["coverage"]["accepted_hours"] + result["coverage"]["extreme_flagged_hours"],
                         base["coverage"]["accepted_hours"])

    def test_complete_weather_excludes_rows_missing_unrelated_variables(self):
        pairwise, _ = self.fit("H1_pooled_log1p_b1_pairwise_complete")
        complete, _ = self.fit("H1_pooled_log1p_b1_complete_weather")
        self.assertEqual(pairwise["n"], self.counts["accepted_rows"])
        self.assertLess(complete["n"], pairwise["n"])
        self.assertEqual(complete["n"], self.counts["complete_weather_cmt8"] + self.counts["complete_weather_oceanpark"])
        self.assertEqual(pairwise["coverage"]["weather_complete_hours"],
                         self.counts["complete_weather_cmt8"] + self.counts["complete_weather_oceanpark"])
        self.assertEqual(pairwise["weather_case"], "pairwise_complete")
        self.assertEqual(complete["weather_case"], "complete_weather")

    def test_design_drops_empty_levels(self):
        rows = [r for r in self.analysis["rows"] if r["hour"] <= 10]
        analysis = {"rows": rows, "dates": self.analysis["dates"], "shared": self.analysis["shared"],
                    "accepted": [r for r in rows if r["pm25"] is not None]}
        _, eligible, _ = st.fit_rows(analysis, self.spec(), set())
        design_rows, columns, p, _ = st.build_design(eligible, self.spec(), self.date_index)
        self.assertEqual(p, 1 + 1 + 10 + 6 + 1 + 1)
        self.assertNotIn("local_hour_11", columns)
        self.assertEqual(len(design_rows), len(eligible))

    def test_prefix_grams_window_equals_direct_sum(self):
        _, eligible, _ = st.fit_rows(self.analysis, self.spec(), self.flagged)
        design_rows, _, p, _ = st.build_design(eligible, self.spec(), self.date_index)
        size = p * (p + 1) // 2
        grams = {day: ([0.0] * size, [0.0] * p, 0) for day in self.analysis["dates"]}
        for (y, x), row in zip(design_rows, eligible):
            g, g_y, count = grams[row["local_date"]]
            for i, j, k in st.pair_indices(p):
                g[k] += x[i] * x[j]
            for i in range(p):
                g_y[i] += x[i] * y
            grams[row["local_date"]] = (g, g_y, count + 1)
        prefix = st.prefix_grams(grams, self.analysis["dates"], p)
        direct = ([0.0] * size, [0.0] * p, 0)
        for day in self.analysis["dates"][10:17]:
            g, g_y, count = grams[day]
            direct = ([a + b for a, b in zip(direct[0], g)], [a + b for a, b in zip(direct[1], g_y)],
                      direct[2] + count)
        high, low = prefix[17], prefix[10]
        merged = ([a - b for a, b in zip(high[0], low[0])], [a - b for a, b in zip(high[1], low[1])],
                  high[2] - low[2])
        self.assertEqual(merged[2], direct[2])
        for a, b in zip(merged[0], direct[0]):
            self.assertAlmostEqual(a, b, places=6)


class PipelineTests(unittest.TestCase):
    def run_pipeline(self, replicates=12):
        bundle = synthetic_bundle(hours=(0, 1))
        with patch.object(st, "SECONDARY_EXPOSURES", ("temperature_2m",)), \
             patch.object(st, "FROZEN_COUNTS", counts_from_bundle(bundle)), \
             patch.object(st, "REPLICATES", replicates):
            return st.compute_statistics(bundle, "0" * 64)

    def test_end_to_end_pipeline_is_deterministic_and_wired(self):
        first = self.run_pipeline()
        second = self.run_pipeline()
        self.assertEqual(digest(first), digest(second))
        self.assertEqual(first["manifest"]["reconciliation"], counts_from_bundle(synthetic_bundle(hours=(0, 1))))
        self.assertEqual(len(first["results"]), 23)
        self.assertIn("H1_pooled_log1p_b1_pairwise_complete", first["manifest"]["formulas"])
        self.assertEqual(first["manifest"]["adjustments"]["primary"]["method"], "Holm")
        self.assertEqual(first["manifest"]["adjustments"]["secondary"]["method"], "Benjamini-Hochberg")
        self.assertEqual(len(first["manifest"]["weather_variables"]), 9)
        self.assertEqual(len(first["manifest"]["pairwise_correlations"]), 28)
        self.assertTrue(all(fit["sampled_dates_per_replicate"] == 91 for fit in first["results"]))
        self.assertTrue(all(fit["sampled_dates_per_replicate"] != 92 for fit in first["results"]))
        primary = next(f for f in first["results"] if f["fit_id"] == "H1_pooled_log1p_b1_pairwise_complete")
        self.assertEqual(primary["inference"], "inferential")
        self.assertIn("p_value_adjusted", primary)

    def test_inference_labels_follow_adjustment_rule(self):
        result = self.run_pipeline()
        by_id = {fit["fit_id"]: fit for fit in result["results"]}
        for fit_id in PRIMARY_IDS + ("S_temperature_2m_pooled_log1p_b1_pairwise_complete",):
            self.assertEqual(by_id[fit_id]["inference"], "inferential", fit_id)
            self.assertIn("p_value_adjusted", by_id[fit_id])
        for fit_id in ("H1_cmt8_log1p_b1_pairwise_complete", "H1_oceanpark_log1p_b1_pairwise_complete",
                       "H3_shared_log1p_b1", "H1_pooled_raw_b1_pairwise_complete",
                       "H2_pooled_raw_b1_pairwise_complete", "H3_shared_raw_b1",
                       "H1_pooled_log1p_b2_pairwise_complete", "H2_pooled_log1p_b2_pairwise_complete",
                       "H1_pooled_log1p_b1_complete_weather", "H2_pooled_log1p_b1_complete_weather",
                       "S_temperature_2m_pooled_log1p_b1_complete_weather",
                       "H1_pooled_log1p_b1_pairwise_complete_excl_extreme",
                       "H2_pooled_log1p_b1_pairwise_complete_excl_extreme", "H3_shared_log1p_b1_excl_extreme"):
            self.assertEqual(by_id[fit_id]["inference"], "exploratory", fit_id)
            self.assertNotIn("p_value_adjusted", by_id[fit_id])
        for fit_id in ("H1_pooled_log1p_b7_pairwise_complete", "H2_pooled_log1p_b7_pairwise_complete",
                       "H3_shared_log1p_b7"):
            self.assertEqual(by_id[fit_id]["inference"], "descriptive_only", fit_id)
            self.assertNotIn("p_value", by_id[fit_id])
        adjusted = {fit["fit_id"] for fit in result["results"] if fit["inference"] == "inferential"}
        self.assertEqual(adjusted, set(PRIMARY_IDS) | {"S_temperature_2m_pooled_log1p_b1_pairwise_complete"})

    def test_pairwise_correlations_are_descriptive_only(self):
        result = self.run_pipeline()
        correlations = result["manifest"]["pairwise_correlations"]
        self.assertEqual(len(correlations), 28)
        for record in correlations:
            self.assertIn(record["weather_case"], ("pairwise_complete", "complete_weather"))
            self.assertEqual(record["response"], "pm25")
            self.assertGreater(record["n"], 0)
            for forbidden in ("p_value", "ci_low", "ci_high", "inference", "gate_pass", "adjustment"):
                self.assertNotIn(forbidden, record)
        exposures = {record["exposure"] for record in correlations}
        self.assertNotIn("wind_direction_10m", exposures)
        self.assertNotIn("apparent_temperature", exposures)
        self.assertEqual(len(exposures), 7)

    def test_reconciliation_mismatch_stops(self):
        bundle = synthetic_bundle(hours=(0, 1))
        counts = counts_from_bundle(bundle)
        counts["accepted_rows"] += 1
        with patch.object(st, "FROZEN_COUNTS", counts), self.assertRaises(ValueError):
            st.compute_statistics(bundle, "0" * 64)

    def test_load_bundle_rejects_tampered_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps(synthetic_bundle(days=14)), encoding="utf-8")
            with self.assertRaises(ValueError):
                st.load_bundle(path)


if __name__ == "__main__":
    unittest.main()
