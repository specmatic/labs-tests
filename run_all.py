from __future__ import annotations

import argparse
from datetime import UTC, datetime
from html import escape
import json
import os
from pathlib import Path
import sys
import shutil
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lablib.command_runner import run_command
from lablib.labs_comparison import COMPARISON_HTML_PATH, COMPARISON_JSON_PATH, generate_labs_comparison
from lablib.report_building import build_consolidated_payload, report_duration_seconds, upstream_labs_git_ref, upstream_readme_href
from lablib.workspace_setup import (
    run_setup,
    setup_failure_action_lines,
    setup_failure_error_lines,
)


OUTPUT_DIR = ROOT / "output"
LABS_OUTPUT_DIR = OUTPUT_DIR / "labs"
CONSOLIDATED_OUTPUT_DIR = OUTPUT_DIR / "consolidated-report"
SETUP_OUTPUT_PATH = CONSOLIDATED_OUTPUT_DIR / "setup-output.json"
CONSOLIDATED_JSON_PATH = CONSOLIDATED_OUTPUT_DIR / "consolidated-report.json"
CONSOLIDATED_HTML_PATH = CONSOLIDATED_OUTPUT_DIR / "consolidated-report.html"
LEGACY_CONSOLIDATED_JSON_PATH = OUTPUT_DIR / "consolidated-report.json"
LEGACY_CONSOLIDATED_HTML_PATH = OUTPUT_DIR / "consolidated-report.html"
LEGACY_CONSOLIDATED_REPORT_JSON_PATH = CONSOLIDATED_OUTPUT_DIR / "report.json"
LEGACY_CONSOLIDATED_REPORT_HTML_PATH = CONSOLIDATED_OUTPUT_DIR / "report.html"
LEGACY_COMPARISON_JSON_PATH = OUTPUT_DIR / "labs-comparison.json"
LEGACY_COMPARISON_HTML_PATH = OUTPUT_DIR / "labs-comparison.html"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run all available lab harnesses and build the consolidated and comparison reports."
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
        "--branch",
        default="main",
        help="Branch to use with --refresh-labs. Defaults to main.",
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # `run_all.py` owns the destructive cleanup so one end-to-end run always starts
    # from a clean generated-output tree. `rebuild_reports.py` deliberately skips this
    # so the existing lab snapshots remain available for report regeneration.
    clean_output_tree()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LABS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CONSOLIDATED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    setup_payload: dict[str, Any] | None = None
    if args.refresh_report:
        print("Refreshing reports from existing captured artifacts...")
    elif not args.skip_setup:
        print("Running shared workspace setup...")
        setup_result = run_setup(
            stream_output=True,
            refresh_labs=args.refresh_labs,
            target_branch=args.branch,
            force=args.force,
            lab_names=args.labs,
        )
        setup_payload = {
            "status": setup_result.status,
            "upstreamLabsPath": setup_result.upstream_labs_path,
            "refreshLabs": args.refresh_labs,
            "branch": args.branch,
            "force": args.force,
            "commands": setup_result.commands,
        }
        SETUP_OUTPUT_PATH.write_text(json.dumps(setup_payload, indent=2) + "\n", encoding="utf-8")
        if setup_result.status != "passed":
            print()
            for line in setup_failure_error_lines(setup_result.commands):
                print(line)
            print()
            for line in setup_failure_action_lines(setup_result.commands):
                print(line)
            print(f"Setup details: {SETUP_OUTPUT_PATH}")
            write_consolidated_report(
                {
                    "generatedAt": datetime.now(UTC).isoformat(),
                    "status": "failed",
                    "summary": [
                        {"label": "Labs discovered", "value": 0},
                        {"label": "Labs passed", "value": 0},
                        {"label": "Labs failed", "value": 0},
                    ],
                    "setup": setup_payload,
                    "labs": [],
                }
            )
            return 1

    labs_git_ref = upstream_labs_git_ref()
    all_labs = discover_labs()
    labs = filter_labs(all_labs, args.labs)
    print(f"Discovered labs: {', '.join(labs) if labs else 'none'}")

    lab_results: list[dict[str, Any]] = []
    total_labs = len(labs)
    for index, lab in enumerate(labs, start=1):
        print()
        print("=" * 78)
        print(f"{'REFRESHING REPORT FOR' if args.refresh_report else 'RUNNING LAB'}: {lab}")
        print(f"Lab # {index} of {total_labs}")
        print("=" * 78)
        lab_command = ["python3", f"{lab}/run.py", "--refresh-report"] if args.refresh_report else ["python3", f"{lab}/run.py", "--skip-setup"]
        result = run_command(
            lab_command,
            ROOT,
            stream_output=True,
            stream_prefix=f"[all:{lab}]",
        )
        report_json_path, report_html_path = snapshot_lab_output(lab)
        copy_lab_snapshot(lab)
        lab_report = load_json(report_json_path) if report_json_path.exists() else None
        duration_seconds = round(report_duration_seconds(lab_report), 2) if lab_report else round(result.duration_seconds, 2)
        lab_results.append(
            {
                "name": lab,
                "readmeHref": upstream_readme_href(lab),
                "status": (lab_report or {}).get("status", "failed"),
                "exitCode": result.exit_code,
                "durationSeconds": duration_seconds,
                "reportJsonPath": str(report_json_path),
                "reportHtmlPath": str(report_html_path),
                "summary": (lab_report or {}).get("summary", []),
                "report": lab_report,
            }
        )

    consolidated = build_consolidated_payload(
        setup_payload=setup_payload,
        labs_git_ref=labs_git_ref,
        lab_results=lab_results,
    )
    consolidated["navigation"] = {
        "comparisonReportHref": "labs-comparison.html",
    }
    write_consolidated_report(consolidated)
    generate_labs_comparison(ROOT, labs)
    print(f"Wrote consolidated JSON report to {CONSOLIDATED_JSON_PATH}")
    print(f"Wrote consolidated HTML report to {CONSOLIDATED_HTML_PATH}")
    print(f"Wrote labs comparison JSON report to {COMPARISON_JSON_PATH}")
    print(f"Wrote labs comparison HTML report to {COMPARISON_HTML_PATH}")
    return 0 if consolidated["status"] == "passed" else 1


