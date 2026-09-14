
# Phase 12 Plan: Portfolio Polish and Reproducible Presentation

Status: planned; execution not started
Date: 2026-09-14 Australia/Melbourne
Owner: next implementation agent, with coordinator review
Repository: /Users/duong/Desktop/Vietnam-Weather-Air-Quality-Analytics

## 1. Objective

Complete the planned portfolio-polish phase for Vietnam Weather & Air Quality
Analytics.

The final result should let a technically literate reader understand:

1. what question the project investigates;
2. which sources and sensors are used and how they differ;
3. what was actually measured, analyzed and verified;
4. what the Phase 6 statistical results support;
5. why the Phase 7–9 feature, baseline and ML artifacts are limited
   diagnostics;
6. how to reproduce the local dashboard and evidence artifacts; and
7. which operational and scientific limitations remain.

This is a documentation, reproducibility and presentation phase. It must not
silently become a live-operations, deployment or new-science phase.

## 2. Current baseline

Before changing anything, verify these facts rather than assuming them:

- main is at commit 6452d07, Complete Phase 11 automation hardening.
- origin/main is aligned with HEAD.
- The worktree is clean, apart from any newly discovered user changes that must
  be preserved.
- Phases 1–11 are delivered at the implementation level.
- Phase 11 automation is locally verified but not activated.
- No scheduler is installed.
- No live ingestion cycle, live Supabase health check, real project backup,
  migration, role creation or public API was performed by the prior work.
- The frozen Phase 4–10 artifacts must remain unchanged.
- The authoritative Phase 10 public bundle digest is
  b3b43813751628cc0d3439c209484a7c588cbdc9f355eb38cbe9233b1e0a167d.
- The frozen Phase 5–9 outputs remain limited or descriptive diagnostics where
  their verification records say so.
- A prospective captured collection period is still required before real
  captured-feature evaluation in Phases 7–9.

Record the observed commit, branch, worktree status and baseline dashboard
digest in the Phase 12 verification record. Do not reset, clean or overwrite
existing worktree content.

## 3. Required reading

Read these documents completely before editing portfolio-facing prose or
creating new result summaries:

- AGENTS.md;
- README.md;
- docs/verification/phase_4.md and the Phase 4 quality artifact;
- docs/verification/phase_5.md and docs/verification/phase_5_plan.md;
- docs/verification/phase_6.md and docs/verification/phase_6_plan.md;
- docs/verification/phase_7.md and docs/verification/phase_7_plan.md;
- docs/verification/phase_8.md and docs/verification/phase_8_plan.md;
- docs/verification/phase_9.md and docs/verification/phase_9_plan.md;
- docs/verification/phase_10.md and docs/verification/phase_10_contract.md;
- docs/verification/phase_11.md and docs/operations.md;
- dashboard/README.md;
- design-system/vietnam-air-observatory/MASTER.md;
- design-system/vietnam-air-observatory/pages/dashboard.md;
- /private/tmp/vietnam-weather-air-quality-analytics-handoff-2026-09-13.md,
  if it is still available.

Use the dated authoritative artifacts named by AGENTS.md. Do not use superseded
Phase 6–9 artifacts for current results unless the text explicitly labels them
as historical evidence.

## 4. Scope

### 4.1 In scope

- A concise portfolio narrative in README.md.
- A reproducible portfolio runbook, preferably docs/portfolio_runbook.md.
- Executable walkthrough artifacts for the completed research phases.
- A curated results summary that distinguishes inferential, exploratory and
  descriptive-only outputs.
- Reproducible local dashboard screenshots at representative widths.
- A Phase 12 verification record under docs/verification/.
- Small documentation corrections needed to make phase status, limitations,
  commands and artifact paths consistent.
- Tests and deterministic checks needed to establish the above claims.

### 4.2 Explicitly out of scope

Do not perform any of the following as part of Phase 12:

- read, print, copy, parse or expose .env values;
- print API keys, database URLs, passwords, request headers or secret-bearing
  exceptions;
