# Phase 12: portfolio polish verification

Date: 2026-09-14 Australia/Melbourne. Scope: documentation, reproducibility and
presentation over the frozen Phase 4-11 evidence. The correction review below
supersedes the original executor's completion claim. It adds reporting and
evidence fixes plus a scoped statistics-table CSS correction. Research data,
calculations, source policies and dashboard bundle bytes are unchanged.
This is coordinator verification, not an independent reviewer approval.

## Correction review: 2026-09-14

The submitted package was reproducible but needed corrections before acceptance.
The original focused suite passed 58 tests, the full suite passed 437 tests
(435 passed, 2 credential skips), and the isolated PostgreSQL suite passed 63.
Those tests did not cover the reporting and visual failures below.

### Findings and changes

1. Walkthrough 02 put H3's raw p-value under an adjusted-p heading. The corrected
   table separates raw and Holm-adjusted values, marks H3 adjustment not
   applicable, and explains 4,070 sensor-hours versus 2,035 shared timestamps.
   The underlying Phase 6 estimates and inference labels are unchanged.
2. Walkthrough 04 labelled all 182 daily rows qualified. It now distinguishes
   the grid from 172 qualified full sensor-days. It labels provenance hash-map
   comparisons as matched declarations rather than new payload-file reads.
   Walkthrough 01 now shows weather-correlation sample sizes, PM2.5 units and
   the daily qualification rule; walkthrough 03 no longer mixes origin counts
   with a feature-row denominator.
3. A synthetic dangling output symlink caused the writer to create a different
   file. Writers now use exclusive creation, reject symlink paths and verify
   all four walkthrough inputs before publishing any report. A late input
   failure leaves no partial report or success manifest. Tests cover these
   failures and reject missing delivered evidence instead of skipping replay.
4. The screenshot manifest did not contain PNG hashes, despite the original
   report saying it did. Capture now checks actual served JSON and CSS bytes,
   checks the displayed canonical digest, blocks off-origin requests and
   websockets before transmission, and records PNG hash, bytes, dimensions,
   viewport and browser version. Full-page image height is distinct from the
   viewport height. Constant failure codes avoid dumping browser exceptions.
5. Visual inspection found single-character wrapping in the air-quality
   statistics table. Its hypothesis column measured about 37px wide in the
   new failing browser regression. Four scoped CSS lines give the ten-column
   table readable minimum widths inside its existing focusable scroll region.
   The regression covers 375/768/1024/1440px and landscape. An intermediate
   zero-width measurement exposed a test timing race; the test now waits for
   the target view to become visible before measuring, without relaxing limits.
6. README and runbook now separate network-dependent initial package setup from
   offline artifact replay, and distinguish the synthetic test database from
   the project database. The summary keeps forecast eligibility scoped to the
   relevant phase. Uncommitted files are no longer described as committed.
   Walkthrough modules now contain the documented cell markers; no notebook
   runtime or new dependency was installed.

### Authoritative corrected evidence

- Walkthrough version: `phase12_walkthroughs_v2`.
- [Corrected nine-file bundle](phase_12_portfolio_2026-09-14_review_corrected/manifest.json):
  manifest SHA-256
  `3bbcec0ffde16801fe6ed5176344fa42715dc66f812be8090e2f2bb0c2f800ed`.
  Each run performs 22 input-file checks across 17 distinct paths. These are
  consumed inputs and pinned SUCCESS files, not a complete Phase 5 archive
  verification. The exact unused Phase 5 README exception remains disclosed
  and unchanged; the dashboard builder validates its specific known bytes.
- [Final screenshot manifest](phase_12_screenshots_2026-09-14_review_verified/screenshots_manifest.json):
  SHA-256 `20041bb4fba1de0d4dbcdc77f1aec66fbcecd7b1bf4c1aab376c06cc54cc6e7b`.
  Five captures; four desktop viewports at 1440x1000 and one mobile at 375x812.
  The air-quality full-page image now measures 1440x2598 rather than 1440x4922.
  Each PNG has its own hash/byte size and actual image dimensions in the manifest.