def discover_labs() -> list[str]:
    return sorted(
        path.name
        for path in ROOT.iterdir()
        if path.is_dir() and not path.name.startswith(".") and (path / "run.py").exists()
    )


def filter_labs(all_labs: list[str], selected_labs: list[str] | None) -> list[str]:
    if not selected_labs:
        return all_labs
    selected_set = set(selected_labs)
    invalid = sorted(selected_set - set(all_labs))
    if invalid:
        raise SystemExit(f"Unknown lab(s): {', '.join(invalid)}")
    return [lab for lab in all_labs if lab in selected_set]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_consolidated_report(payload: dict[str, Any]) -> None:
    CONSOLIDATED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for legacy_path in (
        LEGACY_CONSOLIDATED_JSON_PATH,
        LEGACY_CONSOLIDATED_HTML_PATH,
        LEGACY_CONSOLIDATED_REPORT_JSON_PATH,
        LEGACY_CONSOLIDATED_REPORT_HTML_PATH,
    ):
        if legacy_path.exists():
            legacy_path.unlink()
    CONSOLIDATED_JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    CONSOLIDATED_HTML_PATH.write_text(render_consolidated_html(payload), encoding="utf-8")


def snapshot_lab_output(lab: str) -> tuple[Path, Path]:
    target_dir = LABS_OUTPUT_DIR / f"{lab}-output"
    return target_dir / "report.json", target_dir / "report.html"


def copy_lab_snapshot(lab: str) -> None:
    source_dir = ROOT / lab / "output"
    target_dir = LABS_OUTPUT_DIR / f"{lab}-output"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    if source_dir.exists():
        shutil.copytree(source_dir, target_dir)
        rewrite_snapshot_back_link(target_dir / "report.html")


def rewrite_snapshot_back_link(report_path: Path) -> None:
    if not report_path.exists():
        return
    text = report_path.read_text(encoding="utf-8")
    source_hrefs = (
        "../../output/consolidated-report/consolidated-report.html",
        "../../output/consolidated-report/report.html",
    )
    target_href = os.path.relpath(CONSOLIDATED_HTML_PATH, start=report_path.parent)
    for source_href in source_hrefs:
        if source_href in text:
            report_path.write_text(text.replace(source_href, target_href), encoding="utf-8")
            return


def clean_output_tree() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in (
        LABS_OUTPUT_DIR,
        CONSOLIDATED_OUTPUT_DIR,
        LEGACY_CONSOLIDATED_JSON_PATH,
        LEGACY_CONSOLIDATED_HTML_PATH,
        LEGACY_CONSOLIDATED_REPORT_JSON_PATH,
        LEGACY_CONSOLIDATED_REPORT_HTML_PATH,
        LEGACY_COMPARISON_JSON_PATH,
        LEGACY_COMPARISON_HTML_PATH,
    ):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
    for legacy_dir in OUTPUT_DIR.iterdir():
        if legacy_dir.is_dir() and legacy_dir.name.endswith("-output"):
            shutil.rmtree(legacy_dir)


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


