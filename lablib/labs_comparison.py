from __future__ import annotations

from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from html import escape
import importlib.util
import json
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
COMPARISON_JSON_PATH = OUTPUT_DIR / "labs-comparison.json"
COMPARISON_HTML_PATH = OUTPUT_DIR / "labs-comparison.html"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


def generate_labs_comparison(root: Path | None = None) -> dict[str, Any]:
    repo_root = root or ROOT
    labs = [build_lab_profile(path.parent) for path in sorted(repo_root.glob("*/run.py"))]
    payload = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "summary": build_summary(labs),
        "commonalities": build_commonalities(labs),
        "differences": build_differences(labs),
        "labs": labs,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    COMPARISON_JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    COMPARISON_HTML_PATH.write_text(render_comparison_html(payload), encoding="utf-8")
    return payload


def build_lab_profile(lab_dir: Path) -> dict[str, Any]:
    module = load_lab_module(lab_dir / "run.py")
    spec = module.build_lab_spec()
    command = list(spec.command)
    common_artifacts = [artifact_profile(artifact) for artifact in spec.common_artifact_specs]
    phase_artifacts = []
    for phase in spec.phases:
        phase_artifacts.extend(artifact_profile(artifact) for artifact in phase.artifact_specs)

    upstream_readme_text = spec.readme_path.read_text(encoding="utf-8")
    headings = extract_headings(upstream_readme_text)
    h2_headings = [heading["text"] for heading in headings if heading["level"] == 2]
    command_type = classify_command(command)
    artifact_labels = sorted({artifact["label"] for artifact in [*common_artifacts, *phase_artifacts]})
    artifact_kinds = sorted({artifact["kind"] for artifact in [*common_artifacts, *phase_artifacts]})
    setup_signals = detect_setup_signals(spec.upstream_lab, command, upstream_readme_text)

    return {
        "name": spec.name,
        "description": spec.description,
        "command": command,
        "commandType": command_type,
        "setup": setup_signals,
        "filesUnderTest": {alias: str(path.relative_to(spec.upstream_lab)) for alias, path in spec.files.items()},
        "phases": [
            {
                "name": phase.name,
                "expectedExitCode": phase.expected_exit_code,
                "hasFixSummary": bool(phase.fix_summary),
                "expectedConsolePhrases": list(phase.expected_console_phrases),
                "artifactLabels": [artifact.label for artifact in phase.artifact_specs],
            }
            for phase in spec.phases
        ],
        "artifacts": {
            "labels": artifact_labels,
            "kinds": artifact_kinds,
            "common": common_artifacts,
            "phaseSpecific": phase_artifacts,
            "families": detect_artifact_families(artifact_labels),
        },
        "readme": {
            "h1": next((heading["text"] for heading in headings if heading["level"] == 1), ""),
            "requiredH2": list(spec.readme_structure.required_h2_prefixes) if spec.readme_structure else [],
            "additionalH2": list(spec.readme_structure.additional_h2_prefixes) if spec.readme_structure else [],
            "actualH2": h2_headings,
            "hasStudioSection": any("studio" in heading.lower() for heading in h2_headings),
            "hasTroubleshooting": any("troubleshooting" in heading.lower() for heading in h2_headings),
            "hasPassCriteria": any("pass criteria" in heading.lower() or "verify the fix" in heading.lower() for heading in h2_headings),
            "headingCount": len(headings),
            "h2Count": len(h2_headings),
        },
    }


def load_lab_module(run_file: Path) -> Any:
    module_name = f"labs_tests_{run_file.parent.name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, run_file)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module from {run_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def artifact_profile(artifact: Any) -> dict[str, Any]:
    if is_dataclass(artifact):
        data = asdict(artifact)
    else:
        data = {
            "label": artifact.label,
            "source_relpath": artifact.source_relpath,
            "target_relpath": artifact.target_relpath,
            "kind": artifact.kind,
        }
    return {
        "label": data["label"],
        "kind": data["kind"],
        "source": data["source_relpath"],
        "target": data["target_relpath"],
    }


def extract_headings(text: str) -> list[dict[str, Any]]:
    return [{"level": len(match.group(1)), "text": match.group(2).strip()} for match in HEADING_RE.finditer(text)]


def classify_command(command: list[str]) -> str:
    if command[:2] == ["docker", "compose"]:
        if "--profile" in command:
            return "docker-compose-profile"
        return "docker-compose"
    if command[:2] == ["docker", "run"]:
        return "docker-run"
    return "other"


def detect_setup_signals(upstream_lab: Path, command: list[str], readme_text: str) -> dict[str, Any]:
    compose_file = upstream_lab / "docker-compose.yaml"
    setup_type = classify_command(command)
    compose_text = compose_file.read_text(encoding="utf-8") if compose_file.exists() else ""
    return {
        "type": setup_type,
        "usesDockerCompose": setup_type.startswith("docker-compose"),
        "usesDockerRun": setup_type == "docker-run",
        "hasComposeFile": compose_file.exists(),
        "hasStudioProfile": "--profile studio" in readme_text or "studio:" in compose_text,
        "hasBuildFlag": "--build" in command,
        "hasAbortOnExit": "--abort-on-container-exit" in command,
    }


