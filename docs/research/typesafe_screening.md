# TypeSafe (Jev) screening of the OpenAQ inventory

Status: **exploratory triage aid, not a qualified method.** The tool is
implemented, unit-tested and run against the real capture; its accuracy is
**not measured**. Nothing here changes a project decision, and no disposition,
merge or selection is made by the tool.

Code: [scripts/screen_openaq_typesafe.py](../../scripts/screen_openaq_typesafe.py),
tests: [tests/test_typesafe_screening.py](../../tests/test_typesafe_screening.py)
(27 offline tests, credential-free, no network).

## What it is for

Two judgments only, because these are the only two where a semantic model beat
deterministic code on this project's data:

1. **Placement evidence** - is a sensor outdoors, sheltered, or unknown, judged
   from its name (English or Vietnamese) and metadata;
2. **Record identity** - do two similarly named records describe the same
   physical station?

Everything else stays in code, permanently: instrument class, licence lookup,
freshness, coordinates, distances, spans, coverage arithmetic and every
threshold.

The restriction is deliberate and measured. An earlier probe also asked the
model to classify instrument class and to judge freshness. Instrument class
reproduced the inventory's own `instruments` field exactly (43 Government
Monitor, 16 AirGradient/HabitatMap), and freshness simply tracked
`datetimeLast`. Both were removed rather than kept as decoration, and a test
now fails if those question kinds reappear.

## Change-driven, not continuous polling

The tool fingerprints every location and every candidate pair over the fields
that placement and identity can actually depend on (name, locality, provider,
owner, instruments, monitor/mobile flags, coordinates, licence ids). Each run
asks only about records that are new or whose fingerprint changed, then updates
a state file atomically. **An unchanged inventory costs zero requests.**

Measured on the 2026-09-07 capture, 2026-09-17:

| Run | Screened | Skipped | Requests | Input tokens | Wall clock |
| --- | --- | --- | --- | --- | --- |
| First (all new) | 59 locations, 6 pairs | 0 | 4 | 26,937 | 3.4 s |
| Second (unchanged) | 0 | 59 | **0** | **0** | 0.08 s |

## Verdicts are routed, never acted on

Judgments are split in code by confidence. Identity decisions always require a
human regardless of confidence; placement calls below the review threshold are
queued. From the first run: 22 of 65 judgments were auto-accepted and 43 went to
the review queue (37 low-confidence placement, 3 low-confidence identity, 3
confident identity). Of the six identity candidates, the tool proposed two
merges (confidence 0.95 and 0.75), correctly declined to link the `Tân Mai` /
`Xuân Mai` false-positive trap that name similarity alone would join at 30.5 km
apart, and returned `curator` or an unconvincing 0.10 for the genuinely
ambiguous pairs.

Confident `siting_unknown` answers are treated as first-class results: the model
saying "the metadata carries no placement information" is a useful, honest
answer, not a failure.

## Usage

```bash
# Plan only; sends nothing and writes no state.
PYTHONPATH=src .venv/bin/python -B scripts/screen_openaq_typesafe.py \
  --inventory .local/openaq_vietnam_inventory_2026-09-07.json \
  --output .local/typesafe/run_a.json --state .local/typesafe/state.json --dry-run

# One screening pass; the report path must be new, the state file is updated.
SSL_CERT_FILE=/etc/ssl/cert.pem PYTHONPATH=src .venv/bin/python -B \
  scripts/screen_openaq_typesafe.py \
  --inventory .local/openaq_vietnam_inventory_2026-09-07.json \
  --output .local/typesafe/run_a.json --state .local/typesafe/state.json
```

The credential is read from an owner-only file of literal assignments (default
`.local/typesafe/typesafe.env`, mode `600`; a group- or world-readable file is
refused) or from `TYPESAFE_API_KEY` in the environment. The value is never
printed, logged or written: `write_json` refuses to publish any output that
contains it. Reports are written to new paths only; the state file is the tool's
memory rather than evidence, and is replaced atomically.

## Measuring it

Accuracy is unknown, and two different questions are easy to confuse:

1. **Does it agree with a careful human reading the same metadata?** Measurable
   today, and the operationally useful question: can it read 59 names instead of
   you doing it? It is *not* accuracy, because both sides read the same text.
2. **Is it right about the world?** Placement and station identity need evidence
   from outside the inventory - the provider's page, the owner's description, a
   documented site. Without that, `outdoor_ambient` is an interpretation, not a
   fact.

