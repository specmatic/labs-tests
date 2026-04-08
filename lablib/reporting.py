from __future__ import annotations

from datetime import UTC, datetime
from html import escape
import json
from pathlib import Path
import re
from typing import Any


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_html(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(payload), encoding="utf-8")


def render_html(payload: dict[str, Any]) -> str:
    phases_with_ids, failed_assertions = assign_assertion_ids(payload.get("phases", []))
    title = escape(payload["lab"]["name"])
    generated_at = escape(payload["generatedAt"])
    overall_status = escape(payload["status"].upper())
    summary_items = "".join(
        f"<li><strong>{escape(item['label'])}:</strong> {escape(str(item['value']))}</li>"
        for item in payload.get("summary", [])
    )
    phases = "".join(render_phase(phase) for phase in phases_with_ids)
    failure_index_html = render_failure_index(failed_assertions)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} automation report</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffdf8;
      --text: #182126;
      --muted: #55636f;
      --border: #d7ccb8;
      --pass: #1f7a4d;
      --fail: #ab2e2e;
      --warn: #9a5b00;
      --accent: #145a7a;
    }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, #f1dfb9 0, transparent 28%),
        linear-gradient(180deg, #fbf7ef 0%, var(--bg) 100%);
    }}
    main {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 32px 20px 56px;
    }}
    .hero, .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: 0 14px 40px rgba(35, 31, 25, 0.08);
    }}
    .hero {{
      padding: 24px;
      margin-bottom: 20px;
    }}
    h1, h2, h3 {{
      margin: 0 0 12px;
      font-weight: 700;
    }}
    h1 {{
      font-size: 2rem;
    }}
    h2 {{
      font-size: 1.35rem;
      margin-bottom: 10px;
    }}
    h3 {{
      font-size: 1rem;
    }}
    p, li {{
      line-height: 1.45;
    }}
    .status {{
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      color: white;
      background: var(--accent);
      font-size: 0.88rem;
      letter-spacing: 0.03em;
    }}
    .status.pass {{
      background: var(--pass);
    }}
    .status.fail {{
      background: var(--fail);
    }}
    .grid {{
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      margin-top: 18px;
    }}
    .panel {{
      padding: 18px;
      margin-top: 18px;
    }}
    .toolbar {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 18px;
    }}
    .toolbar button {{
      border: 1px solid #d7ccb8;
      background: #fbf6ec;
      color: #182126;
      border-radius: 999px;
      padding: 8px 12px;
      cursor: pointer;
      font: inherit;
    }}
    .assertions {{
      margin: 0;
      padding-left: 20px;
    }}
    .assertions li {{
      margin-bottom: 10px;
    }}
    .assertion-details {{
      margin-top: 8px;
      padding-top: 0;
      border-top: 0;
    }}
    .assertion-details summary {{
      cursor: pointer;
      color: var(--accent);
      font-size: 0.92rem;
    }}
    .detail-grid {{
      display: grid;
      gap: 8px;
      margin-top: 10px;
    }}
    .detail-item {{
      border: 1px solid #eadfcd;
      border-radius: 10px;
      background: #fbf6ec;
      padding: 10px 12px;
    }}
    .detail-item strong {{
      display: block;
      margin-bottom: 4px;
    }}
    .failure-index {{
      margin-top: 18px;
    }}
    .failure-index ul {{
      margin: 0;
      padding-left: 20px;
    }}
    .failure-index a {{
      color: var(--fail);
      text-decoration: none;
      border-bottom: 1px solid rgba(171, 46, 46, 0.35);
    }}
    .failure-group {{
      margin-top: 14px;
    }}
    .failure-group h3 {{
      margin-bottom: 8px;
    }}
    .category-summary table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
    }}
    .category-summary th, .category-summary td {{
      text-align: left;
      padding: 8px 6px;
      border-bottom: 1px solid #eadfcd;
      vertical-align: top;
    }}
    .category-summary a {{
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px solid rgba(20, 90, 122, 0.35);
    }}
    .table-wrap {{
      margin-top: 10px;
      overflow-x: auto;
    }}
    .table-wrap table {{
      width: 100%;
      min-width: 360px;
      border-collapse: collapse;
      background: #fffaf1;
      border: 1px solid #eadfcd;
      border-radius: 10px;
      overflow: hidden;
    }}
    .table-wrap th,
    .table-wrap td {{
      text-align: left;
      padding: 10px 12px;
      border-bottom: 1px solid #eadfcd;
      vertical-align: top;
      white-space: nowrap;
    }}
    .table-wrap th {{
      background: #f7efe0;
      font-size: 0.95rem;
    }}
    .table-wrap tbody tr:last-child td {{
      border-bottom: 0;
    }}
    .category-summary {{
      margin-bottom: 22px;
    }}
    .phase-block {{
      margin-top: 18px;
    }}
    .phase-block > summary,
    .assertion-section > summary,
    .console-block > summary,
    .artifacts-block > summary {{
      cursor: pointer;
      list-style: none;
      position: relative;
      padding-left: 24px;
    }}
    .phase-block > summary::-webkit-details-marker,
    .assertion-section > summary::-webkit-details-marker,
    .console-block > summary::-webkit-details-marker,
    .artifacts-block > summary::-webkit-details-marker {{
      display: none;
    }}
    .phase-block > summary::before,
    .assertion-section > summary::before,
    .console-block > summary::before,
    .artifacts-block > summary::before {{
      content: "▸";
      position: absolute;
      left: 0;
      top: 2px;
      color: var(--accent);
      font-size: 1rem;
      line-height: 1;
      transition: transform 0.15s ease;
    }}
    .phase-block[open] > summary::before,
    .assertion-section[open] > summary::before,
    .console-block[open] > summary::before,
    .artifacts-block[open] > summary::before {{
      transform: rotate(90deg);
    }}
    .toggle-hint {{
      color: var(--muted);
      font-size: 0.9rem;
      margin: 6px 0 12px;
    }}
    .summary-row {{
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .summary-row h2,
    .summary-row h3 {{
      margin: 0;
    }}
    .assertion-anchor {{
      scroll-margin-top: 24px;
    }}
    .pass-text {{
      color: var(--pass);
    }}
    .fail-text {{
      color: var(--fail);
    }}
    .artifacts {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 12px;
    }}
    .artifacts a {{
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px solid rgba(20, 90, 122, 0.35);
    }}
    details {{
      margin-top: 14px;
      border-top: 1px solid var(--border);
      padding-top: 12px;
    }}
    pre {{
      overflow-x: auto;
      white-space: pre-wrap;
      word-break: break-word;
      border-radius: 12px;
      padding: 14px;
      background: #fbf6ec;
      border: 1px solid #eadfcd;
      font-size: 0.9rem;
    }}
    .meta {{
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .section-heading {{
      margin-top: 10px;
      margin-bottom: 12px;
    }}
  </style>
</head>
<body>
  <main>
    <section class="hero">
      <div class="status {'pass' if payload['status'] == 'passed' else 'fail'}">{overall_status}</div>
      <h1>{title}</h1>
      <p>{escape(payload['lab']['description'])}</p>
      <p class="meta">Generated at {generated_at}</p>
      <div class="grid">
        <section class="panel">
          <h2>Summary</h2>
          <ul>{summary_items}</ul>
        </section>
        <section class="panel">
          <h2>Key Paths</h2>
          <ul>
            <li><strong>Lab folder:</strong> {escape(payload['lab']['labPath'])}</li>
            <li><strong>Spec file:</strong> {escape(payload['lab']['specPath'])}</li>
            <li><strong>Local output:</strong> {escape(payload['lab']['outputPath'])}</li>
          </ul>
        </section>
      </div>
      {failure_index_html}
      <div class="toolbar">
        <button type="button" onclick="toggleAllDetails(true)">Expand All</button>
        <button type="button" onclick="toggleAllDetails(false)">Collapse All</button>
      </div>
    </section>
    {phases}
  </main>
  <script>
    document.addEventListener('DOMContentLoaded', function() {{
      document.querySelectorAll('details.phase-block, details.assertion-section, details.artifacts-block').forEach(function(node) {{
        node.open = false;
      }});
    }});

    function toggleAllDetails(open) {{
      document.querySelectorAll('details.phase-block, details.assertion-section, details.console-block, details.artifacts-block, details.assertion-details').forEach(function(node) {{
        node.open = open;
      }});
    }}
  </script>
</body>
</html>
"""


def render_phase(phase: dict[str, Any]) -> str:
    assertions = render_assertion_sections(phase)
    category_summary = render_category_summary(phase)
    artifacts_html = render_artifacts_section(phase.get("artifacts", []))
    command_html = ""
    command = phase.get("command")
    if command:
        command_html = (
            f"<p><strong>Command:</strong> {escape(command['display'])}<br>"
            f"<span class=\"meta\">Exit code {command['exitCode']} in {command['durationSeconds']}s</span></p>"
        )
    console_html = ""
    if phase.get("consoleSnippet"):
        console_html = (
            "<details class=\"console-block\"><summary>Console Snippet</summary>"
            f"<pre>{escape(phase['consoleSnippet'])}</pre></details>"
        )
    fix_html = ""
    if phase.get("fixSummary"):
        fix_items = "".join(f"<li>{escape(item)}</li>" for item in phase["fixSummary"])
        fix_html = f"<h3>What Changed</h3><ul>{fix_items}</ul>"

    return (
        f"<details class=\"panel phase-block\">"
        f"<summary><div class=\"summary-row\"><div class=\"status {'pass' if phase['status'] == 'passed' else 'fail'}\">{escape(phase['status'].upper())}</div><h2>{escape(phase['name'])}</h2></div></summary>"
        f"<p class=\"toggle-hint\">Click the section title to expand or collapse details.</p>"
        f"<p>{escape(phase['description'])}</p>"
        f"{command_html}"
        f"{fix_html}"
        f"{category_summary}"
        f"{assertions}"
        f"{artifacts_html}"
        f"{console_html}"
        f"</details>"
    )


def render_assertion(assertion: dict[str, Any]) -> str:
    css_class = "pass-text" if assertion["status"] == "passed" else "fail-text"
    details_html = ""
    if assertion.get("details"):
        detail_items = "".join(
            render_detail_item(item)
            for item in assertion["details"]
        )
        details_html = (
            "<details class=\"assertion-details\">"
            "<summary>View details</summary>"
            f"<div class=\"detail-grid\">{detail_items}</div>"
            "</details>"
        )
    return (
        f"<li id=\"{escape(assertion['id'])}\" class=\"assertion-anchor\"><span class=\"{css_class}\"><strong>{escape(assertion['status'].upper())}</strong></span> "
        f"{escape(assertion['message'])}{details_html}</li>"
    )


def render_assertion_sections(phase: dict[str, Any]) -> str:
    assertions = phase.get("assertions", [])
    grouped: dict[str, list[dict[str, Any]]] = {}
    for assertion in assertions:
        grouped.setdefault(assertion.get("category", "other"), []).append(assertion)

    sections = "".join(
        render_assertion_section(phase["name"], category, items) for category, items in grouped.items()
    )
    return f"<h3 class=\"section-heading\">Validations</h3>{sections}"


def render_assertion_section(phase_name: str, category: str, assertions: list[dict[str, Any]]) -> str:
    items = "".join(render_assertion(assertion) for assertion in assertions)
    section_id = category_section_id(phase_name, category)
    return (
        f"<details id=\"{escape(section_id)}\" class=\"assertion-section\">"
        f"<summary><h3>{escape(category_title(category))}</h3></summary>"
        f"<ul class=\"assertions\">{items}</ul>"
        f"</details>"
    )


def render_artifacts_section(artifacts: list[dict[str, Any]]) -> str:
    if not artifacts:
        return ""
    artifact_links = "".join(
        f'<a href="{escape(item["href"])}">{escape(item["label"])}</a>'
        for item in artifacts
    )
    return (
        "<details class=\"artifacts-block\">"
        "<summary><h3>Artifacts</h3></summary>"
        f"<div class=\"artifacts\">{artifact_links}</div>"
        "</details>"
    )


def render_detail_item(item: dict[str, Any]) -> str:
    if item.get("type") == "table":
        headers = item.get("headers", [])
        rows = item.get("rows", [])
        header_html = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
        row_html = "".join(
            "<tr>" + "".join(f"<td>{escape('' if value is None else str(value))}</td>" for value in row) + "</tr>"
            for row in rows
        )
        rendered_value = (
            '<div class="table-wrap"><table>'
            f"<thead><tr>{header_html}</tr></thead>"
            f"<tbody>{row_html}</tbody>"
            "</table></div>"
        )
        return (
            f"<div class=\"detail-item\"><strong>{escape(item['label'])}</strong>{rendered_value}</div>"
        )

    value = "" if item.get("value") is None else str(item["value"])
    if "\n" in value:
        rendered_value = f"<pre>{escape(value)}</pre>"
    else:
        rendered_value = f"<div>{escape(value)}</div>"
    return (
        f"<div class=\"detail-item\"><strong>{escape(item['label'])}</strong>{rendered_value}</div>"
    )


def assign_assertion_ids(phases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    failed_assertions: list[dict[str, str]] = []
    for phase_index, phase in enumerate(phases):
        for assertion_index, assertion in enumerate(phase.get("assertions", [])):
            assertion_id = f"phase-{phase_index + 1}-assertion-{assertion_index + 1}"
            assertion["id"] = assertion_id
            if assertion["status"] != "passed":
                failed_assertions.append(
                    {
                        "id": assertion_id,
                        "phase": phase["name"],
                        "category": assertion.get("category", "other"),
                        "message": assertion["message"],
                    }
                )
    return phases, failed_assertions


def render_failure_index(failed_assertions: list[dict[str, str]]) -> str:
    if not failed_assertions:
        return ""
    grouped: dict[str, list[dict[str, str]]] = {}
    for item in failed_assertions:
        grouped.setdefault(item["category"], []).append(item)

    groups_html = "".join(
        render_failure_group(category, items) for category, items in grouped.items()
    )
    return (
        '<section class="panel failure-index">'
        "<h2>Failure Index</h2>"
        "<p>Jump directly to the failed checks below.</p>"
        f"{groups_html}"
        "</section>"
    )


def render_failure_group(category: str, items: list[dict[str, str]]) -> str:
    list_items = "".join(
        f'<li><a href="#{escape(item["id"])}">{escape(item["phase"])}: {escape(item["message"])}</a></li>'
        for item in items
    )
    return (
        f'<section class="failure-group">'
        f"<h3>{escape(category_label(category))}</h3>"
        f"<ul>{list_items}</ul>"
        f"</section>"
    )


def category_label(category: str) -> str:
    labels = {
        "runtime": "Runtime Failures",
        "readme": "README Failures",
        "artifacts": "Artifact Failures",
        "setup": "Setup Failures",
    }
    return labels.get(category, f"{category.title()} Failures")


def category_title(category: str) -> str:
    labels = {
        "command": "Command Validations",
        "console": "Console Validations",
        "report": "Report Validations",
        "readme": "README Validations",
        "artifacts": "Artifact Validations",
        "setup": "Setup Validations",
    }
    return labels.get(category, f"{category.title()} Validations")


def render_category_summary(phase: dict[str, Any]) -> str:
    assertions = phase.get("assertions", [])
    grouped: dict[str, dict[str, int]] = {}
    for assertion in assertions:
        category = assertion.get("category", "other")
        stats = grouped.setdefault(category, {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "other": 0})
        stats["total"] += 1
        status = assertion.get("status", "other")
        if status == "passed":
            stats["passed"] += 1
        elif status == "failed":
            stats["failed"] += 1
        elif status == "skipped":
            stats["skipped"] += 1
        else:
            stats["other"] += 1

    rows = "".join(
        f"<tr><td><a href=\"#{escape(category_section_id(phase['name'], category))}\">{escape(category_title(category))}</a></td><td>{stats['total']}</td><td>{stats['passed']}</td><td>{stats['failed']}</td><td>{stats['skipped']}</td><td>{stats['other']}</td></tr>"
        for category, stats in grouped.items()
    )
    return (
        '<section class="category-summary">'
        "<h3>Category Summary</h3>"
        "<table>"
        "<thead><tr><th>Category</th><th>Total</th><th>Pass</th><th>Fail</th><th>Skip</th><th>Other</th></tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
        "</section>"
    )


def category_section_id(phase_name: str, category: str) -> str:
    phase_slug = re.sub(r"[^a-z0-9]+", "-", phase_name.lower()).strip("-")
    category_slug = re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")
    return f"{phase_slug}-{category_slug}"


def build_report(
    *,
    lab_name: str,
    description: str,
    lab_path: Path,
    spec_path: Path,
    output_path: Path,
    phases: list[dict[str, Any]],
) -> dict[str, Any]:
    overall_status = "passed" if all(phase["status"] == "passed" for phase in phases) else "failed"
    total_assertions = sum(len(phase["assertions"]) for phase in phases)
    failed_assertions = sum(
        1
        for phase in phases
        for assertion in phase["assertions"]
        if assertion["status"] != "passed"
    )

    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "status": overall_status,
        "lab": {
            "name": lab_name,
            "description": description,
            "labPath": str(lab_path),
            "specPath": str(spec_path),
            "outputPath": str(output_path),
        },
        "summary": [
            {"label": "Phases", "value": len(phases)},
            {"label": "Validations", "value": total_assertions},
            {"label": "Failures", "value": failed_assertions},
        ],
        "phases": phases,
    }
