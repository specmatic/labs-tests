# response-templating automation

This folder contains the scaffolded automation harness for the upstream
`labs/response-templating` lab.

This automation validates the CLI run and generated artifacts only. It does not
validate the optional Specmatic Studio flow.

Run it with:

```bash
python3 response-templating/run.py
```

Or from inside this folder:

```bash
python3 run.py
```

To rebuild `report.json` and `report.html` from the existing captured artifacts without rerunning Docker:

```bash
python3 response-templating/run.py --refresh-report
```

To first force the sibling `../labs` checkout back to the latest `main`:

```bash
python3 response-templating/run.py --refresh-labs --force
```

Outputs are written to:

- `response-templating/output/report.json`
- `response-templating/output/report.html`
- `response-templating/output/baseline/`
- `response-templating/output/task-a/`
- `response-templating/output/fixed/`
