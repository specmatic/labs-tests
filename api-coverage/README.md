# api-coverage automation

This folder contains the JSON-first automation harness for the upstream
`labs/api-coverage` lab.

This automation validates the CLI run and generated artifacts only. It does not
validate the optional Specmatic Studio follow-up flow.

Run it with:

```bash
python3 run_all_labs.py --labs api-coverage
```

To first force the sibling `../labs` checkout back to the latest `main`:

```bash
python3 run_all_labs.py --labs api-coverage --refresh-labs --force
```

To rebuild `report.json` and `report.html` from the existing captured artifacts without rerunning Docker:

```bash
python3 run_all_labs.py --labs api-coverage --refresh-report
```

To run the shared setup stage independently from the repo root:

```bash
python3 setup.py
```

To destructively reset `../labs`, switch to `main`, pull latest, and refresh Docker images:

```bash
python3 setup.py --refresh-labs --force
```

To run every available lab harness and build a consolidated report from the repo root:

```bash
python3 run_all_labs.py
```

To refresh all available lab reports and the consolidated report from previously captured artifacts:

```bash
python3 run_all_labs.py --refresh-report
```

Outputs are written to:

- `api-coverage/output/report.json`
- `api-coverage/output/report.html`
- `api-coverage/output/baseline/`
- `api-coverage/output/fixed/`
