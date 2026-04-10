# continuous-integration automation

This folder contains the scaffolded automation harness for the upstream
`labs/continuous-integration` lab.

This automation validates the CLI run and generated artifacts only. It does not
validate any Studio flow.

Run it with:

```bash
python3 continuous-integration/run.py
```

Or from inside this folder:

```bash
python3 run.py
```

To rebuild `report.json` and `report.html` from the existing captured artifacts without rerunning Docker:

```bash
python3 continuous-integration/run.py --refresh-report
```

To first force the sibling `../labs` checkout back to the latest `main`:

```bash
python3 continuous-integration/run.py --refresh-labs --force
```

Outputs are written to:

- `continuous-integration/output/report.json`
- `continuous-integration/output/report.html`
- `continuous-integration/output/baseline/`
- `continuous-integration/output/fixed/`
