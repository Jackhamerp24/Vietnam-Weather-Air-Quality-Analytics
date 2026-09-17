"""Offline tests for scripts/screen_openaq_typesafe.py.

No network, no credential and no live inventory: the transport is injected, so
the whole orchestration (change detection, chunking, routing, state update) is
exercised deterministically. CI runs this file credential-free.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import screen_openaq_typesafe as mod  # noqa: E402


def record(location_id, name, provider="AirGradient", licence=41,
           lat=10.0, lon=106.0, first="2025-01-01T00:00:00Z",
           last="2025-06-01T00:00:00Z"):
    return {
        "id": location_id,
        "name": name,
        "locality": None,
        "provider": {"id": 66, "name": provider},
        "owner": {"id": 1, "name": "Unknown Governmental Organization"},
        "isMonitor": False,
        "isMobile": False,
        "instruments": [{"id": 1, "name": "Unknown AirGradient Sensor"}],
        "sensors": [{"id": 2, "name": "pm25", "parameter": {
            "id": 2, "name": "pm25", "units": "µg/m³", "displayName": "PM2.5"}}],
        "licenses": ([{"id": licence, "name": "CC BY 4.0"}] if licence else None),
        "datetimeFirst": {"utc": first} if first else None,
        "datetimeLast": {"utc": last} if last else None,
        "coordinates": {"latitude": lat, "longitude": lon},
    }


def stub_transport(location_choice="outdoor_ambient", location_conf=0.9,
                   pair_choice="leave_unlinked", pair_conf=0.9, calls=None):
    def transport(payload):
        answers = {}
        for question_id in payload["questions"]:
            if question_id.endswith("_siting"):
                choice, confidence = location_choice, location_conf
            else:
                choice, confidence = pair_choice, pair_conf
            answers[question_id] = {
                "type": "choice", "choice": choice,
                "probabilities": {choice: confidence}, "confidence": confidence,
            }
        if calls is not None:
            calls.append(payload)
        return {"answers": answers,
                "usage": {"input_tokens": 10, "output_tokens": 2}}, {"status": 200}
    return transport


class FingerprintTests(unittest.TestCase):
    def test_fingerprint_is_stable(self):
        item = mod.project_location(0, record(1, "CMT8"))
        again = mod.project_location(0, record(1, "CMT8"))
        self.assertEqual(mod.location_fingerprint(item), mod.location_fingerprint(again))

    def test_semantic_change_alters_fingerprint(self):
        base = mod.project_location(0, record(1, "CMT8"))
        renamed = mod.project_location(0, record(1, "CMT8 outdoor"))
        relicensed = mod.project_location(0, record(1, "CMT8", licence=None))
        moved = mod.project_location(0, record(1, "CMT8", lat=11.0))
        for variant in (renamed, relicensed, moved):
            self.assertNotEqual(mod.location_fingerprint(base),
                                mod.location_fingerprint(variant))

    def test_date_only_change_does_not_rescreen_siting(self):
        """Placement cannot change because a record's dates moved."""
        base = mod.project_location(0, record(1, "CMT8"))
        redated = mod.project_location(0, record(1, "CMT8", last="2026-01-01T00:00:00Z"))
        self.assertEqual(mod.location_fingerprint(base),
                         mod.location_fingerprint(redated))

    def test_pair_fingerprint_notices_period_change(self):
        left = mod.project_location(0, record(1, "Ngoai phong", provider="HabitatMap", licence=None))
        right = mod.project_location(1, record(2, "Ngoai phong", provider="HabitatMap", licence=None))
        pair = mod.candidate_pairs([left, right])[0]
        moved = mod.project_location(1, record(2, "Ngoai phong", provider="HabitatMap",
                                                licence=None, last="2025-07-01T00:00:00Z"))
        pair2 = mod.candidate_pairs([left, moved])[0]
        self.assertNotEqual(mod.pair_fingerprint(pair), mod.pair_fingerprint(pair2))

    def test_pair_fingerprint_tolerates_missing_periods(self):
        """Real inventory records exist with no datetimeFirst/Last (SPARTAN, outdoor)."""
        left = mod.project_location(0, record(1, "SPARTAN", provider="Spartan",
                                              licence=None, first=None, last=None))
        right = mod.project_location(1, record(2, "SPARTAN", provider="SPARTAN Network",
                                               licence=None, first="2019-11-28T00:00:00Z",
                                               last="2020-06-23T00:00:00Z"))
        pairs = mod.candidate_pairs([left, right])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(len(mod.pair_fingerprint(pairs[0])), 64)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.records = [record(1, "CMT8"), record(2, "OceanPark"), record(3, "Care Centre")]
        self.projected = [mod.project_location(i, r) for i, r in enumerate(self.records)]
        self.pairs = mod.candidate_pairs(self.projected)

    def test_first_run_screens_everything(self):
        todo_locations, todo_pairs = mod.select_unscreened(None, self.projected, self.pairs)
        self.assertEqual(len(todo_locations), 3)
        self.assertEqual(todo_pairs, [])

    def test_unchanged_second_run_screens_nothing(self):
        transport = stub_transport()
        _, state = mod.run_screening({"locations": self.records}, None, transport,
                                     capture_date="2026-09-07")
        todo_locations, todo_pairs = mod.select_unscreened(state, self.projected, self.pairs)
        self.assertEqual(todo_locations, [])
        self.assertEqual(todo_pairs, [])

    def test_only_changed_location_is_rescreened(self):
        transport = stub_transport()
        _, state = mod.run_screening({"locations": self.records}, None, transport,
                                     capture_date="2026-09-07")
        changed = [record(1, "CMT8"), record(2, "OceanPark renamed"), record(3, "Care Centre")]
        projected = [mod.project_location(i, r) for i, r in enumerate(changed)]
        todo_locations, _ = mod.select_unscreened(state, projected, [])
        self.assertEqual([item["id"] for item in todo_locations], [2])

    def test_pair_asked_only_when_a_member_is_dirty(self):
        dupes = [record(1, "Ngoai phong", provider="HabitatMap", licence=None),
                 record(2, "Ngoai phong", provider="HabitatMap", licence=None),
                 record(3, "CMT8")]
        projected = [mod.project_location(i, r) for i, r in enumerate(dupes)]
        pairs = mod.candidate_pairs(projected)
        self.assertEqual(len(pairs), 1)
        transport = stub_transport()
        _, state = mod.run_screening({"locations": dupes}, None, transport,
                                     capture_date="2026-09-07")
        # Nothing changed: the pair is not re-asked.
        _, todo_pairs = mod.select_unscreened(state, projected, pairs)
        self.assertEqual(todo_pairs, [])
        # Change one member's name: the pair is re-asked.
        edited = [record(1, "Ngoai phong 2", provider="HabitatMap", licence=None),
                  record(2, "Ngoai phong", provider="HabitatMap", licence=None),
                  record(3, "CMT8")]
        projected_edited = [mod.project_location(i, r) for i, r in enumerate(edited)]
        pairs_edited = mod.candidate_pairs(projected_edited, threshold=0.8)
        _, todo_pairs = mod.select_unscreened(state, projected_edited, pairs_edited)
        self.assertEqual(len(todo_pairs), 1)


