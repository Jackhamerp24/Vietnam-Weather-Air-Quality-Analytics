# Phase 12 portfolio walkthroughs

Executable, read-only walkthroughs over the frozen Phase 4-9 artifacts. They are
a presentation layer: they never re-fit a model, re-run a statistical test,
open a database, make a network call or read credentials.

## Form and why

A usable notebook runtime (Jupyter) is not installed in this repository and
Phase 12 must not install packages automatically. The approved repository-native
fallback is cell-delimited Python: each walkthrough is a normal Python module
with `# %%`-style logical sections, runs with the existing interpreter, and
writes Markdown plus machine-readable JSON. The limitation (no executed `.ipynb`)
is recorded in `docs/verification/phase_12.md`.

## Walkthroughs

| Id | Covers |
| --- | --- |
| `01_data_quality_and_eda` | Frozen window, source separation, coverage gaps, daily qualification, descriptive EDA |
| `02_sensor_associations` | Phase 6 pre-registered estimands, adjusted estimates, block-bootstrap uncertainty, multiple-testing labels |
| `03_feature_baseline_ml_contract` | Phase 7 availability policy, Phase 8 baselines, Phase 9 model comparison and why they are limited diagnostics |
| `04_dashboard_and_reproducibility` | Dashboard bundle identity, provenance cross-check and local rebuild/serve commands |

## Run

```bash
python3 -B reports/portfolio/run_walkthroughs.py --output-dir /private/tmp/phase12-walkthroughs
```

Each walkthrough also runs on its own with the same flag. The output directory
must not exist. Outputs are deterministic: re-running into a different new
directory produces byte-identical files. Every walkthrough verifies pinned
SHA-256 identities and fails closed on a missing or mismatched input.

The frozen generated bundle lives in
`docs/verification/phase_12_portfolio_2026-09-14_review_corrected/`. Generated walkthrough outputs
and the Phase 12 screenshot set are intended for version control (no ignore
rule); they remain uncommitted until the user requests a commit. Re-runs go to
a new path. Do not overwrite the frozen
bundle; choose a new output path.

The authoritative bundle uses `phase12_walkthroughs_v2`, following the
2026-09-14 correction review in `docs/verification/phase_12.md`. The original
v1 bundle and screenshot set remain unchanged as superseded evidence. Tests
require the v2 bundle; a missing delivered artifact is a failure, not a skip.

## Tests

```bash
PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_portfolio_walkthroughs -v
```