def detect_artifact_families(labels: list[str]) -> list[str]:
    families = []
    if any("coverage" in label for label in labels):
        families.append("coverage")
    if any("ctrf" in label for label in labels):
        families.append("ctrf")
    if any("html" in label or "report.html" in label for label in labels):
        families.append("html")
    if any("mcp" in label for label in labels):
        families.append("mcp")
    if any(label.endswith(".yaml") or label.endswith(".py") for label in labels):
        families.append("source-snapshot")
    return families


def build_summary(labs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    command_types = Counter(lab["commandType"] for lab in labs)
    setup_types = Counter(lab["setup"]["type"] for lab in labs)
    return [
        {"label": "Labs compared", "value": len(labs)},
        {"label": "Execution styles", "value": dict(command_types)},
        {"label": "Setup styles", "value": dict(setup_types)},
        {"label": "Labs with Studio sections", "value": sum(1 for lab in labs if lab["readme"]["hasStudioSection"])},
        {"label": "Labs with coverage artifacts", "value": sum(1 for lab in labs if "coverage" in lab["artifacts"]["families"])},
        {"label": "Labs with CTRF artifacts", "value": sum(1 for lab in labs if "ctrf" in lab["artifacts"]["families"])},
        {"label": "Labs with HTML artifacts", "value": sum(1 for lab in labs if "html" in lab["artifacts"]["families"])},
    ]


def build_commonalities(labs: list[dict[str, Any]]) -> dict[str, Any]:
    if not labs:
        return {}
    required_h2_sets = [set(lab["readme"]["requiredH2"]) for lab in labs if lab["readme"]["requiredH2"]]
    common_required_h2 = sorted(set.intersection(*required_h2_sets)) if required_h2_sets else []
    artifact_counter = Counter(label for lab in labs for label in lab["artifacts"]["labels"])
    phase_counter = Counter(tuple(phase["name"] for phase in lab["phases"]) for lab in labs)
    return {
        "commonRequiredReadmeSections": common_required_h2,
        "artifactLabelsUsedByAllLabs": sorted(label for label, count in artifact_counter.items() if count == len(labs)),
        "artifactLabelsUsedByMultipleLabs": sorted(label for label, count in artifact_counter.items() if count > 1),
        "phaseModels": [
            {"phases": list(phases), "count": count}
            for phases, count in sorted(phase_counter.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sharedCharacteristics": [
            "All automated labs use the same scaffolded LabSpec -> JSON report -> HTML report flow.",
            "Each lab keeps its outputs inside a lab-local output directory.",
            "README structure is validated against explicit required H2 sections.",
            "Most labs follow a two-phase baseline/fixed workflow.",
        ],
    }


def build_differences(labs: list[dict[str, Any]]) -> dict[str, Any]:
    readme_section_counter = Counter(section for lab in labs for section in lab["readme"]["requiredH2"])
    unique_readme_sections = {
        lab["name"]: sorted(section for section in lab["readme"]["requiredH2"] if readme_section_counter[section] == 1)
        for lab in labs
    }
    artifact_only = {
        lab["name"]: lab["artifacts"]["labels"]
        for lab in labs
        if len(lab["artifacts"]["labels"]) != len({label for other in labs for label in other["artifacts"]["labels"] if label in lab["artifacts"]["labels"]})
    }
    return {
        "uniqueReadmeSectionsByLab": unique_readme_sections,
        "executionDifferences": [
            {
                "lab": lab["name"],
                "commandType": lab["commandType"],
                "command": " ".join(lab["command"]),
                "setupType": lab["setup"]["type"],
            }
            for lab in labs
        ],
        "artifactDifferences": [
            {
                "lab": lab["name"],
                "families": lab["artifacts"]["families"],
                "labels": lab["artifacts"]["labels"],
            }
            for lab in labs
        ],
        "labsWithStudioSections": [lab["name"] for lab in labs if lab["readme"]["hasStudioSection"]],
        "labsWithoutStudioSections": [lab["name"] for lab in labs if not lab["readme"]["hasStudioSection"]],
        "sourceFilesUnderTest": {lab["name"]: lab["filesUnderTest"] for lab in labs},
        "artifactInventoryByLab": artifact_only,
    }


def render_comparison_html(payload: dict[str, Any]) -> str:
    summary_rows = "".join(
        f"<tr><th>{escape(item['label'])}</th><td>{escape(format_value(item['value']))}</td></tr>"
        for item in payload.get("summary", [])
    )
    common_list = "".join(f"<li>{escape(item)}</li>" for item in payload.get("commonalities", {}).get("sharedCharacteristics", []))
    common_sections = "".join(
        f"<li>{escape(section)}</li>" for section in payload.get("commonalities", {}).get("commonRequiredReadmeSections", [])
    )
    repeated_artifacts = "".join(
        f"<li>{escape(label)}</li>" for label in payload.get("commonalities", {}).get("artifactLabelsUsedByMultipleLabs", [])
    )
    phase_models = "".join(
        f"<tr><td>{escape(', '.join(item['phases']))}</td><td>{item['count']}</td></tr>"
        for item in payload.get("commonalities", {}).get("phaseModels", [])
    )
    lab_rows = "".join(render_lab_comparison_row(lab) for lab in payload.get("labs", []))
    difference_rows = "".join(
        f"<tr><td>{escape(item['lab'])}</td><td>{escape(item['commandType'])}</td><td><code>{escape(item['command'])}</code></td><td>{escape(item['setupType'])}</td></tr>"
        for item in payload.get("differences", {}).get("executionDifferences", [])
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Labs Comparison Report</title>
  <style>
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background: #f5f1e8;
      color: #182126;
    }}
    main {{
      max-width: 1200px;
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
    th {{
      white-space: nowrap;
    }}
    code {{
      font-family: "SFMono-Regular", "Consolas", monospace;
      font-size: 0.9em;
    }}
    ul {{
      margin: 0.25rem 0 0;
      padding-left: 1.2rem;
    }}
    .muted {{
      color: #5f6b74;
    }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>Labs Similarities And Differences</h1>
      <p class="muted">Generated at {escape(payload['generatedAt'])}</p>
      <table>{summary_rows}</table>
    </section>
    <section class="panel">
      <h2>Shared Patterns</h2>
      <p>These are the strongest common patterns across the automated labs.</p>
      <ul>{common_list}</ul>
      <h3>Common README Sections</h3>
      <ul>{common_sections}</ul>
      <h3>Repeated Artifact Labels</h3>
      <ul>{repeated_artifacts}</ul>
      <h3>Phase Models</h3>
      <table>
        <thead><tr><th>Phases</th><th>Labs</th></tr></thead>
        <tbody>{phase_models}</tbody>
      </table>
    </section>
    <section class="panel">
      <h2>Execution Differences</h2>
      <table>
        <thead><tr><th>Lab</th><th>Command Type</th><th>Command</th><th>Setup Type</th></tr></thead>
        <tbody>{difference_rows}</tbody>
      </table>
    </section>
    <section class="panel">
      <h2>Per-Lab Matrix</h2>
      <table>
        <thead>
          <tr>
            <th>Lab</th>
            <th>README Shape</th>
            <th>Approach</th>
            <th>Setup</th>
            <th>Artifacts</th>
            <th>Files Under Test</th>
          </tr>
        </thead>
        <tbody>{lab_rows}</tbody>
      </table>
    </section>
  </main>
</body>
</html>
"""


def render_lab_comparison_row(lab: dict[str, Any]) -> str:
    readme_bits = [
        f"H2 sections: {lab['readme']['h2Count']}",
        f"Studio section: {'yes' if lab['readme']['hasStudioSection'] else 'no'}",
        f"Troubleshooting: {'yes' if lab['readme']['hasTroubleshooting'] else 'no'}",
        f"Pass criteria/verify fix: {'yes' if lab['readme']['hasPassCriteria'] else 'no'}",
    ]
    approach_bits = [
        f"Phases: {', '.join(phase['name'] for phase in lab['phases'])}",
        f"Command type: {lab['commandType']}",
    ]
    setup_bits = [
        f"Type: {lab['setup']['type']}",
        f"Compose file: {'yes' if lab['setup']['hasComposeFile'] else 'no'}",
        f"Build flag: {'yes' if lab['setup']['hasBuildFlag'] else 'no'}",
        f"Abort on exit: {'yes' if lab['setup']['hasAbortOnExit'] else 'no'}",
    ]
    artifact_bits = [
        f"Families: {', '.join(lab['artifacts']['families']) or 'none'}",
        f"Labels: {', '.join(lab['artifacts']['labels']) or 'none'}",
    ]
    file_bits = ", ".join(f"{alias}: {path}" for alias, path in lab["filesUnderTest"].items())
    return (
        "<tr>"
        f"<td><strong>{escape(lab['name'])}</strong><br><span class='muted'>{escape(lab['description'])}</span></td>"
        f"<td>{render_bullets(readme_bits)}</td>"
        f"<td>{render_bullets(approach_bits)}</td>"
        f"<td>{render_bullets(setup_bits)}</td>"
        f"<td>{render_bullets(artifact_bits)}</td>"
        f"<td><code>{escape(file_bits)}</code></td>"
        "</tr>"
    )


def render_bullets(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"


def format_value(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}={val}" for key, val in value.items())
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)