class RequestPlanningTests(unittest.TestCase):
    def setUp(self):
        self.projected = [mod.project_location(i, record(i + 1, f"Site {i}"))
                          for i in range(5)]

    def test_question_paths_are_chunk_local(self):
        requests = mod.build_requests(self.projected, [], "2026-09-07", 2)
        self.assertEqual(len(requests), 3)
        first = requests[0]["payload"]["questions"]
        second = requests[1]["payload"]["questions"]
        self.assertIn("`locations[0]`", first["loc0_siting"]["instructions"])
        self.assertIn("`locations[1]`", first["loc1_siting"]["instructions"])
        self.assertIn("`locations[0]`", second["loc2_siting"]["instructions"])
        self.assertNotIn("`locations[2]`", second["loc2_siting"]["instructions"])

    def test_state_entries_carry_inventory_index_not_position(self):
        chunk = self.projected[2:4]
        entries = mod.state_locations(chunk)
        self.assertNotIn("index", entries[0])
        self.assertEqual([e["inventory_index"] for e in entries], [2, 3])

    def test_only_siting_and_identity_questions_are_asked(self):
        """Instrument class and freshness are deterministic; they must not return."""
        requests = mod.build_requests(self.projected, mod.candidate_pairs(
            [mod.project_location(0, record(1, "Ngoai phong", provider="HabitatMap", licence=None)),
             mod.project_location(1, record(2, "Ngoai phong", provider="HabitatMap", licence=None))],
        ), "2026-09-07", 20)
        suffixes = {qid.split("_", 1)[1] for r in requests for qid in r["payload"]["questions"]}
        self.assertEqual(suffixes, {"siting", "relationship"})

    def test_dry_run_plans_without_calling_transport(self):
        calls = []
        report, state = mod.run_screening(
            {"locations": [record(1, "CMT8")]}, None,
            lambda payload: calls.append(payload),  # would fail the assertions below
            capture_date="2026-09-07", dry_run=True)
        self.assertEqual(calls, [])
        self.assertIsNone(state)
        self.assertEqual(report["screened_location_count"], 1)
        self.assertEqual(len(report["planned_requests"]), 1)
        self.assertEqual(report["planned_requests"][0]["questions"], 1)


