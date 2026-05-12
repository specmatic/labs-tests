from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
from typing import Any

from lablib.labs_comparison import COMPARISON_HTML_PATH, COMPARISON_JSON_PATH, generate_labs_comparison
from lablib.provenance import build_run_metadata
from lablib.report_building import build_consolidated_payload, upstream_labs_git_ref, upstream_readme_href
from lablib.time_display import format_report_datetime
from lablib.workspace_setup import (
    license_failure_dict,
    license_setup_dict,
    prepare_upstream_labs_license,
    resolve_license_txt_content,
    restore_upstream_labs_license,
    run_setup,
    setup_failure_action_lines,
    setup_failure_error_lines,
)


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


OUTPUT_DIR = ROOT / "output"
LABS_OUTPUT_DIR = OUTPUT_DIR / "labs-output"
LEGACY_LABS_OUTPUT_DIR = OUTPUT_DIR / "labs"
CONSOLIDATED_OUTPUT_DIR = OUTPUT_DIR / "consolidated-report"
RUN_METADATA_PATH = OUTPUT_DIR / "workflow-run-details.txt"
LATEST_OUTPUT_LINK = OUTPUT_DIR / "latest"
SETUP_OUTPUT_PATH = CONSOLIDATED_OUTPUT_DIR / "setup-output.json"
CONSOLIDATED_JSON_PATH = CONSOLIDATED_OUTPUT_DIR / "consolidated-report.json"
CONSOLIDATED_HTML_PATH = CONSOLIDATED_OUTPUT_DIR / "consolidated-report.html"
LEGACY_CONSOLIDATED_JSON_PATH = OUTPUT_DIR / "consolidated-report.json"
LEGACY_CONSOLIDATED_HTML_PATH = OUTPUT_DIR / "consolidated-report.html"
LEGACY_CONSOLIDATED_REPORT_JSON_PATH = CONSOLIDATED_OUTPUT_DIR / "report.json"
LEGACY_CONSOLIDATED_REPORT_HTML_PATH = CONSOLIDATED_OUTPUT_DIR / "report.html"
LEGACY_COMPARISON_JSON_PATH = OUTPUT_DIR / "labs-comparison.json"
LEGACY_COMPARISON_HTML_PATH = OUTPUT_DIR / "labs-comparison.html"
EXCLUDED_LABS = {"coding-agents", "arazzo-workflow-testing"}


def not_in_excluded(var: str) -> bool:
    return var not in EXCLUDED_LABS


def validate_license_prerequisites(args: Any) -> int | None:
    if args.refresh_report or not args.manage_license:
        return None
    try:
        resolve_license_txt_content()
    except RuntimeError as exc:
        setup_payload = failed_setup_payload(args, [license_failure_dict(str(exc))])
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        CONSOLIDATED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        write_setup_payload(setup_payload)
        print()
        print(f"[error] {exc}")
        print()
        print("[Action required]")
        print("")
        print("Fix the license setup issue above and rerun the labs.")
        print(f"Setup details: {SETUP_OUTPUT_PATH}")
        return 1
    return None


def initialize_output_workspace() -> None:
    preserve_existing_local_output()
    clean_output_tree()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LABS_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CONSOLIDATED_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_run_metadata()


def empty_setup_payload(args: Any) -> dict[str, Any]:
    return {
        "status": "passed",
        "upstreamLabsPath": str(ROOT.parent / "labs"),
        "refreshLabs": args.refresh_labs,
        "labsBranch": args.labs_branch,
        "manageLicense": args.manage_license,
        "enterpriseImage": getattr(args, "enterprise_image", "") or "",
        "force": args.force,
        "commands": [],
    }


def failed_setup_payload(args: Any, commands: list[dict[str, Any]]) -> dict[str, Any]:
    payload = empty_setup_payload(args)
    payload["status"] = "failed"
    payload["commands"] = commands
    return payload


