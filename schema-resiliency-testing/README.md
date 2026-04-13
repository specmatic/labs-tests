# schema-resiliency-testing

Automated harness for the upstream `schema-resiliency-testing` lab.

Run from the repo root:

```bash
python3 schema-resiliency-testing/run.py
```

Refresh only the lab report from captured artifacts:

```bash
python3 schema-resiliency-testing/run.py --refresh-report
```

Generated outputs:

- `output/report.json`
- `output/report.html`
