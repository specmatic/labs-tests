# labs-tests

Automation harnesses for Specmatic labs live in lab-named folders in this repo.

Current automation scope validates CLI/runtime behavior and generated artifacts.
It does not automate Specmatic Studio flows, but the comparison report can indicate whether a lab README documents a Studio component.

Prerequisites:

- Python `3.14.x`
- Docker with the daemon running
- sibling upstream checkout at `../labs`

Current labs:

- [`api-coverage`](api-coverage/)
  README: [`api-coverage/README.md`](api-coverage/README.md)
- [`api-resiliency-testing`](api-resiliency-testing/)
  README: [`api-resiliency-testing/README.md`](api-resiliency-testing/README.md)
- [`api-security-schemes`](api-security-schemes/)
  README: [`api-security-schemes/README.md`](api-security-schemes/README.md)
- [`async-event-flow`](async-event-flow/)
  README: [`async-event-flow/README.md`](async-event-flow/README.md)
- [`backward-compatibility-testing`](backward-compatibility-testing/)
  README: [`backward-compatibility-testing/README.md`](backward-compatibility-testing/README.md)
- [`continuous-integration`](continuous-integration/)
  README: [`continuous-integration/README.md`](continuous-integration/README.md)
- [`data-adapters`](data-adapters/)
  README: [`data-adapters/README.md`](data-adapters/README.md)
- [`dictionary`](dictionary/)
  README: [`dictionary/README.md`](dictionary/README.md)
- [`external-examples`](external-examples/)
  README: [`external-examples/README.md`](external-examples/README.md)
- [`filters`](filters/)
  README: [`filters/README.md`](filters/README.md)
- [`kafka-avro`](kafka-avro/)
  README: [`kafka-avro/README.md`](kafka-avro/README.md)
- [`kafka-sqs-retry-dlq`](kafka-sqs-retry-dlq/)
  README: [`kafka-sqs-retry-dlq/README.md`](kafka-sqs-retry-dlq/README.md)
- [`mcp-auto-test`](mcp-auto-test/)
  README: [`mcp-auto-test/README.md`](mcp-auto-test/README.md)
- [`overlays`](overlays/)
  README: [`overlays/README.md`](overlays/README.md)
- [`partial-examples`](partial-examples/)
  README: [`partial-examples/README.md`](partial-examples/README.md)
- [`workflow-in-same-spec`](workflow-in-same-spec/)
  README: [`workflow-in-same-spec/README.md`](workflow-in-same-spec/README.md)
- [`quick-start-api-testing`](quick-start-api-testing/)
  README: [`quick-start-api-testing/README.md`](quick-start-api-testing/README.md)
- [`quick-start-async-contract-testing`](quick-start-async-contract-testing/)
  README: [`quick-start-async-contract-testing/README.md`](quick-start-async-contract-testing/README.md)
- [`quick-start-contract-testing`](quick-start-contract-testing/)
  README: [`quick-start-contract-testing/README.md`](quick-start-contract-testing/README.md)
- [`quick-start-mock`](quick-start-mock/)
  README: [`quick-start-mock/README.md`](quick-start-mock/README.md)
- [`schema-design`](schema-design/)
  README: [`schema-design/README.md`](schema-design/README.md)
- [`schema-resiliency-testing`](schema-resiliency-testing/)
  README: [`schema-resiliency-testing/README.md`](schema-resiliency-testing/README.md)
- [`response-templating`](response-templating/)
  README: [`response-templating/README.md`](response-templating/README.md)

Setup the sibling upstream labs checkout and Docker images from the repo root with:

```bash
python3 setup.py
```

To force `../labs` back to the latest `main` before refreshing Docker images:

```bash
python3 setup.py --refresh-labs --force
```

Run every available lab harness from the repo root and build the consolidated and comparison reports with:

```bash
python3 run_all.py
```

Rebuild the consolidated and comparison reports from the existing lab snapshots without rerunning labs:

```bash
python3 rebuild_reports.py
```

Refresh an individual lab report from previously captured artifacts without rerunning the lab:

```bash
python3 api-coverage/run.py --refresh-report
```

```bash
python3 api-resiliency-testing/run.py --refresh-report
```

```bash
python3 api-security-schemes/run.py --refresh-report
```

