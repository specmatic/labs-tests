---
name: specmatic-labs-automation
description: Use when adding or updating automation harnesses for Specmatic labs in this repo. Covers the standard per-lab folder structure, JSON-first validation strategy, report generation, setup/refresh behavior, README alignment checks, and consolidated reporting expectations established for labs-tests.
---

# Specmatic Labs Automation

Use this skill when working in the `labs-tests` repo to automate another Specmatic lab with the same conventions already established for `api-coverage`.

## Goal

Build a per-lab automation harness that:

- mirrors the upstream lab name as a top-level folder
- writes lab-local machine-readable and human-readable reports
- validates actual observed behavior, not just README claims
- captures before-fix and after-fix verification when the lab has a fix workflow
- contributes cleanly to the root consolidated report

## Expected repo shape

For each lab, create:

```text
<lab-name>/
  run.py
  README.md
  output/                  # generated, gitignored
```

Shared code belongs in `lablib/`.

Do not write generated outputs outside:

- `<lab-name>/output/`
- `output/` at the repo root

## Standard workflow

1. Inspect the upstream lab in `../labs/<lab-name>`.
2. Read the upstream README, but do not trust it as the source of truth.
3. Run the real lab and observe actual console output and generated artifacts.
4. Encode assertions from the observed behavior.
5. Add README drift validations to compare documentation with reality.
6. Generate:
   - `<lab-name>/output/report.json`
   - `<lab-name>/output/report.html`
7. Ensure the lab can participate in `run_all.py`.

## Validation rules

Prefer JSON-first assertions. Treat HTML as a user-facing artifact and as an additional verification source, not the primary source when machine-readable data exists.

Default verification sources:

- console output from `command.log`
- `coverage_report.json`
- `ctrf-report.json`
- generated Specmatic HTML report
- upstream lab README

Validate all relevant layers when applicable:

- command exit code
- console summaries and important failure phrases
- per-operation coverage status
- per-operation counts
- totals and coverage percentages
- report artifact existence
- README alignment with runtime behavior

Automation scope in this repo is CLI/runtime plus generated artifacts only.
Do not add Studio validation unless the user explicitly asks for Studio automation.

## Before/after phase pattern

When a lab has a broken state and a fixed state, represent it as two phases:

- `Baseline mismatch`
- `Fixed contract`

For both phases, validate:

- console output
- machine-readable reports
- Specmatic HTML report
- README expectations if the README documents that phase

Do not only validate the fixed state. Before-fix and after-fix checks should both be explicit.

## Console vs report consistency

When coverage or counts are shown in multiple places, compare them directly.

Add explicit validations for:

- console coverage summary vs `coverage_report.json`
- console coverage summary vs Specmatic HTML coverage
- console `#exercised` vs Specmatic HTML `Results`
- `coverage_report.json` count vs Specmatic HTML `Results`
- total console exercised count vs total Specmatic HTML results

If the runtime sources disagree, keep the failure. Do not normalize away the mismatch.

## README drift rules

README checks should confirm whether the README matches actual Specmatic output.

Rules:

- verify documented summaries against actual output
- verify documented path/status expectations against actual runtime status
- add failures when important runtime details are missing from the README
- prefer exact observed details over README wording when they differ

Example: if runtime shows `422 Unprocessable Entity` but README omits it, that should fail.

## Reporting expectations

Every lab report must produce:

- `report.json`
- `report.html`

The HTML report should support:

- category summaries
- drill-down details for validations
- failure index with jump links
- collapsible phase sections
- collapsible validation-category sections
- collapsible artifacts sections
- expand all / collapse all controls

Default load state:

- phase sections collapsed
- validation-category sections collapsed

Use `Validations` terminology consistently, not `Assertions`.

## Category model

Use categories like these where applicable:

- `command`
- `console`
- `report`
- `readme`
- `artifacts`
- `setup`

The category summary should link directly to the corresponding section in the report.

## Setup and refresh behavior

Root setup behavior is owned by `setup.py` and `lablib/workspace_setup.py`.

Important rules:

- safe setup must not discard `../labs` changes
- destructive refresh must require `--refresh-labs --force` when `../labs` is dirty
- lab runners should support setup skipping
- lab runners should support report-only refreshes from captured artifacts

Current command expectations:

- `python3 setup.py`
- `python3 setup.py --refresh-labs --force`
- `python3 <lab>/run.py`
- `python3 <lab>/run.py --refresh-report`
- `python3 run_all.py`
- `python3 run_all.py --refresh-report`

## Report-only refresh behavior

Every lab runner should support rebuilding reports from existing artifacts without rerunning the lab.

Requirements:

- do not invoke Docker
- do not modify upstream lab files
- rebuild `report.json` and `report.html` from captured artifacts and logs
- preserve the same validations as a normal run

## Consolidated report expectations

`run_all.py` should:

- discover all lab folders containing `run.py`
- run or refresh each lab
- write root consolidated JSON and HTML reports
- link correctly to per-lab reports using paths relative to `output/consolidated-report.html`

## Implementation checklist for a new lab

- create `<lab-name>/run.py`
- create `<lab-name>/README.md`
- reuse shared helpers from `lablib/` where practical
- store captured artifacts under `<lab-name>/output/`
- add JSON-first validations based on real observed behavior
- add console-vs-HTML consistency checks when the lab emits overlapping data
- add README drift validations
- support `--refresh-report`
- verify root `run_all.py` picks up the lab
- refresh the consolidated report

## Guardrails

- Do not edit `../labs` READMEs unless explicitly asked.
- Do not rely only on the upstream README to define expected behavior.
- Do not discard `../labs` changes unless the caller explicitly uses destructive refresh with force.
- Keep generated outputs out of git.
- Keep absolute filesystem paths out of repo README content; use relative links there.
