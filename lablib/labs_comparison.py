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
COMPARISON_OUTPUT_DIR = OUTPUT_DIR / "consolidated-report"
COMPARISON_JSON_PATH = COMPARISON_OUTPUT_DIR / "labs-comparison.json"
COMPARISON_HTML_PATH = COMPARISON_OUTPUT_DIR / "labs-comparison.html"
LEGACY_COMPARISON_JSON_PATH = OUTPUT_DIR / "labs-comparison.json"
LEGACY_COMPARISON_HTML_PATH = OUTPUT_DIR / "labs-comparison.html"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
FENCED_CODE_BLOCK_RE = re.compile(r"```(?P<lang>[a-zA-Z0-9_-]+)?\s*\n(?P<body>.*?)```", re.DOTALL | re.MULTILINE)
SHELL_COMMAND_PREFIXES_RE = re.compile(r"^(docker|python|python3|chmod|git|curl|cd|npm|pnpm|yarn|make|bash|sh)\b")
IGNORED_ARTIFACT_LABELS = {"html", "coverage_report.json", "stub_usage_report.json"}
REPORT_ARTIFACT_LABELS = {"ctrf-report.json", "specmatic-report.html"}


def generate_labs_comparison(root: Path | None = None, lab_names: list[str] | None = None) -> dict[str, Any]:
    repo_root = root or ROOT
    selected = set(lab_names or [])
    run_files = sorted(repo_root.glob("*/run.py"))
    if selected:
        run_files = [path for path in run_files if path.parent.name in selected]
    labs = [build_lab_profile(path.parent) for path in run_files]
    payload = {
        "generatedAt": datetime.now(UTC).isoformat(),
        "summary": build_summary(labs),
        "commonalities": build_commonalities(labs),
        "differences": build_differences(labs),
        "validationMatrix": build_validation_matrix(labs),
        "labs": labs,
        "navigation": {
            "consolidatedReportHref": "consolidated-report.html",
        },
    }
    COMPARISON_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for legacy_path in (LEGACY_COMPARISON_JSON_PATH, LEGACY_COMPARISON_HTML_PATH):
        if legacy_path.exists():
            legacy_path.unlink()
    COMPARISON_JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    COMPARISON_HTML_PATH.write_text(render_comparison_html(payload), encoding="utf-8")
    return payload


def discover_lab_names(root: Path | None = None) -> list[str]:
    repo_root = root or ROOT
    return sorted(path.parent.name for path in repo_root.glob("*/run.py"))


def build_lab_profile(lab_dir: Path) -> dict[str, Any]:
    module = load_lab_module(lab_dir / "run.py")
    spec = module.build_lab_spec()
    common_artifacts = [artifact_profile(artifact) for artifact in spec.common_artifact_specs]
    phase_artifacts = []
    for phase in spec.phases:
        phase_artifacts.extend(artifact_profile(artifact) for artifact in phase.artifact_specs)

    upstream_readme_text = spec.readme_path.read_text(encoding="utf-8")
    headings = extract_headings(upstream_readme_text)
    h2_headings = [heading["text"] for heading in headings if heading["level"] == 2]
    h3_headings = [heading["text"] for heading in headings if heading["level"] == 3]
    code_blocks = extract_fenced_code_blocks(upstream_readme_text)
    readme_command = extract_primary_command(upstream_readme_text) or list(spec.command)
    command_type = classify_command(readme_command)
    setup_types = detect_setup_types(readme_command)
    artifact_labels = sorted({artifact["label"] for artifact in [*common_artifacts, *phase_artifacts]})
    artifact_kinds = sorted({artifact["kind"] for artifact in [*common_artifacts, *phase_artifacts]})
    shell_console_blocks = [block for block in code_blocks if looks_like_console_block(block) and block["language"] in {"shell", "bash", "sh"}]
    console_blocks = [block for block in code_blocks if looks_like_console_block(block)]
    shell_console_sections = build_shell_console_sections(headings, shell_console_blocks)
    additional_artifacts = sorted(
        label for label in artifact_labels if label not in REPORT_ARTIFACT_LABELS and label not in IGNORED_ARTIFACT_LABELS
    )
    report_snapshot = load_lab_report_snapshot(spec.name)
    test_count_consistency = build_test_count_consistency_profile(spec.name, upstream_readme_text, report_snapshot)

    return {
        "name": spec.name,
        "href": f"https://github.com/specmatic/labs/blob/main/{spec.upstream_lab.name}/README.md",
        "description": spec.description,
        "command": readme_command,
        "commandType": command_type,
        "setup": detect_setup_signals(spec.upstream_lab, readme_command, upstream_readme_text, setup_types),
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
        "phaseSignature": tuple(phase.name for phase in spec.phases),
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
            "actualH3": h3_headings,
            "hasStudioSection": any("studio" in heading.lower() for heading in h2_headings),
            "hasTroubleshooting": any("troubleshooting" in heading.lower() for heading in h2_headings),
            "hasPassCriteria": any("pass criteria" in heading.lower() or "verify the fix" in heading.lower() for heading in h2_headings),
            "headingCount": len(headings),
            "h2Count": len(h2_headings),
            "h3Count": len(h3_headings),
            "shellConsoleBlockCount": len(shell_console_blocks),
            "consoleBlockCount": len(console_blocks),
            "hasAtLeastTwoShellConsoleBlocks": len(shell_console_blocks) >= 2,
            "allConsoleBlocksUseShellSyntax": bool(console_blocks) and all(block["language"] in {"shell", "bash", "sh"} for block in console_blocks),
            "openingShellConsoleSection": shell_console_sections[0] if shell_console_sections else {},
            "closingShellConsoleSection": shell_console_sections[-1] if shell_console_sections else {},
            "shellConsoleSections": shell_console_sections,
        },
        "warnings": {
            "additionalArtifacts": additional_artifacts,
        },
        "testCountConsistency": test_count_consistency,
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
    return [
        {
            "line": line_number_for_index(text, match.start()),
            "level": len(match.group(1)),
            "text": match.group(2).strip(),
        }
        for match in HEADING_RE.finditer(text)
    ]


