# api-security-schemes automation

This folder contains the scaffolded automation harness for the upstream
`labs/api-security-schemes` lab.

This automation validates the CLI run and generated artifacts only. It does not
validate any Studio flow.

Run it with:

```bash
python3 api-security-schemes/run.py
```

Or from inside this folder:

```bash
python3 run.py
```

To rebuild `report.json` and `report.html` from the existing captured artifacts without rerunning Docker:

```bash
python3 api-security-schemes/run.py --refresh-report
```

To first force the sibling `../labs` checkout back to the latest `main`:

```bash
python3 api-security-schemes/run.py --refresh-labs --force
```

Outputs are written to:

- `api-security-schemes/output/report.json`
- `api-security-schemes/output/report.html`
- `api-security-schemes/output/baseline/`
- `api-security-schemes/output/fixed/`
