from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from lablib.labs_comparison import generate_labs_comparison
from lablib.readme_runner import build_readme_lab_spec
from lablib.report_building import (
    CONSOLIDATED_OUTPUT_DIR,
    build_consolidated_payload,
    load_lab_results_from_snapshots,
    upstream_labs_git_ref,
)
from lablib.reporting import write_json
from lablib.scaffold import run_lab
from lablib.workspace_setup import (
    cleanup_upstream_lab_snapshot,
    create_upstream_lab_snapshot,
    restore_upstream_lab_snapshot,
    run_setup,
)


ROOT = Path(__file__).resolve().parent
AVAILABLE_LABS = ("api-coverage",)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run README-driven pilot labs.")
    parser.add_argument("--labs", nargs="+", default=list(AVAILABLE_LABS), help="Labs to run.")
    parser.add_argument("--skip-setup", action="store_true", help="Skip shared sibling labs setup.")
    parser.add_argument("--refresh-labs", action="store_true", help="Reset ../labs to the latest state on the selected branch before running.")
    parser.add_argument("--labs-branch", default="auto-labs-tests", help="Branch of ../labs to use. Defaults to auto-labs-tests.")
    parser.add_argument("--force", action="store_true", help="Required with --refresh-labs when ../labs has local changes.")
    parser.add_argument("--refresh-report", action="store_true", help="Refresh lab report from captured artifacts instead of rerunning commands.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_labs = list(dict.fromkeys(args.labs))
    unknown = sorted(set(selected_labs) - set(AVAILABLE_LABS))
    if unknown:
        raise SystemExit(f"Unknown README-driven lab(s): {', '.join(unknown)}")

    print("Running shared setup for the sibling labs repository...")
    setup_payload = None
    overall_exit = 0

    if not args.skip_setup:
        setup_result = run_setup(
            stream_output=True,
            refresh_labs=args.refresh_labs,
            target_branch=args.labs_branch,
            force=args.force,
            lab_names=selected_labs,
        )
        setup_payload = {
            "status": setup_result.status,
            "upstreamLabsPath": setup_result.upstream_labs_path,
            "labsBranch": args.labs_branch,
            "refreshLabs": args.refresh_labs,
            "force": args.force,
            "commands": setup_result.commands,
        }
        if setup_result.status != "passed":
            write_consolidated_payload(setup_payload, [], args.labs_branch)
            return 1
    else:
        setup_payload = {
            "status": "skipped",
            "upstreamLabsPath": str((ROOT.parent / "labs")),
            "labsBranch": args.labs_branch,
            "refreshLabs": args.refresh_labs,
            "force": args.force,
            "commands": [],
        }

    for lab_name in selected_labs:
        print(f"Running README-driven lab: {lab_name}")
        snapshot = create_upstream_lab_snapshot(lab_name)
        try:
            lab_spec = build_readme_lab_spec(lab_name)
            lab_args = argparse.Namespace(
                refresh_report=args.refresh_report,
                skip_setup=True,
                refresh_labs=args.refresh_labs,
                labs_branch=args.labs_branch,
                force=args.force,
            )
            exit_code = run_lab(lab_spec, lab_args)
            overall_exit = max(overall_exit, exit_code)
        finally:
            restore_upstream_lab_snapshot(snapshot)
            cleanup_upstream_lab_snapshot(snapshot)

    lab_results = load_lab_results_from_snapshots(selected_labs)
    write_consolidated_payload(setup_payload, lab_results, args.labs_branch)
    generate_labs_comparison(root=ROOT, lab_names=selected_labs)
    return overall_exit


def write_consolidated_payload(setup_payload: dict | None, lab_results: list[dict], labs_branch: str) -> None:
    generated_at = datetime.now().astimezone().isoformat()
    payload = build_consolidated_payload(
        setup_payload=setup_payload,
        labs_git_ref=upstream_labs_git_ref(),
        lab_results=lab_results,
        generated_at=generated_at,
        environment_overrides={"labsBranchRequested": labs_branch},
    )
    CONSOLIDATED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(CONSOLIDATED_OUTPUT_DIR / "consolidated-report.json", payload)


if __name__ == "__main__":
    raise SystemExit(main())