- run live ingestion or contact OpenAQ, Open-Meteo, CAMS, ERA5 or Supabase;
- run a live automation health check against the project database;
- create a real project backup;
- create database roles, alter grants or change RLS;
- run Alembic migrations or change the database schema;
- install, load or enable launchd, cron, systemd or any scheduler;
- expose a public API or turn the dashboard into a live database-backed app;
- add a paid service, hosted deployment, external notification channel or
  external asset/CDN dependency;
- change the frozen Phase 4–10 evidence artifacts;
- rerun statistical inference on a changed dataset;
- claim forecast skill, production readiness, causal effects, city-wide
  exposure, health guidance or operational automation;
- claim an independent reviewer or hosted CI run that did not occur.

If operational activation or prospective data collection is desired, stop and
create a separate authorization request. Do not fold it into this phase.

## 5. Governing scientific and presentation rules

Preserve these distinctions:

| Stream | Correct description | Do not describe as |
|---|---|---|
| OpenAQ PM2.5 | measured sensor observations at CMT8 and OceanPark | a city-wide or population exposure estimate |
| ERA5 | retrospective reanalysis weather context | historically available operational features |
| Open-Meteo | provider forecast snapshots | ground-truth weather |
| CAMS | modeled air-quality context | measured pollution |
| Phase 6 | sensor-level associations over one frozen 90-day window | causal effects or forecast skill |
| Phase 7 | availability-aware, leakage-safe feature construction | an operational backtest |
| Phase 8 | chronological baseline diagnostics | validated forecasting performance |
| Phase 9 | deterministic Ridge/tree diagnostics | proven model performance |
| Phase 10 | static local research dashboard | deployed monitoring |
| Phase 11 | reviewed automation tooling and activation contract | active production automation |

Use the following result-label vocabulary consistently:

- inferential: only adjusted Phase 6 family results justified by the Holm or
  Benjamini–Hochberg procedure;
- exploratory: unadjusted or sensitivity output that is not the primary
  inferential claim;
- descriptive_only: coverage, diagnostics and Phase 8–9 comparisons;
- limited_diagnostic: the frozen Phase 7–9 artifact status caused by missing
  prospectively captured PM/history and forecast-weather evidence.

Do not promote an exploratory result into a headline claim merely because it is
large or visually interesting.

## 6. Work packages

### Work package A — Repository and evidence audit

1. Inspect git status --short --branch, git log -3 --oneline --decorate,
   git diff --check and remote alignment.
2. Confirm that no user changes overlap the planned files.
3. Locate the authoritative Phase 5–9 output directories and verify that their
   SUCCESS.json, summary manifests and referenced hashes are present.
4. Record the Phase 10 dashboard digest before any dashboard-facing change.
5. Build a phase-to-artifact table for final documentation. Include the exact
   authoritative artifact path, status, purpose and limitation for each phase.
6. Stop if the baseline is dirty in an unexplained way, if an authoritative
   artifact is missing, or if an input hash does not match its verification
   record. Report the discrepancy instead of repairing historical evidence.

Expected audit output:

- a short evidence inventory in the Phase 12 verification record;
- no source-code or data mutation;
- a clear list of files the agent owns for the rest of the task.

### Work package B — Portfolio narrative and results story

Update README.md only after the evidence audit. Keep the opening section short
and reader-oriented, then make the following information easy to find:

1. project question and geographic/sensor scope;
2. source separation and data-quality boundaries;
3. phase roadmap with Phases 1–12 status;
4. authoritative results and evidence paths;
5. dashboard launch instructions;
6. reproducibility instructions;
7. operational status and explicit non-goals;
8. remaining next steps.

Explain that the project has two completion levels:

- the local research and portfolio system is complete through Phase 11;
- Phase 12 portfolio polish is the remaining planned roadmap work;
- operational activation and prospective captured-data evaluation are separate
  future gates, not silently included in “complete.”

Recommended README structure:

