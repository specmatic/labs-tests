# README Metadata Schema

This file documents the YAML front matter options currently recognized by `labs-tests` for lab `README.md` files.

The goal is to keep this small, accurate, and aligned with the code that parses and validates lab READMEs today.

## Team convention

Use README metadata only when the default behavior needs to be overridden.

That means:
- do not restate defaults in a lab README
- do not add metadata just for completeness
- if a lab follows the default behavior, omit the key entirely

Examples:
- good: `reports.ctrf: false`
- good: `test_counts: false`
- avoid: `reports.ctrf: true` when `true` is already the default
- avoid: `reports.console_summary: true` when `true` is already the default

## Where it lives

Place the metadata in YAML front matter at the top of the lab README:

```yaml
# No metadata needed when the lab uses all defaults
```

## Schema model

There is only one supported README schema now: the current canonical schema used by `labs-tests`.

That means:
- lab READMEs do not need a schema version marker
- if a lab uses only default behavior, it does not need any YAML front matter at all
- metadata should be added only for real overrides

## Supported global options

### `reports`

Controls which report sources are expected for comparison and artifact validation.

Example override:

```yaml
reports:
  ctrf: false
  html: false
```

Supported keys recognized by the current code:
- `ctrf`
- `html`
- `readme_summary`
- `console_summary`

Preferred value type:
- boolean

Recommended usage:

```yaml
reports:
  ctrf: false
  html: false
```

Notes:
- Only set `reports.*` when you need to override the default.
- The active labs currently override only `ctrf` and `html`.
- `readme_summary` and `console_summary` are still recognized by the code, but no current lab in `labs-tests` overrides them.

For `ctrf` and `html`, the comparison/artifact path also supports this object form:

```yaml
reports:
  ctrf:
    expected: false
    expected_failure: true
  html:
    expected: false
    expected_failure: true
```

Meaning:
- `expected: true`
  - the artifact is required
- `expected: false`
  - the artifact is optional / not required
- `expected_failure: true`
  - the artifact is expected to be absent

Notes:
- The object form is recognized by the artifact comparison logic.
- No current lab in `labs-tests` uses the object form.
- For `readme_summary` and `console_summary`, use booleans.

### `test_counts`

Default:

```yaml
test_counts: true
```

Use this only when test-count comparison should be disabled for the lab.

Example:

```yaml
test_counts: false
```

Purpose:
- Disables README / console / CTRF / HTML test-count comparison for the lab.
- Causes the test-count report to render those sources as `Not Applicable`.
- Keeps the comparison row visible as `Expected` instead of treating missing counts as a failure.

## Minimal recommended example

The minimum canonical README should have no front matter when no overrides are needed:

```yaml
# No metadata needed when the lab uses all defaults
```

Add more metadata only when a default behavior needs to change.

## Example with optional reports and disabled test counts

```yaml
---
reports:
  ctrf: false
  html: false
test_counts: false
---
```

## Recognized but not currently used by active labs

These are still recognized in code, but none of the current `labs-tests` harnessed labs rely on them today:

- `reports.ctrf/html` object form with `expected` / `expected_failure`
- `reports.readme_summary`
- `reports.console_summary`

Also note:
- hidden `phase-meta` YAML comments are no longer the source of truth for active phase parsing
- phase-level `expected_reports` are not currently populated by the active phase parser

If you want any of those to become first-class supported options, they should be added in `labs-tests` and then documented here.

## YAML parser limitations

`labs-tests` uses a small built-in YAML parser for README front matter.

Safe patterns:
- mappings
- nested mappings
- lists
- booleans
- strings
- integers

Prefer simple YAML like the examples in this file.

## Keeping this file up to date

This file is part of the working contract between `labs` and `labs-tests`.

Whenever any of these change, update this file in the same change:
- a lab README adds, removes, or changes metadata
- `labs-tests` starts supporting a new metadata key
- `labs-tests` stops using a metadata key
- the default behavior for an existing key changes

Required update checklist:
1. Update the key description in this file.
2. Update the examples if needed.
3. Update the `Current usage in labs` table.
4. Update tests if the supported behavior changed.

Recommended rule for the team:
- treat this file as the human-readable source of truth for supported README metadata
- treat the tests and parser code as the executable source of truth
- keep both aligned in the same PR

## Current metadata usage in active labs-tests labs

These are the labs in the current `labs-tests` harness set whose README metadata actively changes validation or comparison behavior.

| Lab | Metadata used | What it changes |
|---|---|---|
| `external-examples` | `reports.ctrf: false` | CTRF is not required for this lab. |
| `external-examples` | `reports.html: false` | Specmatic HTML report is not required for this lab. |
| `partial-examples` | `reports.ctrf: false` | CTRF is not required for this lab. |
| `partial-examples` | `reports.html: false` | Specmatic HTML report is not required for this lab. |
| `backward-compatibility-testing` | `test_counts: false` | Test-count comparison is disabled and shown as not applicable. |
| `continuous-integration` | `test_counts: false` | Test-count comparison is disabled and shown as not applicable. |
| `data-adapters` | `test_counts: false` | Test-count comparison is disabled and shown as not applicable. |
| `quick-start-mock` | `test_counts: false` | Test-count comparison is disabled and shown as not applicable. |

Labs in the sibling `labs` repo that still carry metadata but are not part of the active `labs-tests` harness set should not be treated as active examples for this file.
