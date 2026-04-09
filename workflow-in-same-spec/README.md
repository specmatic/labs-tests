# workflow-in-same-spec automation

This folder contains the scaffolded automation harness for the upstream
`labs/workflow-in-same-spec` lab.

This automation validates the CLI run and generated artifacts only. It does not
validate the optional Specmatic Studio flow.

Run it with:

```bash
python3 workflow-in-same-spec/run.py
```

Or from inside this folder:

```bash
python3 run.py
```

To rebuild `report.json` and `report.html` from the existing captured artifacts without rerunning Docker:

```bash
python3 workflow-in-same-spec/run.py --refresh-report
```

To first force the sibling `../labs` checkout back to the latest `main`:

```bash
python3 workflow-in-same-spec/run.py --refresh-labs --force
```

Outputs are written to:

- `workflow-in-same-spec/output/report.json`
- `workflow-in-same-spec/output/report.html`
- `workflow-in-same-spec/output/baseline/`
- `workflow-in-same-spec/output/fixed/`