def write_setup_payload(payload: dict[str, Any]) -> None:
    SETUP_OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_failed_run_reports(setup_payload: dict[str, Any]) -> int:
    completed_at = report_timestamp()
    write_consolidated_report(
        {
            "generatedAt": completed_at.isoformat(),
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
    generate_labs_comparison(ROOT, [], generated_at=completed_at.isoformat())
    archive_local_output_snapshot(completed_at)
    return 1


def execute_shared_setup(args: Any) -> tuple[dict[str, Any] | None, int | None]:
    if args.refresh_report:
        print("[reports] Refreshing reports from existing captured artifacts...")
        return None, None
    if args.skip_setup:
        return None, None

    print("Running shared setup for the sibling labs repository...")
    setup_result = run_setup(
        stream_output=True,
        refresh_labs=args.refresh_labs,
        target_branch=args.labs_branch,
        force=args.force,
        lab_names=args.labs,
    )
    setup_payload = {
        "status": setup_result.status,
        "upstreamLabsPath": setup_result.upstream_labs_path,
        "refreshLabs": args.refresh_labs,
        "labsBranch": args.labs_branch,
        "manageLicense": args.manage_license,
        "force": args.force,
        "commands": list(setup_result.commands),
    }
    write_setup_payload(setup_payload)
    if setup_result.status == "passed":
        return setup_payload, None

    print()
    for line in setup_failure_error_lines(setup_result.commands):
        print(line)
    print()
    for line in setup_failure_action_lines(setup_result.commands):
        print(line)
    print(f"Setup details: {SETUP_OUTPUT_PATH}")
    return setup_payload, write_failed_run_reports(setup_payload)


def prepare_license_for_run(
    args: Any,
    setup_payload: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, object | None, int | None]:
    if args.refresh_report:
        return setup_payload, None, None
    if not args.manage_license:
        payload = setup_payload or empty_setup_payload(args)
        write_setup_payload(payload)
        return payload, None, None

    try:
        license_state = prepare_upstream_labs_license()
    except RuntimeError as exc:
        payload = failed_setup_payload(args, [license_failure_dict(str(exc))])
        write_setup_payload(payload)
        print()
        print(f"[error] {exc}")
        print()
        print("[Action required]")
        print("")
        print("Fix the license setup issue above and rerun the labs.")
        print(f"Setup details: {SETUP_OUTPUT_PATH}")
        return payload, None, write_failed_run_reports(payload)

    print(f"[license] Prepared ../labs/license.txt using {license_state.applied_source}")
    if license_state.original_content is not None:
        print("[license] Existing ../labs/license.txt will be restored after the run")
    else:
        print("[license] ../labs/license.txt did not exist before this run and will be removed afterward")

    payload = setup_payload or empty_setup_payload(args)
    payload["commands"] = [*payload.get("commands", []), license_setup_dict(license_state)]
    write_setup_payload(payload)
    return payload, license_state, None


def finalize_run(
    setup_payload: dict[str, Any] | None,
    labs: list[str],
    lab_results: list[dict[str, Any]],
) -> int:
    completed_at = report_timestamp()
    consolidated = build_consolidated_payload(
        setup_payload=setup_payload,
        labs_git_ref=upstream_labs_git_ref(),
        lab_results=lab_results,
        generated_at=completed_at.isoformat(),
    )
    consolidated["navigation"] = {
        "comparisonReportHref": "labs-comparison.html",
    }
    write_consolidated_report(consolidated)
    comparison_payload = generate_labs_comparison(ROOT, labs, generated_at=completed_at.isoformat())
    archive_local_output_snapshot(completed_at)
    print(f"[reports] Wrote consolidated JSON report to {CONSOLIDATED_JSON_PATH}")
    print(f"[reports] Wrote consolidated HTML report to {CONSOLIDATED_HTML_PATH}")
    print(f"[reports] Wrote labs comparison JSON report to {COMPARISON_JSON_PATH}")
    print(f"[reports] Wrote labs comparison HTML report to {COMPARISON_HTML_PATH}")

    matrix_rows = comparison_payload.get("validationMatrix", {}).get("rows", [])
    if matrix_rows:
        required_labels = {
            "Command and Output fencing validation",
            "Test counts match across the README, console output, CTRF JSON, and Specmatic HTML",
        }
        selected_rows = [row for row in matrix_rows if row.get("label") in required_labels]
        if selected_rows:
            selected_rows_passed = all(bool(row.get("overallPassed")) for row in selected_rows)
            return 0 if selected_rows_passed else 1
    return 0 if consolidated["status"] == "passed" else 1


def restore_license_after_run(license_state: object | None) -> None:
    if license_state is not None:
        if license_state.existed and license_state.original_content is not None:
            print("[license] Restoring original ../labs/license.txt")
        else:
            print("[license] Removing temporary ../labs/license.txt")
    restore_upstream_labs_license(license_state)


def discover_labs() -> list[str]:
    upstream_labs = ROOT.parent / "labs"
    if not upstream_labs.exists():
        return []
    return sorted(
        path.name
        for path in upstream_labs.iterdir()
        if path.is_dir()
        and not path.name.startswith(".")
        and not_in_excluded(path.name)
        and (path / "README.md").exists()
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


def write_run_metadata() -> None:
    metadata = build_run_metadata(command=current_run_command())
    lines = [
        "Specmatic Labs Reports Metadata",
        "==============================",
        "",
    ]
    lines.extend(
        f"{label}: {value}" for label, value in metadata.items() if value
    )
    lines.append(f"Generated at (UTC): {datetime.now(timezone.utc).isoformat()}")
    RUN_METADATA_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def report_timestamp() -> datetime:
    return datetime.now().astimezone()


def current_run_command() -> str:
    original_args = getattr(sys, "orig_argv", None)
    if original_args:
        return shlex.join(original_args)
    executable = os.path.basename(sys.executable) or sys.executable or "python3"
    args = [executable, *sys.argv]
    return shlex.join(args)


def running_in_github_actions() -> bool:
    return bool(os.getenv("GITHUB_RUN_ID"))


def generated_output_paths() -> list[Path]:
    paths = [
        LABS_OUTPUT_DIR,
        LEGACY_LABS_OUTPUT_DIR,
        CONSOLIDATED_OUTPUT_DIR,
        RUN_METADATA_PATH,
        LEGACY_CONSOLIDATED_JSON_PATH,
        LEGACY_CONSOLIDATED_HTML_PATH,
        LEGACY_CONSOLIDATED_REPORT_JSON_PATH,
        LEGACY_CONSOLIDATED_REPORT_HTML_PATH,
        LEGACY_COMPARISON_JSON_PATH,
        LEGACY_COMPARISON_HTML_PATH,
    ]
    paths.extend(
        path
        for path in OUTPUT_DIR.iterdir()
        if path.is_dir() and path.name.endswith("-output")
    )

    deduplicated_paths: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        deduplicated_paths.append(path)
    return deduplicated_paths


def has_generated_output() -> bool:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return any(path.exists() for path in generated_output_paths())


def preserve_existing_local_output() -> None:
    if running_in_github_actions() or not has_generated_output() or LATEST_OUTPUT_LINK.exists():
        return
    snapshot_dir = archive_output_snapshot(datetime.now())
    update_latest_output_link(snapshot_dir)
    print(f"[reports] Preserved existing local output snapshot at {snapshot_dir}")


def archive_local_output_snapshot(timestamp: datetime) -> None:
    if running_in_github_actions() or not has_generated_output():
        return
    snapshot_dir = archive_output_snapshot(timestamp)
    update_latest_output_link(snapshot_dir)
    print(f"[reports] Archived local output snapshot at {snapshot_dir}")


def archive_output_snapshot(timestamp: datetime) -> Path:
    snapshot_dir = build_snapshot_dir(timestamp)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    for source in generated_output_paths():
        if not source.exists():
            continue
        target = snapshot_dir / source.name
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return snapshot_dir


def build_snapshot_dir(timestamp: datetime) -> Path:
    month_dir = OUTPUT_DIR / timestamp.strftime("%b-%Y")
    day_dir = month_dir / timestamp.strftime("%d-%b")
    base_dir = day_dir / timestamp.strftime("%H-%M-%S")
    if not base_dir.exists():
        return base_dir
    suffix = 1
    while True:
        candidate = day_dir / f"{timestamp.strftime('%H-%M-%S')}-{suffix:02d}"
        if not candidate.exists():
            return candidate
        suffix += 1


def update_latest_output_link(snapshot_dir: Path) -> None:
    if LATEST_OUTPUT_LINK.exists() or LATEST_OUTPUT_LINK.is_symlink():
        if LATEST_OUTPUT_LINK.is_dir() and not LATEST_OUTPUT_LINK.is_symlink():
            shutil.rmtree(LATEST_OUTPUT_LINK)
        else:
            LATEST_OUTPUT_LINK.unlink()
    relative_target = os.path.relpath(snapshot_dir, start=OUTPUT_DIR)
    LATEST_OUTPUT_LINK.symlink_to(relative_target, target_is_directory=True)


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


def clean_output_tree() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in (
        LABS_OUTPUT_DIR,
        LEGACY_LABS_OUTPUT_DIR,
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
    generated_at_html = f"<p>{escape(format_report_datetime(payload['generatedAt']))}</p>" if payload.get("generatedAt") else ""
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
      {generated_at_html}
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


def display_lab_status(status: str, lab_report: dict[str, Any] | None) -> str:
    if status == "failed" and lab_has_command_execution_failure(lab_report):
        return "Test Execution Failed"
    return status


def lab_has_command_execution_failure(lab_report: dict[str, Any] | None) -> bool:
    if not lab_report:
        return False
    for phase in lab_report.get("phases", []):
        if phase.get("status") != "failed":
            continue
        for assertion in phase.get("assertions", []):
            if assertion.get("status") == "failed" and assertion.get("category") == "command":
                return True
    return False


def render_lab_row(lab: dict[str, Any]) -> str:
    failures = next((item["value"] for item in lab.get("summary", []) if item["label"] == "Failures"), "n/a")
    total_tests = next((item["value"] for item in lab.get("summary", []) if item["label"] == "Validations"), "n/a")
    json_link = relative_link(CONSOLIDATED_HTML_PATH.parent, Path(lab["reportJsonPath"]))
    html_link = relative_link(CONSOLIDATED_HTML_PATH.parent, Path(lab["reportHtmlPath"]))
    readme_href = escape(str(lab.get("readmeHref", upstream_readme_href(lab["name"]))))
    return (
        "<tr>"
        f"<td><a href=\"{readme_href}\" target=\"_blank\" rel=\"noopener noreferrer\">{escape(lab['name'])}</a></td>"
        f"<td>{escape(str(lab.get('displayStatus', lab['status'])))}</td>"
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