def extract_fenced_code_blocks(readme_text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for match in FENCED_CODE_BLOCK_RE.finditer(readme_text):
        blocks.append(
            {
                "language": (match.group("lang") or "").strip().lower(),
                "body": match.group("body").strip(),
                "line": line_number_for_index(readme_text, match.start()),
            }
        )
    return blocks


def line_number_for_index(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def looks_like_console_block(block: dict[str, Any]) -> bool:
    lines = [line.strip() for line in block["body"].splitlines() if line.strip()]
    if not lines:
        return False
    return bool(SHELL_COMMAND_PREFIXES_RE.match(lines[0]))


def build_shell_console_sections(headings: list[dict[str, Any]], shell_console_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections = []
    for block in shell_console_blocks:
        heading = heading_before_line(headings, block["line"])
        first_line = next((line.strip() for line in block["body"].splitlines() if line.strip()), "")
        sections.append(
            {
                "heading": heading["text"] if heading else "",
                "headingLevel": heading["level"] if heading else 0,
                "line": block["line"],
                "language": block["language"],
                "command": first_line,
                "summary": summarize_console_section(heading["text"] if heading else "", first_line),
            }
        )
    return sections


def heading_before_line(headings: list[dict[str, Any]], line: int) -> dict[str, Any] | None:
    before = [heading for heading in headings if heading["line"] <= line]
    return before[-1] if before else None


def summarize_console_section(heading: str, command: str) -> str:
    if heading and command:
        return f"{heading}: {command}"
    return heading or command


def extract_primary_command(readme_text: str) -> list[str]:
    for block in extract_fenced_code_blocks(readme_text):
        lines = [line.strip() for line in block["body"].splitlines() if line.strip()]
        for line in lines:
            if SHELL_COMMAND_PREFIXES_RE.match(line):
                return line.split()
    return []


def classify_command(command: list[str]) -> str:
    if command and command[0].startswith("python"):
        return "python"
    if command[:2] == ["docker", "compose"]:
        if "--profile" in command:
            return "docker-compose-profile"
        return "docker-compose"
    if command[:2] == ["docker", "run"]:
        return "docker-run"
    return "other"


def detect_setup_types(command: list[str]) -> list[str]:
    command_type = classify_command(command)
    return [command_type] if command_type != "other" else []


def detect_setup_signals(upstream_lab: Path, command: list[str], readme_text: str, setup_types: list[str]) -> dict[str, Any]:
    return {
        "type": setup_types[0] if setup_types else classify_command(command),
        "types": setup_types,
        "display": format_setup_types(setup_types),
        "usesPython": "python" in setup_types,
        "usesDockerCompose": any(setup_type.startswith("docker-compose") for setup_type in setup_types),
        "usesDockerRun": "docker-run" in setup_types,
        "hasComposeFile": (upstream_lab / "docker-compose.yaml").exists(),
        "hasStudioProfile": "--profile studio" in readme_text,
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
    setup_types = Counter(lab["setup"]["display"] for lab in labs)
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
    phase_sequences = [lab["phaseSignature"] for lab in labs if lab["phaseSignature"]]
    h1_counter = Counter(lab["readme"]["h1"] for lab in labs if lab["readme"]["h1"])
    h2_counter = Counter(tuple(lab["readme"]["actualH2"]) for lab in labs if lab["readme"]["actualH2"])
    return {
        "sharedReadmeH1": h1_counter.most_common(1)[0][0] if h1_counter else "",
        "sharedReadmeH2Sequence": list(h2_counter.most_common(1)[0][0]) if h2_counter else [],
        "commonRequiredReadmeSections": common_required_h2,
        "artifactLabelsUsedByAllLabs": sorted(label for label, count in artifact_counter.items() if count == len(labs)),
        "artifactLabelsUsedByMultipleLabs": sorted(label for label, count in artifact_counter.items() if count > 1),
        "commonPhasePrefix": list(longest_common_prefix(phase_sequences)),
        "phaseModels": [
            {"phases": list(phases), "count": count}
            for phases, count in sorted(phase_counter.items(), key=lambda item: (-item[1], item[0]))
        ],
        "sharedCharacteristics": [
            "All automated labs use the same scaffolded LabSpec -> JSON report -> HTML report flow.",
            "Each lab keeps its outputs inside a lab-local output directory.",
            "README structure is validated against explicit required H2 sections.",
            "Every compared lab begins with a baseline mismatch phase.",
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
                "labHref": lab["href"],
                "commandType": lab["commandType"],
                "command": " ".join(lab["command"]),
                "setupType": lab["setup"]["display"],
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


def build_validation_matrix(labs: list[dict[str, Any]]) -> dict[str, Any]:
    columns = [{"name": lab["name"], "href": lab["href"]} for lab in labs]
    shared_h1 = most_common_value([lab["readme"]["h1"] for lab in labs if lab["readme"]["h1"]])
    shared_h2 = most_common_value([tuple(lab["readme"]["actualH2"]) for lab in labs if lab["readme"]["actualH2"]])
    common_required_h2_sets = [set(lab["readme"]["requiredH2"]) for lab in labs if lab["readme"]["requiredH2"]]
    common_required_h2 = set.intersection(*common_required_h2_sets) if common_required_h2_sets else set()
    artifact_label_counts = Counter(label for lab in labs for label in lab["artifacts"]["labels"])
    common_phase_prefix = longest_common_prefix([lab["phaseSignature"] for lab in labs if lab["phaseSignature"]])
    rows = [
        {"kind": "group", "label": "Similarities", "section": "similarities", "cells": [None] * len(labs)},
        {
            "label": "README starts with a top-level H1",
            "tooltip": {
                "summary": ["Both READMEs start with an H1."],
                "details": build_h1_details(labs),
            },
            "cells": [bool(lab["readme"]["h1"]) for lab in labs],
        },
        {
            "label": "README H2 sequence follows the source README outline",
            "tooltip": build_h2_sequence_tooltip(labs, common_required_h2),
            "cells": [tuple(lab["readme"]["actualH2"]) == shared_h2 for lab in labs],
        },
        {
            "label": "README contains the common required H2 sections",
            "tooltip": {
                "summary": ["Both READMEs include the shared required H2 sections."],
                "details": build_shared_section_details(common_required_h2),
            },
            "cells": [common_required_h2.issubset(set(lab["readme"]["actualH2"])) for lab in labs],
        },
        {
            "label": "README has implementation steps in H3 format",
            "tooltip": {
                "summary": ["Lab-specific walkthrough steps belong in H3 headings."],
                "details": build_h3_details(labs),
            },
            "cells": [lab["readme"]["h3Count"] > 0 for lab in labs],
        },
        {
            "label": "README opening phase is shared across the compared labs",
            "tooltip": {
                "summary": ["Both labs start with the same opening phase pattern."],
                "details": build_phase_prefix_details(common_phase_prefix, labs),
            },
            "cells": [tuple(lab["phaseSignature"][: len(common_phase_prefix)]) == common_phase_prefix for lab in labs] if common_phase_prefix else [False for _ in labs],
        },
        {
            "label": "README has an opening shell console section before implementation",
            "tooltip": {
                "summary": ["Both READMEs include a shell console section before the implementation starts."],
                "details": build_console_section_details(labs, "opening"),
            },
            "cells": [bool(lab["readme"]["openingShellConsoleSection"]) for lab in labs],
        },
        {
            "label": "README has a closing shell console section after implementation",
            "tooltip": {
                "summary": ["Both READMEs end with a shell console section after the implementation."],
                "details": build_console_section_details(labs, "closing"),
            },
            "cells": [bool(lab["readme"]["closingShellConsoleSection"]) for lab in labs],
        },
        {
            "label": "All console sections use shell syntax",
            "tooltip": {
                "summary": ["All console examples use shell-style fences."],
                "details": build_shell_console_details(labs),
            },
            "cells": [lab["readme"]["allConsoleBlocksUseShellSyntax"] for lab in labs],
        },
        {
            "label": "Test count consistency across README, console, CTRF, and HTML",
            "tooltip": {
                "summary": ["The README, console output, CTRF JSON, and Specmatic HTML report should describe the same counts."],
                "details": build_test_count_consistency_details(labs),
            },
            "cells": [lab["testCountConsistency"]["consistent"] for lab in labs],
        },
        {
            "label": "CTRF report available",
            "tooltip": {
                "summary": ["Each lab writes ctrf-report.json as the machine-readable test result."],
                "details": build_artifact_details(labs, "ctrf-report.json"),
            },
            "cells": ["ctrf-report.json" in lab["artifacts"]["labels"] for lab in labs],
        },
        {
            "label": "Sibling HTML report available",
            "tooltip": {
                "summary": ["Each lab writes specmatic-report.html alongside the CTRF JSON output."],
                "details": build_artifact_details(labs, "specmatic-report.html"),
            },
            "cells": ["specmatic-report.html" in lab["artifacts"]["labels"] for lab in labs],
        },
        {"kind": "group", "label": "Differences", "section": "differences", "cells": [None] * len(labs)},
        {
            "label": "README H1 is lab-specific",
            "tooltip": {
                "summary": ["Each lab uses its own H1 title text."],
                "details": build_h1_details(labs),
            },
            "cells": [True for _ in labs],
        },
        {
            "label": "README H2 sequence is lab-specific",
            "tooltip": {
                "summary": ["Each lab uses its own ordered H2 outline."],
                "details": build_h2_sequence_difference_details(labs),
            },
            "cells": [True for _ in labs],
        },
        {
            "label": "README has lab-specific H2 sections",
            "tooltip": {
                "summary": ["Each lab adds sections beyond the shared H2 scaffold."],
                "details": build_lab_specific_h2_details(labs, common_required_h2),
            },
            "cells": [bool(set(lab["readme"]["actualH2"]) - common_required_h2) for lab in labs],
        },
        {
            "label": "README phase sequence is lab-specific",
            "tooltip": {
                "summary": ["Each lab defines its own phase flow."],
                "details": build_phase_details(labs),
            },
            "cells": [True for _ in labs],
        },
        {
            "label": "README has lab-specific artifact labels",
            "tooltip": {
                "summary": ["Each lab has artifact labels beyond the shared report outputs."],
                "details": build_lab_specific_artifact_details(labs, artifact_label_counts),
            },
            "cells": [any(artifact_label_counts[label] == 1 for label in lab["artifacts"]["labels"]) for lab in labs],
        },
        {
            "label": "No additional artifacts beyond report outputs",
            "tooltip": {
                "summary": ["Any extra files beyond the report outputs are treated as deviations."],
                "details": build_additional_artifact_details(labs),
            },
            "cells": [not lab["warnings"]["additionalArtifacts"] for lab in labs],
        },
    ]
    return {"columns": columns, "rows": rows}


def render_comparison_html(payload: dict[str, Any]) -> str:
    summary_rows = "".join(
        f"<tr><th>{escape(item['label'])}</th><td>{escape(format_value(item['value']))}</td></tr>"
        for item in payload.get("summary", [])
    )
    common_list = "".join(f"<li>{escape(item)}</li>" for item in payload.get("commonalities", {}).get("sharedCharacteristics", []))
    shared_h1 = payload.get("commonalities", {}).get("sharedReadmeH1", "")
    shared_h2_sequence = payload.get("commonalities", {}).get("sharedReadmeH2Sequence", [])
    common_phase_prefix = payload.get("commonalities", {}).get("commonPhasePrefix", [])
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
        f"<tr><td>{render_lab_link(item['lab'], item['labHref'])}</td><td>{escape(item['commandType'])}</td><td><code>{escape(item['command'])}</code></td><td>{escape(item['setupType'])}</td></tr>"
        for item in payload.get("differences", {}).get("executionDifferences", [])
    )
    matrix = payload.get("validationMatrix", {"columns": [], "rows": []})
    consolidated_href = escape(payload.get("navigation", {}).get("consolidatedReportHref", "consolidated-report.html"))
    matrix_header = "".join(
        f"<th class='matrix-lab'>{render_lab_link(column['name'], column['href'])}</th>"
        for column in matrix.get("columns", [])
    )
    matrix_rows = "".join(render_validation_matrix_row(row) for row in matrix.get("rows", []))
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
    .nav-link {{
      margin: 0.25rem 0 0.9rem;
    }}
    .nav-link a {{
      color: #145a7a;
      text-decoration: none;
      border-bottom: 1px solid rgba(20, 90, 122, 0.35);
    }}
    .matrix-wrap {{
      overflow-x: auto;
    }}
    table.matrix {{
      min-width: max-content;
    }}
    .matrix th,
    .matrix td {{
      text-align: center;
      padding: 8px 10px;
    }}
    .matrix thead th {{
      position: sticky;
      top: 0;
      background: #fffdf8;
      z-index: 1;
      vertical-align: bottom;
    }}
    .matrix .row-label {{
      text-align: left;
      position: sticky;
      left: 0;
      background: #fffdf8;
      z-index: 2;
      min-width: 240px;
    }}
    .matrix-row-label {{
      display: flex;
      align-items: flex-start;
      gap: 0.5rem;
      justify-content: space-between;
    }}
    .matrix-row-title {{
      flex: 1 1 auto;
      min-width: 0;
    }}
    .tooltip-trigger {{
      appearance: none;
      border: 1px solid #c8bda9;
      background: #fff;
      color: #145a7a;
      border-radius: 999px;
      padding: 0.1rem 0.45rem;
      font: inherit;
      font-size: 0.85rem;
      line-height: 1.2;
      cursor: pointer;
      flex: 0 0 auto;
    }}
    .tooltip-trigger:hover,
    .tooltip-trigger:focus {{
      border-color: #145a7a;
      outline: none;
      box-shadow: 0 0 0 2px rgba(20, 90, 122, 0.12);
    }}
    .matrix-tooltip {{
      position: fixed;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 50;
      padding: 24px;
    }}
    .matrix-tooltip[hidden] {{
      display: none;
    }}
    .matrix-tooltip-backdrop {{
      position: absolute;
      inset: 0;
      background: rgba(24, 33, 38, 0.42);
    }}
    .matrix-tooltip-panel {{
      position: relative;
      z-index: 1;
      width: min(720px, calc(100vw - 48px));
      max-height: min(78vh, 760px);
      overflow: auto;
      background: #ffffff;
      border: 1px solid #c8bda9;
      border-radius: 14px;
      box-shadow: 0 24px 60px rgba(35, 31, 25, 0.28);
      padding: 16px 16px 14px;
    }}
    .matrix-tooltip-header {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 8px;
    }}
    .matrix-tooltip-title {{
      font-weight: 700;
      color: #182126;
    }}
    .tooltip-close {{
      appearance: none;
      border: 1px solid #c8bda9;
      background: #fffdf8;
      color: #182126;
      border-radius: 999px;
      padding: 0.15rem 0.55rem;
      font: inherit;
      font-size: 0.85rem;
      cursor: pointer;
      flex: 0 0 auto;
    }}
    .tooltip-close:hover,
    .tooltip-close:focus {{
      outline: none;
      border-color: #145a7a;
      box-shadow: 0 0 0 2px rgba(20, 90, 122, 0.12);
    }}
    .matrix-tooltip ul {{
      margin: 0;
      padding-left: 1.2rem;
      color: #334155;
    }}
    .matrix-tooltip li + li {{
      margin-top: 0.35rem;
    }}
    .tooltip-details-toggle {{
      appearance: none;
      border: 1px solid #c8bda9;
      background: #fffdf8;
      color: #145a7a;
      border-radius: 999px;
      padding: 0.35rem 0.7rem;
      font: inherit;
      font-size: 0.9rem;
      cursor: pointer;
      margin-top: 10px;
    }}
    .tooltip-details-toggle:hover,
    .tooltip-details-toggle:focus {{
      outline: none;
      border-color: #145a7a;
      box-shadow: 0 0 0 2px rgba(20, 90, 122, 0.12);
    }}
    .matrix-tooltip-details {{
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid #e2d7c6;
    }}
    .matrix-tooltip-section {{
      padding: 12px 14px;
      margin-top: 12px;
      border: 1px solid #e2d7c6;
      border-radius: 12px;
      background: #fffdf9;
    }}
    .matrix-tooltip-section:first-child {{
      margin-top: 0;
    }}
    .matrix-tooltip-section-title {{
      font-weight: 700;
      margin-bottom: 4px;
      color: #182126;
    }}
    .matrix-tooltip-section-note {{
      margin: 0 0 10px;
      color: #5f6b74;
      font-size: 0.95rem;
    }}
    .matrix-tooltip-details-title {{
      font-weight: 700;
      margin-bottom: 8px;
      color: #182126;
    }}
    .matrix-tooltip-details-note {{
      margin: 0 0 10px;
      color: #5f6b74;
      font-size: 0.95rem;
    }}
    .matrix-tooltip-details table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.95rem;
      table-layout: fixed;
    }}
    .matrix-tooltip-details th,
    .matrix-tooltip-details td {{
      border-bottom: 1px solid #eadfcd;
      padding: 8px 6px;
      text-align: left;
      vertical-align: top;
      word-break: break-word;
    }}
    .matrix-group th {{
      text-align: left;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: none;
    }}
    .matrix-group-label {{
      display: inline-block;
      padding: 0.18rem 0.65rem;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.5);
    }}
    .matrix-group-similarities th {{
      background: linear-gradient(90deg, #eaf7ee, #f6fff8);
      color: #1f7a3b;
      border-top: 2px solid #9bd3a9;
      border-bottom: 2px solid #9bd3a9;
    }}
    .matrix-group-differences th {{
      background: linear-gradient(90deg, #fff1ea, #fffaf7);
      color: #b42318;
      border-top: 2px solid #f0b39f;
      border-bottom: 2px solid #f0b39f;
    }}
    .matrix-legend {{
      display: inline-block;
      margin-left: 0.6rem;
      padding: 0.2rem 0.55rem;
      border-radius: 999px;
      font-size: 0.85rem;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    .matrix-legend-similarity {{
      background: #eaf7ee;
      color: #1f7a3b;
      border: 1px solid #9bd3a9;
    }}
    .matrix-legend-difference {{
      background: #fff1ea;
      color: #b42318;
      border: 1px solid #f0b39f;
    }}
    .matrix .matrix-lab {{
      min-width: 120px;
      max-width: 120px;
      white-space: normal;
    }}
    .matrix-cell {{
      font-size: 1.05rem;
      font-weight: 700;
      line-height: 1;
    }}
    .matrix-cell.yes {{
      color: #1f7a3b;
    }}
    .matrix-cell.no {{
      color: #b42318;
    }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>Labs Similarities And Differences</h1>
      <p class="muted">Generated at {escape(payload['generatedAt'])}</p>
      <p class="nav-link"><a href="{consolidated_href}">Back to consolidated report</a></p>
      <table>{summary_rows}</table>
    </section>
    <section class="panel">
      <h2>Shared Patterns</h2>
      <p>These are the strongest common patterns across the automated labs.</p>
      <ul>{common_list}</ul>
      <h3>Shared README H1</h3>
      <p>{escape(shared_h1) or '(no common H1 found)'}</p>
      <h3>Shared README H2 Sequence</h3>
      <ul>{''.join(f'<li>{escape(section)}</li>' for section in shared_h2_sequence) or '<li>(no common H2 sequence found)</li>'}</ul>
      <h3>Common Phase Prefix</h3>
      <ul>{''.join(f'<li>{escape(phase)}</li>' for phase in common_phase_prefix) or '<li>(no shared opening phase found)</li>'}</ul>
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
    <section class="panel">
      <h2>README Similarities and Differences Matrix</h2>
      <p class="muted">Green tick means the validation is present for that lab. Red cross means it is absent. <span class="matrix-legend matrix-legend-similarity">Similarities: shared structure.</span><span class="matrix-legend matrix-legend-difference">Differences: lab-specific deltas.</span></p>
      <div class="matrix-wrap">
        <table class="matrix">
          <thead>
            <tr>
              <th class="row-label">Validation</th>
              {matrix_header}
            </tr>
          </thead>
          <tbody>{matrix_rows}</tbody>
        </table>
      </div>
    </section>
  </main>
    <div id="matrix-tooltip-modal" class="matrix-tooltip" hidden>
    <div class="matrix-tooltip-backdrop" data-modal-close="true" aria-hidden="true"></div>
    <div class="matrix-tooltip-panel" role="dialog" aria-modal="true" aria-labelledby="matrix-tooltip-title">
      <div class="matrix-tooltip-header">
        <div id="matrix-tooltip-title" class="matrix-tooltip-title">What this means</div>
        <button type="button" class="tooltip-close" data-modal-close="true" aria-label="Close tooltip">Close</button>
      </div>
      <ul id="matrix-tooltip-summary"></ul>
      <button id="matrix-tooltip-details-toggle" type="button" class="tooltip-details-toggle" hidden>View details</button>
      <div id="matrix-tooltip-details" class="matrix-tooltip-details" hidden></div>
    </div>
  </div>
  <script>
    (() => {{
      const modal = document.getElementById('matrix-tooltip-modal');
      const title = document.getElementById('matrix-tooltip-title');
      const summary = document.getElementById('matrix-tooltip-summary');
      const details = document.getElementById('matrix-tooltip-details');
      const detailsToggle = document.getElementById('matrix-tooltip-details-toggle');
      let activeTooltip = null;
      let activeTrigger = null;
      const closeAll = () => {{
        const triggerToFocus = activeTrigger;
        document.querySelectorAll('.tooltip-trigger').forEach((trigger) => {{
          trigger.setAttribute('aria-expanded', 'false');
        }});
        if (modal) {{
          modal.hidden = true;
        }}
        if (summary) {{
          summary.innerHTML = '';
        }}
        if (details) {{
          details.hidden = true;
          details.innerHTML = '';
        }}
        if (detailsToggle) {{
          detailsToggle.hidden = true;
          detailsToggle.textContent = 'View details';
        }}
        activeTooltip = null;
        activeTrigger = null;
        document.body.style.overflow = '';
        return triggerToFocus;
      }};
      document.addEventListener('click', (event) => {{
        const target = event.target;
        const trigger = target.closest ? target.closest('.tooltip-trigger') : null;
        const closeButton = target.closest ? target.closest('[data-modal-close="true"]') : null;
        if (trigger) {{
          closeAll();
          if (!modal || !title || !summary || !details || !detailsToggle) return;
          const tooltipJson = trigger.getAttribute('data-tooltip-json') || '';
          if (!tooltipJson) return;
          const tooltip = JSON.parse(tooltipJson);
          activeTooltip = tooltip;
          activeTrigger = trigger;
          title.textContent = tooltip.title || 'What this means';
          renderBulletList(summary, tooltip.summary || ['(no summary available)']);
          renderDetails(details, tooltip.details || null);
          details.hidden = true;
          detailsToggle.hidden = !tooltip.details;
          detailsToggle.textContent = 'View details';
          detailsToggle.setAttribute('aria-expanded', 'false');
          modal.hidden = false;
          document.body.style.overflow = 'hidden';
          trigger.setAttribute('aria-expanded', 'true');
          const closeControl = modal.querySelector('.tooltip-close');
          if (closeControl) {{
            closeControl.focus();
          }}
          return;
        }}
        if (closeButton) {{
          const triggerControl = closeAll();
          if (triggerControl) {{
            triggerControl.focus();
          }}
          return;
        }}
        if (target === detailsToggle) {{
          if (!details || !detailsToggle || !activeTooltip) return;
          const isHidden = details.hidden;
          if (isHidden) {{
            renderDetails(details, activeTooltip.details || null);
            details.hidden = false;
            detailsToggle.textContent = 'Hide details';
            detailsToggle.setAttribute('aria-expanded', 'true');
          }} else {{
            details.hidden = true;
            detailsToggle.textContent = 'View details';
            detailsToggle.setAttribute('aria-expanded', 'false');
          }}
          return;
        }}
        if (target === modal) {{
          const triggerControl = closeAll();
          if (triggerControl) {{
            triggerControl.focus();
          }}
          return;
        }}
        const backdrop = modal ? modal.querySelector('.matrix-tooltip-backdrop') : null;
        if (target === backdrop) {{
          const triggerControl = closeAll();
          if (triggerControl) {{
            triggerControl.focus();
          }}
        }}
      }});
      document.addEventListener('keydown', (event) => {{
        if (event.key === 'Escape') {{
          const triggerControl = closeAll();
          if (triggerControl) {{
            triggerControl.focus();
          }}
        }}
      }});

      function renderBulletList(container, items) {{
        container.innerHTML = '';
        const list = document.createElement('ul');
        items.forEach((item) => {{
          const li = document.createElement('li');
          li.textContent = item;
          list.appendChild(li);
        }});
        container.appendChild(list);
      }}

      function renderDetails(container, detailsData) {{
        container.innerHTML = '';
        if (!detailsData) {{
          return;
        }}
        renderDetailsBlock(container, detailsData, true);
      }}

      function renderDetailsBlock(container, detailsData, isRoot) {{
        if (!detailsData) return;
        if (isRoot) {{
          const sectionTitle = document.createElement('div');
          sectionTitle.className = 'matrix-tooltip-details-title';
          sectionTitle.textContent = detailsData.title || 'View details';
          container.appendChild(sectionTitle);
        }} else if (detailsData.title) {{
          const sectionTitle = document.createElement('div');
          sectionTitle.className = 'matrix-tooltip-section-title';
          sectionTitle.textContent = detailsData.title;
          container.appendChild(sectionTitle);
        }}
        if (detailsData.note) {{
          const note = document.createElement('p');
          note.className = isRoot ? 'matrix-tooltip-details-note' : 'matrix-tooltip-section-note';
          note.textContent = detailsData.note;
          container.appendChild(note);
        }}
        if (detailsData.type === 'sections') {{
          (detailsData.sections || []).forEach((section) => {{
            const sectionContainer = document.createElement('div');
            sectionContainer.className = 'matrix-tooltip-section';
            container.appendChild(sectionContainer);
            renderDetailsBlock(sectionContainer, section, false);
          }});
          return;
        }}
        if (detailsData.type === 'table') {{
          const table = document.createElement('table');
          const thead = document.createElement('thead');
          const headerRow = document.createElement('tr');
          (detailsData.headers || []).forEach((header) => {{
            const th = document.createElement('th');
            th.textContent = header;
            headerRow.appendChild(th);
          }});
          thead.appendChild(headerRow);
          table.appendChild(thead);
          const tbody = document.createElement('tbody');
          (detailsData.rows || []).forEach((row) => {{
            const tr = document.createElement('tr');
            row.forEach((cell) => {{
              const td = document.createElement('td');
              td.textContent = cell;
              tr.appendChild(td);
            }});
            tbody.appendChild(tr);
          }});
          table.appendChild(tbody);
          container.appendChild(table);
          return;
        }}
        if (detailsData.type === 'bullets') {{
          const list = document.createElement('ul');
          (detailsData.items || []).forEach((item) => {{
            const li = document.createElement('li');
            li.textContent = item;
            list.appendChild(li);
          }});
          container.appendChild(list);
          return;
        }}
        if (detailsData.type === 'text') {{
          const paragraph = document.createElement('p');
          paragraph.textContent = detailsData.text || '';
          container.appendChild(paragraph);
        }}
      }}
    }})();
  </script>
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
        f"Type: {lab['setup']['display']}",
        f"Compose file: {'yes' if lab['setup']['hasComposeFile'] else 'no'}",
        f"Python entrypoint: {'yes' if lab['setup']['usesPython'] else 'no'}",
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
        f"<td>{render_lab_link(lab['name'], lab['href'])}<br><span class='muted'>{escape(lab['description'])}</span></td>"
        f"<td>{render_bullets(readme_bits)}</td>"
        f"<td>{render_bullets(approach_bits)}</td>"
        f"<td>{render_bullets(setup_bits)}</td>"
        f"<td>{render_bullets(artifact_bits)}</td>"
        f"<td><code>{escape(file_bits)}</code></td>"
        "</tr>"
    )


def render_lab_link(name: str, href: str) -> str:
    return f"<a href='{escape(href)}' target='_blank' rel='noreferrer'><strong>{escape(name)}</strong></a>"


def render_validation_matrix_row(row: dict[str, Any]) -> str:
    if row.get("kind") == "group":
        section_class = f" matrix-group-{escape(row.get('section', ''))}" if row.get("section") else ""
        group_label = escape(row["label"])
        return f"<tr class='matrix-group{section_class}'><th class='row-label' colspan='{len(row.get('cells', [])) + 1}'><span class='matrix-group-label'>{group_label}</span></th></tr>"
    tooltip_attrs = render_matrix_trigger_attrs(row.get("tooltip", {}), row["label"])
    cells = "".join(render_matrix_cell(bool(cell), row["label"]) for cell in row["cells"])
    return f"<tr><th class='row-label'><span class='matrix-row-label'><span class='matrix-row-title'>{escape(row['label'])}</span><button type='button' class='tooltip-trigger' aria-expanded='false' aria-label='Show details for {escape(row['label'])}'{tooltip_attrs}>i</button></span></th>{cells}</tr>"


def render_matrix_cell(present: bool, validation_label: str) -> str:
    symbol = "&#10003;" if present else "&#10007;"
    state = "yes" if present else "no"
    title = "present" if present else "absent"
    return f"<td title='{escape(validation_label)} is {title}'><span class='matrix-cell {state}' aria-label='{escape(title)}'>{symbol}</span></td>"


def render_matrix_trigger_attrs(tooltip: dict[str, Any], label: str) -> str:
    payload = {
        "title": label,
        "summary": tooltip.get("summary", []),
        "details": tooltip.get("details"),
    }
    return f" data-tooltip-json='{escape(json.dumps(payload, ensure_ascii=False))}'"


def build_h1_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "table",
        "title": "H1 titles",
        "headers": ["Lab", "H1 title"],
        "rows": [[lab["name"], lab["readme"]["h1"] or "(missing)"] for lab in labs],
    }


def build_shared_section_details(common_required_h2: set[str]) -> dict[str, Any]:
    return {
        "type": "bullets",
        "title": "Shared required H2 sections",
        "items": sorted(common_required_h2) or ["(no common required H2 sections found)"],
        "note": "These sections should appear in every README.",
    }


def build_h3_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "table",
        "title": "H3 implementation steps",
        "headers": ["Lab", "H3 count", "H3 headings"],
        "rows": [
            [lab["name"], str(lab["readme"]["h3Count"]), ", ".join(lab["readme"]["actualH3"]) or "(none)"]
            for lab in labs
        ],
        "note": "H3 sections are where the lab-specific implementation steps belong.",
    }


def build_phase_prefix_details(common_phase_prefix: tuple[str, ...], labs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "table",
        "title": "Opening phase pattern",
        "headers": ["Lab", "Phase sequence"],
        "rows": [[lab["name"], " -> ".join(lab["phaseSignature"]) or "(missing)"] for lab in labs],
        "note": ("The shared opening phase prefix is: " + ", ".join(common_phase_prefix)) if common_phase_prefix else "(no shared opening phase found)",
    }


def build_console_section_details(labs: list[dict[str, Any]], which: str) -> dict[str, Any]:
    entries = []
    for lab in labs:
        section = lab["readme"]["openingShellConsoleSection"] if which == "opening" else lab["readme"]["closingShellConsoleSection"]
        entries.append([lab["name"], section.get("summary") or "(missing)"])
    title = "Opening console sections" if which == "opening" else "Closing console sections"
    note = "These console blocks show the before/after command flow in the README."
    return {
        "type": "table",
        "title": title,
        "headers": ["Lab", "Console section"],
        "rows": entries,
        "note": note,
    }


def build_shell_console_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "table",
        "title": "Shell console coverage",
        "headers": ["Lab", "Shell console blocks", "All use shell syntax"],
        "rows": [
            [
                lab["name"],
                str(lab["readme"]["shellConsoleBlockCount"]),
                "Yes" if lab["readme"]["allConsoleBlocksUseShellSyntax"] else "No",
            ]
            for lab in labs
        ],
        "note": "Shell fences keep the README commands copy-pasteable and consistent.",
    }


def build_artifact_details(labs: list[dict[str, Any]], label: str) -> dict[str, Any]:
    return {
        "type": "table",
        "title": f"{label} coverage",
        "headers": ["Lab", "Present"],
        "rows": [[lab["name"], "Yes" if label in lab["artifacts"]["labels"] else "No"] for lab in labs],
    }


def build_h2_sequence_difference_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "table",
        "title": "Lab-specific H2 outlines",
        "headers": ["Lab", "Ordered H2 outline"],
        "rows": [[lab["name"], " -> ".join(lab["readme"]["actualH2"]) or "(missing)"] for lab in labs],
        "note": "The H2 outline is the lab-specific shape of the README.",
    }


def build_lab_specific_h2_details(labs: list[dict[str, Any]], common_required_h2: set[str]) -> dict[str, Any]:
    return {
        "type": "table",
        "title": "Lab-specific H2 sections",
        "headers": ["Lab", "Extra H2 sections"],
        "rows": [
            [
                lab["name"],
                ", ".join(sorted(set(lab["readme"]["actualH2"]) - common_required_h2)) or "(none)",
            ]
            for lab in labs
        ],
        "note": "These are the sections that should be compared against the shared scaffold.",
    }


def build_phase_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "table",
        "title": "Phase sequences",
        "headers": ["Lab", "Phase flow"],
        "rows": [[lab["name"], " -> ".join(lab["phaseSignature"]) or "(missing)"] for lab in labs],
    }