def render_consolidated_html(payload: dict[str, Any]) -> str:
    top_summary_labels = {"Labs discovered", "Labs passed", "Labs failed"}
    summary_items = "".join(
        f"<li><strong>{escape(item['label'])}:</strong> {escape(str(item['value']))}</li>"
        for item in payload.get("summary", [])
        if item.get("label") in top_summary_labels
    )
    setup_html = ""
    if payload.get("setup"):
        setup = payload["setup"]
        setup_html = (
            "<section class=\"panel\">"
            "<h2>Setup</h2>"
            f"<p><strong>Status:</strong> {escape(setup['status'])}</p>"
            f"<p><strong>Output:</strong> <a href=\"setup-output.json\">setup-output.json</a></p>"
            "</section>"
        )

    lab_rows = "".join(render_lab_row(lab) for lab in payload.get("labs", []))
    totals_row = render_totals_row(payload)
    environment = payload.get("environment", {})
    footer_html = (
        "<footer class=\"panel footer-panel\">"
        "<h2>Run Environment</h2>"
        f"<p><strong>Specmatic:</strong> {escape(str(environment.get('specmaticVersion', 'n/a')))}</p>"
        f"<p><strong>Labs git ref:</strong> {escape(str(environment.get('labsGitRef', 'n/a')))}</p>"
        "</footer>"
    )
    comparison_href = escape(payload.get("navigation", {}).get("comparisonReportHref", "labs-comparison.html"))
    report_nav_html = f'<p class="report-nav"><a href="{comparison_href}">Open comparison report</a></p>' if comparison_href else ""
    provenance_html = render_provenance_html(payload.get("provenance"))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Consolidated Labs Report</title>
  <style>
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background: #f5f1e8;
      color: #182126;
    }}
    main {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 28px 20px 56px;
    }}
    .panel {{
      background: #fffdf8;
      border: 1px solid #d7ccb8;
      border-radius: 16px;
      padding: 18px;
      margin-top: 18px;
      box-shadow: 0 14px 40px rgba(35, 31, 25, 0.08);
    }}
    .footer-panel p:last-child {{
      margin-bottom: 0;
    }}
    .report-nav {{
      margin: 10px 0 0;
    }}
    .report-nav a {{
      color: #145a7a;
      text-decoration: none;
      border-bottom: 1px solid rgba(20, 90, 122, 0.35);
    }}
    .status {{
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      color: white;
      background: {"#1f7a4d" if payload["status"] == "passed" else "#ab2e2e"};
      font-size: 0.88rem;
      letter-spacing: 0.03em;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid #eadfcd;
      vertical-align: top;
    }}
    a {{
      color: #145a7a;
      text-decoration: none;
      border-bottom: 1px solid rgba(20, 90, 122, 0.35);
    }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <div class="status">{escape(payload['status'].upper())}</div>
      <h1>Consolidated Labs Report</h1>
      {provenance_html}
      {report_nav_html}
      <ul>{summary_items}</ul>
    </section>
    {setup_html}
    <section class="panel">
      <h2>Labs</h2>
      <table>
        <thead>
          <tr>
            <th>Lab</th>
            <th>Status</th>
            <th>Exit Code</th>
            <th>Time (s)</th>
            <th>Reports</th>
            <th>Failures</th>
            <th>Total tests</th>
          </tr>
        </thead>
        <tbody>
          {lab_rows}
          {totals_row}
        </tbody>
      </table>
    </section>
    {footer_html}
  </main>
</body>
</html>
"""


def render_provenance_html(provenance: dict[str, Any] | None) -> str:
    if not provenance:
        return ""
    label = escape(str(provenance.get("label", "Generated from")))
    display = escape(str(provenance.get("display", "n/a")))
    href = str(provenance.get("href", "") or "")
    if href:
        return f'<p class="report-nav"><strong>{label}:</strong> <a href="{escape(href)}" target="_blank" rel="noopener noreferrer">{display}</a></p>'
    return f'<p class="report-nav"><strong>{label}:</strong> {display}</p>'


def render_lab_row(lab: dict[str, Any]) -> str:
    failures = next((item["value"] for item in lab.get("summary", []) if item["label"] == "Failures"), "n/a")
    total_tests = next((item["value"] for item in lab.get("summary", []) if item["label"] == "Validations"), "n/a")
    json_link = relative_link(CONSOLIDATED_HTML_PATH.parent, Path(lab["reportJsonPath"]))
    html_link = relative_link(CONSOLIDATED_HTML_PATH.parent, Path(lab["reportHtmlPath"]))
    readme_href = escape(str(lab.get("readmeHref", upstream_readme_href(lab["name"]))))
    return (
        "<tr>"
        f"<td><a href=\"{readme_href}\" target=\"_blank\" rel=\"noopener noreferrer\">{escape(lab['name'])}</a></td>"
        f"<td>{escape(lab['status'])}</td>"
        f"<td>{escape(str(lab['exitCode']))}</td>"
        f"<td>{escape(str(lab.get('durationSeconds', 'n/a')))}</td>"
        f"<td><a href=\"{escape(json_link)}\">json</a> / <a href=\"{escape(html_link)}\">html</a></td>"
        f"<td>{escape(str(failures))}</td>"
        f"<td>{escape(str(total_tests))}</td>"
        "</tr>"
    )


def render_totals_row(payload: dict[str, Any]) -> str:
    summary = {item["label"]: item["value"] for item in payload.get("summary", [])}
    return (
        "<tr>"
        "<td><strong>Total</strong></td>"
        "<td></td>"
        "<td></td>"
        f"<td><strong>{escape(str(summary.get('Total run time (s)', 'n/a')))}</strong></td>"
        "<td></td>"
        f"<td><strong>{escape(str(summary.get('Total failures', 'n/a')))}</strong></td>"
        f"<td><strong>{escape(str(summary.get('Total tests', 'n/a')))}</strong></td>"
        "</tr>"
    )


def relative_link(base_dir: Path, target: Path) -> str:
    return os.path.relpath(target, start=base_dir)


if __name__ == "__main__":
    raise SystemExit(main())
