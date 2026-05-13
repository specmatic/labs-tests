---
name: specmatic-labs-automation
description: Use when working in the labs-tests repo to migrate labs toward README-driven automation, shared validation/config, minimal README metadata, shared hooks, Docker image override support, and consistent reports across the team.
---

# Specmatic Labs Automation

Use this skill when working in the `labs-tests` repo on:

- README-driven lab execution
- lab migration away from hard-coded `run.py` implementations
- shared config and shared hooks
- README validation and comparison reports
- pilot lab migrations
- Enterprise Docker image override support

This is the project-facing skill for teammates working on the same repo.

## Project goals

The target model is:

1. Labs should keep working correctly for any new Specmatic Enterprise release.
2. Most validations for new labs should happen automatically.
3. Custom hooks should be minimal, shared, named, and justified.
4. README annotations and metadata should stay minimal.
5. The lab README should be the main human and validation source of truth.

## Current direction

The current preferred architecture is:

- README = source of truth for:
  - phase structure
  - commands
  - expected output
  - test counts
  - visible learner guidance
- shared config = machine-readable declarative layer for:
  - files under test
  - artifact capture
  - fix summaries
  - shared runtime hook selection
  - phase hook names
- hooks = code only for:
  - real file transforms
  - implementation assertions
  - rare reusable wrappers
- README-driven pilot lab config lives under:
  - `lablib/lab_configs/<lab-name>/<lab-name>.yaml`
  - `lablib/lab_configs/<lab-name>/<lab-name>.py`

Do not move complex implementation behavior into README metadata.

## Implementation model

### 1. Prefer README-driven execution

Use `lablib/readme_runner.py` as the preferred execution path.

For a README-driven pilot or migrated lab:

- run through the root `run_all_labs.py`
- do not add or preserve a per-lab `run.py` wrapper
- the README should drive phases, commands, and expected counts
- declarative details should move into shared config
- only true behavior should remain in hooks

Legacy, non-migrated labs still run through `run_all.py` and their existing
per-lab `run.py` files until they are migrated.

### 2. Use central lab config for declarative data

For migrated labs, prefer shared config files under:

- `lablib/lab_configs/<lab-name>/<lab-name>.yaml`
- `lablib/lab_configs/<lab-name>/<lab-name>.py`

Use YAML for declarative wiring and the Python module for named transforms,
assertions, or shared helper hooks that cannot be expressed cleanly as data.

Good config candidates:

- files under test
- extra artifact specs
- fix summaries
- shared runtime env/value hooks
- phase-to-hook-name mappings

Bad config candidates:

- large implementation logic
- ad hoc scripting
- raw business logic encoded as data when code is clearer

### 3. Keep README metadata minimal

README metadata should exist only for:

- true overrides
- small execution hints that cannot be inferred from structure

Do not use README metadata for:

- file transforms
- artifact lists that belong in shared config
- implementation assertions
- repeated defaults

Treat `README_METADATA_SCHEMA.md` as the human-readable contract.

## Pilot migration rules

For pilot labs:

- run only through the root README-driven runner
- do not keep pilot-local `run.py`, `hooks.py`, or local test README files
- keep pilot config and hook code under `lablib/lab_configs/<lab-name>/`
- keep only transforms/assertions in hooks where possible
- verify that existing results do not change:
  - test counts
  - command/output fencing
  - artifacts
  - license reporting

When evaluating a pilot lab, classify every behavior into:

- shared parser behavior
- shared config
- shared named hook
- truly lab-specific hook

## Hooks policy

Hooks must be:

- rare
- named
- shared where feasible
- justified by behavior that cannot be expressed in the common contract

Good hook examples:

- deterministic file transforms
- implementation assertions
- special wrapper execution for unusual runtime flows

Bad hook examples:

- restating phase names already present in README
- hardcoding counts already present in README output blocks
- encoding artifact lists that can live in shared config
- duplicating command discovery that the README parser already performs

