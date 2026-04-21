from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_all as run_all_module
from lablib.labs_comparison import COMPARISON_HTML_PATH, COMPARISON_JSON_PATH, generate_labs_comparison
from lablib.report_building import (
    build_consolidated_payload,
    discover_snapshot_lab_names,
    load_lab_results_from_snapshots,
    upstream_labs_git_ref,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild consolidated and comparison reports from existing lab snapshots.")
    parser.add_argument(
        "--labs",
        nargs="+",
        help="Optional subset of lab snapshot names to include in the rebuilt reports.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_all_module.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    available_labs = discover_snapshot_lab_names()
    if not available_labs:
        print(
            "[error] No lab snapshots were found under output/labs. "
            "Impact: consolidated and comparison reports cannot be rebuilt without existing lab outputs. "
            "Action required: run python3 run_all.py first to generate lab snapshots."
        )
        return 1

    selected_labs = filter_labs(available_labs, args.labs)
    setup_payload = load_setup_payload(run_all_module.SETUP_OUTPUT_PATH)
    lab_results = load_lab_results_from_snapshots(selected_labs)
    consolidated = build_consolidated_payload(
        setup_payload=setup_payload,
        labs_git_ref=upstream_labs_git_ref(),
        lab_results=lab_results,
    )
    run_all_module.write_consolidated_report(consolidated)
    generate_labs_comparison(ROOT, selected_labs)
    print(f"Wrote consolidated JSON report to {run_all_module.CONSOLIDATED_JSON_PATH}")
    print(f"Wrote consolidated HTML report to {run_all_module.CONSOLIDATED_HTML_PATH}")
    print(f"Wrote labs comparison JSON report to {COMPARISON_JSON_PATH}")
    print(f"Wrote labs comparison HTML report to {COMPARISON_HTML_PATH}")
    return 0 if consolidated["status"] == "passed" else 1


def filter_labs(all_labs: list[str], selected_labs: list[str] | None) -> list[str]:
    if not selected_labs:
        return all_labs
    selected_set = set(selected_labs)
    invalid = sorted(selected_set - set(all_labs))
    if invalid:
        raise SystemExit(f"Unknown lab snapshot(s): {', '.join(invalid)}")
    return [lab for lab in all_labs if lab in selected_set]


def load_setup_payload(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
