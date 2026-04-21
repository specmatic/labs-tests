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

from lablib.readme_expectations import EXPECTED_README_H2_SEQUENCE


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
PATH_LIKE_RE = re.compile(r"([A-Za-z]:\\[^\s`]+|/(?:[^\s`]+))")
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
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
    generated_artifact_labels = sorted(
        {
            artifact["label"]
            for artifact in [*common_artifacts, *phase_artifacts]
            if artifact["origin"] == "generated"
        }
    )
    artifact_kinds = sorted({artifact["kind"] for artifact in [*common_artifacts, *phase_artifacts]})
    shell_console_blocks = [block for block in code_blocks if looks_like_console_block(block) and block["language"] in {"shell", "bash", "sh"}]
    console_blocks = [block for block in code_blocks if looks_like_console_block(block)]
    shell_console_sections = build_shell_console_sections(headings, shell_console_blocks)
    os_documentation = analyze_readme_os_documentation(upstream_readme_text, headings, code_blocks)
    additional_artifacts = sorted(
        label
        for label in generated_artifact_labels
        if label not in REPORT_ARTIFACT_LABELS and label not in IGNORED_ARTIFACT_LABELS
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
            "generatedLabels": generated_artifact_labels,
            "kinds": artifact_kinds,
            "common": common_artifacts,
            "phaseSpecific": phase_artifacts,
            "families": detect_artifact_families(generated_artifact_labels),
        },
        "readme": {
            "h1": next((heading["text"] for heading in headings if heading["level"] == 1), ""),
            "requiredH2": list(spec.readme_structure.required_h2_prefixes) if spec.readme_structure else [],
            "additionalH2": list(spec.readme_structure.additional_h2_prefixes) if spec.readme_structure else [],
            "actualH2": h2_headings,
            "actualH3": h3_headings,
            "hasPrerequisites": any("prerequisites" in heading.lower() for heading in h2_headings),
            "hasStudioSection": any("studio" in heading.lower() for heading in h2_headings),
            "hasTroubleshooting": any("troubleshooting" in heading.lower() for heading in h2_headings),
            "hasPassCriteria": any("pass criteria" in heading.lower() or "verify the fix" in heading.lower() for heading in h2_headings),
            "hasCleanupGuidance": any("cleanup" in heading.lower() for heading in [*h2_headings, *h3_headings]),
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
            "filesSectionText": extract_heading_section_text(upstream_readme_text, "Files in this lab", level=2),
            "osDocumentation": os_documentation,
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
        "origin": classify_artifact_origin(data["source_relpath"]),
    }


def classify_artifact_origin(source_relpath: str) -> str:
    normalized = source_relpath.replace("\\", "/")
    return "generated" if normalized.startswith("build/") else "source"


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


def extract_heading_section_text(readme_text: str, heading_title: str, level: int = 2) -> str:
    lines = readme_text.splitlines()
    heading_line_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    start_index = None
    for index, line in enumerate(lines):
        match = heading_line_pattern.match(line)
        if not match:
            continue
        if len(match.group(1)) == level and match.group(2).strip() == heading_title:
            start_index = index + 1
            break
    if start_index is None:
        return ""
    collected: list[str] = []
    for line in lines[start_index:]:
        match = heading_line_pattern.match(line)
        if match and len(match.group(1)) <= level:
            break
        collected.append(line)
    return "\n".join(collected).strip()


def summarize_console_section(heading: str, command: str) -> str:
    if heading and command:
        return f"{heading}: {command}"
    return heading or command


def os_targets_from_text(text: str) -> set[str]:
    lowered = text.lower()
    targets: set[str] = set()
    if any(token in lowered for token in ("windows", "powershell", "cmd", "git bash")):
        targets.add("Windows")
    if any(token in lowered for token in ("macos", "mac os", "mac ")) or "mac/linux" in lowered or "linux/mac" in lowered:
        targets.add("macOS")
    if any(token in lowered for token in ("linux", "ubuntu", "debian", "fedora")) or "mac/linux" in lowered or "linux/mac" in lowered:
        targets.add("Linux")
    if "unix" in lowered:
        targets.update({"macOS", "Linux"})
    return targets


def collect_preceding_context(readme_text: str, line_number: int, window: int = 4) -> str:
    lines = readme_text.splitlines()
    start = max(0, line_number - 1 - window)
    return "\n".join(line.strip() for line in lines[start : max(0, line_number - 1)] if line.strip())


def is_output_block_with_paths(block: dict[str, Any]) -> bool:
    return not looks_like_console_block(block) and bool(PATH_LIKE_RE.search(block["body"]))


def is_command_language_appropriate(os_name: str, language: str) -> bool:
    normalized = language.lower()
    if os_name in {"macOS", "Linux"}:
        return normalized in {"shell", "bash", "sh", "zsh"}
    if os_name == "Windows":
        return normalized in {"powershell", "ps1", "cmd", "bat", "shell", "bash", "sh"}
    return False


