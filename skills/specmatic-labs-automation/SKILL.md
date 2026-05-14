---
name: specmatic-labs-automation
description: Use when migrating or extending labs-tests with the clean-slate README-driven runner. Covers the current shared execution model, fallback phase discovery, reporting behavior, and the default lab-revert flow for this repo.
---

# Specmatic Labs Automation

Use this skill when working in `labs-tests` to add or update labs under the current README-driven model.

## Current model

1. `run_all_labs.py` is the entrypoint.
2. Do not add or restore per-lab `run.py`.
3. The upstream lab README in `../labs/<lab>/README.md` is the source of truth.
4. Execute shell commands from the README.
5. Validate the corresponding `terminaloutput` when required.
6. Treat phase-sequence issues as test failures, not execution blockers.

## Execution rules

- Execute commands from README sections, not from lab-specific Python hooks.
- Prefer shared parsing and shared runner logic over per-lab code.
- If a README does not follow the ideal `Baseline -> Task A/B/... -> Final` structure, still execute the detected shell-command phases in README order.
- Use the nearest preceding H3, or H2 if no H3 applies, as the phase/report section label.
- Skip Studio-only phases in CLI automation.
- Do not execute teardown-only commands such as `docker compose down -v` as implementation steps.
- Commands that do not require `terminaloutput` may still need to execute. Do not equate “no output required” with “skip execution.”

## Validation rules

- The main validations are command fencing and test counts.
- A missing ideal phase sequence should fail validation, but must not stop later phases from running.
- `terminaloutput` is optional for:
  - teardown commands
  - startup commands that are clearly service startup only
  - alternative commands
- Treat small wording variants around alternative commands as equivalent when the nearby prose contains both `alternative` and `command`.
- If test counts are absent in the README for a phase, they must also be absent in console/CTRF/HTML for that phase. That is a pass.
- If test counts are absent in the README but present in console/CTRF/HTML, that is a mismatch.

## README guidance

- Keep README changes minimal.
- Prefer parser improvements over adding heavy metadata.
- Only change the upstream README when something is genuinely required for execution or validation.
- If a phase contains a command that should be executable, ensure the README has the command in a `shell` fence.
- Add a `terminaloutput` block only when that command is expected to have one under the shared rules.

## Revert behavior

- Each lab run should revert changes made in the sibling `../labs/<lab>` directory after the report is written.
- This revert must happen even if the lab fails mid-run.
- This is the default behavior. Do not add an opt-in flag for it.

## Reporting

- Keep comparison reports aligned with the README-driven runner.
- Do not bring back the heading-structure comparison report.
- If the implementation-phase structure is imperfect, report it as a README validation issue while still executing what can be executed.

## Team defaults

- Keep methods small and well-named.
- Avoid “magic” runtime overrides unless explicitly requested.
- Keep shared behavior in `lablib/`.
- Favor shared parser/runner changes that unlock multiple labs at once.
- After making changes, always include concise commit message suggestions.
