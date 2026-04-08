# labs-tests

Automation harnesses for Specmatic labs live in lab-named folders in this repo.

Current labs:

- [`api-coverage`](api-coverage/)
  README: [`api-coverage/README.md`](api-coverage/README.md)

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

Outputs are written to:

- `output/consolidated-report.json`
- `output/consolidated-report.html`
- `output/setup-output.json`
