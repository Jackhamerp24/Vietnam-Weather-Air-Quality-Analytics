#!/usr/bin/env python3
"""Incremental TypeSafe (Jev) screening of the OpenAQ Vietnam inventory.

This tool exists for the two judgments that a semantic model demonstrably does
better than deterministic code on this project's data:

  1. placement evidence - is a sensor outdoors, sheltered, or unknown, judged
     from its name (English or Vietnamese) and metadata;
  2. record identity   - do two similarly named records describe the same
     physical station?

Everything else stays in code: instrument class, licence lookup, freshness,
distances, spans, coverage arithmetic and every threshold. An earlier probe
asked a model to classify instrument class and freshness as well; both
reproduced deterministic field mappings exactly, so they were removed rather
than kept as decoration.

"Continuous" here means change-driven, not polling. Each run fingerprints every
location and every candidate pair, asks questions only about records that are
new or whose semantic fields changed, and updates an append-only state file.
An unchanged inventory costs zero requests.

Conventions preserved from the project's existing probes
(scripts/probe_openaq.py, scripts/audit_openaq.py):
  * standard library only;
  * credentials come from an explicitly selected owner-only file of literal
    assignments, or the environment; the value is never printed, logged or
    written into any output;
  * a run report is written to a new path only and never overwrites;
  * the tool makes no claim about data quality: answers are triage signals.

The state file is deliberately *updated in place* (atomically) because it is the
tool's memory, not evidence. Reports are evidence and are never overwritten.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import os
import stat
import sys
import time
import unicodedata
import urllib.error
import urllib.request

TOOL = "screen_openaq_typesafe"
STATE_VERSION = 1
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
ENV_VAR = "TYPESAFE_API_KEY"

# Reviewed study-city coordinates (docs/research/phase_1.md).
STUDY_CITIES = {
    "hanoi": (21.02450, 105.84117),
    "hcmc": (10.82302, 106.62965),
    "da_nang": (16.06778, 108.22083),
}

KNOWN_LICENCES = {41: "CC BY 4.0", 33: "US Public Domain"}

SITING_CRITERIA = {
    "outdoor_ambient": (
        "The name or metadata indicates outdoor, ambient or open-air placement "
        "(for example an outdoor or roadside site)."
    ),
    "sheltered_or_indoor": (
        "The name or metadata indicates indoor, balcony, room, floor or vehicle "
        "placement, which limits comparability with ambient monitors."
    ),
    "siting_unknown": (
        "The name and metadata carry no usable information about placement."
    ),
}

PAIR_CRITERIA = {
    "merge": "Strong evidence that both records describe the same physical station.",
    "leave_unlinked": "Evidence indicates these are distinct physical stations.",
    "curator": "Genuinely ambiguous; a human should decide before any merge.",
}


# --------------------------------------------------------------------------
# Deterministic facts (never delegated)
# --------------------------------------------------------------------------

def haversine_km(lat_a, lon_a, lat_b, lon_b):
    radius = 6371.0
    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    d_phi = phi_b - phi_a
    d_lambda = math.radians(lon_b - lon_a)
    h = (math.sin(d_phi / 2) ** 2
         + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lambda / 2) ** 2)
    return 2 * radius * math.asin(math.sqrt(h))


def normalize_name(name):
    text = unicodedata.normalize("NFKD", (name or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.split())


def iso_date(value):
    if isinstance(value, dict):
        value = value.get("utc") or value.get("local")
    return str(value)[:10] if value else None


def licence_summary(licences):
    if not licences:
        return {"ids": [], "labels": [], "status": "absent"}
    ids, labels = [], []
    for entry in licences:
        if isinstance(entry, dict):
            ident, name = entry.get("id"), entry.get("name")
        else:
            ident, name = entry, None
        if ident is not None:
            ids.append(str(ident))
        labels.append(name or KNOWN_LICENCES.get(ident, "unknown"))
    return {"ids": ids, "labels": labels,
            "status": "recorded" if ids else "absent"}


def project_location(index, record):
    """Deterministic projection of one inventory record."""
    coord = record.get("coordinates") or {}
    lat, lon = coord.get("latitude"), coord.get("longitude")
    nearest = None
    if lat is not None and lon is not None:
        nearest = min(
            ((city, haversine_km(lat, lon, *point)) for city, point in STUDY_CITIES.items()),
            key=lambda item: item[1],
        )
    first, last = iso_date(record.get("datetimeFirst")), iso_date(record.get("datetimeLast"))
    span_days = None
    if first and last:
        try:
            from datetime import date
            span_days = (date.fromisoformat(last) - date.fromisoformat(first)).days
        except ValueError:
            span_days = None
    return {
        "index": index,
        "id": record.get("id"),
        "name": record.get("name"),
        "locality": record.get("locality"),
        "provider": (record.get("provider") or {}).get("name"),
        "owner": (record.get("owner") or {}).get("name"),
        "isMonitor": record.get("isMonitor"),
        "isMobile": record.get("isMobile"),
        "instruments": [i.get("name") for i in (record.get("instruments") or [])],
        "pm25_sensor_count": sum(
            1 for s in (record.get("sensors") or [])
            if (s.get("parameter") or {}).get("name") == "pm25"
        ),
        "licence": licence_summary(record.get("licenses")),
        "first_observed": first,
        "last_observed": last,
        "observed_span_days": span_days,
        "latitude": lat,
        "longitude": lon,
        "km_to_nearest_study_city": round(nearest[1], 2) if nearest else None,
        "nearest_study_city": nearest[0] if nearest else None,
    }


def semantic_fields(projected):
    """The fields whose change should trigger re-screening.

    Placement and identity can only change when one of these changes, so a
    licence or coordinate edit re-screens while an unrelated field does not.
    """
    return {
        "name": projected["name"],
        "locality": projected["locality"],
        "provider": projected["provider"],
        "owner": projected["owner"],
        "instruments": projected["instruments"],
        "isMonitor": projected["isMonitor"],
        "latitude": projected["latitude"],
        "longitude": projected["longitude"],
        "licence_ids": projected["licence"]["ids"],
    }


def location_fingerprint(projected):
    blob = json.dumps(semantic_fields(projected), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def pair_key(left_id, right_id):
    return "|".join(str(x) for x in sorted((left_id, right_id), key=lambda v: str(v)))


def _canonical(values):
    """Deterministic order that tolerates None (some records have no dates)."""
    return sorted(values, key=lambda v: json.dumps(v, sort_keys=True, ensure_ascii=False))


def pair_fingerprint(pair):
    blob = json.dumps({
        "names": _canonical([pair["left_name"], pair["right_name"]]),
        "providers": _canonical([pair["left_provider"], pair["right_provider"]]),
        "distance_m": pair["coordinate_distance_m"],
        "periods": _canonical([pair["left_period"], pair["right_period"]]),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def candidate_pairs(projected, threshold=0.80):
    """Name-similarity candidates are generated in code; identity is not judged here."""
    pairs = []
    for a in range(len(projected)):
        for b in range(a + 1, len(projected)):
            left, right = projected[a], projected[b]
            if left["id"] == right["id"]:
                continue
            ratio = difflib.SequenceMatcher(
                None, normalize_name(left["name"]), normalize_name(right["name"])
            ).ratio()
            if ratio < threshold:
                continue
            distance_m = None
            if None not in (left["latitude"], left["longitude"],
                            right["latitude"], right["longitude"]):
                distance_m = round(1000 * haversine_km(
                    left["latitude"], left["longitude"],
                    right["latitude"], right["longitude"]), 1)
            pairs.append({
                "key": pair_key(left["id"], right["id"]),
                "left_id": left["id"], "right_id": right["id"],
                "left_name": left["name"], "right_name": right["name"],
                "name_similarity": round(ratio, 3),
                "same_provider": left["provider"] == right["provider"],
                "left_provider": left["provider"], "right_provider": right["provider"],
                "coordinate_distance_m": distance_m,
                "left_period": [left["first_observed"], left["last_observed"]],
                "right_period": [right["first_observed"], right["last_observed"]],
                "left_licence": left["licence"]["labels"],
                "right_licence": right["licence"]["labels"],
            })
    return pairs


# --------------------------------------------------------------------------
# Reviewed rules: evidence that is documented, not inferred
# --------------------------------------------------------------------------

def load_rules(path):
    with open(path, "r", encoding="utf-8") as handle:
        rules = json.load(handle)
    for key in ("placement_rules", "identity_rules"):
        if not isinstance(rules.get(key), list):
            raise SystemExit(f"refusing: {path} has no {key} list")
    missing_sources = [r.get("id") for r in rules["placement_rules"] if not r.get("source")]
    if missing_sources:
        raise SystemExit(f"refusing: placement rules without a source: {missing_sources}")
    # Fail fast: without an unconditional fallback, an unmatched pair would be
    # handed to the model instead of to a human.
    default_identity_rule(rules)
    return rules


def _contains_any(haystack, needles):
    text = " ".join(haystack if isinstance(haystack, list) else [haystack or ""]).lower()
    return any(needle.lower() in text for needle in needles)


def apply_placement_rules(item, rules):
    """Return the documented placement for a record, or None to leave it to a model.

    Rules cite manufacturer or agency documentation. Applied in declared order,
    first match wins, and every match carries its source into the record.
    """
    for rule in (rules or {}).get("placement_rules", []):
        match = rule.get("match") or {}
        tests = []
        if "instrument_contains_any" in match:
            tests.append(_contains_any(item.get("instruments"), match["instrument_contains_any"]))
        if "provider_contains_any" in match:
            tests.append(_contains_any(item.get("provider"), match["provider_contains_any"]))
        if "name_startswith_any" in match:
            name = (item.get("name") or "").lower()
            tests.append(any(name.startswith(prefix.lower())
                             for prefix in match["name_startswith_any"]))
        if not tests:
            continue
        matched = any(tests) if rule.get("match_mode") == "any" else all(tests)
        if matched:
            return {"placement": rule["placement"], "resolved_by": rule["id"],
                    "source": rule.get("source", ""), "source_note": rule.get("source_note", ""),
                    "basis": rule.get("basis", "")}
    return None


def apply_identity_rules(pair, rules):
    """Decide a candidate pair from structural facts, or None to leave it to a model.

    Rules are evaluated in declared order. A rule with no `when` conditions is
    the unconditional fallback and therefore always matches.
    """
    left = normalize_name(pair["left_name"])
    right = normalize_name(pair["right_name"])
    distance = pair.get("coordinate_distance_m")
    for rule in (rules or {}).get("identity_rules", []):
        when = rule.get("when") or {}
        if when:
            if "distance_m_gte" in when:
                if distance is None or distance < when["distance_m_gte"]:
                    continue
            if "distance_m_lte" in when:
                if distance is None or distance > when["distance_m_lte"]:
                    continue
            if when.get("normalized_names_equal") and left != right:
                continue
        return {"decision": rule["decision"], "resolved_by": rule["id"],
                "source": rule.get("source", ""), "source_note": rule.get("source_note", ""),
                "basis": rule.get("basis", "")}
    return None


def default_identity_rule(rules):
    """The declared fallback when no rule matches."""
    fallback = [r for r in (rules or {}).get("identity_rules", []) if not (r.get("when") or {})]
    if not fallback:
        raise SystemExit("refusing: identity_rules has no unconditional fallback rule")
    rule = fallback[0]
    return {"decision": rule["decision"], "resolved_by": rule["id"],
            "source": rule.get("source", ""), "source_note": rule.get("source_note", ""),
            "basis": rule.get("basis", "")}


def select_unscreened(state, projected, pairs, only_changed=True):
    """Change detection: the whole point of the incremental design."""
    known_locations = (state or {}).get("locations", {})
    known_pairs = (state or {}).get("pairs", {})
    dirty_ids = set()
    todo_locations = []
    for item in projected:
        fingerprint = location_fingerprint(item)
        previous = known_locations.get(str(item["id"]))
        if not only_changed or previous is None or previous.get("fingerprint") != fingerprint:
            todo_locations.append(item)
            dirty_ids.add(item["id"])
    todo_pairs = []
    for pair in pairs:
        fingerprint = pair_fingerprint(pair)
        previous = known_pairs.get(pair["key"])
        touches_dirty = pair["left_id"] in dirty_ids or pair["right_id"] in dirty_ids
        if not only_changed:
            todo_pairs.append(pair)
        elif touches_dirty and (previous is None
                               or previous.get("fingerprint") != fingerprint):
            todo_pairs.append(pair)
    return todo_locations, todo_pairs


# --------------------------------------------------------------------------
# Request planning and orchestration (pure; transport is injected)
# --------------------------------------------------------------------------

def state_locations(chunk):
    """Chunk-local entries so `locations[n]` resolves by position, not global index."""
    out = []
    for item in chunk:
        entry = {k: v for k, v in item.items() if k != "index"}
        entry["inventory_index"] = item["index"]
        out.append(entry)
    return out


def siting_questions(chunk):
    questions = {}
    for position, item in enumerate(chunk):
        questions[f"loc{item['index']}_siting"] = {
            "type": "choice",
            "instructions": (
                f"What does the name and metadata of `locations[{position}]` indicate "
                f"about where this sensor is physically placed? Names may be in "
                f"Vietnamese or English; translate and interpret them. Judge placement "
                f"evidence only."
            ),
            "criteria": SITING_CRITERIA,
        }
    return questions


def pair_questions(pairs):
    questions = {}
    for position, _ in enumerate(pairs):
        questions[f"pair{position}_relationship"] = {
            "type": "choice",
            "instructions": (
                f"Do `pairs[{position}].left` and `pairs[{position}].right` describe the "
                f"same physical monitoring station? Judge from the names, provider "
                f"identities, coordinates, observation periods and licence records. "
                f"Similar names alone do not establish identity, and distinct wards or "
                f"deployments must not be merged."
            ),
            "criteria": PAIR_CRITERIA,
        }
    return questions


def build_requests(todo_locations, todo_pairs, capture_date, chunk_size):
    requests = []
    for start in range(0, len(todo_locations), chunk_size):
        chunk = todo_locations[start:start + chunk_size]
        requests.append({
            "kind": "location_siting",
            "location_ids": [item["id"] for item in chunk],
            "payload": {
                "model": MODEL,
                "state": {"capture_date_utc": capture_date,
                          "locations": state_locations(chunk)},
                "questions": siting_questions(chunk),
            },
        })
    if todo_pairs:
        requests.append({
            "kind": "pair_identity",
            "pair_keys": [pair["key"] for pair in todo_pairs],
            "payload": {
                "model": MODEL,
                "state": {"capture_date_utc": capture_date, "pairs": todo_pairs},
                "questions": pair_questions(todo_pairs),
            },
        })
    return requests


def route(answers, review_threshold, always_review=("siting",)):
    """Split judgments into act-on and human-review. Nothing is auto-merged.

    Placement is never auto-accepted. Level-2 verification found the model
    confidently wrong on four of five auto-accepted placement calls, while
    identity errors stayed below the threshold and were caught. A single global
    threshold was therefore the wrong shape, and the policy is per question.
    """
    accepted, review = [], []
    for question_id, answer in sorted(answers.items()):
        confidence = answer.get("confidence")
        kind = "identity" if question_id.startswith("pair") else "siting"
        entry = {
            "question": question_id,
            "kind": kind,
            "choice": answer.get("choice"),
            "confidence": confidence,
            "probabilities": answer.get("probabilities"),
        }
        if kind in always_review:
            entry["reason"] = "placement is never auto-accepted"
            review.append(entry)
        elif kind == "identity":
            entry["reason"] = "identity decisions always need a human"
            review.append(entry)
        elif confidence is None or confidence < review_threshold:
            entry["reason"] = "confidence below review threshold"
            review.append(entry)
        else:
            accepted.append(entry)
    return accepted, review


def run_screening(inventory, state, transport, *, capture_date, chunk_size=20,
                  pair_threshold=0.80, review_threshold=0.75, rules=None,
                  only_changed=True, dry_run=False, now=None):
    """Execute one screening pass. `transport(payload, key) -> (response, meta)`.

    Reviewed rules run first: a record a rule resolves never reaches the model.
    Only the residue is asked about, and placement answers are never accepted
    without a human.
    """
    records = inventory.get("locations") if isinstance(inventory, dict) else inventory
    records = records or []
    projected = [project_location(i, record) for i, record in enumerate(records)]
    pairs = candidate_pairs(projected, pair_threshold)

    rule_placements = {item["id"]: apply_placement_rules(item, rules) for item in projected}
    rule_identities = {pair["key"]: apply_identity_rules(pair, rules) for pair in pairs}
    unresolved_locations = [i for i in projected if not rule_placements[i["id"]]]
    unresolved_pairs = [p for p in pairs if not rule_identities[p["key"]]]

    todo_locations, todo_pairs = select_unscreened(
        state, unresolved_locations, unresolved_pairs, only_changed)
    requests = build_requests(todo_locations, todo_pairs, capture_date, chunk_size)
    timestamp = now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    report = {
        "tool": TOOL,
        "generated_at_utc": timestamp,
        "capture_date_utc": capture_date,
        "model": MODEL,
        "inventory_location_count": len(projected),
        "candidate_pair_count": len(pairs),
        "placement_resolved_by_rule": [
            dict(rule_placements[i["id"]], id=i["id"], name=i["name"])
            for i in projected if rule_placements[i["id"]]],
        "identity_resolved_by_rule": [
            dict(rule_identities[p["key"]], key=p["key"])
            for p in pairs if rule_identities[p["key"]]],
        "locations_left_to_model": len(unresolved_locations),
        "pairs_left_to_model": len(unresolved_pairs),
        "screened_location_count": len(todo_locations),
        "screened_pair_count": len(todo_pairs),
        "skipped_unchanged_locations": len(projected) - len(todo_locations),
        "skipped_unchanged_pairs": len(pairs) - len(todo_pairs),
        "requests": [],
        "answers": {},
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "accepted": [],
        "review_queue": [],
        "rule_caveats": (rules or {}).get("caveats", []),
        "limitations": [
            "Rule-resolved outcomes come from cited documentation; model answers are hints.",
            "Placement is never auto-accepted; identity is always routed to a human.",
            "No disposition, merge or rejection is decided by this tool.",
        ],
    }
    if dry_run:
        report["planned_requests"] = [
            {"kind": r["kind"],
             "items": len(r.get("location_ids") or r.get("pair_keys") or []),
             "questions": len(r["payload"]["questions"]),
             "payload_bytes": len(json.dumps(r["payload"], ensure_ascii=False))}
            for r in requests
        ]
        return report, state

    new_state = {
        "tool": TOOL,
        "state_version": STATE_VERSION,
        "locations": dict((state or {}).get("locations", {})),
        "pairs": dict((state or {}).get("pairs", {})),
        "updated_at_utc": timestamp,
    }
    # Rule outcomes are recorded even though no request was made for them, so a
    # later run can see the decision came from cited documentation.
    for item in projected:
        resolved = rule_placements[item["id"]]
        if not resolved:
            continue
        new_state["locations"][str(item["id"])] = {
            "fingerprint": location_fingerprint(item),
            "name": item["name"],
            "siting": {"type": "rule", "choice": resolved["placement"], "confidence": None,
                       "resolved_by": resolved["resolved_by"], "source": resolved["source"],
                       "source_note": resolved["source_note"]},
            "screened_at_utc": timestamp,
        }
    for pair in pairs:
        resolved = rule_identities[pair["key"]]
        if not resolved:
            continue
        new_state["pairs"][pair["key"]] = {
            "fingerprint": pair_fingerprint(pair),
            "relationship": {"type": "rule", "choice": resolved["decision"], "confidence": None,
                             "resolved_by": resolved["resolved_by"], "source": resolved["source"],
                             "source_note": resolved["source_note"]},
            "decided": None,
            "screened_at_utc": timestamp,
        }
    projected_by_index = {item["index"]: item for item in projected}
    for request in requests:
        response, transport_meta = transport(request["payload"])
        usage = response.get("usage") or {}
        report["usage"]["input_tokens"] += usage.get("input_tokens", 0)
        report["usage"]["output_tokens"] += usage.get("output_tokens", 0)
        report["requests"].append({"kind": request["kind"],
                                   "usage": usage, **transport_meta})
        for question_id, answer in (response.get("answers") or {}).items():
            report["answers"][question_id] = answer
            if question_id.startswith("loc"):
                # Question ids embed the inventory index; state is keyed by the
                # stable location id so reordering the inventory cannot orphan it.
                item = projected_by_index[int(question_id[3:].split("_")[0])]
                new_state["locations"][str(item["id"])] = {
                    "fingerprint": location_fingerprint(item),
                    "name": item["name"],
                    "siting": answer,
                    "screened_at_utc": timestamp,
                }
            else:
                position = int(question_id[4:].split("_")[0])
                pair = todo_pairs[position]
                new_state["pairs"][pair["key"]] = {
                    "fingerprint": pair_fingerprint(pair),
                    "relationship": answer,
                    "decided": None,
                    "screened_at_utc": timestamp,
                }
    report["accepted"], report["review_queue"] = route(report["answers"], review_threshold)
    return report, new_state


# --------------------------------------------------------------------------
# Optional measurement against human labels
# --------------------------------------------------------------------------

def wilson_interval(successes, total, z=1.96):
    """95% Wilson score interval: honest about small n, unlike a raw percentage."""
    if total <= 0:
        return {"low": None, "high": None}
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    half = (z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total))) / denominator
    return {"low": round(max(0.0, centre - half), 4),
            "high": round(min(1.0, centre + half), 4)}


def confidence_bucket(kind, confidence, review_threshold, resolved_by=None):
    """Which side of the gate a judgment fell on.

    A rule-decided outcome is not a model judgment at all, so it gets its own
    bucket rather than being counted as a low-confidence model answer.
    """
    if resolved_by:
        return "resolved_by_rule"
    if kind == "identity":
        return "review_identity"
    if confidence is None or confidence < review_threshold:
        return "review_low_confidence"
    return "auto_accepted"


def label_sheet(projected, pairs):
    """A blinded sheet: it contains no model answer, so a label cannot anchor on one."""
    return {
        "purpose": (
            "Fill in your_siting_label and your_identity_label by reading the name and "
            "metadata yourself, without looking at the screening state first. Anchoring "
            "on the model's answers would inflate agreement and destroy the measurement."
        ),
        "allowed_labels": {"siting": sorted(SITING_CRITERIA),
                           "identity": sorted(PAIR_CRITERIA)},
        "locations": [{
            "id": item["id"],
            "name": item["name"],
            "provider": item["provider"],
            "owner": item["owner"],
            "instruments": item["instruments"],
            "isMonitor": item["isMonitor"],
            "first_observed": item["first_observed"],
            "last_observed": item["last_observed"],
            "your_siting_label": None,
        } for item in sorted(projected, key=lambda i: str(i["id"]))],
        "pairs": [{
            "key": pair["key"],
            "left_id": pair["left_id"], "right_id": pair["right_id"],
            "left_name": pair["left_name"], "right_name": pair["right_name"],
            "left_provider": pair["left_provider"], "right_provider": pair["right_provider"],
            "coordinate_distance_m": pair["coordinate_distance_m"],
            "left_period": pair["left_period"], "right_period": pair["right_period"],
            "your_identity_label": None,
            "independent_evidence_checked": None,
        } for pair in pairs],
    }


def normalize_labels(labels):
    """Accept either the emitted sheet form or the compact mapping form.

    The sheet written by --emit-labels is a list of rows with your_*_label
    fields, so a filled sheet can be scored directly without hand conversion.
    """
    if isinstance(labels.get("locations"), list):
        locations = {}
        for row in labels["locations"]:
            value = row.get("your_siting_label")
            if value:
                locations[str(row.get("id"))] = {"siting": value}
        pairs = {}
        for row in labels.get("pairs") or []:
            value = row.get("your_identity_label")
            if value:
                pairs[row.get("key")] = value
        return {"locations": locations, "pairs": pairs}
    return {"locations": labels.get("locations") or {},
            "pairs": labels.get("pairs") or {}}


def score_labels(labels, state, review_threshold=0.75):
    """Agreement with human labels, reported so that small n cannot flatter the tool.

    The decisive number is not overall agreement. It is whether the auto-accepted
    bucket is materially more accurate than the review bucket: if it is not, the
    confidence gate is decorative and the tool should not act on anything.
    """
    labels = normalize_labels(labels)
    checks = []
    for location_id, expected in (labels.get("locations") or {}).items():
        entry = (state.get("locations") or {}).get(str(location_id)) or {}
        answer = entry.get("siting") or {}
        want = expected.get("siting") if isinstance(expected, dict) else expected
        if want is None:
            continue
        checks.append({"kind": "siting", "id": str(location_id), "expected": want,
                       "actual": answer.get("choice"),
                       "agrees": want == answer.get("choice"),
                       "confidence": answer.get("confidence"),
                       "resolved_by": answer.get("resolved_by"),
                       "source": answer.get("source")})
    for key, want in (labels.get("pairs") or {}).items():
        if want is None:
            continue
        entry = (state.get("pairs") or {}).get(key) or {}
        answer = entry.get("relationship") or {}
        checks.append({"kind": "identity", "id": key, "expected": want,
                       "actual": answer.get("choice"),
                       "agrees": want == answer.get("choice"),
                       "confidence": answer.get("confidence"),
                       "resolved_by": answer.get("resolved_by"),
                       "source": answer.get("source")})

    total = len(checks)
    agreement = sum(1 for c in checks if c["agrees"])

    buckets = {}
    for check in checks:
        name = confidence_bucket(check["kind"], check["confidence"], review_threshold,
                                 check.get("resolved_by"))
        slot = buckets.setdefault(name, {"n": 0, "agreement": 0})
        slot["n"] += 1
        slot["agreement"] += 1 if check["agrees"] else 0
    for slot in buckets.values():
        slot["rate"] = round(slot["agreement"] / slot["n"], 4) if slot["n"] else None
        slot["wilson_95"] = wilson_interval(slot["agreement"], slot["n"])

    confusion = {}
    for check in checks:
        row = confusion.setdefault(check["expected"], {})
        row[check["actual"]] = row.get(check["actual"], 0) + 1

    per_class = {}
    for label in sorted({c["expected"] for c in checks}):
        expected_n = sum(1 for c in checks if c["expected"] == label)
        predicted_n = sum(1 for c in checks if c["actual"] == label)
        hit = sum(1 for c in checks
                  if c["expected"] == label and c["actual"] == label)
        per_class[label] = {
            "support": expected_n,
            "recall": round(hit / expected_n, 4) if expected_n else None,
            "precision": round(hit / predicted_n, 4) if predicted_n else None,
        }

    return {
        "n": total,
        "agreement": agreement,
        "agreement_rate": round(agreement / total, 4) if total else None,
        "wilson_95": wilson_interval(agreement, total),
        "unlabelled_locations": max(0, len(state.get("locations") or {})
                                    - sum(1 for c in checks if c["kind"] == "siting")),
        "by_bucket": buckets,
        "confusion": confusion,
        "per_class": per_class,
        "disagreements": [c for c in checks if not c["agrees"]],
        "caveat": ("Agreement with labels read from the same metadata measures "
                   "interpretation, not ground truth. Placement and station identity "
                   "need independent evidence to be called accurate."),
        "checks": checks,
    }


# --------------------------------------------------------------------------
# Transport and credentials
# --------------------------------------------------------------------------

def load_env_file(path):
    """Parse an owner-only file of literal KEY=VALUE assignments. Never echoes values."""
    if not os.path.exists(path):
        raise SystemExit(f"refusing: env file not found: {path}")
    if os.stat(path).st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SystemExit(f"refusing: {path} is group/world accessible; chmod 600 it first")
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == ENV_VAR:
                return value.strip().strip("'\"")
    raise SystemExit(f"refusing: no {ENV_VAR} assignment found in {path}")


def resolve_key(env_file):
    if os.environ.get(ENV_VAR):
        return os.environ[ENV_VAR]
    return load_env_file(env_file)


def http_post(payload, key, timeout=90, attempts=4):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_error = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            ENDPOINT, data=body, method="POST",
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json",
                     "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                return json.loads(raw), {
                    "status": response.status,
                    "request_sha256": hashlib.sha256(body).hexdigest(),
                    "response_sha256": hashlib.sha256(raw).hexdigest(),
                    "request_bytes": len(body),
                }
        except urllib.error.HTTPError as error:
            detail = error.read()[:300].decode("utf-8", errors="replace")
            last_error = f"HTTP {error.code}: {detail}"
            if error.code in (429, 529) and attempt < attempts - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise SystemExit(f"request failed: {last_error}")
        except urllib.error.URLError as error:
            last_error = f"{type(error).__name__}: {error.reason}"
            if attempt < attempts - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise SystemExit(f"request failed: {last_error}")
    raise SystemExit(f"request failed: {last_error}")


def write_json(path, payload, *, replace=False, key=None):
    """Write JSON. Refuses to overwrite unless replace is set. Never writes a secret."""
    if os.path.exists(path) and not replace:
        raise SystemExit(f"refusing to overwrite existing output: {path}")
    blob = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if key and key in blob:
        raise SystemExit("refusing to write an output containing the credential")
    parent = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(parent):
        raise SystemExit(f"refusing: parent directory does not exist: {parent}")
    if replace:
        temporary = f"{path}.tmp-{os.getpid()}"
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(blob)
        os.replace(temporary, path)
    else:
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(blob)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--inventory", required=True,
                        help="OpenAQ inventory capture JSON (probe_openaq.py output)")
    parser.add_argument("--output", help="run report; must be a new path")
    parser.add_argument("--emit-labels", metavar="PATH",
                        help="write a blinded labeling sheet and exit (no network)")
    parser.add_argument("--state", help="screening state file (created or updated)")
    parser.add_argument("--env-file", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".local/typesafe/typesafe.env"))
    parser.add_argument("--capture-date", default="2026-09-07")
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--pair-threshold", type=float, default=0.80)
    parser.add_argument("--review-threshold", type=float, default=0.75)
    parser.add_argument("--labels", help="optional human labels for an agreement check")
    parser.add_argument("--rules", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "configs/openaq_screening_rules.json"),
        help="reviewed placement and identity rules, applied before any model call")
    parser.add_argument("--rescreen-all", action="store_true",
                        help="ignore state and re-ask every location and pair")
    parser.add_argument("--dry-run", action="store_true",
                        help="plan and print, send nothing, write no state")
    args = parser.parse_args(argv)

    if not args.emit_labels and not args.output:
        parser.error("--output is required unless --emit-labels is used")
    if args.output and os.path.exists(args.output) and not args.dry_run:
        raise SystemExit(f"refusing to overwrite existing output: {args.output}")

    with open(args.inventory, "rb") as handle:
        raw = handle.read()
    inventory = json.loads(raw)

    if args.emit_labels:
        projected = [project_location(i, record) for i, record
                     in enumerate(inventory.get("locations") or [])]
        pairs = candidate_pairs(projected, args.pair_threshold)
        sheet = label_sheet(projected, pairs)
        write_json(args.emit_labels, sheet)
        print(json.dumps({"label_sheet": args.emit_labels,
                          "locations": len(sheet["locations"]),
                          "pairs": len(sheet["pairs"]),
                          "allowed_labels": sheet["allowed_labels"]}, indent=2))
        return 0

    state = None
    if args.state and os.path.exists(args.state):
        with open(args.state, "r", encoding="utf-8") as handle:
            state = json.load(handle)

    options = dict(capture_date=args.capture_date, chunk_size=args.chunk_size,
                   pair_threshold=args.pair_threshold,
                   review_threshold=args.review_threshold, rules=load_rules(args.rules),
                   only_changed=not args.rescreen_all, dry_run=args.dry_run)

    if args.dry_run:
        report, _ = run_screening(inventory, state, None, **options)
        report["inventory_sha256"] = hashlib.sha256(raw).hexdigest()
        summary = {k: report[k] for k in (
            "locations_left_to_model", "pairs_left_to_model",
            "screened_location_count", "screened_pair_count",
            "skipped_unchanged_locations", "skipped_unchanged_pairs",
            "planned_requests")}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    key = resolve_key(args.env_file)
    report, new_state = run_screening(
        inventory, state, lambda payload: http_post(payload, key), **options)
    report["inventory_sha256"] = hashlib.sha256(raw).hexdigest()
    report["env_source"] = ("environment" if os.environ.get(ENV_VAR) else args.env_file)
    if args.labels:
        with open(args.labels, "r", encoding="utf-8") as handle:
            report["label_check"] = score_labels(json.load(handle), new_state)

    write_json(args.output, report, key=key)
    if args.state:
        write_json(args.state, new_state, replace=True, key=key)
    print(json.dumps({
        "screened_locations": report["screened_location_count"],
        "screened_pairs": report["screened_pair_count"],
        "skipped_unchanged": report["skipped_unchanged_locations"],
        "review_queue": len(report["review_queue"]),
        "usage": report["usage"],
        "output": args.output,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