1. one-paragraph project summary;
2. current status banner;
3. key findings and evidence limits;
4. local dashboard preview/runbook;
5. phase roadmap;
6. reproducibility and verification commands;
7. limitations and future work.

Do not add numerical results unless the value can be traced to an authoritative
artifact and the label is explicit. Preserve the existing Phase 6 wording that
the estimates are sensor-level associations, not city-wide or causal claims.

### Work package C — Reproducible portfolio walkthroughs

Create a small, focused set of executable walkthrough artifacts. Prefer a
minimal dependency footprint and reuse existing deterministic builders and
read-only runners.

First inspect whether a usable notebook execution environment is already
available. Do not install Jupyter or other packages automatically.

Choose one implementation form:

1. real .ipynb notebooks executed with existing local tooling;
2. cell-delimited Python walkthroughs that run with the existing environment
   and generate Markdown/HTML evidence;
3. another repository-native executable report format, documented explicitly if
   notebook execution is unavailable.

Preferred walkthrough set:

- 01_data_quality_and_eda: frozen window, source separation, coverage gaps,
  daily qualification and descriptive EDA;
- 02_sensor_associations: predeclared Phase 6 estimands, adjusted estimates,
  block-bootstrap uncertainty and multiple-testing labels;
- 03_feature_baseline_ml_contract: Phase 7 availability policy, Phase 8
  baselines and Phase 9 model comparison, emphasizing why feature/weather
  models are unavailable in the frozen captured artifact;
- 04_dashboard_and_reproducibility: build/serve instructions, bundle identity,
  static-server boundary and selected screenshots.

Each walkthrough must:

- read only pinned local artifacts;
- avoid network and database access;
- avoid .env and credentials;
- verify input hashes before presenting results;
- use deterministic ordering and stable output paths;
- identify the artifact version and frozen window;
- distinguish unavailable values from zero or fabricated values;
- preserve source labels and Vietnam-local date interpretation;
- emit compact human-readable results and machine-readable metadata;
- record the command used to execute it;
- fail closed on missing or mismatched inputs.

Do not duplicate analytical engines in notebook cells. Call existing read-only
modules or consume authoritative outputs. These walkthroughs are a
presentation layer, not a second statistical implementation.

Recommended locations:

- source walkthroughs under notebooks/ or reports/portfolio/;
- generated outputs under a new dated directory such as
  docs/verification/phase_12_portfolio_YYYY-MM-DD/;
- no generated output may overwrite an existing artifact.

Decide and document whether generated outputs are committed, ignored, or
retained only as local evidence. Do not add large or secret-bearing files
without checking repository policy.

### Work package D — Curated results summary

Create a concise portfolio-facing results document, preferably
reports/portfolio_summary.md or docs/portfolio_summary.md.

It must include:

1. Data scope: two measured low-cost sensors, one 90-day frozen window and
   separate modeled/reanalysis streams.
2. Phase 4–5 evidence: coverage, gaps and EDA limitations.
3. Phase 6 primary results: wind-speed association, humidity association and
   site contrast, with adjusted labels and correct sensor-level scope.
4. Phase 6 secondary findings only where the BH/FDR label and exploratory status
   are retained.
5. Phase 7 feature contract: captured versus assumed availability, exact
   horizons, purge/split rules and zero-captured-evidence limitation.
6. Phase 8 baseline status: available and unavailable cells, no fabricated
   scores, train-only fitting and descriptive-only interpretation.
7. Phase 9 model status: declared feature/model families, calendar-only
   diagnostics, unavailable history/weather paths and no forecast-skill claim.
8. Phase 10 dashboard description and local launch command.
9. Phase 11 automation status: tooling delivered, activation not performed.
10. Remaining work: Phase 12 completion, optional activation and prospective
    collection before real feature evaluation.

Every headline number must have an adjacent artifact path or link to its
verification record. Avoid copying large JSON payloads into prose.

### Work package E — Screenshots and visual evidence

