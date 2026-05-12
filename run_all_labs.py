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
from lablib.workspace_setup import run_setup, setup_failure_action_lines, setup_failure_error_lines
from utils import (
    discover_labs,
    display_lab_status,
    filter_labs,
    finalize_run,
    initialize_output_workspace,
    load_json,
    prepare_license_for_run,
    restore_license_after_run,
    snapshot_lab_output,
    validate_license_prerequisites,
    write_failed_run_reports,
    write_setup_payload,
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
        help="Skip the shared sibling labs repository setup stage.",
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


def setup_payload_from_result(args: argparse.Namespace, setup_result: Any) -> dict[str, Any]:
    return {
        "status": setup_result.status,
        "upstreamLabsPath": setup_result.upstream_labs_path,
        "refreshLabs": args.refresh_labs,
        "labsBranch": args.labs_branch,
        "manageLicense": args.manage_license,
        "force": args.force,
        "commands": list(setup_result.commands),
    }


def execute_initial_workspace_setup(args: argparse.Namespace) -> tuple[dict[str, Any] | None, int | None]:
    if args.refresh_report:
        print("Refreshing reports from existing captured artifacts...")
        return None, None
    if args.skip_setup:
        return None, None

    print("Running initial workspace setup without Docker image pull/build...")
    setup_result = run_setup(
        stream_output=True,
        refresh_labs=args.refresh_labs,
        target_branch=args.labs_branch,
        force=args.force,
        lab_names=args.labs,
    )
    setup_payload = setup_payload_from_result(args, setup_result)
    write_setup_payload(setup_payload)
    if setup_result.status == "passed":
        return setup_payload, None

    print()
    for line in setup_failure_error_lines(setup_result.commands):
        print(line)
    print()
    for line in setup_failure_action_lines(setup_result.commands):
        print(line)
    return setup_payload, write_failed_run_reports(setup_payload)


def run_lab_and_collect_result(
    lab: str,
    index: int,
    total_labs: int,
    args: argparse.Namespace,
    setup_payload: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    print()
    print("=" * 78)
    print(f"{'REFRESHING REPORT FOR' if args.refresh_report else 'RUNNING LAB'}: {lab}")
    print(f"Lab # {index} of {total_labs}")
    print("=" * 78)

    spec = build_readme_lab_spec(lab)
    lab_args = SimpleNamespace(
        refresh_report=args.refresh_report,
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
    }, setup_payload


def run_selected_labs(
    labs: list[str],
    args: argparse.Namespace,
    setup_payload: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    lab_results: list[dict[str, Any]] = []
    total_labs = len(labs)
    for index, lab in enumerate(labs, start=1):
        lab_result, setup_payload = run_lab_and_collect_result(lab, index, total_labs, args, setup_payload)
        lab_results.append(lab_result)
    return lab_results, setup_payload


def main() -> int:
    args = parse_args()
    preflight_result = validate_license_prerequisites(args)
    if preflight_result is not None:
        return preflight_result

    initialize_output_workspace()

    license_state = None
    try:
        setup_payload, early_exit = execute_initial_workspace_setup(args)
        if early_exit is not None:
            return early_exit

        setup_payload, license_state, early_exit = prepare_license_for_run(args, setup_payload)
        if early_exit is not None:
            return early_exit

        labs = filter_labs(discover_labs(), args.labs)
        print(f"Discovered labs: {', '.join(labs) if labs else 'none'}")
        lab_results, setup_payload = run_selected_labs(labs, args, setup_payload)
        return finalize_run(setup_payload, labs, lab_results)
    finally:
        restore_license_after_run(license_state)


if __name__ == "__main__":
    raise SystemExit(main())
