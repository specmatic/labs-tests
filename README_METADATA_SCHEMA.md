# README Metadata Schema

This file documents the YAML front matter options currently recognized by `labs-tests` for lab `README.md` files.

The goal is to keep this small, accurate, and aligned with the code that parses and validates lab READMEs today.

## Team convention

Use README metadata only when the default behavior needs to be overridden.

That means:
- do not restate defaults in a lab README
- do not add metadata just for completeness
- if a lab follows the default behavior, omit the key entirely
- exception: keep `lab_schema: v2` because it is still the required schema marker for the v2 path

Examples:
- good: `reports.ctrf: false`
- good: `expected_missing_test_counts: true`
- avoid: `reports.ctrf: true` when `true` is already the default
- avoid: `reports.console_summary: true` when `true` is already the default

## Where it lives

Place the metadata in YAML front matter at the top of the lab README:

```yaml
---
lab_schema: v2
---
```

## Required key

### `lab_schema`

Use:

```yaml
lab_schema: v2
```

Purpose:
- Enables the canonical README structure validation path.
- Tells `labs-tests` to validate the README against the shared H2 sequence.

Note:
- This is currently still used by the code to opt a README into the canonical v2 path.
- It is not just a descriptive label.

## Supported global options

### `reports`

Controls which report sources are expected for comparison and artifact validation.

Example:

```yaml
reports:
  ctrf: false
  html: false
  readme_summary: true
  console_summary: true
```

Supported keys:
- `ctrf`
- `html`
- `readme_summary`
- `console_summary`

Preferred value type:
- boolean

Examples:

```yaml
reports:
  ctrf: true
  html: true
  readme_summary: true
  console_summary: true
```

```yaml
reports:
  ctrf: false
  html: false
  readme_summary: true
  console_summary: true
```

For `ctrf` and `html`, the comparison report also supports this object form:

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
- The object form is currently used by the artifact comparison logic.
- For `readme_summary` and `console_summary`, use booleans.

### `expected_missing_test_counts`

Use this when the lab intentionally does not produce normal test-count summaries across README / console / CTRF / HTML.

Example:

```yaml
expected_missing_test_counts: true
expected_missing_test_counts_reason: "This lab validates behavior, but it does not emit README/console/CTRF/HTML test-count summaries."
```

Purpose:
- Prevents the test-count comparison from treating missing counts as a normal failure.

Related key:
- `expected_missing_test_counts_reason`

### `expected_failure_mismatch`

Use this when a mismatch in pass/fail breakdown is intentional and should be treated as expected.

Example:

```yaml
expected_failure_mismatch: true
expected_failure_mismatch_reason: "This lab intentionally keeps a known mismatch between sources."
```

Purpose:
- Lets the comparison report treat certain count mismatches as expected instead of hard failures.

Related key:
- `expected_failure_mismatch_reason`

### `optional_components`

Currently supported:
- `overview_video`

Example:

```yaml
optional_components:
  overview_video: true
```

Purpose:
- Marks the overview video as optional.
- If the video is optional, the comparison/reporting path should not treat its absence as a failure.

Backward-compatible form still recognized:

```yaml
overview_video_optional: true
```

Preferred form:

```yaml
optional_components:
  overview_video: true
```

## Supported phase-related options

### `required_implementation_phases`

Use this to require additional phase kinds beyond the defaults.

Defaults always required:
- `baseline`
- `final`

Example:

```yaml
required_implementation_phases:
  - studio
```

Purpose:
- Extends the required phase kinds for README validation and comparison reporting.

### `required_phases`

This key is still recognized, but it is no longer the preferred way to model normal v2 labs.

Example:

```yaml
required_phases:
  - baseline
  - intermediate
  - final
```

Purpose:
- Legacy parser hint for recognized phase ids.
- Most v2 labs should not need this, because the parser already recognizes the built-in phase kinds:

```yaml
phases:
  - baseline
  - intermediate
  - studio
  - inspection
  - cleanup_verification
  - final
```

Important note:
- Prefer `phases` for the active comparison/profile path.
- Keep `required_phases` only if an older README or runner still depends on it.

### `phases`

Use this only when the README needs to narrow or override the default recognized phase ids.

```yaml
phases:
  - baseline
  - final
```

Current status:
- This is the active parser/profile hint for recognized phase ids.
- Most v2 labs do not need it, because the default recognized phase kinds are:

```yaml
phases:
  - baseline
  - intermediate
  - studio
  - inspection
  - cleanup_verification
  - final
```

- Use it when a lab intentionally supports a smaller phase set, such as `order-bff` using only `baseline`.

## Minimal recommended example

The minimum v2 README should keep only the required schema marker:

```yaml
---
lab_schema: v2
---
```

Add more metadata only when a default behavior needs to change.

## Example with optional reports and expected missing counts

```yaml
---
lab_schema: v2
reports:
  ctrf: false
  html: false
expected_missing_test_counts: true
expected_missing_test_counts_reason: "This lab validates behavior but does not publish normal cross-source test-count summaries."
optional_components:
  overview_video: true
---
```

## Not currently wired into the active validator

These keys or patterns appear in some READMEs, but they are not currently the source of truth for active validation behavior:

- `overview_video: false`
  - preferred instead:
    - `optional_components.overview_video: true`
    - or `overview_video_optional: true`
- `test_counts: true`
  - not currently consumed
- hidden `phase-meta` YAML comments
  - not currently used by the active phase parser
- phase-level `expected_reports`
  - not currently populated by the active phase parser

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

## Current metadata usage in labs

These are the labs that currently carry README metadata that actively affects validation or comparison behavior.

| Lab | Metadata used | What it changes |
|---|---|---|
| `external-examples` | `lab_schema: v2` | Enables the canonical v2 README validation path. |
| `external-examples` | `reports.ctrf: false` | CTRF is not required for this lab. |
| `external-examples` | `reports.html: false` | Specmatic HTML report is not required for this lab. |
| `quick-start-api-testing` | `lab_schema: v2` | Enables the canonical v2 README validation path. |
| `partial-examples` | `lab_schema: v2` | Enables the canonical v2 README validation path. |
| `partial-examples` | `reports.ctrf: false` | CTRF is not required for this lab. |
| `partial-examples` | `reports.html: false` | Specmatic HTML report is not required for this lab. |
| `order-bff` | `lab_schema: v2` | Enables the canonical v2 README validation path. |
| `order-bff` | `phases: [baseline]` | Uses a non-default phase list in the comparison/profile path. |
| `backward-compatibility-testing` | `expected_missing_test_counts: true` | Missing cross-source test counts are treated as expected. |
| `backward-compatibility-testing` | `expected_missing_test_counts_reason` | Provides the explanation shown in reports. |
| `continuous-integration` | `expected_missing_test_counts: true` | Missing cross-source test counts are treated as expected. |
| `continuous-integration` | `expected_missing_test_counts_reason` | Provides the explanation shown in reports. |
| `data-adapters` | `expected_missing_test_counts: true` | Missing cross-source test counts are treated as expected. |
| `data-adapters` | `expected_missing_test_counts_reason` | Provides the explanation shown in reports. |
| `quick-start-mock` | `expected_missing_test_counts: true` | Missing cross-source test counts are treated as expected. |
| `quick-start-mock` | `expected_missing_test_counts_reason` | Provides the explanation shown in reports. |

### Explicit but same as defaults

These are valid, but they currently restate the default behavior rather than overriding it:

| Lab | Metadata present |
|---|---|
| `order-bff` | `reports.ctrf: true`, `reports.html: true`, `reports.readme_summary: true`, `reports.console_summary: true` |