class RoutingTests(unittest.TestCase):
    def test_identity_always_needs_a_human(self):
        answers = {"pair0_relationship": {"type": "choice", "choice": "leave_unlinked",
                                          "probabilities": {"leave_unlinked": 0.98},
                                          "confidence": 0.98}}
        accepted, review = mod.route(answers, 0.75)
        self.assertEqual(accepted, [])
        self.assertEqual(len(review), 1)
        self.assertIn("human", review[0]["reason"])

    def test_placement_is_never_auto_accepted(self):
        """Level-2 verification: 4 of 5 auto-accepted placement calls were wrong."""
        answers = {
            "loc1_siting": {"type": "choice", "choice": "outdoor_ambient",
                            "probabilities": {"outdoor_ambient": 0.99}, "confidence": 0.99},
            "loc2_siting": {"type": "choice", "choice": "outdoor_ambient",
                            "probabilities": {"outdoor_ambient": 0.25}, "confidence": 0.25},
        }
        accepted, review = mod.route(answers, 0.75)
        self.assertEqual(accepted, [])
        self.assertEqual([r["question"] for r in review], ["loc1_siting", "loc2_siting"])
        self.assertIn("never auto-accepted", review[0]["reason"])

    def test_high_confidence_identity_still_needs_a_human(self):
        accepted, review = mod.route(
            {"pair0_relationship": {"type": "choice", "choice": "merge",
                                    "probabilities": {"merge": 0.97}, "confidence": 0.97}}, 0.75)
        self.assertEqual(accepted, [])
        self.assertEqual(review[0]["reason"], "identity decisions always need a human")

    def test_missing_confidence_is_queued_not_accepted(self):
        accepted, review = mod.route(
            {"loc1_siting": {"type": "choice", "choice": "siting_unknown"}}, 0.75)
        self.assertEqual(accepted, [])
        self.assertEqual(len(review), 1)


class OrchestrationTests(unittest.TestCase):
    def test_state_records_fingerprints_and_usage_is_aggregated(self):
        # Dissimilar names keep this an isolated chunking test: similar names
        # would legitimately add an identity request.
        records = [record(i + 1, name) for i, name in enumerate(
            ["Alpha", "Bravo", "Charlie", "Delta", "Echo"])]
        report, state = mod.run_screening(
            {"locations": records}, None, stub_transport(),
            capture_date="2026-09-07", chunk_size=2)
        self.assertEqual(len(report["requests"]), 3)
        self.assertEqual(report["usage"]["input_tokens"], 30)
        self.assertEqual(len(state["locations"]), 5)
        for entry in state["locations"].values():
            self.assertEqual(len(entry["fingerprint"]), 64)
            self.assertNotIn("decided", entry)
        self.assertEqual(state["state_version"], mod.STATE_VERSION)

    def test_state_update_is_incremental_across_runs(self):
        records = [record(1, "CMT8"), record(2, "OceanPark")]
        _, first = mod.run_screening({"locations": records}, None, stub_transport(),
                                     capture_date="2026-09-07")
        calls = []
        _, second = mod.run_screening({"locations": records}, first,
                                      stub_transport(calls=calls),
                                      capture_date="2026-09-08")
        self.assertEqual(calls, [])
        self.assertEqual(second["locations"], first["locations"])
        self.assertEqual(len(second["locations"]), 2)

    def test_identity_answer_is_stored_against_the_pair_key(self):
        dupes = [record(1, "Ngoai phong", provider="HabitatMap", licence=None),
                 record(2, "Ngoai phong", provider="HabitatMap", licence=None)]
        report, state = mod.run_screening(
            {"locations": dupes}, None,
            stub_transport(pair_choice="merge", pair_conf=0.95),
            capture_date="2026-09-07")
        key = mod.pair_key(1, 2)
        self.assertIn(key, state["pairs"])
        self.assertEqual(state["pairs"][key]["relationship"]["choice"], "merge")
        self.assertIsNone(state["pairs"][key]["decided"])
        queued = [entry["question"] for entry in report["review_queue"]]
        self.assertIn("pair0_relationship", queued)
        self.assertEqual(report["accepted"], [])