def analyze_readme_os_documentation(readme_text: str, headings: list[dict[str, Any]], code_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    command_coverage = {os_name: [] for os_name in ("Windows", "macOS", "Linux")}
    output_coverage = {os_name: [] for os_name in ("Windows", "macOS", "Linux")}
    command_language_issues: list[dict[str, str]] = []
    has_commands = False
    has_path_outputs = False

    for block in code_blocks:
        heading = heading_before_line(headings, block["line"])
        context_text = " ".join(
            filter(
                None,
                [
                    heading["text"] if heading else "",
                    collect_preceding_context(readme_text, block["line"]),
                ],
            )
        )
        os_targets = os_targets_from_text(context_text)
        if looks_like_console_block(block):
            has_commands = True
            for os_name in os_targets:
                command_coverage[os_name].append(
                    {
                        "heading": heading["text"] if heading else "(no heading)",
                        "language": block["language"] or "(none)",
                        "preview": block["preview"] if "preview" in block else next((line.strip() for line in block["body"].splitlines() if line.strip()), ""),
                    }
                )
                if not is_command_language_appropriate(os_name, block["language"] or ""):
                    command_language_issues.append(
                        {
                            "os": os_name,
                            "heading": heading["text"] if heading else "(no heading)",
                            "language": block["language"] or "(none)",
                        }
                    )
        elif is_output_block_with_paths(block):
            has_path_outputs = True
            for os_name in os_targets:
                output_coverage[os_name].append(
                    {
                        "heading": heading["text"] if heading else "(no heading)",
                        "language": block["language"] or "(none)",
                    }
                )

    return {
        "hasCommands": has_commands,
        "missingCommandOs": [os_name for os_name, entries in command_coverage.items() if has_commands and not entries],
        "commandCoverage": command_coverage,
        "commandLanguageIssues": command_language_issues,
        "hasPathOutputs": has_path_outputs,
        "missingOutputOs": [os_name for os_name, entries in output_coverage.items() if has_path_outputs and not entries],
        "outputCoverage": output_coverage,
    }


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
    shared_h2 = tuple(EXPECTED_README_H2_SEQUENCE)
    common_required_h2 = list(EXPECTED_README_H2_SEQUENCE)
    extra_h2_by_lab = {
        lab["name"]: [section for section in lab["readme"]["actualH2"] if section not in shared_h2]
        for lab in labs
    }
    row_definitions = [
        {
            "label": "README starts with a top-level H1 title",
            "tooltip": {
                "summary": ["Every compared README starts with an H1 title."],
                "details": build_h1_details(labs),
            },
            "cells": [bool(lab["readme"]["h1"]) for lab in labs],
        },
        {
            "label": "README H2 order matches the lab's source-of-truth structure",
            "tooltip": build_h2_sequence_tooltip(labs, common_required_h2),
            "cells": [tuple(lab["readme"]["actualH2"]) == shared_h2 for lab in labs],
        },
        {
            "label": "README uses H3 headings for lab-specific implementation steps",
            "tooltip": {
                "summary": ["Lab-specific walkthrough steps belong in H3 headings."],
                "details": build_h3_details(labs, extra_h2_by_lab),
            },
            "cells": [lab["readme"]["h3Count"] > 0 and not extra_h2_by_lab[lab["name"]] for lab in labs],
        },
        {
            "label": "README shows a clear primary execution command for this lab",
            "tooltip": {
                "summary": ["The README should show one primary shell command that clearly communicates how to run the lab."],
                "details": build_execution_command_details(labs),
            },
            "cells": [bool(lab["command"]) and lab["commandType"] != "other" for lab in labs],
        },
        {
            "label": "README provides OS-specific command sections for Windows, macOS, and Linux when commands are documented",
            "tooltip": {
                "summary": ["When a README documents commands, it should show how to run them on Windows, macOS, and Linux."],
                "details": build_os_command_coverage_details(labs),
            },
            "cells": [
                (not lab["readme"]["osDocumentation"]["hasCommands"])
                or not lab["readme"]["osDocumentation"]["missingCommandOs"]
                for lab in labs
            ],
        },
        {
            "label": "README uses OS-appropriate fenced block languages for documented commands",
            "tooltip": {
                "summary": ["OS-specific command sections should use a matching fenced code language such as shell/bash for macOS/Linux or powershell/cmd for Windows."],
                "details": build_os_command_language_details(labs),
            },
            "cells": [
                (not lab["readme"]["osDocumentation"]["hasCommands"])
                or not lab["readme"]["osDocumentation"]["commandLanguageIssues"]
                for lab in labs
            ],
        },
        {
            "label": "README includes a Prerequisites section",
            "tooltip": {
                "summary": ["Every compared README should tell the reader what they need before starting the lab."],
                "details": build_readme_section_presence_details(
                    labs,
                    title="Prerequisites coverage",
                    note="This helps the reader understand setup expectations before they begin the lab.",
                    accessor=lambda lab: lab["readme"]["hasPrerequisites"],
                    success_label="Prerequisites section present",
                    failure_label="Add a Prerequisites H2 section to the README.",
                ),
            },
            "cells": [lab["readme"]["hasPrerequisites"] for lab in labs],
        },
        {
            "label": "README documents the files used by this lab in the 'Files in this lab' section",
            "tooltip": {
                "summary": ["The README should list the important files that this lab uses so a reader knows what to inspect or edit."],
                "details": build_files_under_test_details(labs),
            },
            "cells": [files_under_test_documented(lab) for lab in labs],
        },
        {
            "label": "README includes cleanup guidance",
            "tooltip": {
                "summary": ["Every compared README should tell the reader how to clean up after running the lab."],
                "details": build_readme_section_presence_details(
                    labs,
                    title="Cleanup guidance coverage",
                    note="Cleanup guidance prevents leftover runtime state and keeps the local environment consistent between runs.",
                    accessor=lambda lab: lab["readme"]["hasCleanupGuidance"],
                    success_label="Cleanup guidance present",
                    failure_label="Add cleanup guidance to the README as an H2 or H3 section.",
                ),
            },
            "cells": [lab["readme"]["hasCleanupGuidance"] for lab in labs],
        },
        {
            "label": "README shows the baseline console run before implementation",
            "tooltip": {
                "summary": ["Every compared README includes a shell console section before the implementation starts."],
                "details": build_console_section_details(labs, "opening"),
            },
            "cells": [bool(lab["readme"]["openingShellConsoleSection"]) for lab in labs],
        },
        {
            "label": "README shows the final console run after implementation",
            "tooltip": {
                "summary": ["Every compared README includes a shell console section after the implementation."],
                "details": build_console_section_details(labs, "closing"),
            },
            "cells": [bool(lab["readme"]["closingShellConsoleSection"]) for lab in labs],
        },
        {
            "label": "README provides OS-specific output sections when console output shows paths",
            "tooltip": {
                "summary": ["If a README shows console output with file-system paths, it should provide equivalent output sections for Windows, macOS, and Linux."],
                "details": build_os_output_coverage_details(labs),
            },
            "cells": [
                (not lab["readme"]["osDocumentation"]["hasPathOutputs"])
                or not lab["readme"]["osDocumentation"]["missingOutputOs"]
                for lab in labs
            ],
        },
        {
            "label": "README console sections all use shell fenced blocks",
            "tooltip": {
                "summary": ["All console examples use shell-style fences."],
                "details": build_shell_console_details(labs),
            },
            "cells": [lab["readme"]["allConsoleBlocksUseShellSyntax"] for lab in labs],
        },
        {
            "label": "README includes troubleshooting or common-confusion guidance",
            "tooltip": {
                "summary": ["Every compared README should help the reader recover when the lab flow is unclear or fails unexpectedly."],
                "details": build_readme_section_presence_details(
                    labs,
                    title="Troubleshooting guidance coverage",
                    note="This can be a Troubleshooting section or a common-confusion section with equivalent guidance.",
                    accessor=lambda lab: lab["readme"]["hasTroubleshooting"],
                    success_label="Troubleshooting guidance present",
                    failure_label="Add troubleshooting or common-confusion guidance to the README.",
                ),
            },
            "cells": [lab["readme"]["hasTroubleshooting"] for lab in labs],
        },
        {
            "label": "README includes pass criteria or verify-the-fix guidance",
            "tooltip": {
                "summary": ["Every compared README should tell the reader how to know the lab is complete and correct."],
                "details": build_readme_section_presence_details(
                    labs,
                    title="Pass criteria coverage",
                    note="This can be an explicit Pass criteria section or equivalent verify-the-fix guidance.",
                    accessor=lambda lab: lab["readme"]["hasPassCriteria"],
                    success_label="Pass criteria present",
                    failure_label="Add pass criteria or verify-the-fix guidance to the README.",
                ),
            },
            "cells": [lab["readme"]["hasPassCriteria"] for lab in labs],
        },
        {
            "label": "Implementation phase flow starts with the README baseline or intended-failure step",
            "tooltip": {
                "summary": ["Every compared implementation should begin with the baseline phase described in the README before the fix flow starts."],
                "details": build_phase_start_details(labs),
            },
            "cells": [
                bool(lab["readme"]["openingShellConsoleSection"].get("heading"))
                and "baseline" in lab["readme"]["openingShellConsoleSection"].get("heading", "").lower()
                for lab in labs
            ],
        },
        {
            "label": "Test counts match across the README, console output, CTRF JSON, and Specmatic HTML",
            "tooltip": {
                "summary": ["The README, console output, CTRF JSON, and Specmatic HTML report should describe the same counts."],
                "details": build_test_count_consistency_details(labs),
            },
            "cells": [lab["testCountConsistency"]["consistent"] for lab in labs],
        },
        {
            "label": "Generated artifacts include ctrf-report.json",
            "tooltip": {
                "summary": ["Each lab writes ctrf-report.json as the machine-readable test result."],
                "details": build_artifact_details(labs, "ctrf-report.json"),
            },
            "cells": ["ctrf-report.json" in lab["artifacts"]["generatedLabels"] for lab in labs],
        },
        {
            "label": "Generated artifacts include the sibling Specmatic HTML report",
            "tooltip": {
                "summary": ["Each lab writes specmatic-report.html alongside the CTRF JSON output."],
                "details": build_artifact_details(labs, "specmatic-report.html"),
            },
            "cells": ["specmatic-report.html" in lab["artifacts"]["generatedLabels"] for lab in labs],
        },
        {
            "label": "README does not keep extra, unwanted, or out-of-sequence implementation sections at H2 level",
            "tooltip": {
                "summary": ["Lab-specific walkthrough sections should move from H2 to H3."],
                "details": build_lab_specific_h2_details(labs, common_required_h2),
            },
            "cells": [not extra_h2_by_lab[lab["name"]] for lab in labs],
        },
        {
            "label": "Generated artifacts do not include unexpected extra files",
            "tooltip": {
                "summary": ["Any extra files beyond the report outputs are treated as deviations."],
                "details": build_additional_artifact_details(labs),
            },
            "cells": [not lab["warnings"]["additionalArtifacts"] for lab in labs],
        },
    ]
    rows = [add_row_status_prefix(index, row) for index, row in enumerate(row_definitions, start=1)]
    return {"columns": columns, "rows": rows}


def add_row_status_prefix(index: int, row: dict[str, Any]) -> dict[str, Any]:
    passed = all(bool(cell) for cell in row["cells"])
    row_copy = dict(row)
    row_copy["index"] = index
    row_copy["overallPassed"] = passed
    return row_copy


def render_comparison_html(payload: dict[str, Any]) -> str:
    summary_rows = "".join(
        f"<tr><th>{escape(item['label'])}</th><td>{escape(format_value(item['value']))}</td></tr>"
        for item in payload.get("summary", [])
    )
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
    .matrix-caption {{
      caption-side: top;
      text-align: left;
      font-weight: 700;
      color: #182126;
      padding: 0 0 12px;
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
      width: 420px;
      min-width: 420px;
      max-width: 420px;
    }}
    .matrix-row-label {{
      display: block;
    }}
    .matrix-row-title {{
      display: block;
      min-width: 0;
      line-height: 1.35;
    }}
    .matrix-row-meta {{
      display: flex;
      align-items: center;
      gap: 0.55rem;
      margin-bottom: 0.35rem;
    }}
    .matrix-row-text {{
      display: block;
      white-space: normal;
      overflow-wrap: break-word;
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
    .matrix-tooltip-section-attention {{
      border-color: #f0b39f;
      background: #fff6f3;
    }}
    .matrix-tooltip-section-attention .matrix-tooltip-section-title {{
      color: #b42318;
    }}
    .matrix-tooltip-section-attention .matrix-tooltip-section-note {{
      color: #8f2d1f;
    }}
    .matrix-tooltip-section-ok {{
      border-color: #9bd3a9;
      background: #f6fff8;
    }}
    .matrix-tooltip-section-ok .matrix-tooltip-section-title {{
      color: #1f7a3b;
    }}
    .matrix-tooltip-section-ok .matrix-tooltip-section-note {{
      color: #245b34;
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
      table-layout: auto;
    }}
    .matrix-tooltip-details th,
    .matrix-tooltip-details td {{
      border-bottom: 1px solid #eadfcd;
      padding: 9px 8px;
      text-align: left;
      vertical-align: top;
      overflow-wrap: break-word;
    }}
    .matrix-tooltip-details thead th {{
      font-weight: 700;
      color: #182126;
      background: #fffaf2;
    }}
    .matrix-tooltip-details tbody tr:nth-child(even) {{
      background: #fffdfa;
    }}
    .matrix-tooltip-details th:first-child,
    .matrix-tooltip-details td:first-child {{
      width: 32%;
    }}
    .matrix-tooltip-details th:nth-child(2),
    .matrix-tooltip-details td:nth-child(2) {{
      width: 16%;
    }}
    .matrix-tooltip-details th:last-child,
    .matrix-tooltip-details td:last-child {{
      width: 52%;
    }}
    .matrix-tooltip-cell-status {{
      font-weight: 700;
      white-space: nowrap;
    }}
    .matrix-tooltip-cell-status.ok {{
      color: #1f7a3b;
    }}
    .matrix-tooltip-cell-status.fail {{
      color: #b42318;
    }}
    .matrix-tooltip-cell-action.ok {{
      color: #245b34;
    }}
    .matrix-tooltip-cell-action.fail {{
      color: #8f2d1f;
      font-weight: 600;
    }}
    .matrix .matrix-lab {{
      min-width: 120px;
      max-width: 120px;
      white-space: normal;
    }}
    .matrix-row-status {{
      appearance: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.32rem;
      width: 104px;
      margin-right: 0.55rem;
      padding: 0.18rem 0.55rem;
      border-radius: 999px;
      font: inherit;
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.02em;
      text-align: center;
      white-space: nowrap;
      cursor: pointer;
      background: transparent;
      box-sizing: border-box;
    }}
    .matrix-row-status-info {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      width: 0.95rem;
      height: 0.95rem;
      border-radius: 999px;
      border: 1px solid currentColor;
      font-size: 0.72em;
      font-weight: 700;
      line-height: 1;
      opacity: 0.85;
    }}
    .matrix-row-status-text {{
      display: inline-block;
      min-width: 46px;
      text-align: center;
    }}
    .matrix-row-status.pass {{
      background: #eaf7ee;
      color: #1f7a3b;
      border: 1px solid #9bd3a9;
    }}
    .matrix-row-status.fail {{
      background: #fff1ea;
      color: #b42318;
      border: 1px solid #f0b39f;
    }}
    .matrix-row-status:hover,
    .matrix-row-status:focus {{
      outline: none;
      box-shadow: 0 0 0 2px rgba(20, 90, 122, 0.12);
      border-color: #145a7a;
    }}
    .matrix-row-number {{
      color: #5f6b74;
      margin-right: 0.5rem;
      white-space: nowrap;
      font-weight: 700;
      display: inline-block;
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
      <h2>Execution Differences</h2>
      <table>
        <thead><tr><th>Lab</th><th>Command Type</th><th>Command</th><th>Setup Type</th></tr></thead>
        <tbody>{difference_rows}</tbody>
      </table>
    </section>
    <section class="panel">
      <h2>README Validation Matrix</h2>
      <p class="muted">Each row is one validation. A green <strong>Pass</strong> prefix means every compared lab passed that validation. A red <strong>Failed</strong> prefix means at least one compared lab failed it.</p>
      <div class="matrix-wrap">
        <table class="matrix">
          <caption class="matrix-caption">README, console, and generated-report checks against the README source of truth</caption>
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
            if (section.tone === 'attention') {{
              sectionContainer.classList.add('matrix-tooltip-section-attention');
            }}
            if (section.tone === 'ok') {{
              sectionContainer.classList.add('matrix-tooltip-section-ok');
            }}
            container.appendChild(sectionContainer);
            renderDetailsBlock(sectionContainer, section, false);
          }});
          return;
        }}
        if (detailsData.type === 'table') {{
          const table = document.createElement('table');
          const thead = document.createElement('thead');
          const headerRow = document.createElement('tr');
          const headers = detailsData.headers || [];
          headers.forEach((header) => {{
            const th = document.createElement('th');
            th.textContent = header;
            headerRow.appendChild(th);
          }});
          thead.appendChild(headerRow);
          table.appendChild(thead);
          const tbody = document.createElement('tbody');
          (detailsData.rows || []).forEach((row) => {{
            const tr = document.createElement('tr');
            row.forEach((cell, index) => {{
              const td = document.createElement('td');
              td.textContent = cell;
              const header = headers[index] || '';
              if (header === 'Status' || header === 'Present') {{
                td.classList.add('matrix-tooltip-cell-status');
                if (cell === 'Present' || cell === 'Yes') {{
                  td.classList.add('ok');
                }}
                if (cell === 'Missing' || cell === 'No') {{
                  td.classList.add('fail');
                }}
              }}
              if (header === 'Action') {{
                td.classList.add('matrix-tooltip-cell-action');
                if (cell === 'No change needed.' || cell.endsWith('present') || cell === 'No change needed.') {{
                  td.classList.add('ok');
                }} else {{
                  td.classList.add('fail');
                }}
              }}
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


def render_lab_link(name: str, href: str) -> str:
    return f"<a href='{escape(href)}' target='_blank' rel='noreferrer'><strong>{escape(name)}</strong></a>"


def render_validation_matrix_row(row: dict[str, Any]) -> str:
    tooltip_attrs = render_matrix_trigger_attrs(row.get("tooltip", {}), row["label"])
    cells = "".join(render_matrix_cell(bool(cell), row["label"]) for cell in row["cells"])
    status_class = "pass" if row.get("overallPassed") else "fail"
    status_text = "Pass" if row.get("overallPassed") else "Failed"
    status_symbol = "&#10003;" if row.get("overallPassed") else "&#10007;"
    return (
        "<tr>"
        "<th class='row-label'>"
        "<span class='matrix-row-label'>"
        "<span class='matrix-row-title'>"
        "<span class='matrix-row-meta'>"
        f"<button type='button' class='matrix-row-status tooltip-trigger {status_class}' aria-expanded='false' aria-label='Show details for {escape(row['label'])}'{tooltip_attrs}><span aria-hidden='true'>{status_symbol}</span><span class='matrix-row-status-text'>{status_text}</span><span class='matrix-row-status-info' aria-hidden='true'>i</span></button>"
        "</span>"
        f"<span class='matrix-row-text'><span class='matrix-row-number'>{row.get('index', '')}.</span>{escape(row['label'])}</span>"
        "</span>"
        "</span>"
        "</th>"
        f"{cells}"
        "</tr>"
    )


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


def files_under_test_documented(lab: dict[str, Any]) -> bool:
    section_text = lab["readme"].get("filesSectionText", "").lower()
    if not lab["filesUnderTest"]:
        return True
    if not section_text:
        return False
    for alias, path in lab["filesUnderTest"].items():
        file_name = Path(path).name.lower()
        if alias.lower() not in section_text and path.lower() not in section_text and file_name not in section_text:
            return False
    return True


def build_execution_command_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        command_text = " ".join(lab["command"]) if lab["command"] else "(missing)"
        recognized = bool(lab["command"]) and lab["commandType"] != "other"
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Primary command",
                        "note": "This is the main shell command detected from the README.",
                        "items": [command_text],
                    },
                    {
                        "type": "bullets",
                        "title": "Execution style",
                        "note": "This is how the README command is classified.",
                        "items": [lab["commandType"]],
                    },
                    {
                        "type": "bullets",
                        "title": "Action",
                        "tone": "attention" if not recognized else "ok",
                        "note": "Use this to make the README command easier to understand and automate.",
                        "items": (
                            ["Rewrite the README so it shows one clear docker compose, docker run, or python command for the main lab flow."]
                            if not recognized
                            else ["No change needed."]
                        ),
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "Primary execution commands",
        "note": "Each README should expose one clear primary command so the documented execution style is obvious.",
        "sections": sections,
    }


def build_os_command_coverage_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        os_doc = lab["readme"]["osDocumentation"]
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Command sections found",
                        "note": "These OS-specific command sections were detected in the README.",
                        "items": [
                            f"{os_name}: "
                            + (", ".join(entry["heading"] for entry in entries) if entries else "(none)")
                            for os_name, entries in os_doc["commandCoverage"].items()
                        ]
                        if os_doc["hasCommands"]
                        else ["No command sections found in the README."],
                    },
                    {
                        "type": "bullets",
                        "title": "Add command sections",
                        "tone": "attention" if os_doc["missingCommandOs"] else "ok",
                        "note": "These OS-specific command variants are still missing.",
                        "items": os_doc["missingCommandOs"] or ["(none)"],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "OS-specific command coverage",
        "note": "When commands are documented, the README should show Windows, macOS, and Linux variants.",
        "sections": sections,
    }


def build_os_command_language_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        os_doc = lab["readme"]["osDocumentation"]
        issues = [
            f"{issue['os']}: '{issue['heading']}' uses ```{issue['language']}```"
            for issue in os_doc["commandLanguageIssues"]
        ]
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Fence language issues",
                        "tone": "attention" if issues else "ok",
                        "note": "These command sections should use an OS-appropriate fenced code language.",
                        "items": issues or ["(none)"],
                    },
                    {
                        "type": "bullets",
                        "title": "Action",
                        "tone": "attention" if issues else "ok",
                        "items": (
                            ["Use ```shell```/```bash``` for macOS and Linux sections, and ```powershell``` or ```cmd``` for Windows sections."]
                            if issues
                            else ["No change needed."]
                        ),
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "OS-specific command fence languages",
        "note": "OS-specific command sections should use fenced block languages that match the shell the reader is expected to use.",
        "sections": sections,
    }


def build_files_under_test_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        section_text = lab["readme"].get("filesSectionText", "")
        documented: list[str] = []
        missing: list[str] = []
        for alias, path in lab["filesUnderTest"].items():
            file_name = Path(path).name
            if (
                alias.lower() in section_text.lower()
                or path.lower() in section_text.lower()
                or file_name.lower() in section_text.lower()
            ):
                documented.append(f"{alias}: {path}")
            else:
                missing.append(f"{alias}: {path}")
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Documented in README",
                        "tone": "ok",
                        "note": "These files are already mentioned in the 'Files in this lab' section.",
                        "items": documented or ["(none)"],
                    },
                    {
                        "type": "bullets",
                        "title": "Add to README",
                        "tone": "attention" if missing else "ok",
                        "note": "These files are used by the lab but are not clearly listed in the 'Files in this lab' section.",
                        "items": missing or ["(none)"],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "Files used by each lab",
        "note": "Readers should be able to see which files matter by scanning the README section named 'Files in this lab'.",
        "sections": sections,
    }


def build_readme_section_presence_details(
    labs: list[dict[str, Any]],
    title: str,
    note: str,
    accessor: Any,
    success_label: str,
    failure_label: str,
) -> dict[str, Any]:
    sections = []
    for lab in labs:
        present = accessor(lab)
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Status",
                        "tone": "ok" if present else "attention",
                        "items": ["Present" if present else "Missing"],
                    },
                    {
                        "type": "bullets",
                        "title": "Action",
                        "tone": "ok" if present else "attention",
                        "items": [success_label if present else failure_label],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": title,
        "note": note,
        "sections": sections,
    }


def build_phase_start_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        first_phase = lab["readme"]["openingShellConsoleSection"].get("heading") or "(missing)"
        ok = bool(first_phase) and "baseline" in first_phase.lower()
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "First phase",
                        "items": [first_phase],
                    },
                    {
                        "type": "bullets",
                        "title": "Action",
                        "tone": "ok" if ok else "attention",
                        "items": [
                            "No change needed."
                            if ok
                            else "Move the README baseline or intended-failure step to the start of the implementation flow."
                        ],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "Implementation phase starts",
        "note": "The first implementation phase should be the README's baseline or intended-failure step so the documented before/after flow stays consistent.",
        "sections": sections,
    }


def build_h1_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "H1 title",
                        "items": [lab["readme"]["h1"] or "(missing)"],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "H1 titles",
        "sections": sections,
    }

def build_h3_details(labs: list[dict[str, Any]], extra_h2_by_lab: dict[str, list[str]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "H3 headings",
                        "note": "These are the implementation-step headings already using H3.",
                        "items": lab["readme"]["actualH3"] or ["(none)"],
                    },
                    {
                        "type": "bullets",
                        "title": "H2 sections to convert to H3",
                        "tone": "attention",
                        "note": "These walkthrough sections are still at H2 level and should move to H3.",
                        "items": extra_h2_by_lab[lab["name"]] or ["(none)"],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "H3 implementation steps",
        "note": "Lab-specific implementation steps belong in H3 headings. Any extra H2 sections should be converted to H3.",
        "sections": sections,
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
    sections = []
    for lab in labs:
        section = lab["readme"]["openingShellConsoleSection"] if which == "opening" else lab["readme"]["closingShellConsoleSection"]
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "README section",
                        "note": "This is the README heading that contains the console block.",
                        "items": [section.get("heading") or "(missing)"],
                    },
                    {
                        "type": "bullets",
                        "title": "Console run",
                        "note": "This is the shell command shown in the README.",
                        "items": [section.get("command") or "(missing)"],
                    },
                ],
            }
        )
    title = "Opening console sections" if which == "opening" else "Closing console sections"
    note = "These console blocks show the baseline and final command flow in the README."
    return {
        "type": "sections",
        "title": title,
        "note": note,
        "sections": sections,
    }


