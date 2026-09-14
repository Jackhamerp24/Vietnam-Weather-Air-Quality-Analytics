# Walkthrough 04: Dashboard bundle identity and local reproducibility

Command: `python3 -B reports/portfolio/walkthrough_04_dashboard_and_reproducibility.py --output-dir <output-dir>`

The dashboard is a local presentation of frozen Phase 5-9 artifacts. Nothing in it is fitted, fetched or recalculated in the browser.

## Bundle identity

| Identity | SHA-256 |
| --- | --- |
| Canonical bundle excluding the digest field | b3b43813751628cc0d3439c209484a7c588cbdc9f355eb38cbe9233b1e0a167d |
| JSON file bytes | d2c017952150828f30a1a6617940983ece43c06c20aa4498a44d933046fe131d |

## Projected counts

| Dataset | Rows |
| --- | --- |
| Hourly PM2.5 grid | 4320 (4191 accepted, 129 absent) |
| Qualified local days | 182 |
| Diurnal summaries | 48 |
| CAMS modeled days | 273 |
| Recorded statistical fits | 31 |
| Baseline metric cells | 90 |
| ML metric cells | 288 |
| ML comparison records | 360 |

## Provenance cross-check

| Phase | Artifact | Identity (manifest/bundle digest) | Files verified |
| --- | --- | --- | --- |
| 5 | Frozen EDA | 92370a857153f2d2a476ab35dbceab3873503239ad6211170e99b8075d1e9e63 | 25 |
| 6 | Pre-registered statistics | 71f7b17bff4bd43a406d235bbc585a268ec56b07f2554cc2b19939b5b5dcf918 | 4 |
| 7 | Availability-aware features | 6aa92f0add8046379445c2f3b5beb77fa2ad05cc981a43f6ca61f1af4fcf60aa | 5 |
| 8 | Chronological baselines | ec651c4df04cb605f8849c1af96a3aea58f0902370e16ec39b9c48fdee22775e | 4 |
| 9 | Chronological ML | 378f2e7f34476fe885ce6ec9827b7a48c346706f36b548fbc8db78ce94d8a770 | 6 |

Each verified file's projected hash equals the frozen phase SUCCESS.json declaration. All three Phase 7-9 statuses remain `limited_diagnostic`.

## Reproduce locally

```bash
python3 -B scripts/build_dashboard.py --output /private/tmp/vietnam-air-replay.json
cmp dashboard/data/dashboard.json /private/tmp/vietnam-air-replay.json
python3 -B scripts/serve_dashboard.py
```

Then open http://127.0.0.1:8765/. Browser verification and the Phase 12 screenshot set use the existing Playwright/Chrome runtime; see `docs/portfolio_runbook.md`.

Boundary: Loopback-only static server, read-only public JSON, no database API, no external assets, no model fitting in the browser.

## Documented integrity notes

- docs/verification/phase_5_eda_2026-09-07_final/README.md: Reviewed pre-existing documentation-only mismatch: the committed README ends in LF; one additional trailing LF would match its declared hash. The file is hashed but not consumed, normalized or rewritten. All displayed data are strictly verified; the complete Phase 5 artifact is not fully verified.

- Daily qualification: Full 24-hour Vietnam date, at least 18 accepted hours; observed summaries retained for all dates
- Sources: OpenAQ/AirGradient measured PM2.5 (ug/m3) is the target, not a city mean. Open-Meteo/ERA5 is retrospective weather context: instantaneous variables align to PM interval start; preceding-hour precipitation sums and radiation means align to interval end. CAMS via Open-Meteo is separate modeled PM2.5 context; Da Nang is modeled-only. Provider forecasts are not ground truth and ERA5/CAMS never replace measured values or captured forecast features.
