# mcp-auto-test automation

This folder contains the scaffolded automation harness for the upstream
`labs/mcp-auto-test` lab.

This automation validates the CLI run and generated artifacts only. It does not
validate any Studio flow.

Run it with:

```bash
python3 mcp-auto-test/run.py
```

Or from inside this folder:

```bash
python3 run.py
```

To rebuild `report.json` and `report.html` from the existing captured artifacts without rerunning Docker:

```bash
python3 mcp-auto-test/run.py --refresh-report
```

To first force the sibling `../labs` checkout back to the latest `main`:

```bash
python3 mcp-auto-test/run.py --refresh-labs --force
```

Outputs are written to:

- `mcp-auto-test/output/report.json`
- `mcp-auto-test/output/report.html`
- `mcp-auto-test/output/baseline/`
- `mcp-auto-test/output/fixed/`
