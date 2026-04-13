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

Be careful about report layout variants:

- synchronous HTTP labs often emit reports under `build/reports/specmatic/test/...`
- async labs may emit reports under `build/reports/specmatic/async/...`
- MCP-style labs may emit HTML reports that are human-readable only and do not embed a `const report = ...` payload
- some validation-only labs do not emit Specmatic reports at all; in those cases, rely on console output plus captured source/example snapshots instead of forcing artifact assertions that the lab never generates
- some labs create new files only in the fixed state, such as generated dictionaries or newly added external examples; the scaffold should manage those as first-class lab files and restore/delete them when the run completes

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

If an HTML report does not contain an embedded Specmatic payload, do not crash shared parsing logic. Fall back to JSON artifacts or skip HTML-structure-dependent comparisons for that lab while still asserting that the HTML file exists.

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

## Docker-owned artifact cleanup

Many Specmatic labs generate `build/` outputs as `root` inside Docker containers. Do not delete those directories with a plain `shutil.rmtree()` in lab code.

Rules:

- for Docker Compose-based labs, always tear containers down before clearing prior reports
- use shared helpers from `lablib/scaffold.py` for cleanup instead of ad hoc file deletion
- prefer a non-fatal cleanup path (`docker compose down -v` followed by best-effort `rmtree(..., ignore_errors=True)`) so CI does not crash on Docker-owned files
- apply the same cleanup pattern to every new Docker-based lab from the start

Also note:

- if consolidated metadata depends on `../labs`, compute it after setup/clone has completed, not before

## Report-only refresh behavior

Every lab runner should support rebuilding reports from existing artifacts without rerunning the lab.

Requirements:

- do not invoke Docker
- do not modify upstream lab files
- rebuild `report.json` and `report.html` from captured artifacts and logs
- preserve the same validations as a normal run
- if required saved artifacts are missing, do not crash the runner; generate a failed phase/report entry that explains what is missing and how to regenerate it

## Consolidated report expectations

`run_all.py` should:

- discover all lab folders containing `run.py`
- run or refresh each lab
- write root consolidated JSON and HTML reports
- link correctly to per-lab reports using paths relative to `output/consolidated-report.html`

## Close-out requirements

After adding or changing any lab automation, refresh all affected project artifacts before considering the task complete.

Always update:

- the changed lab's `README.md`
- the root `README.md` when the set of automated labs or supported commands changes
- the changed lab's `output/report.json`
- the changed lab's `output/report.html`
- root `output/consolidated-report.json`
- root `output/consolidated-report.html`
- root comparison outputs when lab inventory or comparison inputs changed:
  - `output/labs-comparison.json`
  - `output/labs-comparison.html`

Preferred close-out command from the repo root:

- `python3 run_all.py --refresh-report`

Use that refresh step even when implementation work was completed earlier in the session, so READMEs and generated reports do not drift.

## CI consistency rules

- For git-based labs that compare against a base branch inside Docker, do not depend on a symbolic ref like `origin/main` being available inside the container. Resolve the base revision on the host with `git rev-parse`, create a stable internal ref such as `refs/labs-tests/base-main` with `git update-ref`, and pass that ref into the tool instead of a raw SHA.
- When Specmatic emits multiple report layers for the same phase, do not assume they all use the same counting semantics. Validate each layer against its actual meaning.
- In particular, do not force top-level `specmatic.html` totals to equal CTRF `tests` if `specmatic.html` excludes skipped tests. Compare:
  - `success`, `failed`, `errors`, and `skipped` to their expected values
  - `total` to `success + failed + errors`
- Do not require `coverage_report.json` and `specmatic-report.html` to have identical operation lists when the HTML intentionally includes additional `not covered` rows. Instead:
  - validate each artifact against the expected rows for that artifact
  - validate that overlapping operation rows agree on status and count

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