- CSS SHA-256:
  `9da6f2cce151e75aede38a047e1ced2b3002a39b0f16d52867a97fb6f0295ada`.
- [Browser review checks](phase_12_ui_review_2026-09-14.json): the original
  13 interaction groups plus the readable-column regression, with no script
  errors or external requests. Visual inspection covered the overview,
  filtered air quality, model diagnostics, methods and mobile views.

The original v1 walkthrough directory and original screenshot directory remain
byte-for-byte unchanged and superseded. The intermediate pre-layout capture
is local review evidence under
`/private/tmp/vn-air-phase12-review.Y5CNcz/screenshots-pre-layout/`, not the
authoritative screenshot set. No evidence was deleted or overwritten.

### Review verification

Final observed results:

| Check | Result |
| --- | --- |
| `PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_dashboard tests.test_dashboard_server tests.test_portfolio_walkthroughs -q` | 71 tests, OK, no skips |
| `PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -q` | 450 tests; 448 passed, 2 documented credential skips; OK |
| `PYTHONPATH=src .venv/bin/python -B scripts/test_database.py` | 63 tests, OK; synthetic socket-only cluster |
| `node --test scripts/test_dashboard_capture.cjs` | 4 tests, passed; no browser or network required |
| Browser `scripts/test_dashboard_ui.cjs` against loopback port 8767 | 14 groups passed after CSS correction |
| `scripts/capture_dashboard_screenshots.cjs` against loopback port 8767 | 5 captures, served JSON/CSS identities verified, 0 errors/external requests |
| `scripts/build_dashboard.py` into a new temporary file plus `cmp` | Byte-identical to the frozen dashboard bundle |
| Two fresh v2 walkthrough runs and replay against the authoritative corrected bundle | All 9 files byte-identical; focused and full tests cover both comparisons |
| Original v1 walkthrough manifest and payload hashes | Unchanged; pinned preservation test passes |
| Original screenshot PNGs and manifest | All six hashes unchanged from review start |
| Protected Phase 4-11 files, dashboard JSON, source code and automation configuration | No tracked changes |
| `git diff --check` and scoped untracked-file whitespace scan | Clean |

The sandbox blocked the first PostgreSQL initdb and loopback server bind. The
approved isolated database and loopback browser runs succeeded outside it.
Only the synthetic test cluster and loopback HTTP were used; no provider or
Supabase contact, credential-file read, scheduler, migration on the project
database, role/RLS change or real project backup occurred. The underlying DB
code and tests did not change, so the passing 63-test isolated result is reused.

Review status: delivered after corrections; all required checks passed.
Nothing has been committed or pushed. Portfolio completion continues to exclude
operational activation and prospective captured-feature evaluation.

## Original executor evidence (superseded by correction review)

The remaining sections describe the initial v1 submission and its original
test runs. Use the corrected paths and review results above for current work.

## Baseline and worktree state

| Item | Value |
| --- | --- |
| Baseline commit | `6452d07` (`Complete Phase 11 automation hardening`) |
| Branch / remote | `main`; `origin/main` aligned at `6452d07` (verified before edits) |
| Worktree before | Clean except untracked `docs/verification/phase_12_portfolio_polish_plan.md` |
| Phase 10 dashboard file bytes | `d2c017952150828f30a1a6617940983ece43c06c20aa4498a44d933046fe131d` |
| Phase 10 canonical bundle digest | `b3b43813751628cc0d3439c209484a7c588cbdc9f355eb38cbe9233b1e0a167d` |
| Frozen audit inventory | Consumed Phase 4-9 payloads and pinned SUCCESS files matched; Phase 10 bundle matched. The unused Phase 5 README has the exact documented exception, not a passing checksum |

No commit or push was performed. The user's plan document is the only untracked
file owned by the user; three lines of its header carried trailing double spaces
that break the repository's public-text whitespace gate, so those were trimmed
with no content change and are recorded here.

