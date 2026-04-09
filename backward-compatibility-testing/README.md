# backward-compatibility-testing automation

This folder contains the scaffolded automation harness for the upstream
`labs/backward-compatibility-testing` lab.

This automation validates the CLI run and generated artifacts only. It does not
validate the optional Specmatic Studio follow-up flow.

Run it with:

```bash
python3 backward-compatibility-testing/run.py
```

Or from inside this folder:

```bash
python3 run.py
```

To rebuild `report.json` and `report.html` from the existing captured artifacts without rerunning Docker:

```bash
python3 backward-compatibility-testing/run.py --refresh-report
```

Or from inside this folder:

```bash
python3 run.py --refresh-report
```

To first force the sibling `../labs` checkout back to the latest `main`:

```bash
python3 backward-compatibility-testing/run.py --refresh-labs --force
```

Or from inside this folder:

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

To refresh all available lab reports and the consolidated report from previously captured artifacts:

```bash
python3 run_all.py --refresh-report
```

Outputs are written to:

- `backward-compatibility-testing/output/report.json`
- `backward-compatibility-testing/output/report.html`
- `backward-compatibility-testing/output/baseline/`
- `backward-compatibility-testing/output/fixed/`