def build_os_output_coverage_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        os_doc = lab["readme"]["osDocumentation"]
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Path-based output sections found",
                        "note": "These OS-specific output sections were detected for console output that shows file-system paths.",
                        "items": [
                            f"{os_name}: "
                            + (", ".join(entry["heading"] for entry in entries) if entries else "(none)")
                            for os_name, entries in os_doc["outputCoverage"].items()
                        ]
                        if os_doc["hasPathOutputs"]
                        else ["No path-based console output sections detected."],
                    },
                    {
                        "type": "bullets",
                        "title": "Add output sections",
                        "tone": "attention" if os_doc["missingOutputOs"] else "ok",
                        "note": "These OS-specific output variants are still missing.",
                        "items": os_doc["missingOutputOs"] or ["(none)"],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "OS-specific output coverage",
        "note": "When console output includes file-system paths, the README should provide equivalent output examples for Windows, macOS, and Linux.",
        "sections": sections,
    }


def build_shell_console_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        ok = lab["readme"]["allConsoleBlocksUseShellSyntax"]
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Shell console blocks",
                        "items": [str(lab["readme"]["shellConsoleBlockCount"])],
                    },
                    {
                        "type": "bullets",
                        "title": "Shell syntax check",
                        "tone": "ok" if ok else "attention",
                        "items": ["All console blocks use shell syntax." if ok else "Some console blocks do not use shell syntax."],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "Shell console coverage",
        "note": "Shell fences keep the README commands copy-pasteable and consistent.",
        "sections": sections,
    }


