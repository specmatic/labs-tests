from __future__ import annotations

from datetime import UTC, datetime
from html import escape
import json
from pathlib import Path
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
    </section>
    {phases}
  </main>
</body>
</html>
"""


def render_phase(phase: dict[str, Any]) -> str:
    artifacts = "".join(
        f'<a href="{escape(item["href"])}">{escape(item["label"])}</a>'
        for item in phase.get("artifacts", [])
    )
    assertions = "".join(render_assertion(assertion) for assertion in phase.get("assertions", []))
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
            "<details><summary>Console snippet</summary>"
            f"<pre>{escape(phase['consoleSnippet'])}</pre></details>"
        )
    fix_html = ""
    if phase.get("fixSummary"):
        fix_items = "".join(f"<li>{escape(item)}</li>" for item in phase["fixSummary"])
        fix_html = f"<h3>What Changed</h3><ul>{fix_items}</ul>"

    return (
        f"<section class=\"panel\">"
        f"<div class=\"status {'pass' if phase['status'] == 'passed' else 'fail'}\">{escape(phase['status'].upper())}</div>"
        f"<h2>{escape(phase['name'])}</h2>"
        f"<p>{escape(phase['description'])}</p>"
        f"{command_html}"
        f"{fix_html}"
        f"<h3>Assertions</h3>"
        f"<ul class=\"assertions\">{assertions}</ul>"
        f"<div class=\"artifacts\">{artifacts}</div>"
        f"{console_html}"
        f"</section>"
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


def render_detail_item(item: dict[str, Any]) -> str:
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
            {"label": "Assertions", "value": total_assertions},
            {"label": "Failures", "value": failed_assertions},
        ],
        "phases": phases,
    }