```bash
python3 async-event-flow/run.py --refresh-report
```

```bash
python3 backward-compatibility-testing/run.py --refresh-report
```

```bash
python3 continuous-integration/run.py --refresh-report
```

```bash
python3 data-adapters/run.py --refresh-report
```

```bash
python3 dictionary/run.py --refresh-report
```

```bash
python3 external-examples/run.py --refresh-report
```

```bash
python3 filters/run.py --refresh-report
```

```bash
python3 kafka-avro/run.py --refresh-report
```

```bash
python3 kafka-sqs-retry-dlq/run.py --refresh-report
```

```bash
python3 mcp-auto-test/run.py --refresh-report
```

```bash
python3 overlays/run.py --refresh-report
```

```bash
python3 workflow-in-same-spec/run.py --refresh-report
```

```bash
python3 partial-examples/run.py --refresh-report
```

```bash
python3 quick-start-api-testing/run.py --refresh-report
```

```bash
python3 quick-start-async-contract-testing/run.py --refresh-report
```

```bash
python3 quick-start-contract-testing/run.py --refresh-report
```

```bash
python3 quick-start-mock/run.py --refresh-report
```

```bash
python3 schema-resiliency-testing/run.py --refresh-report
```

```bash
python3 schema-design/run.py --refresh-report
```

```bash
python3 response-templating/run.py --refresh-report
```

Outputs are written to:

- `output/consolidated-report/consolidated-report.json`
- `output/consolidated-report/consolidated-report.html`
- `output/consolidated-report/labs-comparison.json`
- `output/consolidated-report/labs-comparison.html`
- `output/consolidated-report/setup-output.json`
- `output/labs/<lab-name>-output/` for each lab run

Each lab’s `output/` directory is copied into `output/labs/<lab-name>-output/` after the run completes. The consolidated report uses those copied folders so the links remain stable even after the live lab output is cleaned up or refreshed.

`run_all.py` starts by clearing the generated `output/labs/` and `output/consolidated-report/` folders before regenerating reports, so stale files from earlier runs do not leak into a new report set. `rebuild_reports.py` does not clean the output tree; it only refreshes the consolidated and comparison reports from the existing lab snapshots.

Each individual lab run also clears its own `<lab>/output/` directory before a normal run starts. Refresh-only runs skip that cleanup so they can rebuild from the saved artifacts already on disk.

For Docker-based labs, a normal run also performs a best-effort runtime cleanup before the first phase starts and again after the lab finishes. This keeps stale containers, networks, or volumes from an earlier lab attempt from leaking into later results without adding heavy cleanup work between every command.

Failure messages should be explicit and actionable.

Validation focus:

- the upstream lab `README.md` is the source of truth
- the console output from the automated lab run should match the README
- the generated CTRF JSON and sibling Specmatic HTML report should match the README and console output
- when a README documents commands, it should provide command sections for Windows, macOS, and Linux
- OS-specific command sections should use appropriate fenced block languages such as `shell`/`bash` for macOS and Linux, and `powershell`/`cmd` for Windows
- every documented command section should be followed by a console output snippet
- OS-specific command sections should have matching OS-specific console output snippets
- all README console output snippets should use `terminaloutput` fenced blocks
- when README console output includes timestamps, comparison logic should ignore the datetime stamp and focus on the meaningful output content
- Studio-only phases that are not automated yet should be reported as known limitations or skipped validations, not as failures
- intentional differences that are part of the lab design should be recorded as expected differences, not counted in the failure index
- copied source snapshots such as `specmatic.yaml`, example JSON files, or service source files may still be archived for inspection, but they should not drive pass/fail assertions by themselves
- the shared README template is configured in [`lablib/readme_expectations.py`](/Users/anand.bagmar/projects/specmatic/labs-tests/lablib/readme_expectations.py)
  - `README_TEMPLATE` defines the shared H1/H2/H3 schema and section-level command/output expectations
  - `LAB_README_OVERRIDES` defines lab-specific exceptions or manual Studio allowances
  - `EXPECTED_README_H2_SEQUENCE` is derived from that template for compatibility with existing comparison logic

README command/output conventions:

- use executable fenced blocks for commands:
  - `shell`, `bash`, `sh`, or `zsh` for macOS and Linux
  - `powershell`, `ps1`, `cmd`, or `bat` for Windows
