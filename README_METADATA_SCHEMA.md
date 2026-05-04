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
- good: `expected_missing_test_counts: true`
- avoid: `reports.ctrf: true` when `true` is already the default
- avoid: `reports.console_summary: true` when `true` is already the default

## Where it lives

Place the metadata in YAML front matter at the top of the lab README:

```yaml
---
lab_schema: v2
reports:
  ctrf: true
  html: true
  readme_summary: true
  console_summary: true
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

Use this when the README needs additional phase ids to be recognized by the current parser.

Example:

```yaml
required_phases:
  - baseline
  - intermediate
  - final
```

Purpose:
- Helps the README parser recognize additional H3 phase ids.
- Defaults to:

```yaml
required_phases:
  - baseline
  - final
```

Important note:
- Today, `required_phases` is the parser hint that determines which H3 titles are recognized as phases.
- If you introduce additional phase ids like `intermediate` or `studio`, include them here.

### `phases`

Some current READMEs also use:

```yaml
phases:
  - baseline
  - intermediate
  - final
```

Current status:
- This is used by parts of the phase-sequence validation/reporting path.
- Keep it aligned with `required_phases` for now if you use it.

Recommended safe pattern today:

```yaml
required_phases:
  - baseline
  - intermediate
  - final
phases:
  - baseline
  - intermediate
  - final
```

## Minimal recommended example

No metadata at all, unless the lab needs an override.

If a lab follows all defaults, prefer an empty front-matter set:

```md
# Lab Title
```

Add YAML front matter only when one or more defaults need to change.

## Example with optional reports and expected missing counts

```yaml
---
lab_schema: v2
reports:
  ctrf: false
  html: false
  readme_summary: true
  console_summary: true
expected_missing_test_counts: true
expected_missing_test_counts_reason: "This lab validates behavior but does not publish normal cross-source test-count summaries."
optional_components:
  overview_video: true
required_phases:
  - baseline
  - final
phases:
  - baseline
  - final
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

## Current usage in labs

These are the labs that currently use README metadata to override default behavior in a meaningful way.

| Lab | Metadata used | What it changes |
|---|---|---|
| `external-examples` | `lab_schema: v2` | Enables the canonical v2 README validation path. |
| `external-examples` | `reports.ctrf: false` | CTRF is not required for this lab. |
| `external-examples` | `reports.html: false` | Specmatic HTML report is not required for this lab. |
| `quick-start-api-testing` | `lab_schema: v2` | Enables the canonical v2 README validation path. |
| `quick-start-api-testing` | `phases: [baseline, intermediate, final]` | Extends the phase list beyond the default baseline/final flow. |
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

### Present in some READMEs, but not currently wired

These keys appear in current lab READMEs but do not actively change validator behavior today:

| Lab | Metadata present | Current status |
|---|---|---|
| `external-examples` | `overview_video: false` | Not currently consumed by the active validator. |
| `external-examples` | `test_counts: true` | Not currently consumed by the active validator. |

### Explicit but same as defaults

These are valid, but they currently restate the default behavior rather than overriding it:

| Lab | Metadata present |
|---|---|
| `quick-start-api-testing` | `reports.ctrf: true`, `reports.html: true`, `reports.readme_summary: true`, `reports.console_summary: true` |
| `order-bff` | `reports.ctrf: true`, `reports.html: true`, `reports.readme_summary: true`, `reports.console_summary: true` |
