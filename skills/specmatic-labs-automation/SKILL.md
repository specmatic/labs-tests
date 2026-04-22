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

When a validation fails, the message must be explicit and actionable:

- state what failed in plain language
- state the impact of the failure, especially what the user cannot trust or cannot do next
- state the exact action needed to resolve the failure
- prefer concrete paths, commands, and missing artifacts over generic wording
- do not bury the fix inside raw log output or a vague summary

Automation scope in this repo is CLI/runtime plus generated artifacts only.
Do not add Studio automation unless the user explicitly asks for Studio automation, but it is acceptable to report whether a lab README documents a Studio component.

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
- when a README mismatch fails, explain the runtime impact and the README change needed to resolve it
- when a README documents commands, require OS-specific command sections for Windows, macOS, and Linux
- require OS-appropriate fenced block languages for those command sections: `shell`/`bash` for macOS and Linux, `powershell`/`cmd` for Windows
- require every documented command section to be followed by a console output snippet
- require OS-specific command sections to have matching OS-specific console output snippets
- require all README console output snippets to use `terminaloutput` fenced blocks
- when README console output includes timestamps, ignore the datetime stamp during comparison and focus on the meaningful output content
- when a README shows console output with file-system paths, require equivalent output sections for Windows, macOS, and Linux
- when README-documented Studio-only steps are not automated yet, record them as skipped or known limitations, not failures
- when a difference is intentional and should remain visible but non-blocking, record it as an expected difference, not a failure

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

Failure and warning text in the HTML report should also be explicit:

- every error should say what failed, what that means for the lab or report, and how to fix it
- warnings should say what extra or unexpected condition was found and why it matters
- avoid merging the action text into the raw console log output
- prefer separate labeled sections such as `Impact`, `Action required`, or `How to fix`
- skipped and expected validations should remain visible in the report, but they should not appear in the failure index

Default load state:

- phase sections collapsed
- validation-category sections collapsed

Use `Validations` terminology consistently, not `Assertions`.

Shared validation-state helpers:

- use `assert_skipped(...)` when a check is intentionally not implemented yet
- use `assert_expected(...)` when a difference is intentional and should not block the lab
- only `failed` validations should contribute to the failure index and failure totals

Expected-difference pattern:

- add `assert_expected(...)` inside the relevant phase `extra_assertions`
- keep the message explicit about why the difference is intentional
- include `detail(...)` items for reason and action
- prefer a stable `code` when the difference is likely to be referenced again

Expected missing test-count summaries:

- if a lab does not produce README/console/CTRF/HTML count summaries by design, set:
  - `expected_missing_test_counts=True`
  - `expected_missing_test_counts_reason="..."`
- this should make the comparison report show `Expected` for those phases instead of treating them as an unexplained absence

Hidden README ignore annotation pattern:

- use an HTML comment so nothing appears in the rendered README
- syntax:
  - `<!-- labs-tests: ignore readme.os_commands.coverage -->`
  - `<!-- labs-tests: ignore readme.command_output.followup readme.output.terminaloutput_fence -->`
- when present, the matching validation should become `skipped`, stay visible in the report, and not count as a failure
- structure-related ignore codes can include `readme.structure.required_h2_sections`, `readme.structure.required_h2_order`, and `readme.structure.unexpected_h2_sections`

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
- normal lab runs should clear the lab-local `output/` directory before generating new artifacts; refresh-only runs should skip that cleanup
- normal Docker-based lab runs should also do a best-effort runtime cleanup before the first phase and again after the lab completes, so stale containers, networks, or volumes do not leak into later results
- the upstream lab `README.md` is the source of truth; the console output and generated CTRF/Specmatic HTML reports should match it
- copied source snapshots such as specs, examples, and service files may be archived for inspection, but they should not be treated as primary pass/fail assertions on their own
- the shared README schema should live in one editable module: `lablib/readme_expectations.py`
  - `README_TEMPLATE` defines the shared H1/H2/H3 structure and section-level command/output rules
  - `LAB_README_OVERRIDES` defines lab-specific exceptions or manual Studio allowances
  - `EXPECTED_README_H2_SEQUENCE` is derived from the shared template and can continue to support compatibility checks

Current command expectations:

- `python3 setup.py`
- `python3 setup.py --refresh-labs --force`
- `python3 <lab>/run.py`
- `python3 <lab>/run.py --refresh-report`
- `python3 run_all.py`
- `python3 rebuild_reports.py`

README command and output fence expectations:

- use executable fenced blocks for commands:
  - `shell`, `bash`, `sh`, or `zsh` for macOS and Linux
  - `powershell`, `ps1`, `cmd`, or `bat` for Windows
- place a `terminaloutput` fenced block immediately after each documented command block
- when commands differ by OS, include a matching `terminaloutput` block for each OS-specific command

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
- clear the generated `output/labs/` and `output/consolidated-report/` folders before regenerating reports
- write root consolidated JSON and HTML reports
- link correctly to per-lab reports using paths relative to `output/consolidated-report/consolidated-report.html`

`rebuild_reports.py` should regenerate the consolidated and comparison reports in place without clearing the output tree, so existing lab snapshots remain available for report regeneration.

CI artifact upload must also follow discovery rather than a hardcoded lab list.

Rules:

- GitHub Actions report archiving must upload `output/` plus every top-level lab `output/` folder using a wildcard such as `*/output/`
- GitHub Actions job summary must read the consolidated payload from `output/consolidated-report/consolidated-report.json`
- when report locations change, update the GitHub Actions summary step in `.github/workflows/labs-tests.yml` in the same change so CI summaries do not silently stop rendering
- the GitHub Actions summary should mention both the consolidated report and comparison report locations when they are available
- do not hardcode only the labs that existed at one point in time, because new lab reports will then be missing from the archived artifact and consolidated report links will fail for downloaded reports
- after adding a new lab harness, verify that its `output/report.json` and `output/report.html` are both included by the artifact upload pattern
- in the comparison report, be explicit about counting scope:
  - artifact availability rows such as `Generated artifacts include ctrf-report.json` and `Generated artifacts include the sibling Specmatic HTML report` are counted per lab
  - count-consistency details such as `Test counts match across the README, console output, CTRF JSON, and Specmatic HTML` may show `not-available` per phase
  - do not compare those two counts directly without normalizing them to the same unit first
  - when a source is absent, show `not-available` rather than `missing` so the report distinguishes unavailable data from a true mismatch

## Close-out requirements

After adding or changing any lab automation, refresh all affected project artifacts before considering the task complete.

Always update:

- the changed lab's `README.md`
- the root `README.md` when the set of automated labs or supported commands changes
- the changed lab's `output/report.json`
- the changed lab's `output/report.html`
- root `output/consolidated-report/consolidated-report.json`
- root `output/consolidated-report/consolidated-report.html`
- root comparison outputs when lab inventory or comparison inputs changed:
  - `output/consolidated-report/labs-comparison.json`
  - `output/consolidated-report/labs-comparison.html`

Preferred close-out command from the repo root:

- `python3 rebuild_reports.py`

Use that refresh step even when implementation work was completed earlier in the session, so READMEs and generated reports do not drift.

Before closing a task that changes the automated lab inventory, also check:

- the GitHub Actions workflow artifact upload still archives every lab report
- the GitHub Actions workflow summary still renders from the current consolidated report path
- the new lab folder is tracked in git; locally generated reports alone are not enough for CI to discover a new harness

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
