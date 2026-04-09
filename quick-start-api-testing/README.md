# quick-start-api-testing automation

This folder contains the scaffolded automation harness for the upstream
`labs/quick-start-api-testing` lab.

This automation validates the CLI run and generated artifacts only. It does not
validate the optional Specmatic Studio flow.

Run it with:

```bash
python3 quick-start-api-testing/run.py
```

Or from inside this folder:

```bash
python3 run.py
```

To rebuild `report.json` and `report.html` from the existing captured artifacts without rerunning Docker:

```bash
python3 quick-start-api-testing/run.py --refresh-report
```

To first force the sibling `../labs` checkout back to the latest `main`:

```bash
python3 quick-start-api-testing/run.py --refresh-labs --force
```

Outputs are written to:

- `quick-start-api-testing/output/report.json`
- `quick-start-api-testing/output/report.html`
- `quick-start-api-testing/output/baseline/`
- `quick-start-api-testing/output/task-a/`
- `quick-start-api-testing/output/fixed/`
