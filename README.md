# labs-tests

Automation harnesses for Specmatic labs live in lab-named folders in this repo.

Current automation scope validates CLI/runtime behavior and generated artifacts.
It does not automate or validate Specmatic Studio flows.

Current labs:

- [`api-coverage`](api-coverage/)
  README: [`api-coverage/README.md`](api-coverage/README.md)
- [`api-resiliency-testing`](api-resiliency-testing/)
  README: [`api-resiliency-testing/README.md`](api-resiliency-testing/README.md)
- [`backward-compatibility-testing`](backward-compatibility-testing/)
  README: [`backward-compatibility-testing/README.md`](backward-compatibility-testing/README.md)
- [`overlays`](overlays/)
  README: [`overlays/README.md`](overlays/README.md)
- [`workflow-in-same-spec`](workflow-in-same-spec/)
  README: [`workflow-in-same-spec/README.md`](workflow-in-same-spec/README.md)
- [`quick-start-api-testing`](quick-start-api-testing/)
  README: [`quick-start-api-testing/README.md`](quick-start-api-testing/README.md)
- [`schema-design`](schema-design/)
  README: [`schema-design/README.md`](schema-design/README.md)
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

Refresh an individual lab report from previously captured artifacts without rerunning the lab:

```bash
python3 api-coverage/run.py --refresh-report
```

```bash
python3 api-resiliency-testing/run.py --refresh-report
```

```bash
python3 backward-compatibility-testing/run.py --refresh-report
```

```bash
python3 overlays/run.py --refresh-report
```

```bash
python3 workflow-in-same-spec/run.py --refresh-report
```

```bash
python3 quick-start-api-testing/run.py --refresh-report
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
- `output/setup-output.json`

GitHub Actions workflow:

- `.github/workflows/labs-tests.yml`
- runs `python3 run_all.py --refresh-labs --force`
- publishes a GitHub job summary based on `output/consolidated-report.json`
- uploads all generated reports as the `specmatic-labs-reports` artifact