When a hook remains, document why it remains.

## Reports and validations

Keep shared validations centralized wherever possible:

- test counts
- command/output fencing
- artifacts
- license mode
- heading structure

Use standalone comparison reports for major shared validations.

Avoid duplicated validations where a shared README-driven validation already covers the same behavior.

Execution failures must fail the outer validation. If a phase has `Test
Execution Failed`, derive the reason from runtime report data, especially the
failed command assertion, actual exit code, expected exit code, and command.
Do not infer this reason from README metadata.

For README count validation:

- runnable command blocks should be fenced as `shell`
- expected output blocks should be fenced as `terminaloutput`
- do not treat `shell` blocks as expected terminal output

For README-driven pilot output:

- live lab output belongs under `output/<lab-name>-output/`
- report snapshots may be copied to `output/labs-output/<lab-name>-output/`
- legacy labs may continue using their existing output layout until migrated

## Docker rules

Do not add a shared Docker pull/build setup stage in `labs-tests`.

Rules:

- shared setup is only for the sibling `labs` repository lifecycle
  - clone
  - branch refresh
  - `license.txt` management
- each lab owns its own Docker execution flow
  - `docker compose`
  - `docker run`
  - Dockerfile-based runtime behavior

### Enterprise image override

Preferred direction:

- support a shared Specmatic Enterprise image override
- avoid per-lab ad hoc image replacement logic

For pilot labs, the current pattern is:

- `run_all_labs.py --enterprise-image <image-or-tag>`
- `SPECMATIC_ENTERPRISE_IMAGE`
- compose file uses:
  - `${SPECMATIC_ENTERPRISE_IMAGE:-specmatic/enterprise:latest}`

When adding this to more labs:

- keep the default unchanged
- make the override opt-in
- wire it through shared CLI/runtime handling
- pass the runtime command environment explicitly from `run_lab`
- do not read runner CLI arguments inside lower-level phase execution helpers

## GitHub Actions rules

Keep legacy and README-driven pilot automation separate:

- `labs-tests.yml` runs the legacy `run_all.py` flow
- `labs-tests-readme-pilot.yml` runs `run_all_labs.py`
- the README-driven pilot workflow currently targets:
  - `api-coverage`
  - `quick-start-api-testing`

For branch testing, a temporary branch-specific `push` trigger can be added to
the pilot workflow. Remove it before merge unless the team intentionally wants
that branch to stay as a CI trigger.

If `run_all_labs.py` exits before producing the consolidated report, the
workflow may create a minimal failed report so the job summary remains useful.
The actual runtime failure should still be captured in:

- `output/consolidated-report/run-all-labs.log`

## Team consistency rules

- Use one shared README structure across labs.
- Use one shared metadata schema reference file.
- Prefer shared config over repeated per-lab Python.
- Prefer shared hooks over bespoke per-lab wrappers.
- Keep docs, tests, and code aligned in the same change.
- When metadata or execution behavior changes, update:
  - code
  - tests
  - `README_METADATA_SCHEMA.md`
  - any related skill/docs content

## Cleanup expectations

When migrating a lab or removing old behavior, also add cleanup for:

- old metadata references
- duplicated `run.py` logic
- duplicated hook declarations
- stale docs/examples
- stale report wording
- tests that still encode old assumptions

Do not leave the old path and the new path both as primary implementations.

## Recommended workflow for a migrated lab

1. Read the upstream lab README.
2. Confirm phase extraction from the README.
3. Move declarative details into shared config.
4. Keep only true transforms/assertions in hooks.
5. Remove pilot-local wrappers or docs once the root runner owns the flow.
6. Verify comparison/report parity with the old implementation.
7. Add or update focused tests for the migrated shape.
8. Add cleanup tasks for any removed metadata or duplicated logic.

## Commit message rule

After making code or README changes, always include 1-3 concise git commit message suggestions grouped by logical change boundaries.
