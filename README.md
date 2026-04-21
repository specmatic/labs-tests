# labs-tests

Automation harnesses for Specmatic labs live in lab-named folders in this repo.

Current automation scope validates CLI/runtime behavior and generated artifacts.
It does not automate or validate Specmatic Studio flows.

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
- [`order-bff`](order-bff/)
  README: [`order-bff/README.md`](order-bff/README.md)
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
python3 order-bff/run.py --refresh-report
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

Failure messages should be explicit and actionable.

When a command or validation fails, the message should always say:

- what failed
- what the impact is
- what action is needed to fix it

Prefer concrete paths, commands, and missing artifacts over vague summaries or raw log excerpts.

GitHub Actions workflow:

- `.github/workflows/labs-tests.yml`
- runs `python3 run_all.py --refresh-labs --force`
- emits a 60-second heartbeat while the suite is still running, so quiet phases remain visibly active in Actions
- uses a 30-minute timeout for the workflow job and the main lab execution step
- publishes a GitHub job summary based on `output/consolidated-report/consolidated-report.json`
- uploads `output/` plus every lab-local `*/output/` folder as the `specmatic-labs-reports` artifact