### Level 1: agreement with a blinded human label

```bash
PYTHONPATH=src .venv/bin/python -B scripts/screen_openaq_typesafe.py \
  --inventory .local/openaq_vietnam_inventory_2026-09-07.json \
  --emit-labels .local/typesafe/label_sheet.json
```

That writes 59 location rows and 6 pair rows with **no model answer in them**, so
your labels cannot anchor on what the tool said. Fill in `your_siting_label` and
`your_identity_label`, then score the filled sheet directly - no conversion step:

```bash
  ... --output .local/typesafe/run_labelled.json \
      --labels .local/typesafe/label_sheet.json
```

`label_check` in the report then carries agreement, a Wilson 95% interval, a
confusion matrix, per-class precision/recall, and agreement per bucket. **The
decisive number is the bucket comparison**: if `auto_accepted` is not clearly
better than `review_low_confidence`, the confidence gate is decorative and the
tool should not act on anything.

Interval width is reported rather than hidden. A perfect 4/4 gives a Wilson
interval near [0.51, 1.00], which rules almost nothing out; 59 labels are the
minimum worth reading, and small subsets should be reported as such.

### Level 2: independent evidence

For 10-15 locations, check placement against something outside the inventory,
such as the provider's or owner's own description. That is the only route to
calling a placement judgment *accurate*, and the only way to catch systematic
bias - for example, treating every street address as outdoors. Station identity
is usually cheaper to verify independently than placement, because provider and
owner records are decisive.

### Level 2 result (2026-09-17)

Independent evidence was found for 6 of the 59 locations, and it reversed the
level-1 picture.

| Location | Independent evidence | Verified placement | Jev's call |
| --- | --- | --- | --- |
| 6123215 OceanPark | instrument `AirGradient Open Air (O-1PST)`; the manufacturer documents Open Air as an outdoor monitor | outdoor_ambient | outdoor_ambient (0.98), correct |
| 6068138 Care Centre | instrument `AirGradient ONE (I-9PSL-DE)`; the manufacturer documents ONE as an indoor monitor | sheltered_or_indoor | siting_unknown (0.40), wrong |
| 7441 Hanoi | AirNow / Department of State embassy network; EPA documents these as reference-grade ambient monitors | outdoor_ambient | siting_unknown (0.84), wrong |
| 7440, 2539, 2446 Diplomatic Post | same network | outdoor_ambient | siting_unknown (0.78-0.82), wrong |

Jev was correct on **1 of 6** verified locations. Of the five placement calls it
auto-accepted, **one** was correct.

That contradicts the level-1 result of 95.5% on the same bucket, and the reason
is the whole point of level 2: level 1 measured agreement with a reader who
shared the same blind spot. Both treated "US Diplomatic Post" as carrying no
placement information, when programme documentation establishes that it does.
Shared blind spots inflate agreement; only outside evidence exposes them. An
agreement figure between two readers of the same text is therefore not a
substitute for verification, however high it looks.

A second finding is instability. Care Centre was screened twice, with the same
question and the same state, and answered differently: `sheltered_or_indoor` at
0.17, then `siting_unknown` at 0.40. The second run was *more* confident and
wrong, so confidence does not guard this question.

What follows:

- These placements are a **knowledge** problem, not a language problem. The
  decisive facts - manufacturer model semantics and programme membership - belong
  in code as a reviewed rule table with cited sources, not in a model question.
- The model retains a role only for records with no objective evidence (the
  Vietnamese low-cost sensor names), and there its answers are hints, never
  dispositions.
- On this evidence, placement should not be auto-accepted at all; the current
  `--review-threshold 0.75` default is too permissive for this question.

The verified labels and their sources are in
`.local/typesafe/level2_verification_2026-09-17.json`, a git-ignored working
artifact rather than a committed record.

### Level 2 result: identity (2026-09-17)

All 6 candidate pairs were checked against structural facts and, where possible,
external documentation.

