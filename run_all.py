from __future__ import annotations

import argparse
from datetime import UTC, datetime
from html import escape
import json
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lablib.command_runner import run_command
from lablib.workspace_setup import run_setup


OUTPUT_DIR = ROOT / "output"
SETUP_OUTPUT_PATH = OUTPUT_DIR / "setup-output.json"
CONSOLIDATED_JSON_PATH = OUTPUT_DIR / "consolidated-report.json"
CONSOLIDATED_HTML_PATH = OUTPUT_DIR / "consolidated-report.html"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all available lab harnesses and build a consolidated report.")
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
            print(f"Workspace setup failed. Details: {SETUP_OUTPUT_PATH}")
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

    labs = discover_labs()
    print(f"Discovered labs: {', '.join(labs) if labs else 'none'}")

    lab_results: list[dict[str, Any]] = []
    for lab in labs:
        print()
        print("=" * 78)
        print(f"{'REFRESHING REPORT FOR' if args.refresh_report else 'RUNNING LAB'}: {lab}")
        print("=" * 78)
        lab_command = ["python3", f"{lab}/run.py", "--refresh-report"] if args.refresh_report else ["python3", f"{lab}/run.py", "--skip-setup"]
        result = run_command(
            lab_command,
            ROOT,
            stream_output=True,
            stream_prefix=f"[all:{lab}]",
        )
        report_json_path = ROOT / lab / "output" / "report.json"
        report_html_path = ROOT / lab / "output" / "report.html"
        lab_report = load_json(report_json_path) if report_json_path.exists() else None
        duration_seconds = round(report_duration_seconds(lab_report), 2) if lab_report else round(result.duration_seconds, 2)
        lab_results.append(
            {
                "name": lab,
                "status": (lab_report or {}).get("status", "failed"),
                "exitCode": result.exit_code,
                "durationSeconds": duration_seconds,
                "reportJsonPath": str(report_json_path),
                "reportHtmlPath": str(report_html_path),
                "summary": (lab_report or {}).get("summary", []),
                "report": lab_report,
            }
        )

    passed = sum(1 for item in lab_results if item["status"] == "passed")
    failed = len(lab_results) - passed
    consolidated = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "status": "passed" if failed == 0 else "failed",
        "summary": [
            {"label": "Labs discovered", "value": len(lab_results)},
            {"label": "Labs passed", "value": passed},
            {"label": "Labs failed", "value": failed},
        ],
        "setup": setup_payload,
        "labs": lab_results,
    }
    write_consolidated_report(consolidated)
    print(f"Wrote consolidated JSON report to {CONSOLIDATED_JSON_PATH}")
    print(f"Wrote consolidated HTML report to {CONSOLIDATED_HTML_PATH}")
    return 0 if consolidated["status"] == "passed" else 1


def discover_labs() -> list[str]:
    return sorted(
        path.name
        for path in ROOT.iterdir()
        if path.is_dir() and not path.name.startswith(".") and (path / "run.py").exists()
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def report_duration_seconds(report: dict[str, Any] | None) -> float:
    if not report:
        return 0.0
    return sum(phase.get("command", {}).get("durationSeconds", 0.0) for phase in report.get("phases", []))


def write_consolidated_report(payload: dict[str, Any]) -> None:
    CONSOLIDATED_JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    CONSOLIDATED_HTML_PATH.write_text(render_consolidated_html(payload), encoding="utf-8")


def render_consolidated_html(payload: dict[str, Any]) -> str:
    summary_items = "".join(
        f"<li><strong>{escape(item['label'])}:</strong> {escape(str(item['value']))}</li>"
        for item in payload.get("summary", [])
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
          </tr>
        </thead>
        <tbody>
          {lab_rows}
        </tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def render_lab_row(lab: dict[str, Any]) -> str:
    failures = next((item["value"] for item in lab.get("summary", []) if item["label"] == "Failures"), "n/a")
    json_link = relative_link(CONSOLIDATED_HTML_PATH.parent, Path(lab["reportJsonPath"]))
    html_link = relative_link(CONSOLIDATED_HTML_PATH.parent, Path(lab["reportHtmlPath"]))
    return (
        "<tr>"
        f"<td>{escape(lab['name'])}</td>"
        f"<td>{escape(lab['status'])}</td>"
        f"<td>{escape(str(lab['exitCode']))}</td>"
        f"<td>{escape(str(lab.get('durationSeconds', 'n/a')))}</td>"
        f"<td><a href=\"{escape(json_link)}\">json</a> / <a href=\"{escape(html_link)}\">html</a></td>"
        f"<td>{escape(str(failures))}</td>"
        "</tr>"
    )


def relative_link(base_dir: Path, target: Path) -> str:
    return os.path.relpath(target, start=base_dir)


if __name__ == "__main__":
    raise SystemExit(main())