class LabelScoringTests(unittest.TestCase):
    def test_agreement_and_disagreement_are_reported(self):
        state = {
            "locations": {"1": {"siting": {"choice": "outdoor_ambient", "confidence": 0.9}},
                          "2": {"siting": {"choice": "siting_unknown", "confidence": 0.4}}},
            "pairs": {"1|2": {"relationship": {"choice": "leave_unlinked", "confidence": 0.97}}},
        }
        labels = {"locations": {"1": {"siting": "outdoor_ambient"},
                                "2": {"siting": "sheltered_or_indoor"}},
                  "pairs": {"1|2": "leave_unlinked"}}
        result = mod.score_labels(labels, state)
        self.assertEqual(result["n"], 3)
        self.assertEqual(result["agreement"], 2)
        self.assertEqual([c["id"] for c in result["checks"] if not c["agrees"]], ["2"])

    def test_filled_sheet_scores_without_hand_conversion(self):
        """The emitted sheet form must feed straight back into --labels."""
        sheet = {
            "locations": [{"id": 1, "your_siting_label": "outdoor_ambient"},
                          {"id": 2, "your_siting_label": None}],
            "pairs": [{"key": "1|2", "your_identity_label": "merge"}],
        }
        state = {
            "locations": {"1": {"siting": {"choice": "outdoor_ambient", "confidence": 0.9}},
                          "2": {"siting": {"choice": "siting_unknown", "confidence": 0.8}}},
            "pairs": {"1|2": {"relationship": {"choice": "leave_unlinked", "confidence": 0.9}}},
        }
        result = mod.score_labels(sheet, state)
        self.assertEqual(result["n"], 2)
        self.assertEqual(result["agreement"], 1)
        self.assertEqual(result["disagreements"][0]["id"], "1|2")

    def test_rule_decided_outcomes_get_their_own_bucket(self):
        """A rule outcome is not a low-confidence model answer."""
        state = {
            "locations": {"6123215": {"siting": {
                "type": "rule", "choice": "outdoor_ambient", "confidence": None,
                "resolved_by": "airgradient_open_air_is_outdoor",
                "source": "https://www.airgradient.com/outdoor/"}}},
            "pairs": {},
        }
        labels = {"locations": {"6123215": {"siting": "outdoor_ambient"}}}
        result = mod.score_labels(labels, state)
        self.assertEqual(result["by_bucket"]["resolved_by_rule"]["n"], 1)
        self.assertEqual(result["by_bucket"]["resolved_by_rule"]["rate"], 1.0)
        self.assertNotIn("review_low_confidence", result["by_bucket"])
        self.assertEqual(result["checks"][0]["resolved_by"],
                         "airgradient_open_air_is_outdoor")

    def test_buckets_separate_auto_accepted_from_review(self):
        """The decisive number: is the acted-on bucket better than the review bucket?"""
        state = {
            "locations": {"1": {"siting": {"choice": "outdoor_ambient", "confidence": 0.9}},
                          "2": {"siting": {"choice": "siting_unknown", "confidence": 0.4}}},
            "pairs": {"1|2": {"relationship": {"choice": "leave_unlinked", "confidence": 0.97}}},
        }
        labels = {"locations": {"1": {"siting": "outdoor_ambient"},
                                "2": {"siting": "sheltered_or_indoor"}},
                  "pairs": {"1|2": "leave_unlinked"}}
        result = mod.score_labels(labels, state, review_threshold=0.75)
        buckets = result["by_bucket"]
        self.assertEqual(buckets["auto_accepted"]["n"], 1)
        self.assertEqual(buckets["auto_accepted"]["rate"], 1.0)
        self.assertEqual(buckets["review_low_confidence"]["n"], 1)
        self.assertEqual(buckets["review_low_confidence"]["rate"], 0.0)
        self.assertEqual(buckets["review_identity"]["n"], 1)

    def test_confusion_and_per_class_are_reported(self):
        state = {
            "locations": {"1": {"siting": {"choice": "outdoor_ambient", "confidence": 0.9}},
                          "2": {"siting": {"choice": "outdoor_ambient", "confidence": 0.9}},
                          "3": {"siting": {"choice": "siting_unknown", "confidence": 0.8}}},
            "pairs": {},
        }
        labels = {"locations": {"1": {"siting": "outdoor_ambient"},
                                "2": {"siting": "sheltered_or_indoor"},
                                "3": {"siting": "siting_unknown"}}}
        result = mod.score_labels(labels, state)
        self.assertEqual(result["confusion"]["sheltered_or_indoor"]["outdoor_ambient"], 1)
        self.assertEqual(result["per_class"]["outdoor_ambient"]["support"], 1)
        self.assertEqual(result["per_class"]["outdoor_ambient"]["recall"], 1.0)
        # It predicted outdoor twice but was right once; support and precision differ.
        self.assertEqual(result["per_class"]["outdoor_ambient"]["precision"], 0.5)
        self.assertEqual(result["unlabelled_locations"], 0)

    def test_wilson_interval_widens_for_small_n(self):
        small = mod.wilson_interval(9, 10)
        large = mod.wilson_interval(90, 100)
        self.assertLess(large["high"] - large["low"], small["high"] - small["low"])
        self.assertLessEqual(small["low"], 0.9)
        self.assertGreaterEqual(small["high"], 0.9)

    def test_empty_interval_is_null_not_zero(self):
        self.assertEqual(mod.wilson_interval(0, 0), {"low": None, "high": None})

    def test_label_sheet_carries_no_model_answer(self):
        """Blinding is the difference between a measurement and a rubber stamp."""
        dupes = [record(1, "Ngoai phong", provider="HabitatMap", licence=None),
                 record(2, "Ngoai phong", provider="HabitatMap", licence=None)]
        projected = [mod.project_location(i, r) for i, r in enumerate(dupes)]
        sheet = mod.label_sheet(projected, mod.candidate_pairs(projected))
        blob = json.dumps(sheet, ensure_ascii=False)
        self.assertNotIn('"choice"', blob)
        self.assertNotIn("confidence", blob)
        self.assertIsNone(sheet["locations"][0]["your_siting_label"])
        self.assertIsNone(sheet["pairs"][0]["your_identity_label"])

    def test_emit_labels_writes_sheet_without_a_credential(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        inventory = Path(tmp.name) / "inventory.json"
        inventory.write_text(json.dumps({"locations": [record(1, "CMT8")]}), encoding="utf-8")
        sheet_path = Path(tmp.name) / "sheet.json"
        code = mod.main(["--inventory", str(inventory),
                         "--emit-labels", str(sheet_path)])
        self.assertEqual(code, 0)
        sheet = json.loads(sheet_path.read_text(encoding="utf-8"))
        self.assertEqual(len(sheet["locations"]), 1)
        self.assertEqual(sheet["locations"][0]["your_siting_label"], None)

    def test_output_is_required_unless_emitting_labels(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        inventory = Path(tmp.name) / "inventory.json"
        inventory.write_text(json.dumps({"locations": []}), encoding="utf-8")
        with self.assertRaises(SystemExit):
            mod.main(["--inventory", str(inventory)])


class CredentialAndOutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_env_file_rejects_group_or_world_readable(self):
        path = self.dir / "typesafe.env"
        path.write_text("TYPESAFE_API_KEY=secret-value\n", encoding="utf-8")
        os.chmod(path, 0o600)
        self.assertEqual(mod.load_env_file(str(path)), "secret-value")
        os.chmod(path, 0o644)
        with self.assertRaises(SystemExit):
            mod.load_env_file(str(path))

    def test_env_file_without_key_is_refused(self):
        path = self.dir / "typesafe.env"
        path.write_text("SOMETHING_ELSE=1\n", encoding="utf-8")
        os.chmod(path, 0o600)
        with self.assertRaises(SystemExit):
            mod.load_env_file(str(path))

    def test_write_refuses_overwrite_and_creation_in_missing_parent(self):
        target = self.dir / "report.json"
        mod.write_json(str(target), {"a": 1})
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"a": 1})
        with self.assertRaises(SystemExit):
            mod.write_json(str(target), {"a": 2})
        with self.assertRaises(SystemExit):
            mod.write_json(str(self.dir / "missing" / "report.json"), {"a": 1})

    def test_write_refuses_payload_containing_the_credential(self):
        with self.assertRaises(SystemExit):
            mod.write_json(str(self.dir / "leak.json"),
                           {"note": "oops secret-value here"}, key="secret-value")
        self.assertFalse((self.dir / "leak.json").exists())

    def test_secret_never_reaches_report_or_state(self):
        secret = "apikey_deadbeef_test"
        report, state = mod.run_screening(
            {"locations": [record(1, "CMT8")]}, None, stub_transport(),
            capture_date="2026-09-07")
        blob = json.dumps({"report": report, "state": state}, ensure_ascii=False)
        self.assertNotIn(secret, blob)
        self.assertNotIn("Authorization", blob)
        self.assertNotIn("Bearer", blob)