## Authoritative artifact inventory

The consumed paths and pins were present before the Phase 12 edit. Walkthroughs
re-verify their consumed subset; this does not claim that the complete Phase 5
archive passes, because the unused README has the documented discrepancy.

| Phase | Authoritative artifact | Identity | Status and limitation |
| --- | --- | --- | --- |
| 4 | `docs/verification/phase_4_quality_2026-09-07_final.json` | file `c1570b86...` | Frozen structural audit; coverage/provenance only, no calibration or exposure claim |
| 5 | `docs/verification/phase_5_eda_2026-09-07_final/` | bundle `92370a85...` | Frozen descriptive EDA; no inference |
| 6 | `docs/verification/phase_6_statistics_2026-09-09_corrected/` | manifest `71f7b17b...` | Authoritative corrected run; 2026-09-08 superseded; sensor-level one-window associations |
| 7 | `docs/verification/phase_7_features_2026-09-10_structural_hardened/` | manifest `6aa92f0a...` | Authoritative v7; captured evidence zero, limited diagnostic |
| 8 | `docs/verification/phase_8_baselines_2026-09-11_v2_verified/` | manifest `ec651c4d...` | Authoritative v2; 72/90 cells unavailable, descriptive only |
| 9 | `docs/verification/phase_9_models_2026-09-12_comparison_hardened/` | manifest `378f2e7f...` | Authoritative v4; 24/96 instances trained (calendar-only), descriptive only |
| 10 | `dashboard/data/dashboard.json` plus `docs/verification/phase_10.md` | canonical `b3b43813...` | Frozen local dashboard; static read-only presentation |
| 11 | `docs/verification/phase_11.md` plus `configs/automation.json` | version `phase11_automation_v1` | Delivered, not activated; no scheduler, role or live run |

Full hashes are in the verification records above and in the generated
walkthrough input metadata; they are not duplicated here.

## Files added and changed

Added:

- `reports/portfolio/portfolio_common.py`, `run_walkthroughs.py` and the four
  walkthrough modules (`walkthrough_01_data_quality_and_eda.py`,
  `walkthrough_02_sensor_associations.py`,
  `walkthrough_03_feature_baseline_ml_contract.py`,
  `walkthrough_04_dashboard_and_reproducibility.py`);
- `reports/portfolio/README.md`;
- `reports/portfolio_summary.md`;
- `docs/portfolio_runbook.md`;
- `docs/verification/phase_12_portfolio_2026-09-14/` (9 generated files);
- `docs/verification/phase_12_screenshots_2026-09-14/` (5 PNGs plus manifest);
- `scripts/capture_dashboard_screenshots.cjs`;
- `tests/test_portfolio_walkthroughs.py`;
- this record.

Changed:

- `README.md` restructured into the portfolio narrative (project summary,
  status banner, scope, labelled results, dashboard, roadmap, reproducibility,
  architecture, commitments, operational status, limitations, source record).
  Numerical claims are unchanged; each links to its artifact record.
- `AGENTS.md` adds the Phase 12 project-state sentence, required reading and a
  Phase 12 focus section; no behavioral rule changed.
- `docs/verification/phase_12_portfolio_polish_plan.md` (user file): trailing
  whitespace trimmed on 3 lines as described above.

## Walkthrough evidence

Form: Jupyter is not installed and Phase 12 must not install packages, so the
approved repository-native fallback is used: cell-delimited Python modules
(`# %%`-style sections) with Markdown plus JSON output. This limitation is
recorded here and in `reports/portfolio/README.md`.

```bash
python3 -B reports/portfolio/run_walkthroughs.py --output-dir docs/verification/phase_12_portfolio_2026-09-14
```

Frozen bundle: `docs/verification/phase_12_portfolio_2026-09-14/manifest.json`,
SHA-256 `d25caf1ffa85778fe3101ec792b50a5ee9ac02a37a715ddd90890f12e54026d2`.
Each walkthrough verified every pinned input (6+4+6+6 = 22 identities) before
presenting a value, in deterministic order, and wrote:

