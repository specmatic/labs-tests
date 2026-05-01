from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
from typing import Any

from lablib.labs_comparison import not_in_excluded
from lablib.provenance import detect_report_provenance


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
LABS_OUTPUT_DIR = OUTPUT_DIR / "labs-output"
CONSOLIDATED_OUTPUT_DIR = OUTPUT_DIR / "consolidated-report"


def discover_snapshot_lab_names(labs_output_dir: Path | None = None) -> list[str]:
    base_dir = labs_output_dir or LABS_OUTPUT_DIR
    if not base_dir.exists():
        return []
    return sorted(
        path.name.removesuffix("-output")
        for path in base_dir.iterdir()
        if path.is_dir()
        and path.name.endswith("-output")
        and not_in_excluded(path.name.removesuffix("-output"))
    )


def load_lab_results_from_snapshots(lab_names: list[str] | None = None, labs_output_dir: Path | None = None) -> list[dict[str, Any]]:
    base_dir = labs_output_dir or LABS_OUTPUT_DIR
    selected = set(lab_names or [])
    discovered = discover_snapshot_lab_names(base_dir)
    if selected:
        invalid = sorted(selected - set(discovered))
        if invalid:
            raise SystemExit(
                "Unknown lab snapshot(s): "
                f"{', '.join(invalid)}. Impact: the consolidated report cannot be rebuilt for labs that do not have snapshot outputs. "
                "Action required: rerun python3 run_all.py for those labs first."
            )
        discovered = [lab for lab in discovered if lab in selected]

    lab_results: list[dict[str, Any]] = []
    for lab in discovered:
        snapshot_dir = base_dir / f"{lab}-output"
        report_json_path = snapshot_dir / "report.json"
        report_html_path = snapshot_dir / "report.html"
        if not report_json_path.exists() or not report_html_path.exists():
            missing = [str(path) for path in (report_json_path, report_html_path) if not path.exists()]
            raise FileNotFoundError(
                "Missing snapshot report file(s): "
                + ", ".join(missing)
                + ". Impact: the consolidated report cannot be rebuilt from an incomplete lab snapshot. "
                "Action required: rerun python3 run_all.py to regenerate the missing snapshot reports."
            )
        lab_report = load_json(report_json_path)
        lab_results.append(
            {
                "name": lab,
                "readmeHref": upstream_readme_href(lab),
                "status": lab_report.get("status", "failed"),
                "exitCode": 0 if lab_report.get("status") == "passed" else 1,
                "durationSeconds": round(report_duration_seconds(lab_report), 2),
                "reportJsonPath": str(report_json_path),
                "reportHtmlPath": str(report_html_path),
                "summary": lab_report.get("summary", []),
                "report": lab_report,
            }
        )
    return lab_results


def build_consolidated_payload(
    *,
    setup_payload: dict[str, Any] | None,
    labs_git_ref: str,
    lab_results: list[dict[str, Any]],
    generated_at: str,
    environment_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    passed = sum(1 for item in lab_results if item["status"] == "passed")
    failed = len(lab_results) - passed
    total_runtime_seconds = round(sum(item.get("durationSeconds", 0.0) for item in lab_results), 2)
    total_failures = sum(summary_value(item, "Failures") for item in lab_results)
    total_tests = sum(summary_value(item, "Validations") for item in lab_results)
    return {
        "generatedAt": generated_at,
        "provenance": detect_report_provenance(),
        "status": "passed" if failed == 0 else "failed",
        "summary": [
            {"label": "Labs discovered", "value": len(lab_results)},
            {"label": "Labs passed", "value": passed},
            {"label": "Labs failed", "value": failed},
            {"label": "Total run time (s)", "value": total_runtime_seconds},
            {"label": "Total failures", "value": total_failures},
            {"label": "Total tests", "value": total_tests},
        ],
        "setup": setup_payload,
        "environment": {
            "specmaticVersion": detect_shared_specmatic_version(lab_results),
            "labsGitRef": labs_git_ref,
            **(environment_overrides or {}),
        },
        "labs": lab_results,
    }


def detect_shared_specmatic_version(lab_results: list[dict[str, Any]]) -> str:
    versions = [
        extract_specmatic_version(Path(lab["reportJsonPath"]))
        for lab in lab_results
        if lab.get("reportJsonPath")
    ]
    versions = [version for version in versions if version != "n/a"]
    if not versions:
        return "n/a"
    unique_versions = sorted(set(versions))
    return unique_versions[0] if len(unique_versions) == 1 else " / ".join(unique_versions)


def extract_specmatic_version(report_json_path: Path) -> str:
    output_dir = report_json_path.parent
    for command_log in sorted(output_dir.glob("*/command.log")):
        text = command_log.read_text(encoding="utf-8", errors="ignore")
        enterprise_match = re.search(r"Specmatic Enterprise v([^\s]+)", text)
        core_match = re.search(r"Specmatic Core v([^\s]+)", text)
        versions: list[str] = []
        if enterprise_match:
            versions.append(f"Enterprise {enterprise_match.group(1)}")
        if core_match:
            versions.append(f"Core {core_match.group(1)}")
        if versions:
            return " / ".join(versions)
    return "n/a"


def upstream_readme_href(lab_name: str) -> str:
    return f"https://github.com/specmatic/labs/blob/main/{lab_name}/README.md"


def upstream_labs_git_ref() -> str:
    labs_dir = ROOT.parent / "labs"
    try:
        branch = subprocess.check_output(
            ["git", "-C", str(labs_dir), "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
        ).strip()
        short_sha = subprocess.check_output(
            ["git", "-C", str(labs_dir), "rev-parse", "--short", "HEAD"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "n/a"
    return f"{branch}@{short_sha}"


def report_duration_seconds(report: dict[str, Any] | None) -> float:
    if not report:
        return 0.0
    return sum(phase.get("command", {}).get("durationSeconds", 0.0) for phase in report.get("phases", []))


def summary_value(lab: dict[str, Any], label: str) -> int:
    for item in lab.get("summary", []):
        if item.get("label") == label:
            try:
                return int(item.get("value", 0))
            except (TypeError, ValueError):
                return 0
    return 0


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
