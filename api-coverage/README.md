# api-coverage automation

This folder contains the JSON-first automation harness for the upstream
`labs/api-coverage` lab.

Run it with:

```bash
python3 api-coverage/run.py
```

To first force the sibling `../labs` checkout back to the latest `main`:

```bash
python3 api-coverage/run.py --refresh-labs --force
```

Or from inside this folder:

```bash
python3 run.py
```

From inside this folder, the destructive refresh form is:

```bash
python3 run.py --refresh-labs --force
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
python3 run_all.py
```

Outputs are written to:

- `api-coverage/output/report.json`
- `api-coverage/output/report.html`
- `api-coverage/output/baseline/`
- `api-coverage/output/fixed/`
