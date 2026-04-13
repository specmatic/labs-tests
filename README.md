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
- [`backward-compatibility-testing`](backward-compatibility-testing/)
  README: [`backward-compatibility-testing/README.md`](backward-compatibility-testing/README.md)
- [`continuous-integration`](continuous-integration/)
  README: [`continuous-integration/README.md`](continuous-integration/README.md)
- [`dictionary`](dictionary/)
  README: [`dictionary/README.md`](dictionary/README.md)
- [`external-examples`](external-examples/)
  README: [`external-examples/README.md`](external-examples/README.md)
- [`filters`](filters/)
  README: [`filters/README.md`](filters/README.md)
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

Run every available lab harness from the repo root and build a consolidated report with:

```bash
python3 run_all.py
```

Refresh all available lab reports and the consolidated report from existing captured artifacts without rerunning labs:

```bash
python3 run_all.py --refresh-report
```

Generate a root-level similarities/differences report across all automated labs:

```bash
python3 compare_labs.py
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
python3 backward-compatibility-testing/run.py --refresh-report
```

```bash
python3 continuous-integration/run.py --refresh-report
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
python3 schema-resiliency-testing/run.py --refresh-report
```

```bash
python3 schema-design/run.py --refresh-report
```

```bash
python3 response-templating/run.py --refresh-report
```

Outputs are written to:

- `output/consolidated-report.json`
- `output/consolidated-report.html`
- `output/labs-comparison.json`
- `output/labs-comparison.html`
- `output/setup-output.json`

GitHub Actions workflow:

- `.github/workflows/labs-tests.yml`
- runs `python3 run_all.py --refresh-labs --force`
- emits a 60-second heartbeat while the suite is still running, so quiet phases remain visibly active in Actions
- uses a 30-minute timeout for the workflow job and the main lab execution step
- publishes a GitHub job summary based on `output/consolidated-report.json`
- uploads all generated reports as the `specmatic-labs-reports` artifact