| File | SHA-256 |
| --- | --- |
| `01_data_quality_and_eda.json` | `338711dd1d0048f3b16102f8fe74b91fcbdb5e5abdb66bc489f011ad3f373704` |
| `01_data_quality_and_eda.md` | `76067d3420555743269e6f505bc78c67a05f8018e288d99be2a510b4abdb5a43` |
| `02_sensor_associations.json` | `73979a98e1a3d8fce62621e647189f74b749866ebce8cc3fa72884514b2c0c13` |
| `02_sensor_associations.md` | `b19413147d783a9d7a3aa607f4757549a4aae27341d328065999df73b9a7d4c1` |
| `03_feature_baseline_ml_contract.json` | `2af6a4c31ccafab9a39309dd4dda267a6a56d8ed731026c5bd195514a2783259` |
| `03_feature_baseline_ml_contract.md` | `b27ec2661c8b56d9df787763eb6c2d2e40b2acb9532830755da5b1b514fbbd8b` |
| `04_dashboard_and_reproducibility.json` | `7fce8cbdf81dc6b0f8cf23ea82a12a3f9ede29da3afbeb872183d46388fda322` |
| `04_dashboard_and_reproducibility.md` | `96bb9230a8c13d8711b6213d1fabe7ccf644c7578747357756ff320ece8b03c9` |

Deterministic checks:

- Two runs into fresh temporary directories were byte-identical across all 9
  files, including `manifest.json`.
- The frozen bundle replay test re-runs the four walkthroughs into a new
  directory and compares byte-for-byte with the frozen bundle; it passes.
- Individual walkthrough CLIs, new-directory enforcement, existing-directory
  refusal and wrong-hash rejection are covered by
  `tests/test_portfolio_walkthroughs.py`.
- The original AST import check found only standard-library and walkthrough
  imports. This alone does not prove a no-I/O boundary; the correction review
  adds runtime guards for environment access, network sockets, child processes
  and credential-file reads along the exercised path.
- Generated outputs and screenshots are intended for version control, but
  remain uncommitted until the user requests a commit. Re-runs use new paths.

## Screenshot evidence

```bash
python3 -B scripts/serve_dashboard.py
NODE_PATH=<existing playwright package dir> node scripts/capture_dashboard_screenshots.cjs \
  http://127.0.0.1:8765/ docs/verification/phase_12_screenshots_2026-09-14
```

The capture used the existing Playwright/Chrome verification runtime with a
loopback URL and a new output directory; no dashboard asset changed. The
manifest records the bundle identity, capture time and viewports:

| File | Viewport | Content |
| --- | --- | --- |
| `01-overview-desktop.png` | 1440x1000 | Overview, full frozen window |
| `02-air-quality-filtered-desktop.png` | 1440x1000 | Air quality filtered to CMT8, 2026-07-01 to 2026-07-07 (Vietnam local) |
| `03-model-diagnostics-limited-desktop.png` | 1440x1000 | Model diagnostics showing the limited-diagnostic boundary |
| `04-methods-provenance-desktop.png` | 1440x1000 | Methods and provenance with artifact chain and documented exception |
| `05-overview-mobile.png` | 375x812 | Narrow responsive layout |

Screenshot manifest:
`docs/verification/phase_12_screenshots_2026-09-14/screenshots_manifest.json`,
captured 2026-09-13T15:25:22.696Z, 0 script errors and 0 external requests.
The original manifest did not record PNG hashes. The correction review adds
them in a new manifest and preserves this original set. The images are static
views of frozen artifacts, not live monitoring.

Browser verification rerun: `scripts/test_dashboard_ui.cjs` passed all 13
interaction groups (filters, keyboard chart inspection, table fallback, CSV,
themes/contrast, reflow at 375/768/1024/1440 and landscape, reduced motion,
server path rejection, failure/retry, no script errors or external requests)
into a new temporary evidence directory.

