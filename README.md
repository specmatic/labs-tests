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

Generated root-level outputs:

- [`output/consolidated-report.json`](output/consolidated-report.json)
- [`output/consolidated-report.html`](output/consolidated-report.html)
- [`output/setup-output.json`](output/setup-output.json)
