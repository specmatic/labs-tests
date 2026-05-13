# README Metadata Schema

## Philosophy

The README is the primary source of truth for both humans learning the lab and `labs-tests` automating and validating the lab.

The automation model is convention-driven.

`labs-tests` should derive the following from the README structure instead of lab-name hard-coding:

- phase sequence
- runnable commands
- expected console output
- implementation phases
- validation phases
- cleanup commands

Metadata should only be used for:

- optional capabilities
- small overrides
- disabling validations that are not applicable for a specific lab

If a behavior can be derived from the README structure, commands, or fenced blocks, it should not be duplicated in metadata.

## Canonical README Structure

Every lab README should have the following phase model:

```text
Baseline Phase
Task ...
Task ...
Studio Phase
Studio Phase
Final Phase
```

Notes:

- `Baseline Phase` and `Final Phase` are mandatory.
- `Task ...` phases are optional.
- `Studio Phase` is optional.
- `Studio Phase` may appear multiple times.
- `Studio Phase` may appear anywhere between `Baseline Phase` and `Final Phase`.
- Additional non-phase sections may exist before, between, or after phases.

## Phase Model

`labs-tests` derives execution phases from H2 headings.

### Mandatory phases

```markdown
## Baseline Phase
## Final Phase
```

### Optional implementation phases

A phase is considered an implementation phase if:

- the heading level is H2
- the heading text starts with `Task `

Examples:

```markdown
## Task A: Fix matcher
## Task B: Add dynamic validation
```

### Optional Studio phases

A phase is considered a Studio phase if the H2 heading is:

```markdown
## Studio Phase
```

`Studio Phase` may appear one or more times, but it must always be after `Baseline Phase` and before `Final Phase`.

### Optional Studio subphases

A Studio subphase is any H3 (or lower) heading containing `Studio` inside a valid phase.

Examples:

```markdown
### Studio verification
### Studio validation
```

Rules:

- Studio subphases belong to the parent H2 phase.
- Studio subphases do not affect phase ordering validation.
- Studio subphases are optional.
- Studio subphases may contain runnable commands and `terminaloutput` blocks.
- Studio subphases are useful when Studio validation verifies the same state as the parent phase instead of representing an independent execution phase.

## Valid Phase Sequence

Rules:

- `Baseline Phase` must exist.
- `Final Phase` must exist.
- `Baseline Phase` must appear before `Final Phase`.
- No `Task ...` phase may appear before `Baseline Phase`.
- No `Task ...` phase may appear after `Final Phase`.
- No `Studio Phase` may appear before `Baseline Phase`.
- No `Studio Phase` may appear after `Final Phase`.
- Multiple `Task ...` phases are allowed.
- Multiple `Studio Phase` sections are allowed.
- Non-phase sections may appear anywhere and should not be treated as executable phases.

`labs-tests` should fail README hygiene validation if phase ordering is invalid.

## Runnable Commands

Any fenced `shell` block inside a phase is a runnable command.

A phase may contain one or more runnable commands.

A runnable command may or may not have a following `terminaloutput` block.

Examples:

```markdown
Run:

```shell
docker compose up api-test --build --abort-on-container-exit
```

Expected output:

```terminaloutput
Tests run: 4, Successes: 4, Failures: 0, Errors: 0
```

Clean up:

```shell
docker compose down -v
```
```

Rules:

- Every fenced `shell` block inside a phase should be considered executable.
- The command and its expected output do not need to be adjacent.
- There may be explanatory content or setup steps between a command and its expected output.
- Cleanup commands such as `docker compose down -v` are also runnable commands.
- A command without a following `terminaloutput` block should still be executed.
- A phase should pass only when all runnable commands and relevant validations for that phase pass.

## Expected Output Validation

Expected output must use fenced `terminaloutput` blocks.

Example:

```markdown
Expected output:

```terminaloutput
Tests run: 4, Successes: 4, Failures: 0, Errors: 0
```
```

Rules:

- `terminaloutput` blocks are validation expectations.
- A phase may contain zero, one, or many `terminaloutput` blocks.
- `labs-tests` should validate command output against the relevant `terminaloutput` blocks in the same phase.
- A `terminaloutput` block should not be required after every `shell` command.

## Metadata

Metadata should remain minimal.

Metadata exists only to indicate:

- optional capabilities not present in the lab
- small lab-specific overrides that cannot be derived automatically

Metadata should not duplicate:

- commands
- phase names
- expected outputs
- implementation steps
- validation logic already inferable from the README

## Metadata Format

Metadata is embedded as an HTML comment near the top of the README.

Example:

```markdown
<!--
reports:
  ctrf: false
  html: false

test_counts: false
-->
```

## Supported Metadata

### reports

Disable report validation if the lab does not generate reports.

Example:

```yaml
reports:
  ctrf: false
  html: false
```

Defaults:

```yaml
reports:
  ctrf: true
  html: true
```

### test_counts

Disable test count validation if the lab does not produce deterministic test counts.

Example:

```yaml
test_counts: false
```

Default:

```yaml
test_counts: true
```

### artifacts

Optional override for custom artifact validation.

Example:

```yaml
artifacts:
  - build/custom-report/index.html
```

### license

Optional override if the lab does not require enterprise license validation.

Example:

```yaml
license:
  required: false
```

Default:

```yaml
license:
  required: true
```

## Guiding Principle

README first.

Metadata only for exceptions.