## Dashboard digest before and after

| Identity | Before | After |
| --- | --- | --- |
| `dashboard/data/dashboard.json` file bytes | `d2c017952150828f30a1a6617940983ece43c06c20aa4498a44d933046fe131d` | unchanged |
| Canonical bundle digest | `b3b43813751628cc0d3439c209484a7c588cbdc9f355eb38cbe9233b1e0a167d` | unchanged |

`python3 -B scripts/build_dashboard.py --output /private/tmp/vietnam-air-replay.json`
followed by `cmp` reproduced the committed bundle byte-identically.

## Test commands and observed results

| Command | Observed result |
| --- | --- |
| `PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_portfolio_walkthroughs tests.test_research_artifacts -v` | 16 tests; OK (3 skips: 2 credential checks, frozen-artifact pre-generation skip resolved) |
| `PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_dashboard tests.test_dashboard_server tests.test_portfolio_walkthroughs -v` | 58 tests; OK |
| `PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v` | 437 tests ran; 435 passed; 2 documented credential skips; OK |
| `PYTHONPATH=src .venv/bin/python -B scripts/test_database.py` | 63 tests; OK (disposable socket-only cluster) |
| `git diff --check` | clean |
| `cmp dashboard/data/dashboard.json /private/tmp/vietnam-air-replay.json` | byte-identical |
| Browser `scripts/test_dashboard_ui.cjs` | 13/13 groups passed |
| Walkthrough replay into a new directory | 9/9 files byte-identical to the frozen bundle |

The two credential skips require an exported `OPENAQ_API_KEY` or a
password-bearing `DATABASE_URL`; neither was present, and no credential was
searched for, read or printed.

## Frozen-artifact immutability

- `git diff --stat` over `docs/verification/phase_4*` through `phase_11*`,
  `dashboard/data/dashboard.json` and `configs/automation.json` is empty (0
  lines of diff).
- Phase 4-9 hash inventory matched the verification records before any change;
  the walkthroughs re-verify those identities on every run.
- The Phase 10 UI evidence and Phase 11 evidence/configuration are unchanged.
- No historical JSON/CSV/PNG artifact was regenerated, normalized or reformatted.

## Limitations and missed or blocked checks

- No executed `.ipynb` notebook: Jupyter is unavailable and automatic package
  installation is out of scope. The approved cell-delimited Python fallback and
  its limitation are documented in `reports/portfolio/README.md`.
- No independent reviewer: this is executor verification, consistent with the
  Phase 10/11 closeout pattern. No review approval is claimed.
- Screenshots are static captures of frozen artifacts; capture time is evidence
  metadata, and no screenshot implies live monitoring.
- `test_markdown_local_links_and_references` fails until this record exists;
  the final green run above was executed after it was written.
- Operational activation, real backups, live cycles and prospective captured
  collection were not performed and remain separately authorized.
- The plan document's pre-existing trailing whitespace had to be trimmed for
  the repository whitespace gate; this is a whitespace-only normalization.

## Final status

Delivered. All required walkthroughs executed, the screenshot set covers
desktop and narrow layouts, deterministic replay and frozen-artifact
immutability were verified, the dashboard remained static and unchanged, and
the focused, full offline and isolated PostgreSQL gates pass. Portfolio polish
is complete; operational activation and prospective captured-data evaluation
remain the two explicit, separately authorized future gates.

## Evidence links

- [Phase 12 plan](phase_12_portfolio_polish_plan.md)
- [Frozen walkthrough bundle](phase_12_portfolio_2026-09-14/manifest.json)
- [Screenshot manifest](phase_12_screenshots_2026-09-14/screenshots_manifest.json)
- [Walkthrough sources](../../reports/portfolio/README.md)
- [Curated results summary](../../reports/portfolio_summary.md)
- [Portfolio runbook](../portfolio_runbook.md)
- [Phase 11 record](phase_11.md) and [operations runbook](../operations.md)
