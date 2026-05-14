from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil

from lablib.labs_comparison import generate_labs_comparison
from lablib.readme_runner import build_readme_lab_spec
from lablib.report_building import (
    LABS_OUTPUT_DIR,
    CONSOLIDATED_OUTPUT_DIR,
    build_consolidated_payload,
    load_lab_results_from_snapshots,
    upstream_labs_git_ref,
)
from lablib.reporting import build_report, write_html, write_json
from lablib.scaffold import run_lab
from lablib.workspace_setup import (
    cleanup_upstream_lab_snapshot,
    create_upstream_lab_snapshot,
    discover_available_labs,
    load_ignored_lab_names,
    prepare_upstream_license_for_run,
    restore_upstream_lab_snapshot,
    restore_upstream_license_after_run,
    run_setup,
)


ROOT = Path(__file__).resolve().parent
GITHUB_ACTIONS = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run README-driven pilot labs.")
    parser.add_argument("--labs", nargs="+", help="Labs to run. If omitted, run all discovered labs.")
    parser.add_argument("--skip-setup", action="store_true", help="Skip shared sibling labs setup.")
    parser.add_argument("--refresh-labs", action="store_true", help="Reset ../labs to the latest state on the selected branch before running.")
    parser.add_argument("--labs-branch", default="auto-labs-tests", help="Branch of ../labs to use. Defaults to auto-labs-tests.")
    parser.add_argument("--force", action="store_true", help="Required with --refresh-labs when ../labs has local changes.")
    parser.add_argument("--refresh-report", action="store_true", help="Refresh lab report from captured artifacts instead of rerunning commands.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requested_labs = list(dict.fromkeys(args.labs or []))
    print("Running shared setup for the sibling labs repository...")
    setup_payload = None
    overall_exit = 0

    if not args.skip_setup:
        setup_result = run_setup(
            stream_output=True,
            refresh_labs=args.refresh_labs,
            target_branch=args.labs_branch,
            force=args.force,
            lab_names=requested_labs or None,
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

    available_labs = discover_available_labs()
    ignored_labs = load_ignored_lab_names()
    if not available_labs:
        raise SystemExit(
            "No labs were discovered in the sibling labs repository. "
            "Action required: ensure ../labs exists and contains lab folders with README.md."
        )

    selected_labs = requested_labs or available_labs
    unknown = sorted(set(selected_labs) - set(available_labs))
    if unknown:
        raise SystemExit(
            "Unknown lab(s): "
            + ", ".join(unknown)
            + ". Action required: choose from the discovered labs in ../labs or omit --labs to run all discovered labs."
        )

    print(
        f"Discovered {len(available_labs)} runnable labs"
        + (f" ({len(ignored_labs)} ignored)." if ignored_labs else "."),
        flush=True,
    )
    print(f"Selected {len(selected_labs)} lab(s) to run.", flush=True)

    license_snapshot = None
    try:
        if not args.refresh_report:
            clear_output_root()
            license_snapshot = prepare_upstream_license_for_run()
            if license_snapshot.applied_temp_license:
                print(
                    f"Using temporary license for this run from {license_snapshot.temp_license_path}.",
                    flush=True,
                )

        for index, lab_name in enumerate(selected_labs, start=1):
            print("", flush=True)
            print("-" * 80, flush=True)
            print(f"Running lab {index} of {len(selected_labs)}: {lab_name}", flush=True)
            print("-" * 80, flush=True)
            print("", flush=True)
            snapshot = create_upstream_lab_snapshot(lab_name)
            try:
                try:
                    lab_spec = build_readme_lab_spec(lab_name)
                except Exception as exc:
                    write_lab_construction_failure_report(lab_name, exc)
                    print(
                        f"[warning] Failed to build README-driven lab '{lab_name}': {exc}. "
                        "Impact: this lab is marked failed in the generated report, but the run will continue.",
                        flush=True,
                    )
                    overall_exit = 1
                    continue
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
                try:
                    restore_upstream_lab_snapshot(snapshot)
                except Exception as exc:
                    if GITHUB_ACTIONS:
                        print(
                            f"[warning] Failed to restore sibling lab '{lab_name}' after execution: {exc}. "
                            "Impact: this run may leave modified files in the GitHub Actions workspace, "
                            "but the workflow started from a clean checkout so the job will continue.",
                            flush=True,
                        )
                    else:
                        raise
                finally:
                    cleanup_upstream_lab_snapshot(snapshot)

        lab_results = load_lab_results_from_snapshots(selected_labs)
        write_consolidated_payload(setup_payload, lab_results, args.labs_branch)
        generate_labs_comparison(root=ROOT, lab_names=selected_labs)
        return overall_exit
    finally:
        if license_snapshot is not None:
            restore_upstream_license_after_run(license_snapshot)


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


def clear_output_root() -> None:
    remove_path_if_exists(ROOT / "output")


def remove_path_if_exists(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    path.unlink(missing_ok=True)


def write_lab_construction_failure_report(lab_name: str, error: Exception) -> None:
    output_dir = LABS_OUTPUT_DIR / f"{lab_name}-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    readme_path = ROOT.parent / "labs" / lab_name / "README.md"
    phase_result = {
        "name": "README execution discovery",
        "description": "Build the executable phase list from the lab README.",
        "status": "failed",
        "readmePhase": {
            "id": "readme-execution-discovery",
            "title": "README execution discovery",
        },
        "command": {
            "display": "(lab construction)",
            "exitCode": "n/a",
            "durationSeconds": 0.0,
            "timedOut": False,
            "timeoutReason": "",
        },
        "assertions": [
            {
                "status": "failed",
                "message": "The lab README could not be turned into executable phases.",
                "category": "readme",
                "details": [
                    {"label": "Reason", "value": str(error)},
                    {
                        "label": "Impact",
                        "value": "This lab could not execute, but the remaining labs continued running.",
                    },
                    {
                        "label": "Action",
                        "value": "Add executable shell-command sections under recognizable headings in the README, or broaden the shared README discovery rules.",
                    },
                ],
            }
        ],
        "artifacts": [],
        "consoleSnippet": "",
        "fixSummary": [],
        "warnings": [],
    }
    report = build_report(
        lab_name=lab_name,
        description=f"README-driven automation for {lab_name}.",
        lab_path=readme_path.parent,
        spec_path=readme_path,
        readme_path=readme_path,
        output_path=output_dir,
        phases=[phase_result],
    )
    write_json(output_dir / "report.json", report)
    write_html(output_dir / "report.html", report)
    print(f"Wrote JSON report to {output_dir / 'report.json'}", flush=True)
    print(f"Wrote HTML report to {output_dir / 'report.html'}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