class SortingTests(unittest.TestCase):
    def test_pair_key_is_order_independent(self):
        self.assertEqual(mod.pair_key(7440, 2446), mod.pair_key(2446, 7440))

    def test_name_similarity_ignores_diacritics(self):
        self.assertEqual(mod.normalize_name("Cầu Diễn"), "cau dien")


SHIPPED_RULES = ROOT / "configs/openaq_screening_rules.json"

# The six placements and six pairs verified from independent evidence on
# 2026-09-17. Fixtures reproduce the real inventory field values.
VERIFIED_PLACEMENTS = [
    ({"name": "OceanPark", "provider": "AirGradient",
      "instruments": ["AirGradient Open Air Generation 1 (O-1PST)"]}, "outdoor_ambient"),
    ({"name": "Care Centre", "provider": "AirGradient",
      "instruments": ["AirGradient ONE Generation 9 (I-9PSL-DE)"]}, "sheltered_or_indoor"),
    ({"name": "Hanoi", "provider": "AirNow", "instruments": ["Government Monitor"]},
     "outdoor_ambient"),
    ({"name": "US Diplomatic Post: Hanoi", "provider": "StateAir Hanoi",
      "instruments": ["Government Monitor"]}, "outdoor_ambient"),
    ({"name": "US Diplomatic Post: Ho Chi Minh City", "provider": "Ho Chi Minh City",
      "instruments": ["Government Monitor"]}, "outdoor_ambient"),
]

