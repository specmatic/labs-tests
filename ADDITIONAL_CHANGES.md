# Suggested Additional Changes

## labs-tests

Recommended updates to support the README-driven contract:

### Add README hygiene validation

Validate:
- mandatory phases exist
- valid phase ordering
- only H2 phase headings are used
- Task phases start with `Task `

### Add README phase parser

Derive:
- Baseline Phase
- Task phases
- Studio Phase
- Final Phase

directly from README headings.

### Add executable command extraction

Use fenced `shell` blocks inside phases.

### Add expected output extraction

Use fenced `terminaloutput` blocks inside phases.

### Remove lab-name hardcoding

Execution should be README-driven rather than:

```python
if lab_name == "...":
```

### Continue supporting existing validations

Existing validations should remain:
- command fencing
- test counts
- artifact checks
- license checks
- report checks

but should operate on README-derived execution.

# Update Notes

## README_METADATA_SCHEMA.md

Updated based on latest guidance:
- Studio Phase may appear anywhere between Baseline Phase and Final Phase.
- Studio Phase may appear multiple times.
- Any fenced `shell` block inside a phase is runnable.
- A phase may contain one or more runnable commands.
- Runnable commands do not need a following `terminaloutput` block.
- Content may exist between a command and relevant output.
- Removed the "Existing Validation Support" section.

## Lab READMEs

The lab README content has been preserved as much as possible.
Only phase headings were updated and, where required, sections were moved to satisfy the proposed phase model.