def build_lab_specific_artifact_details(labs: list[dict[str, Any]], artifact_label_counts: Counter[str]) -> dict[str, Any]:
    return {
        "type": "table",
        "title": "Lab-specific artifact labels",
        "headers": ["Lab", "Unique labels"],
        "rows": [
            [
                lab["name"],
                ", ".join(label for label in lab["artifacts"]["labels"] if artifact_label_counts[label] == 1) or "(none)",
            ]
            for lab in labs
        ],
    }


def build_additional_artifact_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "type": "table",
        "title": "Additional artifact warnings",
        "headers": ["Lab", "Additional artifacts"],
        "rows": [
            [lab["name"], ", ".join(lab["warnings"]["additionalArtifacts"]) or "(none)"]
            for lab in labs
        ],
    }


def build_h2_sequence_tooltip(labs: list[dict[str, Any]], common_required_h2: set[str]) -> dict[str, Any]:
    shared_scaffold = sorted(common_required_h2) or ["(no shared required H2 sections found)"]
    lab_sections = []
    for lab in labs:
        extra_sections = [section for section in lab["readme"]["actualH2"] if section not in common_required_h2]
        lab_sections.append(
            {
                "type": "bullets",
                "title": lab["name"],
                "note": "Extra H2 sections in this README.",
                "items": extra_sections or ["(none)"],
            }
        )
    return {
        "summary": [
            "Both READMEs share the same H2 scaffold.",
            "The lab-specific H2 sections are broken out below.",
        ],
        "details": {
            "type": "sections",
            "title": "H2 scaffold and differences",
            "note": "Keep the shared H2 sequence stable. Move lab-specific walkthrough steps into H3 headings.",
            "sections": [
                {
                    "type": "bullets",
                    "title": "Shared scaffold",
                    "note": "These H2 sections appear in every compared README.",
                    "items": shared_scaffold,
                },
                *lab_sections,
                {
                    "type": "bullets",
                    "title": "Action",
                    "items": [
                        "Keep the shared H2 sequence stable across labs.",
                        "Move lab-specific walkthrough steps into H3 headings.",
                    ],
                },
            ],
        },
    }