VERIFIED_PAIRS = [
    ({"left_name": "Ngoai nha", "right_name": "Ngoai nha",
      "coordinate_distance_m": 0.0}, "merge"),
    ({"left_name": "US Diplomatic Post: Ho Chi Minh City",
      "right_name": "US Diplomatic Post: Ho Chi Minh City",
      "coordinate_distance_m": 80.7}, "merge"),
    ({"left_name": "SPARTAN - Vietnam Acad. Sci.", "right_name": "SPARTAN - Vietnam Acad. Sci.",
      "coordinate_distance_m": 22.2}, "merge"),
    ({"left_name": "Tân Mai", "right_name": "Xuân Mai",
      "coordinate_distance_m": 30476.0}, "leave_unlinked"),
    ({"left_name": "outdoor", "right_name": "outdoor2",
      "coordinate_distance_m": 50.9}, "curator"),
    ({"left_name": "Ngoai phong", "right_name": "Ngoai phong",
      "coordinate_distance_m": 2619.4}, "curator"),
]


class RuleEngineTests(unittest.TestCase):
    def setUp(self):
        self.rules = mod.load_rules(str(SHIPPED_RULES))

    def test_shipped_rules_reproduce_every_verified_placement(self):
        for item, expected in VERIFIED_PLACEMENTS:
            resolved = mod.apply_placement_rules(item, self.rules)
            self.assertIsNotNone(resolved, f"no rule matched {item['name']}")
            self.assertEqual(resolved["placement"], expected, item["name"])
            self.assertTrue(resolved["source"], "every rule must carry its source")

    def test_shipped_rules_reproduce_every_verified_pair(self):
        for pair, expected in VERIFIED_PAIRS:
            resolved = mod.apply_identity_rules(pair, self.rules)
            self.assertEqual(resolved["decision"], expected, pair["left_name"])

    def test_government_monitor_elsewhere_is_not_resolved(self):
        """The EPA rule is about DOS posts, not every 'Government Monitor'."""
        item = {"name": "An Khánh", "provider": "Hanoi Air Quality Monitoring Network",
                "instruments": ["Government Monitor"]}
        self.assertIsNone(mod.apply_placement_rules(item, self.rules))

    def test_unknown_airgradient_model_is_not_resolved(self):
        item = {"name": "CMT8", "provider": "AirGradient",
                "instruments": ["Unknown AirGradient Sensor"]}
        self.assertIsNone(mod.apply_placement_rules(item, self.rules))

    def test_missing_distance_falls_back_to_curator(self):
        pair = {"left_name": "Ngoai phong", "right_name": "Ngoai phong",
                "coordinate_distance_m": None}
        self.assertEqual(mod.apply_identity_rules(pair, self.rules)["decision"], "curator")

    def test_unconditional_fallback_rule_is_required(self):
        broken = {"placement_rules": [], "identity_rules": [
            {"id": "conditional", "decision": "curator", "when": {"distance_m_gte": 1}}]}
        with self.assertRaises(SystemExit):
            mod.default_identity_rule(broken)

    def test_load_rules_refuses_a_malformed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rules.json"
            path.write_text(json.dumps({"placement_rules": []}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                mod.load_rules(str(path))

    def test_rule_resolved_records_never_reach_the_model(self):
        """Every verified location and pair is decided before any request is built."""
        records = [record(1, "OceanPark", provider="AirGradient"),
                   record(2, "An Khánh", provider="Hanoi Air Quality Monitoring Network")]
        records[0]["instruments"] = [{"id": 1, "name": "AirGradient Open Air Generation 1 (O-1PST)"}]
        records[1]["instruments"] = [{"id": 1, "name": "Government Monitor"}]
        calls = []
        report, state = mod.run_screening(
            {"locations": records}, None, stub_transport(calls=calls),
            capture_date="2026-09-07", rules=self.rules)
        self.assertEqual(report["locations_left_to_model"], 1)
        self.assertEqual(len(report["placement_resolved_by_rule"]), 1)
        asked = [qid for payload in calls for qid in payload["questions"]]
        self.assertEqual(asked, ["loc1_siting"])

    def test_state_records_which_rule_decided(self):
        rules = self.rules
        records = [record(1, "OceanPark", provider="AirGradient")]
        records[0]["instruments"] = [{"id": 1, "name": "AirGradient Open Air Generation 1 (O-1PST)"}]
        _, state = mod.run_screening({"locations": records}, None, stub_transport(),
                                     capture_date="2026-09-07", rules=rules)
        entry = state["locations"]["1"]["siting"]
        self.assertEqual(entry["type"], "rule")
        self.assertEqual(entry["choice"], "outdoor_ambient")
        self.assertEqual(entry["resolved_by"], "airgradient_open_air_is_outdoor")
        self.assertIn("airgradient.com", entry["source"])

    def test_report_carries_rule_sources_and_caveats(self):
        report, _ = mod.run_screening(
            {"locations": [record(1, "CMT8")]}, None, stub_transport(),
            capture_date="2026-09-07", rules=self.rules)
        for entry in report["placement_resolved_by_rule"]:
            self.assertTrue(entry["source"])
        self.assertTrue(report["rule_caveats"])

    def test_shipped_rule_file_declares_its_caveats(self):
        caveats = " ".join(self.rules["caveats"])
        self.assertIn("proposals", caveats)
        self.assertIn("not validation", caveats)


if __name__ == "__main__":
    unittest.main()