def build_artifact_details(labs: list[dict[str, Any]], label: str) -> dict[str, Any]:
    sections = []
    for lab in labs:
        present = label in lab["artifacts"]["generatedLabels"]
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Status",
                        "tone": "ok" if present else "attention",
                        "items": ["Present" if present else "Missing"],
                    },
                    {
                        "type": "bullets",
                        "title": "Action",
                        "tone": "ok" if present else "attention",
                        "items": ["No change needed." if present else f"Generate {label} for this lab output."],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": f"{label} coverage",
        "sections": sections,
    }


def build_lab_specific_h2_details(labs: list[dict[str, Any]], common_required_h2: list[str] | tuple[str, ...] | set[str]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        extra_h2 = [section for section in lab["readme"]["actualH2"] if section not in common_required_h2]
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Move to H3",
                        "tone": "attention",
                        "note": "These walkthrough sections are currently H2 headings and should be converted to H3.",
                        "items": extra_h2 or ["(none)"],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "H2 sections that should be H3",
        "note": "These H2 sections are lab-specific walkthrough content. They should be changed to H3 in the lab README.",
        "sections": sections,
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
        "title": "Lab-specific generated artifacts",
        "headers": ["Lab", "Unique labels"],
        "rows": [
            [
                lab["name"],
                ", ".join(label for label in lab["artifacts"]["generatedLabels"] if artifact_label_counts[label] == 1) or "(none)",
            ]
            for lab in labs
        ],
    }