Produce a small curated screenshot set from the existing local dashboard:

- desktop overview;
- air-quality view with a station/date filter;
- model-diagnostics view showing the limited-diagnostic state;
- methods/provenance view;
- one narrow/mobile layout showing responsive behavior.

Use the existing local server and browser verification tooling. Keep the server
loopback-only. Do not add remote fonts, analytics, map tiles or CDN assets.

For each screenshot, record:

- viewport size;
- dashboard bundle identity;
- browser/tool command;
- capture date/time as evidence metadata, not dashboard data;
- the fact that the screenshot is a static view of frozen artifacts.

Do not alter the dashboard merely to make screenshots look more favorable. If
visual defects are found, make only scoped accessibility/layout fixes and rerun
Phase 10 dashboard tests plus Phase 12 checks.

### Work package F — Portfolio runbook

Create or update docs/portfolio_runbook.md with exact, safe commands for a new
reader:

1. repository and environment prerequisites;
2. offline test suite;
3. isolated PostgreSQL test suite;
4. dashboard bundle reproduction into a new output path;
5. local dashboard launch;
6. browser verification, if optional tooling exists;
7. walkthrough/report execution;
8. links to authoritative phase verification documents;
9. explicit warning that live ingestion, Supabase and scheduler activation are
   not part of portfolio reproduction.

Use source-mode commands where the installed entry point may lag:

~~~bash
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
python3 -B scripts/build_dashboard.py --output /private/tmp/vietnam-air-replay.json
python3 -B scripts/serve_dashboard.py
~~~

The runbook must never instruct a reader to source .env for portfolio
reproduction. If an operational runbook is linked, label it as an
authorization-gated activation document and link to docs/operations.md.

### Work package G — Phase 12 verification record

Create docs/verification/phase_12.md after implementation. It must contain:

- scope and non-scope;
- baseline commit and worktree state;
- files added/changed;
- walkthrough commands and output locations;
- screenshot evidence and viewport list;
- deterministic-output checks;
- dashboard digest before/after;
- test commands and exact observed counts;
- git diff --check result;
- frozen-artifact immutability check;
- limitations, failed/blocked checks and causes;
- final status: delivered, partial or blocked.

Do not call Phase 12 complete if a required walkthrough was not executed, if
screenshots were not captured or if deterministic verification was skipped. Use
partial and list exact missing evidence when optional tooling is unavailable.

## 7. Verification plan

### Gate 0 — Authority and scope

Pass criteria:

- required reading completed;
- current commit and remote alignment recorded;
- no .env access;
- authoritative artifact inventory complete;
- frozen input digests recorded;
- planned file ownership does not overlap unexplained user changes.

### Gate 1 — Narrative and analytical integrity

Pass criteria:

- every numerical claim maps to an authoritative artifact;
- Phase 6 adjusted/inferential labels are correct;
- Phase 7–9 limitations remain visible;
- measured, reanalysis, forecast and modeled streams remain separate;
- no claim says “best model,” “accurate forecast,” “causal effect,” “production
  ready” or equivalent without evidence that does not currently exist;
- README, portfolio summary and dashboard text agree on project status.

### Gate 2 — Reproducibility

Run the walkthroughs from the documented commands. Confirm:

- no network requests;
- no database connection;
- no credential reads;
- input hashes are checked;
- repeated execution produces byte-identical machine-readable outputs where
  deterministic output is promised;
- output paths are new and existing evidence is not overwritten;
- unavailable cells remain null/unavailable with reasons.

If a notebook framework is used, execute from a clean kernel/environment and
record the exact tool version. If notebook execution is unavailable, use the
approved repository-native fallback and document the limitation.

### Gate 3 — Dashboard visual evidence

Run:

~~~bash
PYTHONPATH=src .venv/bin/python -B -m unittest tests.test_dashboard tests.test_dashboard_server -v
python3 -B scripts/build_dashboard.py --output /private/tmp/vietnam-air-replay.json
cmp dashboard/data/dashboard.json /private/tmp/vietnam-air-replay.json
~~~

