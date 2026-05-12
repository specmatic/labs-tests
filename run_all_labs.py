from __future__ import annotations

import argparse
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lablib.readme_runner import build_readme_lab_spec
from lablib.report_building import report_duration_seconds, upstream_readme_href
from lablib.scaffold import run_lab
from utils import (
    discover_labs,
    display_lab_status,
    execute_shared_setup,
    filter_labs,
    finalize_run,
    initialize_output_workspace,
    load_json,
    prepare_license_for_run,
    restore_license_after_run,
    snapshot_lab_output,
    validate_license_prerequisites,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run labs from README-derived execution plans and build consolidated reports."
    )
    parser.add_argument(
        "--refresh-report",
        action="store_true",
        help="Rebuild each lab report and the consolidated report from existing captured artifacts without rerunning labs.",
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip the shared workspace setup stage.",
    )
    parser.add_argument(
        "--refresh-labs",
        action="store_true",
        help="Destructively reset ../labs to the latest state on the selected branch before running.",
    )
    parser.add_argument(
        "--labs-branch",
        default="main",
        help="Branch of ../labs to use with --refresh-labs. Defaults to main.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required with --refresh-labs when ../labs has local changes. Discards tracked and untracked changes.",
    )
    parser.add_argument(
        "--labs",
        nargs="+",
        help="Optional subset of lab folder names to run and include in the consolidated reports.",
    )
    parser.add_argument(
        "--manage-license",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="Create or replace ../labs/license.txt from the current local/GitHub license source before running and restore it afterward. Defaults to enabled.",
    )
    return parser.parse_args()


def run_lab_and_collect_result(lab: str, index: int, total_labs: int, refresh_report: bool) -> dict[str, Any]:
    print()
    print("=" * 78)
    print(f"{'REFRESHING REPORT FOR' if refresh_report else 'RUNNING LAB'}: {lab}")
    print(f"Lab # {index} of {total_labs}")
    print("=" * 78)

    spec = build_readme_lab_spec(lab)
    lab_args = SimpleNamespace(
        refresh_report=refresh_report,
        skip_setup=True,
        refresh_labs=False,
        labs_branch="main",
        force=False,
    )
    exit_code = run_lab(spec, lab_args)
    report_json_path, report_html_path = snapshot_lab_output(lab)
    lab_report = load_json(report_json_path) if report_json_path.exists() else None
    duration_seconds = round(report_duration_seconds(lab_report), 2) if lab_report else 0.0
    status = (lab_report or {}).get("status", "failed")
    return {
        "name": lab,
        "readmeHref": upstream_readme_href(lab),
        "status": status,
        "displayStatus": display_lab_status(status, lab_report),
        "exitCode": exit_code,
        "durationSeconds": duration_seconds,
        "reportJsonPath": str(report_json_path),
        "reportHtmlPath": str(report_html_path),
        "summary": (lab_report or {}).get("summary", []),
        "report": lab_report,
    }


def run_selected_labs(labs: list[str], refresh_report: bool) -> list[dict[str, Any]]:
    lab_results: list[dict[str, Any]] = []
    total_labs = len(labs)
    for index, lab in enumerate(labs, start=1):
        lab_results.append(run_lab_and_collect_result(lab, index, total_labs, refresh_report))
    return lab_results


def main() -> int:
    args = parse_args()
    preflight_result = validate_license_prerequisites(args)
    if preflight_result is not None:
        return preflight_result

    initialize_output_workspace()

    license_state = None
    try:
        setup_payload, early_exit = execute_shared_setup(args)
        if early_exit is not None:
            return early_exit

        setup_payload, license_state, early_exit = prepare_license_for_run(args, setup_payload)
        if early_exit is not None:
            return early_exit

        labs = filter_labs(discover_labs(), args.labs)
        print(f"Discovered labs: {', '.join(labs) if labs else 'none'}")
        lab_results = run_selected_labs(labs, args.refresh_report)
        return finalize_run(setup_payload, labs, lab_results)
    finally:
        restore_license_after_run(license_state)


if __name__ == "__main__":
    raise SystemExit(main())