def build_additional_artifact_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        extra = lab["warnings"]["additionalArtifacts"]
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Additional artifacts",
                        "tone": "attention" if extra else "ok",
                        "items": extra or ["(none)"],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "Additional artifact warnings",
        "sections": sections,
    }


def build_h2_sequence_tooltip(labs: list[dict[str, Any]], common_required_h2: list[str] | tuple[str, ...] | set[str]) -> dict[str, Any]:
    shared_scaffold = list(common_required_h2) or ["(no shared required H2 sections configured)"]
    lab_sections = []
    for lab in labs:
        actual_h2 = list(lab["readme"]["actualH2"])
        actual_h2_set = set(actual_h2)
        expected_h2_set = set(common_required_h2)
        extra_sections = [section for section in actual_h2 if section not in expected_h2_set]
        missing_sections = [section for section in common_required_h2 if section not in actual_h2_set]
        incorrect_order_sections = []
        actual_positions = {section: index for index, section in enumerate(actual_h2)}
        previous_position = -1
        for section in common_required_h2:
            if section not in actual_positions:
                continue
            current_position = actual_positions[section]
            if current_position < previous_position:
                incorrect_order_sections.append(section)
            else:
                previous_position = current_position
        lab_sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "note": "These are the concrete README heading changes needed for this lab.",
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Keep as H2",
                        "tone": "ok",
                        "note": "These shared H2 sections should remain at H2 level in this order.",
                        "items": shared_scaffold,
                    },
                    {
                        "type": "bullets",
                        "title": "Move to H3",
                        "tone": "attention",
                        "note": "These H2 sections are lab-specific walkthrough content and should move to H3.",
                        "items": extra_sections or ["(none)"],
                    },
                    {
                        "type": "bullets",
                        "title": "Add as H2",
                        "tone": "attention",
                        "note": "These shared H2 sections are missing and should be added at H2 level.",
                        "items": missing_sections or ["(none)"],
                    },
                    {
                        "type": "bullets",
                        "title": "Fix H2 order",
                        "tone": "attention",
                        "note": "These shared H2 sections appear out of sequence and should be reordered.",
                        "items": incorrect_order_sections or ["(none)"],
                    },
                ],
            }
        )
    return {
        "summary": [
            "Every compared README should use the configured H2 sequence after the H1 title.",
            "Any extra, unwanted, or out-of-sequence H2 section is treated as a failure.",
        ],
        "details": {
            "type": "sections",
            "title": "Configured shared H2 sequence and README differences",
            "note": "The shared H2 sequence is configurable in one place. Keep that sequence stable and move lab-specific walkthrough steps into H3 headings.",
            "sections": [
                {
                    "type": "bullets",
                    "title": "Configured shared H2 sequence",
                    "note": "These H2 sections should appear in this exact order after the H1 title.",
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
        console_summary = extract_phase_command_log_summary(phase_path) or extract_tests_run_summary(phase.get("consoleSnippet", ""))
        readme_summary = readme_summaries[index]["summary"] if index < len(readme_summaries) else None
        readme_phase_name = readme_summaries[index]["heading"] if index < len(readme_summaries) else None
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
                "phase": readme_phase_name or phase.get("name", f"Phase {index + 1}"),
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


def extract_tests_run_summaries(readme_text: str) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    headings = extract_headings(readme_text)
    pattern = re.compile(r"Tests run:\s*\d+,\s*Successes:\s*\d+,\s*Failures:\s*\d+,\s*Errors:\s*\d+")
    for match in pattern.finditer(readme_text):
        line = line_number_for_index(readme_text, match.start())
        heading = heading_before_line(headings, line)
        summaries.append(
            {
                "heading": heading["text"] if heading else "",
                "summary": match.group(0),
            }
        )
    return summaries


def extract_tests_run_summary(console_output: str) -> str | None:
    clean_output = ANSI_ESCAPE_RE.sub("", console_output)
    matches = re.findall(r"Tests run:\s*\d+,\s*Successes:\s*\d+,\s*Failures:\s*\d+,\s*Errors:\s*\d+", clean_output)
    return matches[-1] if matches else None


def extract_phase_command_log_summary(phase_path: Path | None) -> str | None:
    if phase_path is None:
        return None
    command_log = phase_path / "command.log"
    if not command_log.exists():
        return None
    return extract_tests_run_summary(command_log.read_text(encoding="utf-8", errors="ignore"))


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
    clean_summary = ANSI_ESCAPE_RE.sub("", summary_text)
    match = re.search(
        r"Tests run:\s*(?P<tests>\d+),\s*Successes:\s*(?P<successes>\d+),\s*Failures:\s*(?P<failures>\d+),\s*Errors:\s*(?P<errors>\d+)",
        clean_summary,
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