If browser tooling is available, run the existing UI check into a new temporary
directory. Confirm the required views, filters, table fallbacks, keyboard
accessibility, responsive layout, reduced motion and no-external-network
behavior.

Do not accept a changed dashboard bundle digest without identifying the exact
intended source change and updating the verification record. A portfolio-only
documentation change should leave the digest unchanged.

### Gate 4 — Repository closeout

Run:

~~~bash
git diff --check
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -v
PYTHONPATH=src .venv/bin/python -B scripts/test_database.py
~~~

Then inspect:

~~~bash
git status --short --branch
git diff --stat
git diff -- README.md docs/portfolio_runbook.md docs/portfolio_summary.md docs/verification/phase_12.md
~~~

If application code or dashboard assets changed, rerun the relevant focused
tests and verify the Phase 10 public bundle contract. If only documentation and
new portfolio artifacts changed, still run the full offline suite and isolated
database suite because the repository instructions require both gates.

## 8. Frozen-artifact protection

Before finalizing, compare the worktree diff against these protected areas:

- docs/verification/phase_4*;
- docs/verification/phase_5*;
- docs/verification/phase_6*;
- docs/verification/phase_7*;
- docs/verification/phase_8*;
- docs/verification/phase_9*;
- dashboard/data/dashboard.json, unless a deliberate dashboard fix is in
  scope and its digest is reverified;
- existing Phase 10 verification evidence;
- existing Phase 11 verification evidence and automation configuration.

Do not rewrite, normalize, reformat or regenerate frozen JSON/CSV/PNG evidence
just to make it easier to cite. Add a new portfolio-facing summary instead.

## 9. Stop conditions

Stop and report a blocker if:

- an authoritative artifact hash fails;
- the dashboard bundle cannot be reproduced;
- a walkthrough requires live credentials, network access or a project database;
- a requested result cannot be traced to a pinned artifact;
- the agent discovers a scientific contradiction between planned narrative and
  verification records;
- the current branch contains unexplained user changes in the same files;
- completing the task would require installing a scheduler, touching Supabase,
  creating a role, changing RLS or adding a paid/external service;
- a required browser/notebook tool is missing and no safe fallback can establish
  the required evidence.

Do not work around a stop condition by weakening a hash check, suppressing a
test, replacing a missing value or labeling a diagnostic as a result.

## 10. Definition of done

Phase 12 is complete only when all of the following are true:

- README.md tells a coherent, evidence-backed project story;
- a reader can follow docs/portfolio_runbook.md without credentials or a live
  database;
- the portfolio summary links every headline result to authoritative evidence;
- walkthrough artifacts execute successfully or their fallback/limitation is
  explicitly recorded;
- screenshots cover desktop and narrow layouts and show the
  limited-diagnostic boundary honestly;
- the local dashboard remains static, read-only and hash-verified;
- no frozen Phase 4–10 evidence was changed unintentionally;
- no live operation, scheduler installation, migration, role/RLS change or
  secret exposure occurred;
- focused dashboard checks, full offline tests, isolated PostgreSQL tests and
  git diff --check pass;
- docs/verification/phase_12.md records exact evidence and remaining limits;
- final status distinguishes portfolio complete from operational activation
  pending and prospective captured-data evaluation pending.

## 11. Handoff format for the next agent

At the end of the task, report:

1. files added and modified;
2. whether Phase 12 is delivered, partial or blocked;
3. exact commands run and observed outcomes;
4. artifact paths and screenshot paths;
5. dashboard digest before and after;
6. protected artifacts confirmed unchanged;
7. limitations or missing optional tooling;
8. explicit confirmation that no .env, live service, scheduler, migration,
   role, RLS change or real backup was touched.

Do not commit or push unless the user separately requests it. If a commit is
requested later, use a focused message such as Complete Phase 12 portfolio polish
and verify worktree and remote state after the operation.
