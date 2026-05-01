from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import run_all as run_all_module
import lablib.labs_comparison as labs_comparison_module
import lablib.report_building as report_building_module
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
    parser.add_argument(
        "--output-root",
        type=Path,
        help="Directory containing the existing labs-output/ and consolidated-report/ folders to rebuild in place.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_root is not None:
        configure_output_root(args.output_root.resolve())
    run_all_module.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().astimezone().isoformat()

    available_labs = discover_snapshot_lab_names(run_all_module.LABS_OUTPUT_DIR)
    if not available_labs:
        print(
            "[error] No lab snapshots were found under output/labs-output. "
            "Impact: consolidated and comparison reports cannot be rebuilt without existing lab outputs. "
            "Action required: run python3 run_all.py first to generate lab snapshots."
        )
        return 1

    selected_labs = filter_labs(available_labs, args.labs)
    setup_payload = load_setup_payload(run_all_module.SETUP_OUTPUT_PATH)
    lab_results = load_lab_results_from_snapshots(selected_labs, run_all_module.LABS_OUTPUT_DIR)
    consolidated = build_consolidated_payload(
        setup_payload=setup_payload,
        labs_git_ref=upstream_labs_git_ref(),
        lab_results=lab_results,
        generated_at=generated_at,
    )
    run_all_module.write_consolidated_report(consolidated)
    labs_comparison_module.generate_labs_comparison(ROOT, selected_labs, generated_at=generated_at)
    print(f"Wrote consolidated JSON report to {run_all_module.CONSOLIDATED_JSON_PATH}")
    print(f"Wrote consolidated HTML report to {run_all_module.CONSOLIDATED_HTML_PATH}")
    print(f"Wrote labs comparison JSON report to {labs_comparison_module.COMPARISON_JSON_PATH}")
    print(f"Wrote labs comparison HTML report to {labs_comparison_module.COMPARISON_HTML_PATH}")
    print(f"Wrote labs heading-structure comparison JSON report to {labs_comparison_module.HEADINGS_COMPARISON_JSON_PATH}")
    print(f"Wrote labs heading-structure comparison HTML report to {labs_comparison_module.HEADINGS_COMPARISON_HTML_PATH}")
    print(f"Wrote labs test-counts comparison JSON report to {labs_comparison_module.TEST_COUNT_COMPARISON_JSON_PATH}")
    print(f"Wrote labs test-counts comparison HTML report to {labs_comparison_module.TEST_COUNT_COMPARISON_HTML_PATH}")
    print(f"Wrote labs command-output fencing comparison JSON report to {labs_comparison_module.FENCING_COMPARISON_JSON_PATH}")
    print(f"Wrote labs command-output fencing comparison HTML report to {labs_comparison_module.FENCING_COMPARISON_HTML_PATH}")
    print(f"Wrote labs artifacts comparison JSON report to {labs_comparison_module.ARTIFACT_COMPARISON_JSON_PATH}")
    print(f"Wrote labs artifacts comparison HTML report to {labs_comparison_module.ARTIFACT_COMPARISON_HTML_PATH}")
    print(f"Wrote labs license comparison JSON report to {labs_comparison_module.LICENSE_COMPARISON_JSON_PATH}")
    print(f"Wrote labs license comparison HTML report to {labs_comparison_module.LICENSE_COMPARISON_HTML_PATH}")
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


def configure_output_root(output_root: Path) -> None:
    labs_output_dir = output_root / "labs-output"
    consolidated_output_dir = output_root / "consolidated-report"

    report_building_module.OUTPUT_DIR = output_root
    report_building_module.LABS_OUTPUT_DIR = labs_output_dir
    report_building_module.CONSOLIDATED_OUTPUT_DIR = consolidated_output_dir

    run_all_module.OUTPUT_DIR = output_root
    run_all_module.LABS_OUTPUT_DIR = labs_output_dir
    run_all_module.CONSOLIDATED_OUTPUT_DIR = consolidated_output_dir
    run_all_module.RUN_METADATA_PATH = output_root / "workflow-run-details.txt"
    run_all_module.LATEST_OUTPUT_LINK = output_root / "latest"
    run_all_module.SETUP_OUTPUT_PATH = consolidated_output_dir / "setup-output.json"
    run_all_module.CONSOLIDATED_JSON_PATH = consolidated_output_dir / "consolidated-report.json"
    run_all_module.CONSOLIDATED_HTML_PATH = consolidated_output_dir / "consolidated-report.html"
    run_all_module.LEGACY_CONSOLIDATED_JSON_PATH = output_root / "consolidated-report.json"
    run_all_module.LEGACY_CONSOLIDATED_HTML_PATH = output_root / "consolidated-report.html"
    run_all_module.LEGACY_CONSOLIDATED_REPORT_JSON_PATH = consolidated_output_dir / "report.json"
    run_all_module.LEGACY_CONSOLIDATED_REPORT_HTML_PATH = consolidated_output_dir / "report.html"
    run_all_module.LEGACY_COMPARISON_JSON_PATH = output_root / "labs-comparison.json"
    run_all_module.LEGACY_COMPARISON_HTML_PATH = output_root / "labs-comparison.html"

    labs_comparison_module.OUTPUT_DIR = output_root
    labs_comparison_module.COMPARISON_OUTPUT_DIR = consolidated_output_dir
    labs_comparison_module.COMPARISON_JSON_PATH = consolidated_output_dir / "labs-comparison.json"
    labs_comparison_module.COMPARISON_HTML_PATH = consolidated_output_dir / "labs-comparison.html"
    labs_comparison_module.HEADINGS_COMPARISON_JSON_PATH = consolidated_output_dir / "labs-heading-structure-comparison.json"
    labs_comparison_module.HEADINGS_COMPARISON_HTML_PATH = consolidated_output_dir / "labs-heading-structure-comparison.html"
    labs_comparison_module.TEST_COUNT_COMPARISON_JSON_PATH = consolidated_output_dir / "labs-test-counts-comparison.json"
    labs_comparison_module.TEST_COUNT_COMPARISON_HTML_PATH = consolidated_output_dir / "labs-test-counts-comparison.html"
    labs_comparison_module.FENCING_COMPARISON_JSON_PATH = consolidated_output_dir / "labs-command-output-fencing-comparison.json"
    labs_comparison_module.FENCING_COMPARISON_HTML_PATH = consolidated_output_dir / "labs-command-output-fencing-comparison.html"
    labs_comparison_module.ARTIFACT_COMPARISON_JSON_PATH = consolidated_output_dir / "labs-artifacts-comparison.json"
    labs_comparison_module.ARTIFACT_COMPARISON_HTML_PATH = consolidated_output_dir / "labs-artifacts-comparison.html"
    labs_comparison_module.LICENSE_COMPARISON_JSON_PATH = consolidated_output_dir / "labs-license-comparison.json"
    labs_comparison_module.LICENSE_COMPARISON_HTML_PATH = consolidated_output_dir / "labs-license-comparison.html"
    labs_comparison_module.LEGACY_COMPARISON_JSON_PATH = output_root / "labs-comparison.json"
    labs_comparison_module.LEGACY_COMPARISON_HTML_PATH = output_root / "labs-comparison.html"


if __name__ == "__main__":
    raise SystemExit(main())