- place a `terminaloutput` fenced block immediately after each documented command block
- when commands differ by OS, include a matching `terminaloutput` block for each OS-specific command

When a command or validation fails, the message should always say:

- what failed
- what the impact is
- what action is needed to fix it

Prefer concrete paths, commands, and missing artifacts over vague summaries or raw log excerpts.

Non-failing validation states:

- use `assert_skipped(...)` for validations that are intentionally not implemented yet, such as documented Studio-only steps that labs-tests does not automate yet
- use `assert_expected(...)` for intentional differences that should stay visible in the report but should not count as failures
- skipped and expected validations should remain visible in the HTML report, but they should not appear in the failure index or contribute to the failure count

How to mark an intentional difference as expected in a lab runner:

Use `assert_expected(...)` inside a phase's `extra_assertions`.

Example:

```python
from lablib.scaffold import assert_expected, detail

def baseline_assertions(context):
    return [
        assert_expected(
            "This baseline mismatch is intentional and should stay visible without failing the lab.",
            category="readme",
            code="readme.intentional-baseline-difference",
            details=[
                detail("Reason", "The README documents this mismatch as the before state."),
                detail("Action", "Do not fix this in labs-tests; fix only if the upstream README changes."),
            ],
        )
    ]
```

How to ignore a shared README validation without showing anything in the rendered README:

Add an HTML comment to the upstream README. GitHub and browsers do not render it, but labs-tests will read it.

Example:

```md
<!-- labs-tests: ignore readme.os_commands.coverage -->
<!-- labs-tests: ignore readme.command_output.followup readme.output.terminaloutput_fence -->
```

Supported shared README ignore codes currently include:

- `readme.commands.minimum_count`
- `readme.commands.executable_fences`
- `readme.os_commands.coverage`
- `readme.os_commands.fence_languages`
- `readme.os_output.path_coverage`
- `readme.command_output.followup`
- `readme.output.terminaloutput_fence`
- `readme.os_output.command_coverage`
- `readme.tests_run_summary.matches_console`
- `readme.structure.single_h1`
- `readme.structure.required_h2_sections`
- `readme.structure.required_h2_order`
- `readme.structure.unexpected_h2_sections`

When an ignore annotation is present:

- the validation is shown as `skipped`
- it remains visible in the report for traceability
- it does not count as a failure

How to mark missing test-count summaries as expected behavior for a lab:

- set `expected_missing_test_counts=True` in the lab's `LabSpec`
- set `expected_missing_test_counts_reason` to explain why this lab does not emit README/console/CTRF/HTML count summaries

Example:

```python
return LabSpec(
    ...,
    expected_missing_test_counts=True,
    expected_missing_test_counts_reason="This lab validates compatibility verdicts and does not emit test-count summaries.",
)
```

The comparison report will then show those phases as `Expected` instead of plain `Not available`.

GitHub Actions workflow:

- `.github/workflows/labs-tests.yml`
- runs `python3 run_all.py --refresh-labs --force --labs-branch dynamic-labs` by default
- accepts an optional space-separated `labs` workflow input to run only selected labs
- accepts an optional `labs_branch` workflow input; until the `dynamic-labs` work is merged, the default branch is `dynamic-labs`
- accepts an optional `manage_license` workflow input; by default the workflow creates or replaces `../labs/license.txt` before the run and restores or removes it afterward
- emits a 60-second heartbeat while the suite is still running, so quiet phases remain visibly active in Actions
- uses a 40-minute timeout for the workflow job and the main lab execution step
- publishes a GitHub job summary based on `output/consolidated-report/consolidated-report.json`
- includes the consolidated report path and comparison report path in the GitHub job summary so workflow runs can be checked quickly
- uploads `output/` plus every lab-local `*/output/` folder as the `specmatic-labs-reports` artifact

License lifecycle:

- `python3 run_all.py` manages `../labs/license.txt` by default
- local runs read `status.license` from `~/.specmatic/license.json` and write it to `../labs/license.txt`
- GitHub Actions runs read `SPECMATIC_LICENSE_KEY` and write it to `../labs/license.txt`
- after the run completes, the original `../labs/license.txt` content is restored, or the file is removed if it did not exist before the run
- use `python3 run_all.py --no-manage-license ...` to opt out locally