def build_test_count_consistency_profile(lab_name: str, readme_text: str, snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not snapshot:
        return {"available": False, "consistent": False, "phases": []}

    readme_summaries = extract_tests_run_summaries(readme_text)
    report_phases = snapshot.get("phases", [])
    comparisons: list[dict[str, Any]] = []
    all_consistent = bool(report_phases)
    snapshot_root = snapshot.get("root")
    for index, phase in enumerate(report_phases):
        phase_path = phase_artifact_root(snapshot_root, phase)
        console_summary = extract_tests_run_summary(phase.get("consoleSnippet", ""))
        readme_summary = readme_summaries[index] if index < len(readme_summaries) else None
        ctrf_summary = None
        html_summary = None
        if phase_path and phase_path.exists():
            ctrf_artifact = phase_path / "ctrf-report.json"
            html_artifact = phase_path / "specmatic" / "test" / "html" / "index.html"
            if ctrf_artifact.exists():
                ctrf_summary = format_tests_run_summary_from_report_json(ctrf_artifact)
            if html_artifact.exists():
                html_summary = format_tests_run_summary_from_html(html_artifact)
        counts = [
            parse_tests_run_counts(readme_summary),
            parse_tests_run_counts(console_summary),
            ctrf_summary,
            html_summary,
        ]
        present_counts = [item for item in counts if item is not None]
        consistent = bool(present_counts) and len({tuple(sorted(item.items())) for item in present_counts}) == 1
        all_consistent = all_consistent and consistent
        comparisons.append(
            {
                "phase": phase.get("name", f"Phase {index + 1}"),
                "readme": readme_summary or "(missing)",
                "console": console_summary or "(missing)",
                "ctrf": format_tests_run_counts_short(ctrf_summary) if ctrf_summary else "(missing)",
                "html": format_tests_run_counts_short(html_summary) if html_summary else "(missing)",
                "consistent": consistent,
            }
        )

    return {
        "available": True,
        "consistent": all_consistent,
        "phases": comparisons,
    }


def load_lab_report_snapshot(lab_name: str) -> dict[str, Any] | None:
    snapshot_dir = ROOT / "output" / "labs" / f"{lab_name}-output"
    report_path = snapshot_dir / "report.json"
    if not report_path.exists():
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["root"] = snapshot_dir
    return report


def extract_tests_run_summaries(readme_text: str) -> list[str]:
    return re.findall(r"Tests run:\s*\d+,\s*Successes:\s*\d+,\s*Failures:\s*\d+,\s*Errors:\s*\d+", readme_text)


def extract_tests_run_summary(console_output: str) -> str | None:
    matches = re.findall(r"Tests run:\s*\d+,\s*Successes:\s*\d+,\s*Failures:\s*\d+,\s*Errors:\s*\d+", console_output)
    return matches[-1] if matches else None


def phase_artifact_root(snapshot_root: Any, phase: dict[str, Any]) -> Path | None:
    if not isinstance(snapshot_root, Path):
        return None
    for artifact in phase.get("artifacts", []):
        href = artifact.get("href")
        if href:
            return snapshot_root / Path(href).parts[0]
    return None


def parse_tests_run_counts(summary_text: str | None) -> dict[str, int] | None:
    if not summary_text:
        return None
    match = re.search(
        r"Tests run:\s*(?P<tests>\d+),\s*Successes:\s*(?P<successes>\d+),\s*Failures:\s*(?P<failures>\d+),\s*Errors:\s*(?P<errors>\d+)",
        summary_text,
    )
    if not match:
        return None
    return {
        "tests": int(match.group("tests")),
        "passed": int(match.group("successes")),
        "failed": int(match.group("failures")),
        "skipped": 0,
        "other": int(match.group("errors")),
    }


def format_tests_run_counts(counts: dict[str, int] | None) -> str:
    if not counts:
        return "(missing)"
    return (
        f"Tests run: {counts['tests']}, Successes: {counts['passed']}, "
        f"Failures: {counts['failed']}, Errors: {counts['other']}"
    )


def format_tests_run_counts_short(counts: dict[str, int] | None) -> str:
    if not counts:
        return "(missing)"
    return f"T={counts['tests']} P={counts['passed']} F={counts['failed']} S={counts['skipped']} O={counts['other']}"


def format_tests_run_summary_from_report_json(report_path: Path) -> dict[str, int] | None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    summary = report.get("results", {}).get("summary", {})
    return {
        "tests": int(summary.get("tests", 0)),
        "passed": int(summary.get("passed", 0)),
        "failed": int(summary.get("failed", 0)),
        "skipped": int(summary.get("skipped", 0)),
        "other": int(summary.get("other", 0)),
    }


def format_tests_run_summary_from_html(html_path: Path) -> dict[str, int] | None:
    html_text = html_path.read_text(encoding="utf-8")
    try:
        report = parse_html_embedded_report(html_text)
    except ValueError:
        return None
    summary = report.get("results", {}).get("summary", {})
    return {
        "tests": int(summary.get("tests", 0)),
        "passed": int(summary.get("passed", 0)),
        "failed": int(summary.get("failed", 0)),
        "skipped": int(summary.get("skipped", 0)),
        "other": int(summary.get("other", 0)),
    }


def parse_html_embedded_report(html_text: str) -> dict[str, Any]:
    match = re.search(r"const report = (\{.*?\});\s*const specmaticConfig =", html_text, re.DOTALL)
    if not match:
        raise ValueError("Could not find the embedded Specmatic report payload inside the HTML report.")
    return json.loads(match.group(1))


def build_test_count_consistency_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    verdict_items = []
    for lab in labs:
        comparisons = lab["testCountConsistency"].get("phases", [])
        mismatch_phases = [item["phase"] for item in comparisons if not item["consistent"]]
        if lab["testCountConsistency"].get("consistent"):
            verdict_items.append(f"{lab['name']}: consistent across {len(comparisons)} report-bearing phase(s).")
        elif mismatch_phases:
            verdict_items.append(f"{lab['name']}: mismatches in {', '.join(mismatch_phases)}.")
        else:
            verdict_items.append(f"{lab['name']}: no report data was available to validate.")
        sections.append(
            {
                "type": "table",
                "title": lab["name"],
                "note": "Each row compares the README summary, console output, CTRF JSON, and Specmatic HTML for one phase.",
                "headers": ["Phase", "README", "Console", "CTRF", "HTML", "Status"],
                "rows": [
                    [
                        item["phase"],
                        item["readme"],
                        item["console"],
                        item["ctrf"],
                        item["html"],
                        "Match" if item["consistent"] else "Mismatch",
                    ]
                    for item in comparisons
                ] or [["(no report data found)", "(missing)", "(missing)", "(missing)", "(missing)", "Mismatch"]],
            }
        )
    return {
        "type": "sections",
        "title": "Test count consistency",
        "note": "The README, console, CTRF JSON, and Specmatic HTML should all describe the same run for each report-bearing phase.",
        "sections": [
            {
                "type": "bullets",
                "title": "Quick verdict",
                "items": verdict_items or ["No copied lab report snapshots were available to validate."],
            },
            *sections
        ] if sections else [
            {
                "type": "bullets",
                "title": "Quick verdict",
                "items": verdict_items or ["No copied lab report snapshots were available to validate."],
            },
            {
                "type": "bullets",
                "title": "No report data found",
                "items": ["No copied lab report snapshots were available to validate."],
            },
        ],
    }


def render_bullets(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"


def format_setup_types(setup_types: list[str]) -> str:
    return " + ".join(setup_types) if setup_types else "unknown"


def most_common_value(values: list[Any]) -> Any:
    if not values:
        return ""
    return Counter(values).most_common(1)[0][0]


def longest_common_prefix(sequences: list[tuple[str, ...]]) -> tuple[str, ...]:
    if not sequences:
        return ()
    prefix = list(sequences[0])
    for sequence in sequences[1:]:
        limit = min(len(prefix), len(sequence))
        index = 0
        while index < limit and prefix[index] == sequence[index]:
            index += 1
        prefix = prefix[:index]
        if not prefix:
            break
    return tuple(prefix)


def format_lab_value_map(items: Any) -> str:
    return "; ".join(f"{lab}: {value}" for lab, value in items)


def format_value(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}={val}" for key, val in value.items())
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)
