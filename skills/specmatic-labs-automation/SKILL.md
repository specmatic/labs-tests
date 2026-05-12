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

Do not move complex implementation behavior into README metadata.

## Implementation model

### 1. Prefer README-driven execution

Use `lablib/readme_runner.py` as the preferred execution path.

For a migrated lab:

- `run.py` should be a thin wrapper only
- the README should drive phases, commands, and expected counts
- declarative details should move into shared config
- only true behavior should remain in hooks

### 2. Use central lab config for declarative data

For migrated labs, prefer shared config files under:

- `lablib/lab_configs/<lab-name>.yaml`

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

- keep `run.py` as a thin compatibility wrapper if discovery/reporting still expects it
- move declarative content out of `run.py` and preferably out of `hooks.py`
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

- `SPECMATIC_ENTERPRISE_IMAGE`
- compose file uses:
  - `${SPECMATIC_ENTERPRISE_IMAGE:-specmatic/enterprise:latest}`

When adding this to more labs:

- keep the default unchanged
- make the override opt-in
- wire it through shared CLI/runtime handling

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
5. Keep `run.py` thin or compatibility-only.
6. Verify comparison/report parity with the old implementation.
7. Add or update focused tests for the migrated shape.
8. Add cleanup tasks for any removed metadata or duplicated logic.

## Commit message rule

After making code or README changes, always include 1-3 concise git commit message suggestions grouped by logical change boundaries.