| Pair | Decisive evidence | Verified | Jev |
| --- | --- | --- | --- |
| 6477970 / 6477971 "Ngoai nha" | identical coordinates (0.0 m) | merge | merge (0.95), correct |
| 2161313 / 2161323 Tan Mai / Xuan Mai | 30,476 m apart | leave_unlinked | leave_unlinked (0.98), correct |
| 2446 / 7440 Diplomatic Post HCMC | identical name and provider, 80.7 m apart, exactly adjacent periods | merge | merge (0.75), correct |
| 268816 / 268821 outdoor / outdoor2 | 50.9 m apart, no dates | curator | curator (0.31), correct |
| 1285357 / 18 SPARTAN | SPARTAN documents a global set of discrete ground sites; same institution 22.2 m apart | merge | curator (0.29), wrong |
| 6473874 / 6497944 "Ngoai phong" | 2,619 m apart, disjoint periods, no per-device record published | curator | leave_unlinked (0.10), wrong |

Jev was correct on 4 of 6, and both errors carried confidence 0.29 and 0.10 -
below the review threshold. Identity is unconditionally routed to a human by
design, so no incorrect identity action was ever proposed.

The contrast with placement is the useful result, and it generalises:

- Where the decisive evidence is **structural and present in the state**
  (distance, period continuity), the model performs well and its low confidence
  tracks its own errors.
- Where the decisive evidence is **external knowledge absent from the state**
  (manufacturer model semantics, programme membership), it fails systematically
  and confidently. A model cannot be asked about facts it was never given.

Two pairs therefore stay `curator` rather than verified: HabitatMap's AirCasting
platform publishes no per-device placement record, so a community AirBeam
redeployed 2.6 km away cannot be told apart from a second device.

This also settles the threshold question from the placement section: a single
global `--review-threshold` is the wrong shape. Identity was well served by the
gate; placement was not. Thresholds belong per question, and for placement the
correct threshold is "always review".

The identity labels and sources are in
`.local/typesafe/level2_identity_2026-09-17.json`, also a git-ignored working
artifact.

## Reviewed rules (implemented 2026-09-17)

The level-2 findings are now implemented rather than merely recorded. Placement
and identity are decided by a reviewed rule file,
`configs/openaq_screening_rules.json`, and a record that a rule resolves never
reaches the model.

- **Placement rules** cite manufacturer and agency documentation: AirGradient
  Open Air (O-1PST) is an outdoor monitor, AirGradient ONE (I-9PSL) is an indoor
  monitor, and the Department of State post monitors are reference-grade ambient
  monitors per EPA. Every match carries its rule id and source into the state, so
  each stored placement names the document it came from.
- **Identity rules** decide from structural facts: at least 10 km apart is a
  different station, an identical normalised name within 100 m is a merge, and
  everything else falls to `curator`. The thresholds are proposals derived from
  the six verified pairs, not measured values, and the file says so.
- **Placement is never auto-accepted** and identity is always routed to a human.
  That per-question policy replaced the single global threshold.

Scored against the twelve independently verified labels, the rules are correct
on **12 of 12** with no model call at all:

| Basis | Correct |
| --- | --- |
| Reviewed rules (12 verified items) | 12/12 |
| Model, placement | 1/6 |
| Model, identity | 4/6 |

Stating the limit plainly: the rules reproduce those labels by construction,
because the labels were used to choose the thresholds. That is not independent
validation and the Wilson interval on 12 items is still far too wide to lean on.
What the rules add is not accuracy but **auditability** - every decision names
its source, and a reviewer can dispute one line of a JSON file instead of
re-reading a model's output.

What remains for the model is the residue no rule resolves: 53 of 59 locations,
mostly the 37 Hanoi network stations and the HabitatMap community sensors. Its
answers there are hints in a review queue, never dispositions, and none of them
can currently be verified from an independent source - which is exactly why they
stay hints.

Until a labelled set exists and is large enough to mean something, this tool
stays a triage aid: it proposes candidates and confidence-gated review items,
and a person decides.

## Boundaries

- **Never inside the frozen pipelines.** `features.py`, `baselines.py` and
  `ml.py` `run`/`replay` contracts make no network calls and the analytical
  runners are standard-library only; this tool is a separate, explicitly
  invoked script and stays outside them.
- **No scheduler is installed.** Phase 11 tooling activation remains separately
  authorized; this tool is written to be safe to invoke per cycle, not to
  invoke itself.
- **CI runs only the offline tests.** The live path needs a credential and a
  paid endpoint, so the GitHub workflow never calls TypeSafe; the 27 tests
  inject a stub transport instead.
- **No disposition.** The three licensed but undispositioned candidates found
  beside this work are recorded in
  [the qualification report addendum](openaq_qualification.md#addendum-undispositioned-licensed-candidates-2026-09-17);
  deciding them remains open.
