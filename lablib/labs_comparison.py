from __future__ import annotations

from collections import Counter
from dataclasses import asdict, is_dataclass
from datetime import datetime
from html import escape
import importlib.util
import json
from pathlib import Path
import re
from typing import Any

from lablib.readme_expectations import (
    EXPECTED_README_H2_SEQUENCE,
    EXECUTABLE_COMMAND_FENCE_LANGUAGES,
    command_block_language,
    README_TEMPLATE,
    get_lab_readme_override,
    heading_matches,
    optional_h2_titles,
    shared_h2_sequence_matches,
    shared_h2_titles,
    title_present,
    unexpected_h2_titles_for_lab,
)
from lablib.readme_schema import (
    BASELINE_PHASE,
    FINAL_PHASE,
    DEFAULT_REQUIRED_PHASES,
    expected_h2_titles_for_document,
    extract_overview_video_section,
    parse_readme_document,
    parse_required_implementation_phases,
    phase_sequence_is_valid,
    validate_external_link,
)
from lablib.provenance import detect_report_provenance
from lablib.time_display import format_report_datetime


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "output"
COMPARISON_OUTPUT_DIR = OUTPUT_DIR / "consolidated-report"
COMPARISON_JSON_PATH = COMPARISON_OUTPUT_DIR / "labs-comparison.json"
COMPARISON_HTML_PATH = COMPARISON_OUTPUT_DIR / "labs-comparison.html"
OTHER_COMPARISON_JSON_PATH = COMPARISON_OUTPUT_DIR / "labs-other-comparison.json"
OTHER_COMPARISON_HTML_PATH = COMPARISON_OUTPUT_DIR / "labs-other-comparison.html"
TEST_COUNT_COMPARISON_JSON_PATH = COMPARISON_OUTPUT_DIR / "labs-test-counts-comparison.json"
TEST_COUNT_COMPARISON_HTML_PATH = COMPARISON_OUTPUT_DIR / "labs-test-counts-comparison.html"
FENCING_COMPARISON_JSON_PATH = COMPARISON_OUTPUT_DIR / "labs-command-output-fencing-comparison.json"
FENCING_COMPARISON_HTML_PATH = COMPARISON_OUTPUT_DIR / "labs-command-output-fencing-comparison.html"
LEGACY_COMPARISON_JSON_PATH = OUTPUT_DIR / "labs-comparison.json"
LEGACY_COMPARISON_HTML_PATH = OUTPUT_DIR / "labs-comparison.html"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
FENCED_CODE_BLOCK_RE = re.compile(r"```(?P<lang>[a-zA-Z0-9_-]+)?\s*\n(?P<body>.*?)```", re.DOTALL | re.MULTILINE)
SHELL_COMMAND_PREFIXES_RE = re.compile(r"^(docker|python|python3|chmod|git|curl|cd|npm|pnpm|yarn|make|bash|sh)\b")
PATH_LIKE_RE = re.compile(r"([A-Za-z]:\\[^\s`]+|(?:\./|\.\./|/Users/|/usr/|/tmp/|/var/|/home/|/opt/|/etc/)[^\s`]+)")
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
TESTS_RUN_SUMMARY_RE = re.compile(r"Tests run:\s*\d+,\s*Successes:\s*\d+,\s*Failures:\s*\d+(?:,\s*Errors:\s*\d+)?")
EXAMPLES_SUMMARY_RE = re.compile(r"Examples:\s*(?P<passed>\d+)\s+passed\s+and\s+(?P<failed>\d+)\s+failed\s+out of\s+(?P<tests>\d+)\s+total", re.IGNORECASE)
MCP_SUMMARY_RE = re.compile(
    r"(?:(?P<prefix>SUMMARY:)\s*)?Total:\s*(?P<tests>\d+)\s*(?:\||\n|\r\n)\s*Passed:\s*(?P<passed>\d+)\s*(?:\||\n|\r\n)\s*Failed:\s*(?P<failed>\d+)",
    re.IGNORECASE,
)
TERMINAL_OUTPUT_FENCE_LANGUAGE = "terminaloutput"
IGNORED_ARTIFACT_LABELS = {"html", "coverage_report.json", "stub_usage_report.json"}
REPORT_ARTIFACT_LABELS = {"ctrf-report.json", "specmatic-report.html"}
CORE_VALIDATION_LABELS = {
    "README starts with a top-level H1 title",
    "README H2 order matches the lab's source-of-truth structure",
    "Command and Output fencing validation",
    "Test counts match across the README, console output, CTRF JSON, and Specmatic HTML",
    "Generated artifacts include ctrf-report.json",
    "Generated artifacts include the sibling Specmatic HTML report",
}
IGNORABLE_MESSAGES = ("(none)",)


def build_bullet_section(title: str, items: list[str] | None, ignorable_messages: tuple[str, ...] = IGNORABLE_MESSAGES, **kwargs) -> dict[str, Any] | None:
    """Build a bullet section, returning None if items are only placeholders."""
    if not items:
        # Return success message instead of None to show in modal
        # Override tone to "ok" (green) when all items pass
        kwargs_with_success_tone = {**kwargs, "tone": "ok"}
        return {"type": "bullets", "title": title, "items": ["All passed"], **kwargs_with_success_tone}
    if len(items) == 1 and items[0] in ignorable_messages:
        return None
    return {"type": "bullets", "title": title, "items": items, **kwargs}


def add_lab_section(sections: list[dict[str, Any]], lab: dict[str, Any], lab_sections: list[dict[str, Any] | None], note: str | None = None) -> None:
    """Filter and append lab sections to parent sections list, skipping if all are None."""
    visible_sections = [s for s in lab_sections if s is not None]
    if visible_sections:
        section = {
            "type": "sections",
            "title": lab["name"],
            "href": lab["href"],
            "sections": visible_sections,
        }
        if note:
            section["note"] = note
        sections.append(section)


def add_action_section(lab_sections: list[dict[str, Any]], issues: list[str] | None, action_messages: list[str] | str) -> None:
    """Add Action section to lab_sections if there are issues.

    Only adds Action section when issues exist. Skips when there are no issues.

    Args:
        lab_sections: List to append the Action section to
        issues: List of issues (or any truthy value) to check if Action should be shown
        action_messages: Single message or list of messages to display when there are issues
    """
    if not issues:
        return

    messages = [action_messages] if isinstance(action_messages, str) else action_messages
    lab_sections.append({
        "type": "bullets",
        "title": "Action",
        "tone": "attention",
        "items": messages,
    })


def generate_labs_comparison(
    root: Path | None = None,
    lab_names: list[str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    repo_root = root or ROOT
    selected = set(discover_report_lab_names(repo_root) if lab_names is None else lab_names)
    run_files = sorted(repo_root.glob("*/run.py"))
    if selected:
        run_files = [path for path in run_files if path.parent.name in selected]
    labs = [build_lab_profile(path.parent) for path in run_files]
    validation_rows = build_validation_rows(labs)
    payload = {
        "title": "Labs Comparison",
        "generatedAt": generated_at or datetime.now().astimezone().isoformat(),
        "provenance": detect_report_provenance(),
        "summary": build_summary(labs),
        "commonalities": build_commonalities(labs),
        "differences": build_differences(labs),
        "validationMatrix": build_validation_matrix(labs, validation_rows, mode="core"),
        "labs": labs,
        "navigation": {
            "consolidatedReportHref": "consolidated-report.html",
        },
    }
    other_payload = {
        **payload,
        "title": "Labs Other Comparison",
        "validationMatrix": build_validation_matrix(labs, validation_rows, mode="other"),
    }
    test_count_payload = build_test_count_comparison_payload(labs, generated_at or datetime.now().astimezone().isoformat())
    fencing_payload = build_fencing_comparison_payload(labs, generated_at or datetime.now().astimezone().isoformat())
    COMPARISON_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for legacy_path in (LEGACY_COMPARISON_JSON_PATH, LEGACY_COMPARISON_HTML_PATH):
        if legacy_path.exists():
            legacy_path.unlink()
    COMPARISON_JSON_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    COMPARISON_HTML_PATH.write_text(render_comparison_html(payload), encoding="utf-8")
    OTHER_COMPARISON_JSON_PATH.write_text(json.dumps(other_payload, indent=2) + "\n", encoding="utf-8")
    OTHER_COMPARISON_HTML_PATH.write_text(render_comparison_html(other_payload), encoding="utf-8")
    TEST_COUNT_COMPARISON_JSON_PATH.write_text(json.dumps(test_count_payload, indent=2) + "\n", encoding="utf-8")
    TEST_COUNT_COMPARISON_HTML_PATH.write_text(render_test_count_comparison_html(test_count_payload), encoding="utf-8")
    FENCING_COMPARISON_JSON_PATH.write_text(json.dumps(fencing_payload, indent=2) + "\n", encoding="utf-8")
    FENCING_COMPARISON_HTML_PATH.write_text(render_fencing_comparison_html(fencing_payload), encoding="utf-8")
    return payload


def discover_report_lab_names(root: Path | None = None) -> list[str]:
    repo_root = root or ROOT
    snapshot_dir = repo_root / "output" / "labs-output"
    discovered = (
        sorted(
            path.name.removesuffix("-output")
            for path in snapshot_dir.iterdir()
            if path.is_dir() and path.name.endswith("-output")
        )
        if snapshot_dir.exists()
        else []
    )
    if discovered:
        return discovered
    return sorted(path.parent.name for path in repo_root.glob("*/run.py"))


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
    readme_doc = parse_readme_document(upstream_readme_text)
    headings = extract_headings(upstream_readme_text)
    h2_headings = [heading["text"] for heading in headings if heading["level"] == 2]
    h3_headings = [heading["text"] for heading in headings if heading["level"] == 3]
    code_blocks = extract_fenced_code_blocks(upstream_readme_text)
    readme_command = extract_primary_command(upstream_readme_text)
    command_type = classify_command(readme_command)
    setup_types = detect_setup_types(readme_command)
    artifact_labels = sorted({artifact["label"] for artifact in [*common_artifacts, *phase_artifacts]})
    generated_artifact_profiles = [artifact for artifact in [*common_artifacts, *phase_artifacts] if artifact["origin"] == "generated"]
    generated_artifact_labels = sorted(
        {
            artifact["label"]
            for artifact in generated_artifact_profiles
        }
    )
    artifact_kinds = sorted({artifact["kind"] for artifact in [*common_artifacts, *phase_artifacts]})
    shell_console_blocks = [block for block in code_blocks if looks_like_console_block(block) and block["language"] in {"shell", "bash", "sh", "zsh", "powershell", "ps1", "cmd", "bat"}]
    console_blocks = [block for block in code_blocks if looks_like_console_block(block)]
    shell_console_sections = build_shell_console_sections(headings, shell_console_blocks)
    os_documentation = analyze_readme_os_documentation(upstream_readme_text, headings, code_blocks)
    if readme_doc.is_v2:
        os_documentation = normalize_v2_os_documentation(os_documentation, readme_doc)
    video_links = detect_video_links(readme_doc)
    # Check if "Overview Video" H3 section exists
    video_section_text, _ = extract_overview_video_section(upstream_readme_text, readme_doc.headings)
    has_overview_video_section = video_section_text is not None
    additional_artifacts = sorted(
        artifact["target"]
        for artifact in generated_artifact_profiles
        if artifact["label"] not in REPORT_ARTIFACT_LABELS and artifact["label"] not in IGNORED_ARTIFACT_LABELS
    )
    report_snapshot = load_lab_report_snapshot(spec.name)
    readme_efm = readme_doc.metadata.get("expected_failure_mismatch", False)
    readme_efm_reason = readme_doc.metadata.get("expected_failure_mismatch_reason", "")
    readme_emtc = readme_doc.metadata.get("expected_missing_test_counts", False)
    readme_emtc_reason = readme_doc.metadata.get("expected_missing_test_counts_reason", "")
    effective_efm = spec.expected_failure_mismatch or bool(readme_efm)
    effective_efm_reason = spec.expected_failure_mismatch_reason or readme_efm_reason
    effective_emtc = spec.expected_missing_test_counts or bool(readme_emtc)
    effective_emtc_reason = spec.expected_missing_test_counts_reason or readme_emtc_reason
    test_count_consistency = build_test_count_consistency_profile(
        spec,
        readme_doc,
        report_snapshot,
        expected_missing=effective_emtc,
        expected_missing_reason=effective_emtc_reason,
        expected_failure_mismatch=effective_efm,
        expected_failure_mismatch_reason=effective_efm_reason,
    )
    override = get_lab_readme_override(spec.name)
    required_h2 = list(expected_h2_titles_for_document(readme_doc) or shared_h2_titles())
    unexpected_h2 = unexpected_h2_titles_for_lab(spec.name, h2_headings)
    shared_h2_matches = (h2_headings == required_h2) if readme_doc.is_v2 else shared_h2_sequence_matches(h2_headings)

    # Helper function to parse report metadata with backward compatibility
    def parse_report_metadata(report_metadata: Any) -> dict[str, bool]:
        """
        Parse report metadata, supporting both old boolean and new object formats.

        Old format: ctrf: true
        New format: ctrf: { expected: true, expected_failure: false }
        """
        if isinstance(report_metadata, bool):
            # Old format: ctrf: true
            return {"expected": report_metadata, "expected_failure": False}
        elif isinstance(report_metadata, dict):
            # New format: ctrf: { expected: true, expected_failure: false }
            return {
                "expected": report_metadata.get("expected", False),
                "expected_failure": report_metadata.get("expected_failure", False)
            }
        else:
            # Default
            return {"expected": False, "expected_failure": False}

    # Create mapping from phase id to readme_doc phase metadata
    phase_metadata_map = {
        phase.id: phase.metadata.get("expected_reports", {})
        for phase in readme_doc.phases
    }
    defaults_from_readme = readme_doc.metadata.get("reports", {})

    # Parse required_implementation_phases from README frontmatter
    required_phase_kinds = parse_required_implementation_phases(readme_doc.metadata)

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
                "expectedReports": {
                    "ctrf": parse_report_metadata(
                        phase_metadata_map.get(phase.name, {}).get("ctrf", defaults_from_readme.get("ctrf", False))
                    ),
                    "html": parse_report_metadata(
                        phase_metadata_map.get(phase.name, {}).get("html", defaults_from_readme.get("html", False))
                    ),
                },
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
            "h1": next((heading["text"] for heading in headings[:1] if heading["level"] == 1), ""),
            "actualH1": [heading["text"] for heading in headings if heading["level"] == 1],
            "requiredH2": required_h2,
            "optionalH2": [] if readme_doc.is_v2 else list(optional_h2_titles()),
            "additionalH2": list(override.allowed_additional_h2_titles),
            "actualH2": h2_headings,
            "actualH3": h3_headings,
            "hasPrerequisites": title_present(h2_headings, "Prerequisites"),
            "hasStudioSection": any("studio" in heading.lower() for heading in h2_headings),
            "hasStudioComponent": any("studio" in heading.lower() for heading in [*h2_headings, *h3_headings]) or "--profile studio" in upstream_readme_text.lower(),
            "hasTroubleshooting": title_present(h2_headings, "Troubleshooting"),
            "hasPassCriteria": any(heading_matches(heading, "Pass criteria") or "verify the fix" in heading.lower() for heading in h2_headings),
            "hasCleanupGuidance": any("cleanup" in heading.lower() for heading in [*h2_headings, *h3_headings]),
            "headingCount": len(headings),
            "h2Count": len(h2_headings),
            "h3Count": len(h3_headings),
            "phaseIds": [phase.id for phase in readme_doc.phases],
            "requiredPhases": readme_doc.metadata.get("required_phases", list(DEFAULT_REQUIRED_PHASES)),
            "shellConsoleBlockCount": len(shell_console_blocks),
            "consoleBlockCount": len(console_blocks),
            "hasAtLeastTwoShellConsoleBlocks": len(shell_console_blocks) >= 2,
            "allCommandBlocksUseExecutableSyntax": bool(console_blocks) and all(block["rawLanguage"] == "shell" for block in console_blocks),
            "everyCommandHasOutputSnippet": not os_documentation["commandsMissingOutput"],
            "allOutputBlocksUseTerminalOutput": not os_documentation["outputLanguageIssues"],
            "openingShellConsoleSection": shell_console_sections[0] if shell_console_sections else {},
            "closingShellConsoleSection": shell_console_sections[-1] if shell_console_sections else {},
            "shellConsoleSections": shell_console_sections,
            "filesSectionText": extract_heading_section_text(upstream_readme_text, "Files in this lab", level=2),
            "osDocumentation": os_documentation,
            "videoLinks": video_links,
            "hasOverviewVideoSection": has_overview_video_section,
            "unexpectedH2": unexpected_h2,
            "sharedH2OrderMatches": shared_h2_matches,
            "schemaVersion": readme_doc.schema_version or "legacy",
        },
        "warnings": {
            "additionalArtifacts": additional_artifacts,
        },
        "testCountConsistency": test_count_consistency,
        "phaseRequirements": {
            "requiredKinds": required_phase_kinds,
            "actualKinds": [phase.id for phase in readme_doc.phases],
            "allRequiredPresent": set(required_phase_kinds) <= {phase.id for phase in readme_doc.phases},
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
        "origin": classify_artifact_origin(data["source_relpath"]),
    }


def normalize_v2_os_documentation(profile: dict[str, Any], readme_doc: Any) -> dict[str, Any]:
    normalized = {**profile}
    # os_scope metadata removed - no longer checking for common command scope
    common_command_issues: list[str] = []
    common_output_issues: list[str] = []
    common_phase_titles: list[str] = []
    common_output_titles: list[str] = []

    # os_scope detection removed - phases now declare their OS specificity through structure

    normalized["commonCommandForAllOs"] = bool(common_phase_titles) and not common_command_issues
    normalized["commonCommandPhaseTitles"] = common_phase_titles
    normalized["commonOutputForAllOs"] = bool(common_output_titles) and not common_output_issues
    normalized["commonOutputPhaseTitles"] = common_output_titles
    normalized["commonCommandIssues"] = common_command_issues
    normalized["commonOutputIssues"] = common_output_issues
    if common_command_issues:
        normalized["commandLanguageIssues"] = [
            *normalized.get("commandLanguageIssues", []),
            *[
                {"os": "all", "heading": issue.split(":")[0], "language": "mixed/common-scope-mismatch"}
                for issue in common_command_issues
            ],
        ]
    return normalized


def detect_video_links(readme_doc: Any) -> list[dict[str, str]]:
    """Detect overview video links in README.

    New behavior: Extracts from "Why this lab matters" > "### Overview Video" section.
    Falls back to scanning entire document for backward compatibility.
    """
    # NEW: Check overview_video_url field first
    if readme_doc.overview_video_url:
        return [{
            "label": "Overview Video",
            "target": readme_doc.overview_video_url,
            "source": "overview_video_section"
        }]

    # FALLBACK: Scan entire document (backward compatible)
    video_links: list[dict[str, str]] = []
    for link in readme_doc.links:
        target = link.target.strip()
        lowered_target = target.lower()
        lowered_label = link.label.strip().lower()
        is_video = any(
            token in lowered_target
            for token in ("youtube.com", "youtu.be", "vimeo.com", "loom.com")
        ) or any(token in lowered_label for token in ("video", "walkthrough", "overview"))
        if is_video:
            video_links.append({"label": link.label or target, "target": target, "source": "document_scan"})
    return video_links


def overview_video_is_optional(readme_doc: Any) -> bool:
    metadata = readme_doc.metadata or {}
    optional_components = metadata.get("optional_components", {}) or {}
    if isinstance(optional_components, dict) and "overview_video" in optional_components:
        return bool(optional_components.get("overview_video"))
    if "overview_video_optional" in metadata:
        return bool(metadata.get("overview_video_optional"))
    return False


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
        body = match.group("body").strip()
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        preview = lines[0] if lines else ""
        blocks.append(
            {
                "rawLanguage": (match.group("lang") or "").strip(),
                "language": (match.group("lang") or "").strip().lower(),
                "body": body,
                "preview": preview,
                "normalizedPreview": normalize_output_preview(preview),
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


def normalize_output_preview(text: str) -> str:
    if not text:
        return ""
    normalized = re.sub(
        r"^\s*(?:\[\d{4}-\d{2}-\d{2}[^\]]*\]\s*|\d{4}-\d{1,2}-\d{1,2}[ T]\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s*|[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}:\d{2}\s*)",
        "",
        text,
    )
    return normalized.strip()


def is_command_language_appropriate(os_name: str, language: str) -> bool:
    return language == "shell"


def is_ignored_teardown_command(command: str) -> bool:
    normalized = " ".join(command.strip().lower().split())
    if (
        ("docker compose" in normalized or "docker-compose" in normalized)
        and " down" in f" {normalized}"
    ):
        return True
    teardown_prefixes = ("docker stop", "docker rm")
    return normalized.startswith(teardown_prefixes)


def analyze_readme_os_documentation(readme_text: str, headings: list[dict[str, Any]], code_blocks: list[dict[str, Any]]) -> dict[str, Any]:
    command_coverage = {os_name: [] for os_name in ("Windows", "macOS", "Linux")}
    output_coverage = {os_name: [] for os_name in ("Windows", "macOS", "Linux")}
    command_language_issues: list[dict[str, str]] = []
    output_language_issues: list[str] = []
    commands_missing_output: list[str] = []
    command_fence_violations: list[dict[str, str]] = []
    output_fence_violations: list[dict[str, str]] = []
    missing_output_pairs: list[dict[str, str]] = []
    command_output_checks: list[dict[str, str]] = []
    has_commands = False
    has_path_outputs = False

    for index, block in enumerate(code_blocks):
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
            heading_text = heading["text"] if heading else "(no heading)"
            for os_name in os_targets:
                command_coverage[os_name].append(
                    {
                        "heading": heading_text,
                        "language": block["language"] or "(none)",
                        "preview": block["normalizedPreview"] or "(blank)",
                    }
                )
                if not is_command_language_appropriate(os_name, block["rawLanguage"] or ""):
                    issue = {
                        "os": os_name,
                        "heading": heading_text,
                        "language": block["rawLanguage"] or "(none)",
                    }
                    command_language_issues.append(issue)
            if block["rawLanguage"] != "shell":
                command_fence_violations.append(
                    {
                        "heading": heading_text,
                        "line": str(block["line"]),
                        "command": block["preview"] or "(blank)",
                        "commandFence": block["rawLanguage"] or "(none)",
                    }
                )
            if is_ignored_teardown_command(block["preview"] or ""):
                continue
            next_block = code_blocks[index + 1] if index + 1 < len(code_blocks) else None
            next_heading = heading_before_line(headings, next_block["line"]) if next_block is not None else None
            if (
                next_block is None
                or looks_like_console_block(next_block)
                or (next_heading["text"] if next_heading else "") != (heading["text"] if heading else "")
            ):
                issue_text = f"{heading_text} -> {block['normalizedPreview'] or '(blank)'}"
                commands_missing_output.append(issue_text)
                missing_output_pairs.append(
                    {
                        "heading": heading_text,
                        "line": str(block["line"]),
                        "command": block["preview"] or "(blank)",
                        "commandFence": block["rawLanguage"] or "(none)",
                        "outputFence": "(missing)",
                        "output": "(missing)",
                    }
                )
                failure_notes: list[str] = []
                if block["rawLanguage"] != "shell":
                    failure_notes.append("Command fence must be ```shell```.")
                failure_notes.append("Missing following terminaloutput block in the same section.")
                command_output_checks.append(
                    {
                        "line": str(block["line"]),
                        "heading": heading_text,
                        "commandFence": block["rawLanguage"] or "(none)",
                        "command": block["preview"] or "(blank)",
                        "outputFence": "(missing)",
                        "output": "(missing)",
                        "status": "fail",
                        "notes": " ".join(failure_notes),
                    }
                )
                continue
            output_targets = set(os_targets) or set(next_block.get("osTargets", []))
            next_heading_text = next_heading["text"] if next_heading else "(no heading)"
            for os_name in output_targets:
                output_coverage[os_name].append(
                    {
                        "heading": next_heading_text,
                        "language": next_block["language"] or "(none)",
                        "preview": next_block["normalizedPreview"] or "(blank)",
                    }
                )
            if next_block["rawLanguage"] != TERMINAL_OUTPUT_FENCE_LANGUAGE:
                output_language_issues.append(
                    f"{heading_text} -> {block['normalizedPreview'] or '(blank)'} uses ```{next_block['rawLanguage'] or '(none)'}``` for output"
                )
                output_fence_violations.append(
                    {
                        "heading": heading_text,
                        "line": str(block["line"]),
                        "command": block["preview"] or "(blank)",
                        "commandFence": block["rawLanguage"] or "(none)",
                        "outputFence": next_block["rawLanguage"] or "(none)",
                        "output": next_block["preview"] or "(blank)",
                    }
                )
            status = "pass"
            failure_notes: list[str] = []
            if block["rawLanguage"] != "shell":
                status = "fail"
                failure_notes.append("Command fence must be ```shell```.")
            if next_block["rawLanguage"] != TERMINAL_OUTPUT_FENCE_LANGUAGE:
                status = "fail"
                failure_notes.append("Output fence must be ```terminaloutput```.")
            command_output_checks.append(
                {
                    "line": str(block["line"]),
                    "heading": heading_text,
                    "commandFence": block["rawLanguage"] or "(none)",
                    "command": block["preview"] or "(blank)",
                    "outputFence": next_block["rawLanguage"] or "(none)",
                    "output": next_block["preview"] or "(blank)",
                    "status": status,
                    "notes": " ".join(failure_notes) if failure_notes else "Command/output fencing is valid.",
                }
            )
        elif is_output_block_with_paths(block):
            has_path_outputs = True
            heading_text = heading["text"] if heading else "(no heading)"
            for os_name in os_targets:
                output_coverage[os_name].append(
                    {
                        "heading": heading_text,
                        "language": block["language"] or "(none)",
                        "preview": block["normalizedPreview"] or "(blank)",
                    }
                )
            if block["rawLanguage"] != TERMINAL_OUTPUT_FENCE_LANGUAGE:
                output_language_issues.append(
                    f"{heading_text} uses ```{block['rawLanguage'] or '(none)'}``` for output"
                )
                output_fence_violations.append(
                    {
                        "heading": heading_text,
                        "line": str(block["line"]),
                        "command": "(no associated command)",
                        "commandFence": "(n/a)",
                        "outputFence": block["rawLanguage"] or "(none)",
                        "output": block["preview"] or "(blank)",
                    }
                )
                command_output_checks.append(
                    {
                        "line": str(block["line"]),
                        "heading": heading_text,
                        "commandFence": "(n/a)",
                        "command": "(no associated command)",
                        "outputFence": block["rawLanguage"] or "(none)",
                        "output": block["preview"] or "(blank)",
                        "status": "fail",
                        "notes": "Standalone output-like snippet must use ```terminaloutput```.",
                    }
                )

    return {
        "hasCommands": has_commands,
        "missingCommandOs": [os_name for os_name, entries in command_coverage.items() if has_commands and not entries],
        "commandCoverage": command_coverage,
        "commandLanguageIssues": command_language_issues,
        "commandFenceViolations": command_fence_violations,
        "hasPathOutputs": has_path_outputs,
        "missingOutputOs": [os_name for os_name, entries in output_coverage.items() if has_path_outputs and not entries],
        "outputCoverage": output_coverage,
        "commandsMissingOutput": commands_missing_output,
        "outputLanguageIssues": output_language_issues,
        "outputFenceViolations": output_fence_violations,
        "missingOutputPairs": missing_output_pairs,
        "commandOutputChecks": command_output_checks,
        "missingOutputForCommandOs": [os_name for os_name, entries in command_coverage.items() if entries and not output_coverage[os_name]],
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


def check_expected_failure(lab: dict[str, Any], artifact_label: str, report_key: str) -> bool | str:
    """
    Check if an artifact passes validation, considering expected_failure.

    Returns:
    - True: Normal pass (report produced when expected, or not required)
    - False: Normal fail (report missing when expected, or produced when marked as expected_failure)
    - "expected_failure_pass": Special pass (! icon) when report not produced but marked as expected_failure

    Args:
        lab: Lab profile dictionary
        artifact_label: The artifact file name (e.g., "ctrf-report.json")
        report_key: The report type key (e.g., "ctrf" or "html")
    """
    artifact_exists = artifact_label in lab["artifacts"]["generatedLabels"]

    # Check if any phase has this report marked as expected_failure
    has_expected_failure = any(
        phase["expectedReports"][report_key]["expected_failure"]
        for phase in lab["phases"]
    )

    if has_expected_failure:
        # Inverted logic: report should NOT be produced
        if artifact_exists:
            return False  # Fail - report was produced despite expected_failure
        else:
            return "expected_failure_pass"  # Special pass - ! icon
    else:
        # Normal logic: check if report is expected and exists
        any_expected = any(
            phase["expectedReports"][report_key]["expected"]
            for phase in lab["phases"]
        )
        return (not any_expected) or artifact_exists


def build_validation_rows(labs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    columns = [{"name": lab["name"], "href": lab["href"]} for lab in labs]
    shared_h2 = tuple(labs[0]["readme"]["requiredH2"]) if labs else ()
    common_required_h2 = list(shared_h2)
    extra_h2_by_lab = {
        lab["name"]: list(lab["readme"]["unexpectedH2"])
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
            "cells": [lab["readme"]["sharedH2OrderMatches"] for lab in labs],
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
            "label": "README documents either one common command for all OSes or explicit commands for Windows, macOS, and Linux",
            "tooltip": {
                "summary": ["When a README documents commands, it should either show one command that applies to every OS or separate commands for Windows, macOS, and Linux."],
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
            "label": "README documents a Studio component for this lab",
            "tooltip": {
                "summary": ["This row shows whether the lab README includes a Studio section or Studio command flow."],
                "details": build_studio_component_details(labs),
            },
            "cells": [lab["readme"]["hasStudioComponent"] for lab in labs],
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
            "label": "README documents either one common output snippet for all OSes or matching output for each OS-specific command",
            "tooltip": {
                "summary": ["When commands are documented, the README should either show one shared output snippet for all OSes or provide matching output for each OS-specific command."],
                "details": build_os_output_coverage_details(labs),
            },
            "cells": [
                (not lab["readme"]["osDocumentation"]["hasCommands"])
                or not lab["readme"]["osDocumentation"]["missingOutputForCommandOs"]
                for lab in labs
            ],
        },
        {
            "label": "README overview video links are surfaced when present",
            "tooltip": {
                "summary": [
                    "All READMEs must include an 'Overview Video' section in 'Why this lab matters' with a video link.",
                    "Video is mandatory."
                ],
                "details": build_video_link_details(labs),
            },
            "cells": [
                # Pass if: H3 exists with video link(s)
                bool(lab["readme"].get("hasOverviewVideoSection", False) and lab["readme"]["videoLinks"])
                for lab in labs
            ],
        },
        {
            "label": "Command and Output fencing validation",
            "tooltip": {
                "summary": [
                    "Documented commands must use ```shell``` fences.",
                    "Each command must be followed by a ```terminaloutput``` block in the same section.",
                ],
                "details": build_command_output_fencing_details(labs),
                "fullReportHref": "labs-command-output-fencing-comparison.html",
                "fullReportLabel": "Open full command/output fencing report",
            },
            "cells": [
                lab["readme"]["allCommandBlocksUseExecutableSyntax"]
                and lab["readme"]["everyCommandHasOutputSnippet"]
                and lab["readme"]["allOutputBlocksUseTerminalOutput"]
                for lab in labs
            ],
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
                "summary": [
                    "The README, console output, CTRF JSON, and Specmatic HTML report should describe the same counts.",
                    "Artifact availability rows are counted per lab, while these count-comparison details are shown per phase.",
                    "When a source is absent for a phase, it is shown as not-available rather than treated as a mismatch.",
                ],
                "details": build_test_count_consistency_details(labs),
                "fullReportHref": "labs-test-counts-comparison.html",
                "fullReportLabel": "Open full test-counts report",
            },
            "cells": [lab["testCountConsistency"]["consistent"] for lab in labs],
        },
        {
            "label": "Generated artifacts include ctrf-report.json",
            "tooltip": {
                "summary": ["Each lab writes ctrf-report.json as the machine-readable test result."],
                "details": build_artifact_details(labs, "ctrf-report.json"),
            },
            "cells": [
                check_expected_failure(lab, "ctrf-report.json", "ctrf")
                for lab in labs
            ],
        },
        {
            "label": "Generated artifacts include the sibling Specmatic HTML report",
            "tooltip": {
                "summary": ["Each lab writes specmatic-report.html alongside the CTRF JSON output."],
                "details": build_artifact_details(labs, "specmatic-report.html"),
            },
            "cells": [
                check_expected_failure(lab, "specmatic-report.html", "html")
                for lab in labs
            ],
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
        }
    ]
    return row_definitions


def build_validation_matrix(
    labs: list[dict[str, Any]],
    row_definitions: list[dict[str, Any]] | None = None,
    *,
    mode: str = "core",
) -> dict[str, Any]:
    columns = [{"name": lab["name"], "href": lab["href"]} for lab in labs]
    definitions = list(row_definitions or build_validation_rows(labs))
    if mode == "core":
        definitions = [row for row in definitions if row["label"] in CORE_VALIDATION_LABELS]
    elif mode == "other":
        definitions = [row for row in definitions if row["label"] not in CORE_VALIDATION_LABELS]
    rows = [add_row_status_prefix(index, row) for index, row in enumerate(definitions, start=1)]
    return {"columns": columns, "rows": rows}


def build_test_count_comparison_payload(labs: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    sections = []
    summary_items = []
    for lab in labs:
        comparisons = lab["testCountConsistency"].get("phases", [])
        mismatch_phases = [item["phase"] for item in comparisons if item.get("status") == "mismatch"]
        matched_phases = [item["phase"] for item in comparisons if item.get("status") == "match"]
        unavailable_phases = [item["phase"] for item in comparisons if item.get("status") == "not-available"]
        expected_unavailable_phases = [item["phase"] for item in comparisons if item.get("status") == "expected-not-available"]
        if mismatch_phases:
            summary_items.append({"lab": lab["name"], "status": "mismatch", "message": f"Mismatches in {', '.join(mismatch_phases)}."})
        elif matched_phases:
            summary_items.append({"lab": lab["name"], "status": "match", "message": "Matching counts where data is available."})
        elif expected_unavailable_phases:
            reason = lab["testCountConsistency"].get("expectedMissingReason") or "This lab does not publish test-count summaries."
            summary_items.append({"lab": lab["name"], "status": "expected-not-available", "message": f"Count data is expected to be not available. {reason}"})
        elif unavailable_phases:
            summary_items.append({"lab": lab["name"], "status": "not-available", "message": "Count data is not available for comparison."})
        else:
            summary_items.append({"lab": lab["name"], "status": "not-available", "message": "No phase data was available to validate."})

        sections.append(
            {
                "lab": lab["name"],
                "href": lab["href"],
                "note": "Each row compares the README summary, console output, CTRF JSON, and Specmatic HTML for one phase.",
                "rows": [
                    {
                        "phase": item["phase"],
                        "readme": build_count_cell(item.get("readmeCounts"), item),
                        "console": build_count_cell(item.get("consoleCounts"), item),
                        "ctrf": build_count_cell(item.get("ctrfCounts"), item),
                        "html": build_count_cell(item.get("htmlCounts"), item),
                        "status": format_count_status(item.get("status", "not-available")),
                    }
                    for item in comparisons
                ] or [
                    {
                        "phase": "(no phase data found)",
                        "readme": count_cell_text(None),
                        "console": count_cell_text(None),
                        "ctrf": count_cell_text(None),
                        "html": count_cell_text(None),
                        "status": "Not available",
                    }
                ],
            }
        )
    return {
        "title": "Labs Test Counts Comparison",
        "generatedAt": generated_at,
        "provenance": detect_report_provenance(),
        "summary": summary_items,
        "labs": sections,
    }


def build_fencing_comparison_payload(labs: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    sections = []
    summary_items = []
    for lab in labs:
        os_doc = lab["readme"]["osDocumentation"]
        command_fence_violations = os_doc.get("commandFenceViolations", [])
        output_fence_violations = os_doc.get("outputFenceViolations", [])
        missing_output_pairs = os_doc.get("missingOutputPairs", [])
        total_issues = len(command_fence_violations) + len(output_fence_violations) + len(missing_output_pairs)
        if total_issues:
            summary_items.append(
                {
                    "lab": lab["name"],
                    "status": "issues",
                    "message": f"{total_issues} fencing issue(s): {len(command_fence_violations)} non-shell command fence, {len(output_fence_violations)} non-terminaloutput output fence, {len(missing_output_pairs)} missing same-section pairing.",
                }
            )
        else:
            summary_items.append(
                {
                    "lab": lab["name"],
        "status": "ok",
        "message": "No command/output fencing issues detected.",
                }
            )
        sections.append(
            {
                "lab": lab["name"],
                "href": lab["href"],
                "checks": os_doc.get("commandOutputChecks", []),
            }
        )
    return {
        "title": "Labs Command And Output Fencing Comparison",
        "generatedAt": generated_at,
        "provenance": detect_report_provenance(),
        "summary": summary_items,
        "labs": sections,
    }


def add_row_status_prefix(index: int, row: dict[str, Any]) -> dict[str, Any]:
    passed = all(bool(cell) for cell in row["cells"])
    row_copy = dict(row)
    row_copy["index"] = index
    row_copy["overallPassed"] = passed
    return row_copy


def render_comparison_html(payload: dict[str, Any]) -> str:
    page_title = escape(payload.get("title", "Labs Comparison"))
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
    provenance_html = render_provenance_html(payload.get("provenance"))
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
    .tooltip-report-link {{
      margin-top: 10px;
    }}
    .tooltip-report-link a {{
      color: #145a7a;
      text-decoration: none;
      border-bottom: 1px solid rgba(20, 90, 122, 0.35);
      font-weight: 600;
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
    .matrix-tooltip-section-expected-failure {{
      border-color: #fde047;
      background: #fef9c3;
    }}
    .matrix-tooltip-section-expected-failure .matrix-tooltip-section-title {{
      color: #ca8a04;
    }}
    .matrix-tooltip-section-expected-failure .matrix-tooltip-section-note {{
      color: #a16207;
    }}
    .matrix-tooltip-section:first-child {{
      margin-top: 0;
    }}
    .matrix-tooltip-section-title {{
      display: inline-block;
      font-weight: 700;
      margin-bottom: 4px;
      color: #182126;
      text-decoration: none;
      border-bottom: 1px solid rgba(20, 90, 122, 0.28);
    }}
    a.matrix-tooltip-section-title:hover,
    a.matrix-tooltip-section-title:focus {{
      color: #145a7a;
      border-bottom-color: rgba(20, 90, 122, 0.55);
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
      white-space: pre-line;
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
    .matrix-tooltip-details table.matrix-tooltip-counts-table {{
      table-layout: fixed;
    }}
    .matrix-tooltip-details table.matrix-tooltip-counts-table th,
    .matrix-tooltip-details table.matrix-tooltip-counts-table td {{
      font-size: 0.92rem;
      padding: 9px 6px;
    }}
    .matrix-tooltip-details table.matrix-tooltip-counts-table th:first-child,
    .matrix-tooltip-details table.matrix-tooltip-counts-table td:first-child {{
      width: 27%;
    }}
    .matrix-tooltip-details table.matrix-tooltip-counts-table th:nth-child(2),
    .matrix-tooltip-details table.matrix-tooltip-counts-table td:nth-child(2),
    .matrix-tooltip-details table.matrix-tooltip-counts-table th:nth-child(3),
    .matrix-tooltip-details table.matrix-tooltip-counts-table td:nth-child(3),
    .matrix-tooltip-details table.matrix-tooltip-counts-table th:nth-child(4),
    .matrix-tooltip-details table.matrix-tooltip-counts-table td:nth-child(4),
    .matrix-tooltip-details table.matrix-tooltip-counts-table th:nth-child(5),
    .matrix-tooltip-details table.matrix-tooltip-counts-table td:nth-child(5) {{
      width: 14%;
    }}
    .matrix-tooltip-details table.matrix-tooltip-counts-table th:last-child,
    .matrix-tooltip-details table.matrix-tooltip-counts-table td:last-child {{
      width: 17%;
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
    .matrix-tooltip-count.ok {{
      color: #245b34;
    }}
    .matrix-tooltip-count {{
      display: block;
      white-space: pre;
      line-height: 1.25;
      font-size: 0.88rem;
      min-width: 0;
      max-width: 100%;
      overflow-wrap: normal;
      word-break: normal;
    }}
    .matrix-tooltip-count.mismatch {{
      color: #b42318;
      font-weight: 700;
      background: #fff1ea;
      border-radius: 0.35rem;
      padding: 0.2rem 0.35rem;
    }}
    .matrix-tooltip-count.na {{
      color: #5f6b74;
      font-style: italic;
    }}
    .matrix-tooltip-count.partial {{
      color: #92400e;
      font-weight: 600;
      background: #fef9c3;
      border-radius: 0.35rem;
      padding: 0.2rem 0.35rem;
    }}
    .partial-match-status {{
      color: #92400e;
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
    .matrix-row-status.expected-failure {{
      background: #fef9c3;
      color: #ca8a04;
      border: 1px solid #fde047;
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
    .matrix-cell.expected-failure {{
      color: #ca8a04;
    }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>{page_title}</h1>
      <p class="muted">{escape(format_report_datetime(payload['generatedAt']))}</p>
      {provenance_html}
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
      <p id="matrix-tooltip-report-link" class="tooltip-report-link" hidden><a id="matrix-tooltip-report-link-anchor" href="#" target="_blank" rel="noopener noreferrer">Open full report</a></p>
      <button id="matrix-tooltip-details-toggle" type="button" class="tooltip-details-toggle" hidden>View details</button>
      <div id="matrix-tooltip-details" class="matrix-tooltip-details" hidden></div>
    </div>
  </div>
  <script>
    (() => {{
      const modal = document.getElementById('matrix-tooltip-modal');
      const title = document.getElementById('matrix-tooltip-title');
      const summary = document.getElementById('matrix-tooltip-summary');
      const reportLink = document.getElementById('matrix-tooltip-report-link');
      const reportLinkAnchor = document.getElementById('matrix-tooltip-report-link-anchor');
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
        if (reportLink) {{
          reportLink.hidden = true;
        }}
        if (reportLinkAnchor) {{
          reportLinkAnchor.href = '#';
          reportLinkAnchor.textContent = 'Open full report';
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
          if (!modal || !title || !summary || !reportLink || !reportLinkAnchor || !details || !detailsToggle) return;
          const tooltipJson = trigger.getAttribute('data-tooltip-json') || '';
          if (!tooltipJson) return;
          const tooltip = JSON.parse(tooltipJson);
          activeTooltip = tooltip;
          activeTrigger = trigger;
          title.textContent = tooltip.title || 'What this means';
          renderBulletList(summary, tooltip.summary || ['(no summary available)']);
          if (tooltip.fullReportHref) {{
            reportLink.hidden = false;
            reportLinkAnchor.href = tooltip.fullReportHref;
            reportLinkAnchor.textContent = tooltip.fullReportLabel || 'Open full report';
          }} else {{
            reportLink.hidden = true;
          }}
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
          li.innerHTML = renderSimpleMarkdown(item);
          list.appendChild(li);
        }});
        container.appendChild(list);
      }}

      function escapeHtml(text) {{
        return String(text)
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/\"/g, '&quot;')
          .replace(/'/g, '&#39;');
      }}

      function renderSimpleMarkdown(text) {{
        const escaped = escapeHtml(text || '');
        return escaped
          .replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>')
          .replace(/\\n/g, '<br>');
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
          if (detailsData.href) {{
            const sectionTitleLink = document.createElement('a');
            sectionTitleLink.className = 'matrix-tooltip-section-title';
            sectionTitleLink.href = detailsData.href;
            sectionTitleLink.target = '_blank';
            sectionTitleLink.rel = 'noreferrer';
            sectionTitleLink.textContent = detailsData.title;
            container.appendChild(sectionTitleLink);
          }} else {{
            const sectionTitle = document.createElement('div');
            sectionTitle.className = 'matrix-tooltip-section-title';
            sectionTitle.textContent = detailsData.title;
            container.appendChild(sectionTitle);
          }}
        }}
        if (detailsData.note) {{
          const note = document.createElement('p');
          note.className = isRoot ? 'matrix-tooltip-details-note' : 'matrix-tooltip-section-note';
          note.innerHTML = renderSimpleMarkdown(detailsData.note);
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
            if (section.tone === 'expected-failure') {{
              sectionContainer.classList.add('matrix-tooltip-section-expected-failure');
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
          if (
            headers.length === 6 &&
            headers[0] === 'Phase' &&
            headers[1] === 'README' &&
            headers[2] === 'Console' &&
            headers[3] === 'CTRF' &&
            headers[4] === 'HTML' &&
            headers[5] === 'Status'
          ) {{
            table.classList.add('matrix-tooltip-counts-table');
          }}
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
              const rawValue = (cell && typeof cell === 'object' && !Array.isArray(cell)) ? cell : null;
              const textValue = rawValue ? (rawValue.text || '') : cell;
              if (rawValue && rawValue.className) {{
                const content = document.createElement('div');
                content.textContent = textValue;
                rawValue.className.split(/\s+/).filter(Boolean).forEach((name) => content.classList.add(name));
                if (rawValue.ariaLabel) {{
                  content.setAttribute('aria-label', rawValue.ariaLabel);
                }}
                td.appendChild(content);
              }} else {{
                td.textContent = textValue;
              }}
              if (rawValue && rawValue.title) {{
                td.title = rawValue.title;
              }} else if (typeof textValue === 'string' && textValue.includes('T=') && textValue.includes('P=')) {{
                td.title = 'T = Total\\nP = Passed\\nF = Failed\\nS = Skipped';
                td.setAttribute('aria-label', 'T = Total, P = Passed, F = Failed, S = Skipped');
              }}
              const header = headers[index] || '';
              if ((header === 'Status' || header === 'Present') && !rawValue?.className) {{
                td.classList.add('matrix-tooltip-cell-status');
                if (textValue === 'Present' || textValue === 'Yes') {{
                  td.classList.add('ok');
                }}
                if (textValue === 'Missing' || textValue === 'No') {{
                  td.classList.add('fail');
                }}
              }}
              if (header === 'Action' && !rawValue?.className) {{
                td.classList.add('matrix-tooltip-cell-action');
                if (textValue === 'No change needed.' || textValue.endsWith('present') || textValue === 'No change needed.') {{
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
            // Support both plain text (string) and HTML content (object with html field)
            if (typeof item === 'object' && item.html) {{
              li.innerHTML = item.html;
            }} else {{
              li.textContent = item;
            }}
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


def render_test_count_comparison_html(payload: dict[str, Any]) -> str:
    summary_items = "".join(
        f"<li><strong>{escape(item['lab'])}:</strong> {escape(item['message'])}</li>"
        for item in payload.get("summary", [])
    ) or "<li>No lab report snapshots were available.</li>"
    sections_html = "".join(render_test_count_lab_section(section) for section in payload.get("labs", []))
    provenance_html = render_provenance_html(payload.get("provenance"))
    generated_at_html = f"<p class='muted'>{escape(format_report_datetime(payload['generatedAt']))}</p>" if payload.get("generatedAt") else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(payload.get("title", "Labs Test Counts Comparison"))}</title>
  <style>
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background: #f5f1e8;
      color: #182126;
    }}
    main {{
      max-width: 1180px;
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
    .muted {{
      color: #5b6570;
    }}
    h1, h2, h3 {{
      margin-top: 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid #eadfcd;
      vertical-align: top;
    }}
    .counts-cell {{
      white-space: pre-line;
    }}
    .status-chip {{
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 0.88rem;
      font-weight: 600;
    }}
    .status-match {{
      color: #1f7a4d;
      background: #e5f5eb;
    }}
    .status-mismatch {{
      color: #ab2e2e;
      background: #fae8e5;
    }}
    .status-not-available {{
      color: #6b7280;
      background: #edf0f3;
    }}
    .status-expected {{
      color: #9a6700;
      background: #fff2cc;
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
      <h1>{escape(payload.get("title", "Labs Test Counts Comparison"))}</h1>
      {generated_at_html}
      {provenance_html}
      <p class="muted">The README, console, CTRF JSON, and Specmatic HTML should describe the same run wherever those sources are available.</p>
      <ul>{summary_items}</ul>
    </section>
    {sections_html}
  </main>
</body>
</html>
"""


def render_fencing_comparison_html(payload: dict[str, Any]) -> str:
    summary_items = "".join(
        f"<li><strong>{escape(item['lab'])}:</strong> {escape(item['message'])}</li>"
        for item in payload.get("summary", [])
    ) or "<li>No lab report snapshots were available.</li>"
    sections_html = "".join(render_fencing_lab_section(section) for section in payload.get("labs", []))
    provenance_html = render_provenance_html(payload.get("provenance"))
    generated_at_html = f"<p class='muted'>{escape(format_report_datetime(payload['generatedAt']))}</p>" if payload.get("generatedAt") else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(payload.get("title", "Labs Command And Output Fencing Comparison"))}</title>
  <style>
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background: #f5f1e8;
      color: #182126;
    }}
    main {{
      max-width: 1180px;
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
    .muted {{ color: #5b6570; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      margin-bottom: 18px;
    }}
    th, td {{
      text-align: left;
      padding: 10px 8px;
      border-bottom: 1px solid #eadfcd;
      vertical-align: top;
    }}
    code, pre {{
      font-family: "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
      font-size: 0.92rem;
    }}
    a {{
      color: #145a7a;
      text-decoration: none;
      border-bottom: 1px solid rgba(20, 90, 122, 0.35);
    }}
    .ok {{
      color: #1f7a4d;
      font-weight: 600;
    }}
    .warn {{
      color: #ab2e2e;
      font-weight: 600;
    }}
    .status-chip {{
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      font-size: 0.88rem;
      font-weight: 600;
    }}
    .status-pass {{
      color: #1f7a4d;
      background: #e5f5eb;
    }}
    .status-fail {{
      color: #ab2e2e;
      background: #fae8e5;
    }}
    .fence-chip {{
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      font-family: "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
      font-size: 0.88rem;
      font-weight: 600;
      white-space: nowrap;
    }}
    .fence-ok {{
      color: #1f7a4d;
      background: #e5f5eb;
    }}
    .fence-fail {{
      color: #ab2e2e;
      background: #fae8e5;
    }}
    .snippet-box {{
      margin: 0;
      padding: 10px;
      border-radius: 8px;
      border: 1px solid #eadfcd;
      background: #fbf7ef;
      font-family: "SFMono-Regular", Menlo, Monaco, Consolas, monospace;
      font-size: 0.92rem;
      white-space: pre-wrap;
      word-break: break-word;
      overflow-wrap: anywhere;
      max-width: 100%;
    }}
    .note-text {{
      white-space: normal;
      line-height: 1.35;
    }}
  </style>
</head>
<body>
  <main>
    <section class="panel">
      <h1>{escape(payload.get("title", "Labs Command And Output Fencing Comparison"))}</h1>
      {generated_at_html}
      {provenance_html}
      <p class="muted">Commands must use <code>```shell</code>, outputs must use <code>```terminaloutput</code>, and every command must be followed by its output in the same section.</p>
      <ul>{summary_items}</ul>
    </section>
    {sections_html}
  </main>
</body>
</html>
"""


def render_fencing_lab_section(section: dict[str, Any]) -> str:
    checks = section.get("checks", [])
    status_html = "<p class='ok'>No command/output fencing issues detected.</p>" if not checks else ""
    tables = render_fencing_issue_table(
        "Command and Output fencing validation",
        ["Status", "Line", "Section", "Command fence", "Command snippet", "Output fence", "Output snippet", "Notes"],
        [
            [
                render_fencing_status_chip(item["status"]),
                item["line"],
                item["heading"],
                render_fencing_fence_chip(item["commandFence"], expected="shell", allow_missing=False),
                render_fencing_snippet(item["command"]),
                render_fencing_fence_chip(item["outputFence"], expected=TERMINAL_OUTPUT_FENCE_LANGUAGE, allow_missing=True),
                render_fencing_snippet(item["output"]),
                render_fencing_notes(item["notes"], item["status"]),
            ]
            for item in checks
        ],
        raw_html_columns={0, 3, 4, 5, 6, 7},
    )
    return (
        "<section class='panel'>"
        f"<h2><a href='{escape(section['href'])}' target='_blank' rel='noopener noreferrer'>{escape(section['lab'])}</a></h2>"
        f"{status_html}{tables}"
        "</section>"
    )


def render_fencing_issue_table(title: str, headers: list[str], rows: list[list[str]], raw_html_columns: set[int] | None = None) -> str:
    if not rows:
        return ""
    raw_html_columns = raw_html_columns or set()
    header_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    rows_html = "".join(
        "<tr>" + "".join(
            f"<td>{cell if index in raw_html_columns else render_fencing_cell(cell)}</td>"
            for index, cell in enumerate(row)
        ) + "</tr>"
        for row in rows
    )
    return f"<h3>{escape(title)}</h3><table><thead><tr>{header_html}</tr></thead><tbody>{rows_html}</tbody></table>"


def render_fencing_cell(value: str) -> str:
    return escape(value)


def render_fencing_status_chip(status: str) -> str:
    normalized = status.strip().lower()
    css_class = "status-pass" if normalized == "pass" else "status-fail"
    return f"<span class='status-chip {css_class}'>{escape(status.title())}</span>"


def render_fencing_fence_chip(fence: str, *, expected: str, allow_missing: bool) -> str:
    normalized = fence.strip()
    is_match = normalized == expected
    if allow_missing and normalized == "(missing)":
        is_match = False
    css_class = "fence-ok" if is_match else "fence-fail"
    return f"<span class='fence-chip {css_class}'>{escape(normalized)}</span>"


def render_fencing_snippet(snippet: str) -> str:
    return f"<div class='snippet-box'>{escape(snippet)}</div>"


def render_fencing_notes(notes: str, status: str) -> str:
    css_class = "ok" if status.strip().lower() == "pass" else "warn"
    return f"<div class='note-text {css_class}'>{escape(notes)}</div>"


def render_test_count_lab_section(section: dict[str, Any]) -> str:
    rows_html = "".join(
        "<tr>"
        f"<td>{escape(str(row['phase']))}</td>"
        f"<td class='counts-cell'>{render_count_cell_html(row['readme'])}</td>"
        f"<td class='counts-cell'>{render_count_cell_html(row['console'])}</td>"
        f"<td class='counts-cell'>{render_count_cell_html(row['ctrf'])}</td>"
        f"<td class='counts-cell'>{render_count_cell_html(row['html'])}</td>"
        f"<td>{render_count_status_chip(str(row['status']))}</td>"
        "</tr>"
        for row in section.get("rows", [])
    )
    return (
        "<section class='panel'>"
        f"<h2><a href='{escape(section['href'])}' target='_blank' rel='noopener noreferrer'>{escape(section['lab'])}</a></h2>"
        f"<p class='muted'>{escape(section.get('note', ''))}</p>"
        "<table>"
        "<thead><tr><th>Phase</th><th>README</th><th>Console</th><th>CTRF</th><th>HTML</th><th>Status</th></tr></thead>"
        f"<tbody>{rows_html}</tbody>"
        "</table>"
        "</section>"
    )


def render_count_cell_html(value: Any) -> str:
    if isinstance(value, dict):
        return escape(str(value.get("text", ""))).replace("\n", "<br>")
    return escape(str(value)).replace("\n", "<br>")


def render_count_status_chip(status: str) -> str:
    normalized = status.strip().lower()
    if normalized == "match":
        css_class = "status-match"
    elif normalized == "mismatch":
        css_class = "status-mismatch"
    elif normalized == "expected":
        css_class = "status-expected"
    else:
        css_class = "status-not-available"
    return f"<span class='status-chip {css_class}'>{escape(status)}</span>"


def render_provenance_html(provenance: dict[str, Any] | None) -> str:
    if not provenance:
        return ""
    label = escape(str(provenance.get("label", "Generated from")))
    display = escape(str(provenance.get("display", "n/a")))
    href = str(provenance.get("href", "") or "")
    if href:
        return f'<p class="muted"><strong>{label}:</strong> <a href="{escape(href)}" target="_blank" rel="noopener noreferrer">{display}</a></p>'
    return f'<p class="muted"><strong>{label}:</strong> {display}</p>'


def render_lab_link(name: str, href: str) -> str:
    return f"<a href='{escape(href)}' target='_blank' rel='noreferrer'><strong>{escape(name)}</strong></a>"


def render_validation_matrix_row(row: dict[str, Any]) -> str:
    tooltip_attrs = render_matrix_trigger_attrs(row.get("tooltip", {}), row["label"])
    cells = "".join(render_matrix_cell(cell, row["label"]) for cell in row["cells"])

    # Check if any cell is an expected_failure_pass
    has_expected_failure_pass = any(cell == "expected_failure_pass" for cell in row["cells"])

    if has_expected_failure_pass:
        status_class = "expected-failure"
        status_text = "Pass"
        status_symbol = "&#33;"
    else:
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


def render_matrix_cell(cell_value: bool | str, validation_label: str) -> str:
    """
    Render a validation matrix cell, handling boolean and expected_failure_pass states.

    Args:
        cell_value: True (pass), False (fail), or "expected_failure_pass" (! icon)
        validation_label: The validation label for title/aria attributes
    """
    if cell_value == "expected_failure_pass":
        symbol = "&#33;"  # Exclamation mark
        state = "expected-failure"
        title = "expected failure - report not produced as intended"
    elif cell_value:
        symbol = "&#10003;"  # Checkmark
        state = "yes"
        title = "present"
    else:
        symbol = "&#10007;"  # X mark
        state = "no"
        title = "absent"
    return f"<td title='{escape(validation_label)} is {title}'><span class='matrix-cell {state}' aria-label='{escape(title)}'>{symbol}</span></td>"


def render_matrix_trigger_attrs(tooltip: dict[str, Any], label: str) -> str:
    payload = {
        "title": label,
        "summary": tooltip.get("summary", []),
        "details": tooltip.get("details"),
        "fullReportHref": tooltip.get("fullReportHref"),
        "fullReportLabel": tooltip.get("fullReportLabel"),
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
        lab_sections = [
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
        ]
        issues = None if recognized else ["unrecognized command type"]
        add_action_section(lab_sections, issues, "Rewrite the README so it shows one clear docker compose, docker run, or python command for the main lab flow.")
        sections.append({
            "type": "sections",
            "title": lab["name"],
            "sections": lab_sections,
        })
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
        if os_doc.get("commonCommandForAllOs"):
            found_items = [
                "Common command flow for all OSes: "
                + (", ".join(os_doc.get("commonCommandPhaseTitles", [])) or "(none)")
            ]
            note = "The README marks these phases as using one common command flow for all OSes."
        else:
            found_items = [
                f"{os_name}: "
                + (", ".join(entry["heading"] for entry in entries) if entries else "(none)")
                for os_name, entries in os_doc["commandCoverage"].items()
            ] if os_doc["hasCommands"] else ["No command sections found in the README."]
            note = "These OS-specific command sections were detected in the README."
        lab_sections = [
            {
                "type": "bullets",
                "title": "Command sections found",
                "note": note,
                "items": found_items,
            },
        ]
        missing_items = os_doc["missingCommandOs"]
        missing_section = build_bullet_section(
            "Add command sections",
            missing_items,
            tone="attention" if missing_items and not os_doc.get("commonCommandForAllOs") else "ok",
            note="These command variants are still missing only when the README does not already declare one common command flow for all OSes.",
        )
        if missing_section:
            lab_sections.append(missing_section)
        add_lab_section(sections, lab, lab_sections)
    return {
        "type": "sections",
        "title": "OS-specific command coverage",
        "note": "When commands are documented, the README should either show one common command for all OSes or separate variants for Windows, macOS, and Linux.",
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
        lab_sections = [
            build_bullet_section(
                "Fence language issues",
                issues,
                tone="attention",
                note="These command sections should use an OS-appropriate fenced code language.",
            ),
        ]
        add_action_section(lab_sections, issues, "Use ```shell```/```bash``` for macOS and Linux sections, and ```powershell``` or ```cmd``` for Windows sections.")
        add_lab_section(sections, lab, lab_sections)
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
        lab_sections = [
            build_bullet_section(
                "Documented in README",
                documented,
                tone="ok",
                note="These files are already mentioned in the 'Files in this lab' section.",
            ),
            build_bullet_section(
                "Add to README",
                missing,
                tone="attention" if missing else "ok",
                note="These files are used by the lab but are not clearly listed in the 'Files in this lab' section.",
            ),
        ]
        add_lab_section(sections, lab, lab_sections)
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
        lab_sections = [
            {
                "type": "bullets",
                "title": "Status",
                "tone": "ok" if present else "attention",
                "items": ["Present" if present else "Missing"],
            },
        ]
        issues = None if present else ["missing"]
        add_action_section(lab_sections, issues, failure_label)
        sections.append({
            "type": "sections",
            "title": lab["name"],
            "href": lab["href"],
            "sections": lab_sections,
        })
    return {
        "type": "sections",
        "title": title,
        "note": note,
        "sections": sections,
    }


def build_phase_start_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    """Build details for phase sequence validation."""
    sections = []
    for lab in labs:
        phase_ids = lab.get("readme", {}).get("phaseIds", [])

        # Check if baseline is first and final is last
        has_baseline = phase_ids and phase_ids[0] == BASELINE_PHASE
        has_final = phase_ids and phase_ids[-1] == FINAL_PHASE
        ok = has_baseline and has_final

        # Skip if everything is OK (will show "All passed" automatically)
        if ok:
            continue

        # Only build sections if there's an error
        lab_sections = []

        # Show current phase state
        if phase_ids:
            lab_sections.append(
                build_bullet_section(
                    "Phase sequence",
                    [f"First: {phase_ids[0]}", f"Last: {phase_ids[-1]}"],
                    tone="attention"
                )
            )

        # Show what's missing
        missing = []
        if not has_baseline:
            missing.append(BASELINE_PHASE)
        if not has_final:
            missing.append(FINAL_PHASE)

        if missing:
            lab_sections.append(
                build_bullet_section("Missing required phases", missing, tone="attention")
            )
            issues = ["missing phases"]
            add_action_section(
                lab_sections,
                issues,
                [f'Add "### {p.replace("-", " ").title()} Phase"' for p in missing]
            )

        add_lab_section(sections, lab, lab_sections)

    return {
        "title": "Phase sequence coverage",
        "note": f"First phase must be {BASELINE_PHASE}, last must be {FINAL_PHASE}.",
        "sections": sections,
    }


def build_h1_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        actual_h1 = list(lab["readme"]["actualH1"])
        h1_title = lab["readme"]["h1"] or "(missing)"
        matching_h1 = actual_h1[1:] if lab["readme"]["h1"] else actual_h1

        # When H1 exists but is not in first position
        if not lab["readme"]["h1"] and matching_h1:
            section_label = "H1 title found (wrong position)"
            section_note = "H1 title exists but is not the first heading."
        else:
            section_label = "Other H1 titles"
            section_note = None

        lab_sections = [
            {
                "type": "bullets",
                "title": "H1 title",
                "tone": "ok" if lab["readme"]["h1"] else "attention",
                "items": [h1_title],
            },
            build_bullet_section(
                section_label,
                matching_h1,
                tone="ok",
                note=section_note,
            ),
        ]
        add_lab_section(sections, lab, lab_sections)
    return {
        "type": "sections",
        "title": "H1 titles",
        "sections": sections,
    }

def build_h3_details(labs: list[dict[str, Any]], extra_h2_by_lab: dict[str, list[str]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        lab_sections = [
            build_bullet_section(
                "H3 headings",
                lab["readme"]["actualH3"],
                note="These are the implementation-step headings already using H3.",
            ),
            build_bullet_section(
                "H2 sections to convert to H3",
                extra_h2_by_lab[lab["name"]],
                tone="attention",
                note="These walkthrough sections are still at H2 level and should move to H3.",
            ),
        ]
        add_lab_section(sections, lab, lab_sections)
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
                "href": lab["href"],
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
        if os_doc.get("commonOutputForAllOs"):
            found_items = [
                "Common output flow for all OSes: "
                + (", ".join(os_doc.get("commonOutputPhaseTitles", [])) or "(none)")
            ]
            note = "The README marks these phases as using one shared output snippet for all OSes."
        else:
            found_items = [
                f"{os_name}: "
                + (", ".join(entry["heading"] for entry in entries) if entries else "(none)")
                for os_name, entries in os_doc["outputCoverage"].items()
            ] if os_doc["hasCommands"] else ["No OS-specific command sections detected."]
            note = "These OS-specific output snippets were detected after OS-specific command sections."
        lab_sections = [
            {
                "type": "bullets",
                "title": "Command outputs found",
                "note": note,
                "items": found_items,
            },
        ]
        missing_items = os_doc["missingOutputForCommandOs"]
        missing_section = build_bullet_section(
            "Add output snippets",
            missing_items,
            tone="attention" if missing_items and not os_doc.get("commonOutputForAllOs") else "ok",
            note="These output variants are still missing only when the README does not already declare one shared output flow for all OSes.",
        )
        if missing_section:
            lab_sections.append(missing_section)
        add_lab_section(sections, lab, lab_sections)
    return {
        "type": "sections",
        "title": "OS-specific output coverage",
        "note": "When commands are documented, the README should either show one shared output snippet for all OSes or provide matching output for each OS-specific command.",
        "sections": sections,
    }


def build_shell_console_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        ok = lab["readme"]["allCommandBlocksUseExecutableSyntax"]
        sections.append(
            {
                "type": "sections",
                "title": lab["name"],
                "href": lab["href"],
                "sections": [
                    {
                        "type": "bullets",
                        "title": "Documented command sections",
                        "items": [str(lab["readme"]["shellConsoleBlockCount"])],
                    },
                    {
                        "type": "bullets",
                        "title": "shell fence check",
                        "tone": "ok" if ok else "attention",
                        "items": [
                            "All command sections use ```shell``` fenced blocks."
                            if ok
                            else "Some command sections do not use ```shell``` fenced blocks."
                        ],
                    },
                ],
            }
        )
    return {
        "type": "sections",
        "title": "shell fence coverage",
        "note": "Use ```shell``` for every documented command block.",
        "sections": sections,
    }


def build_command_output_fencing_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        os_doc = lab["readme"]["osDocumentation"]
        command_fence_violations = os_doc.get("commandFenceViolations", [])
        output_fence_violations = os_doc.get("outputFenceViolations", [])
        missing_output_pairs = os_doc.get("missingOutputPairs", [])

        lab_sections: list[dict[str, Any] | None] = [
            build_snippet_table_section(
                "Non-shell command fences",
                command_fence_violations,
                ["Line", "Section", "Command fence", "Command snippet"],
                lambda item: [item["line"], item["heading"], f"```{item['commandFence']}```", item["command"]],
            ),
            build_snippet_table_section(
                "Non-terminaloutput output fences",
                output_fence_violations,
                ["Line", "Section", "Command snippet", "Output fence", "Output snippet"],
                lambda item: [item["line"], item["heading"], item["command"], f"```{item['outputFence']}```", item["output"]],
            ),
            build_snippet_table_section(
                "Missing same-section command/output pairing",
                missing_output_pairs,
                ["Line", "Section", "Command fence", "Command snippet", "Expected output"],
                lambda item: [item["line"], item["heading"], f"```{item['commandFence']}```", item["command"], item["output"]],
            ),
        ]
        issues_present = bool(command_fence_violations or output_fence_violations or missing_output_pairs)
        add_action_section(
            lab_sections,  # type: ignore[arg-type]
            issues_present,
            [
                "Use ```shell``` for every documented command block.",
                "Place a ```terminaloutput``` block immediately after each command in the same section.",
            ],
        )
        add_lab_section(sections, lab, lab_sections)
    return {
        "type": "sections",
        "title": "Command and Output fencing validation",
        "note": "Commands must use ```shell```, outputs must use ```terminaloutput```, and each command must be followed by its output in the same section.",
        "sections": sections,
    }


def build_command_output_presence_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        missing = lab["readme"]["osDocumentation"]["commandsMissingOutput"]
        lab_sections = [
            build_bullet_section(
                "Commands missing output",
                missing,
                tone="attention",
                note="Each command section should be followed by a console output snippet.",
            ),
        ]
        add_action_section(lab_sections, missing, "Add a terminaloutput snippet immediately after each listed command section.")
        add_lab_section(sections, lab, lab_sections)
    return {
        "type": "sections",
        "title": "Command-output pairing",
        "note": "Readers should see the command first and the resulting console output immediately after it.",
        "sections": sections,
    }


def build_terminal_output_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        issues = lab["readme"]["osDocumentation"]["outputLanguageIssues"]
        lab_sections = [
            build_bullet_section(
                "Output fence issues",
                issues,
                tone="attention",
                note="Console output snippets should use ```terminaloutput``` fences.",
            ),
        ]
        add_action_section(lab_sections, issues, "Change the listed output snippets to ```terminaloutput``` fenced blocks.")
        add_lab_section(sections, lab, lab_sections)
    return {
        "type": "sections",
        "title": "terminaloutput fence coverage",
        "note": "Use ```terminaloutput``` for console output so commands and output stay visually distinct.",
        "sections": sections,
    }


def build_snippet_table_section(
    title: str,
    items: list[dict[str, str]],
    headers: list[str],
    row_builder: Any,
) -> dict[str, Any] | None:
    if not items:
        return None
    return {
        "type": "table",
        "title": title,
        "headers": headers,
        "rows": [row_builder(item) for item in items],
    }


def build_studio_component_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        has_studio = lab["readme"]["hasStudioComponent"]
        studio_signals = []
        if lab["readme"]["hasStudioSection"]:
            studio_signals.append("README includes a Studio heading.")
        if lab["setup"]["hasStudioProfile"]:
            studio_signals.append("README command flow references --profile studio.")
        lab_sections = [
            build_bullet_section(
                "Studio signals",
                studio_signals,
                tone="ok" if has_studio else "attention",
            ),
            {
                "type": "bullets",
                "title": "Status",
                "tone": "ok" if has_studio else "attention",
                "items": ["Studio component documented" if has_studio else "Studio component not documented"],
            },
        ]
        add_lab_section(sections, lab, lab_sections)
    return {
        "type": "sections",
        "title": "Studio component coverage",
        "note": "This row is informational: it shows whether the README documents a Studio section or Studio command flow for the lab.",
        "sections": sections,
    }


def build_video_link_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        video_links = lab["readme"]["videoLinks"]
        has_video_section = lab["readme"].get("hasOverviewVideoSection", False)

        # Skip URL validation for video links - just store them
        video_link_items = [
            f"{item['label']}: {item['target']}"
            for item in video_links
        ]

        # Check validation status
        if not has_video_section:
            # No video section exists - FAIL validation
            lab_sections = [
                {
                    "type": "bullets",
                    "title": "Overview video status",
                    "tone": "attention",
                    "items": ["No overview video section found in 'Why this lab matters'."],
                }
            ]
            # Add action section
            lab_sections.append({
                "type": "bullets",
                "title": "Action",
                "tone": "attention",
                "items": ["Add an '### Overview Video' section with a video link to the 'Why this lab matters' H2 section."],
            })
        elif len(video_links) == 0:
            # Video section exists but no video link found - FAIL
            lab_sections = [
                {
                    "type": "bullets",
                    "title": "Overview video status",
                    "tone": "attention",
                    "items": ["Overview Video section exists but no video link was found."],
                }
            ]
            # Add action section
            lab_sections.append({
                "type": "bullets",
                "title": "Action",
                "tone": "attention",
                "items": ["Add a video link to the 'Why this lab matters' > '### Overview Video' section."],
            })
        else:
            # Video section exists with link(s) - PASS
            lab_sections = [
                {
                    "type": "bullets",
                    "title": "Metadata policy",
                    "tone": "ok",
                    "items": ["Overview video is mandatory for all READMEs."],
                }
            ]

            # Show video links section
            if video_link_items:
                lab_sections.append(
                    build_bullet_section(
                        "Overview video links",
                        video_link_items,
                        tone="ok",
                        note="These overview video links were detected in the README.",
                    )
                )

        add_lab_section(sections, lab, lab_sections)
    return {
        "type": "sections",
        "title": "Overview video links",
        "note": "Overview video is mandatory for all READMEs. Add an '### Overview Video' section with a video link to 'Why this lab matters'.",
        "sections": sections,
    }


def build_artifact_details(labs: list[dict[str, Any]], label: str) -> dict[str, Any]:
    sections = []
    # Map artifact labels to expected report keys
    label_to_report_key = {
        "ctrf-report.json": "ctrf",
        "specmatic-report.html": "html",
    }
    report_key = label_to_report_key.get(label)

    for lab in labs:
        present = label in lab["artifacts"]["generatedLabels"]

        # Check if this artifact has expected_failure or expected set
        expected = False
        expected_failure = False
        if report_key:
            for phase in lab["phases"]:
                expected = expected or phase["expectedReports"][report_key]["expected"]
                expected_failure = expected_failure or phase["expectedReports"][report_key]["expected_failure"]

        # Build sections based on state
        if expected_failure:
            # Expected failure case
            if present:
                # Report was produced despite expected_failure - this is a problem
                lab_sections = [
                    {
                        "type": "bullets",
                        "title": "Status",
                        "tone": "attention",
                        "items": ["Produced (marked as expected failure)"],
                    },
                    {
                        "type": "bullets",
                        "title": "Issue",
                        "tone": "attention",
                        "items": [f"Report {label} was produced despite being marked as expected_failure. Remove the file or update metadata."],
                    },
                ]
            else:
                # Report not produced as expected - this is correct
                lab_sections = [
                    {
                        "type": "bullets",
                        "title": "Status",
                        "tone": "expected-failure",
                        "items": [
                            {
                                "html": "<span style='font-size: 1.2em; font-weight: 700; color: #ca8a04;'>&#33;</span> Expected Failure - report not produced as intended"
                            }
                        ],
                    },
                ]
        elif expected:
            # Normal expected case
            lab_sections = [
                {
                    "type": "bullets",
                    "title": "Status",
                    "tone": "ok" if present else "attention",
                    "items": ["Present" if present else "Missing"],
                },
            ]
            if not present:
                add_action_section(lab_sections, ["missing artifact"], f"Generate {label} for this lab output.")
        else:
            # Not required
            lab_sections = [
                {
                    "type": "bullets",
                    "title": "Status",
                    "tone": "ok",
                    "items": ["Not required (marked as optional in phase metadata)"],
                },
            ]

        sections.append({
            "type": "sections",
            "title": lab["name"],
            "href": lab["href"],
            "sections": lab_sections,
        })
    return {
        "type": "sections",
        "title": f"{label} coverage",
        "sections": sections,
    }


def build_lab_specific_h2_details(labs: list[dict[str, Any]], common_required_h2: list[str] | tuple[str, ...] | set[str]) -> dict[str, Any]:
    sections = []
    for lab in labs:
        extra_h2 = list(lab["readme"]["unexpectedH2"])
        lab_sections = [
            build_bullet_section(
                "Move to H3",
                extra_h2,
                tone="attention",
                note="These walkthrough sections are currently H2 headings and should be converted to H3.",
            ),
            build_bullet_section(
                "Allowed H2 exceptions",
                lab["readme"]["optionalH2"] + lab["readme"]["additionalH2"],
                tone="ok",
                note="These extra H2 sections are allowed by the shared schema or lab override.",
            ),
        ]
        add_lab_section(sections, lab, lab_sections)
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
        lab_sections = [
            build_bullet_section(
                "Additional artifacts",
                extra,
                tone="attention" if extra else "ok",
            ),
        ]
        add_lab_section(sections, lab, lab_sections)
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
        extra_sections = list(lab["readme"]["unexpectedH2"])
        h1_title = lab["readme"]["h1"] or ""
        h1_as_h2 = [title for title in actual_h2 if heading_matches(title, h1_title)] if h1_title else []
        missing_sections = [section for section in common_required_h2 if not any(heading_matches(actual, section) for actual in actual_h2)]
        incorrect_order_sections = []
        actual_positions = []
        for index, title in enumerate(actual_h2):
            matched = next((section for section in common_required_h2 if heading_matches(title, section)), None)
            if matched is not None:
                actual_positions.append((matched, index))
        previous_position = -1
        previous_expected_title = ""
        for section in common_required_h2:
            current = next((index for matched, index in actual_positions if heading_matches(matched, section)), None)
            if current is None:
                continue
            if current < previous_position:
                message = f"'{section}'"
                if previous_expected_title:
                    message += f" appears before '{previous_expected_title}'"
                incorrect_order_sections.append(message)
            else:
                previous_position = current
                previous_expected_title = section
        lab_section_list = [
            build_bullet_section(
                "Move to H3",
                extra_sections or h1_as_h2,
                tone="attention",
                note="These H2 sections are lab-specific walkthrough content and should move to H3.",
            ),
            build_bullet_section(
                "Allowed optional H2",
                lab["readme"]["optionalH2"] + lab["readme"]["additionalH2"],
                tone="ok",
                note="These H2 sections are allowed by the shared template or lab override.",
            ),
            build_bullet_section(
                "Add as H2",
                missing_sections,
                tone="attention",
                note="These shared H2 sections are missing and should be added at H2 level.",
            ),
            build_bullet_section(
                "Fix H2 order",
                incorrect_order_sections,
                tone="attention",
                note="These shared H2 sections appear out of sequence and should be reordered.",
            ),
        ]
        add_lab_section(lab_sections, lab, lab_section_list, note="These are the concrete README heading changes needed for this lab.")
    details_sections = [
        {
            "type": "bullets",
            "title": "Configured shared H2 sequence",
            "note": "These H2 sections should appear in this exact order after the H1 title.",
            "items": shared_scaffold,
        },
        *lab_sections,
    ]
    if lab_sections:
        details_sections.append({
            "type": "bullets",
            "title": "Action",
            "items": [
                "Keep the shared H2 sequence stable across labs.",
                "Move lab-specific walkthrough steps into H3 headings.",
            ],
        })
    return {
        "summary": [
            "Every compared README should use the configured H2 sequence after the H1 title.",
            "Any extra, unwanted, or out-of-sequence H2 section is treated as a failure.",
        ],
        "details": {
            "type": "sections",
            "title": "Configured shared H2 sequence and README differences",
            "note": "The shared H2 sequence is configurable in one place. Keep that sequence stable and move lab-specific walkthrough steps into H3 headings.",
            "sections": details_sections,
        },
    }

def build_test_count_consistency_profile(
    spec: Any,
    readme_doc: Any,
    snapshot: dict[str, Any] | None,
    *,
    expected_missing: bool = False,
    expected_missing_reason: str = "",
    expected_failure_mismatch: bool = False,
    expected_failure_mismatch_reason: str = "",
) -> dict[str, Any]:
    if not snapshot:
        return {
            "available": False,
            "consistent": True,
            "expectedMissing": expected_missing,
            "expectedMissingReason": expected_missing_reason,
            "expectedFailureMismatch": expected_failure_mismatch,
            "expectedFailureMismatchReason": expected_failure_mismatch_reason,
            "phases": [],
        }

    readme_summaries = extract_tests_run_summaries(readme_doc.body_text)
    report_phases = snapshot.get("phases", [])
    comparisons: list[dict[str, Any]] = []
    all_consistent = True
    snapshot_root = snapshot.get("root")
    spec_phases = list(getattr(spec, "phases", ()))
    for index, phase in enumerate(report_phases):
        phase_path = phase_artifact_root(snapshot_root, phase)
        console_summary = extract_phase_command_log_summary(phase_path) or extract_tests_run_summary(phase.get("consoleSnippet", ""))
        spec_phase = spec_phases[index] if index < len(spec_phases) else None
        readme_phase = readme_doc.phase_by_id(getattr(spec_phase, "readme_phase_id", None)) if getattr(readme_doc, "is_v2", False) else None
        selected_summary = (
            select_readme_summary_for_v2_phase(readme_phase)
            if readme_phase is not None
            else select_readme_summary_for_phase(readme_summaries, spec_phase, index)
        )
        readme_summary = selected_summary["summary"] if selected_summary else None
        readme_phase_name = readme_phase.title if readme_phase is not None else (selected_summary["label"] if selected_summary else None)
        expected_sources = expected_report_sources_for_phase(readme_doc, readme_phase)
        validates_counts = test_counts_for_phase(readme_phase)
        ctrf_summary = None
        html_summary = None
        if phase_path and phase_path.exists():
            ctrf_artifact = phase_path / "ctrf-report.json"
            if not ctrf_artifact.exists():
                ctrf_artifact = phase_path / "mcp" / "mcp_test_report.json"
            html_artifact = phase_path / "specmatic" / "test" / "html" / "index.html"
            if not html_artifact.exists():
                html_artifact = phase_path / "mcp" / "specmatic_report.html"
            if ctrf_artifact.exists():
                ctrf_summary = format_tests_run_summary_from_report_json(ctrf_artifact)
            if html_artifact.exists():
                html_summary = format_tests_run_summary_from_html(html_artifact)
        readme_counts = parse_tests_run_counts(readme_summary) if expected_sources["readme_summary"] else None
        console_counts = parse_tests_run_counts(console_summary) if expected_sources["console_summary"] else None
        ctrf_counts = ctrf_summary if expected_sources["ctrf"] else None
        html_counts = html_summary if expected_sources["html"] else None
        if expected_failure_mismatch:
            consistency_counts = [readme_counts, console_counts]
        else:
            consistency_counts = [readme_counts, console_counts, ctrf_counts, html_counts]
        present_counts = [item for item in consistency_counts if item is not None]
        expected_source_count = sum(1 for enabled in expected_sources.values() if enabled)
        comparable = validates_counts and len(present_counts) >= 2
        consistent = comparable and len({tuple(sorted(item.items())) for item in present_counts}) == 1

        totals_match = comparable and len({c["tests"] for c in present_counts}) == 1

        if expected_failure_mismatch and comparable and not consistent and totals_match:
            status = "partial-match"
        else:
            status = (
                "match"
                if consistent
                else "mismatch"
                if comparable
                else "expected-not-available"
                if expected_missing or not validates_counts or expected_source_count < 2
                else "not-available"
            )

        if comparable and status not in ("partial-match",):
            all_consistent = all_consistent and consistent
        comparisons.append(
            {
                "phase": getattr(spec_phase, "readme_summary_query", None) or readme_phase_name or phase.get("name", f"Phase {index + 1}"),
                "readmeCounts": readme_counts,
                "consoleCounts": console_counts,
                "ctrfCounts": ctrf_counts,
                "htmlCounts": html_counts,
                "consistent": consistent,
                "status": status,
                "expectedSources": expected_sources,
            }
        )

    return {
        "available": bool(snapshot),
        "consistent": all_consistent,
        "expectedMissing": expected_missing,
        "expectedMissingReason": expected_missing_reason,
        "expectedFailureMismatch": expected_failure_mismatch,
        "expectedFailureMismatchReason": expected_failure_mismatch_reason,
        "phases": comparisons,
    }


def select_readme_summary_for_v2_phase(readme_phase: Any) -> dict[str, str] | None:
    summaries = extract_tests_run_summaries(readme_phase.content)
    if not summaries:
        return None
    return {
        "label": readme_phase.title,
        "summary": summaries[0]["summary"],
    }


def expected_report_sources_for_phase(readme_doc: Any, readme_phase: Any) -> dict[str, bool]:
    # Only use global settings, ignore phase-level expected_reports
    return {
        "readme_summary": bool(readme_doc.metadata.get("reports", {}).get("readme_summary", True)),
        "console_summary": bool(readme_doc.metadata.get("reports", {}).get("console_summary", True)),
        "ctrf": bool(readme_doc.metadata.get("reports", {}).get("ctrf", True)),
        "html": bool(readme_doc.metadata.get("reports", {}).get("html", True)),
    }


def test_counts_for_phase(readme_phase: Any) -> bool:
    # Always validate test counts - no longer configurable per phase
    return True


def select_readme_summary_for_phase(
    readme_summaries: list[dict[str, str]],
    phase_spec: Any,
    phase_index: int,
) -> dict[str, str] | None:
    query = getattr(phase_spec, "readme_summary_query", None)
    if query:
        normalized_query = query.strip().lower()
        for summary in readme_summaries:
            label = (summary.get("label") or "").strip().lower()
            heading = (summary.get("heading") or "").strip().lower()
            heading_path = (summary.get("headingPath") or "").strip().lower()
            if (
                normalized_query == label
                or normalized_query == heading
                or normalized_query in label
                or normalized_query in heading
                or normalized_query in heading_path
            ):
                return summary
    if phase_index < len(readme_summaries):
        return readme_summaries[phase_index]
    return None


def load_lab_report_snapshot(lab_name: str) -> dict[str, Any] | None:
    snapshot_dir = ROOT / "output" / "labs-output" / f"{lab_name}-output"
    report_path = snapshot_dir / "report.json"
    if not report_path.exists():
        return None
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["root"] = snapshot_dir
    return report


def extract_tests_run_summaries(readme_text: str) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    headings = extract_headings(readme_text)
    matches = (
        list(TESTS_RUN_SUMMARY_RE.finditer(readme_text))
        + list(EXAMPLES_SUMMARY_RE.finditer(readme_text))
        + list(MCP_SUMMARY_RE.finditer(readme_text))
    )
    matches.sort(key=lambda match: match.start())
    for match in matches:
        line = line_number_for_index(readme_text, match.start())
        heading = heading_before_line(headings, line)
        if match.re is MCP_SUMMARY_RE:
            summary_text = format_mcp_summary_match(match)
        else:
            summary_text = match.group(0)
        summaries.append(
            {
                "heading": heading["text"] if heading else "",
                "headingPath": heading_path_before_line(headings, line),
                "label": summary_label_before_line(readme_text, line, heading["text"] if heading else ""),
                "summary": summary_text,
            }
        )
    return summaries


def heading_path_before_line(headings: list[dict[str, Any]], line_number: int) -> str:
    path: list[dict[str, Any]] = []
    for heading in headings:
        if heading["line"] > line_number:
            break
        while path and path[-1]["level"] >= heading["level"]:
            path.pop()
        path.append(heading)
    return " > ".join(item["text"] for item in path)


def summary_label_before_line(readme_text: str, line_number: int, fallback_heading: str) -> str:
    lines = readme_text.splitlines()
    start_index = max(0, line_number - 2)
    for index in range(start_index, -1, -1):
        raw = lines[index].strip()
        if not raw:
            continue
        if raw.startswith("```"):
            continue
        if raw.startswith("#"):
            return raw.lstrip("#").strip()
        if re.match(r"^\d+\.\s+", raw):
            return raw
        if re.match(r"^[-*]\s+", raw):
            return raw[2:].strip()
        if raw.endswith(":") or raw.endswith("."):
            return raw.rstrip(":")
    return fallback_heading


def extract_tests_run_summary(console_output: str) -> str | None:
    clean_output = normalize_summary_source_text(ANSI_ESCAPE_RE.sub("", console_output))
    tests_matches = TESTS_RUN_SUMMARY_RE.findall(clean_output)
    if tests_matches:
        return tests_matches[-1]
    example_matches = EXAMPLES_SUMMARY_RE.finditer(clean_output)
    last_match = None
    for last_match in example_matches:
        pass
    if last_match:
        return last_match.group(0)
    mcp_matches = MCP_SUMMARY_RE.finditer(clean_output)
    last_match = None
    for last_match in mcp_matches:
        pass
    if not last_match:
        return None
    return format_mcp_summary_match(last_match)


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
    clean_summary = normalize_summary_source_text(ANSI_ESCAPE_RE.sub("", summary_text))
    match = re.search(
        r"Tests run:\s*(?P<tests>\d+),\s*Successes:\s*(?P<successes>\d+),\s*Failures:\s*(?P<failures>\d+)(?:,\s*Errors:\s*(?P<errors>\d+))?",
        clean_summary,
    )
    if not match:
        example_match = EXAMPLES_SUMMARY_RE.search(clean_summary)
        if example_match:
            return {
                "tests": int(example_match.group("tests")),
                "passed": int(example_match.group("passed")),
                "failed": int(example_match.group("failed")),
                "skipped": 0,
                "other": 0,
            }
        mcp_match = MCP_SUMMARY_RE.search(clean_summary)
        if not mcp_match:
            return None
        return {
            "tests": int(mcp_match.group("tests")),
            "passed": int(mcp_match.group("passed")),
            "failed": int(mcp_match.group("failed")),
            "skipped": 0,
            "other": 0,
        }
    return {
        "tests": int(match.group("tests")),
        "passed": int(match.group("successes")),
        "failed": int(match.group("failures")),
        "skipped": 0,
        "other": int(match.group("errors") or 0),
    }


def format_tests_run_counts(counts: dict[str, int] | None) -> str:
    if not counts:
        return "not-available"
    return (
        f"T={counts['tests']}\n"
        f"P={counts['passed']}\n"
        f"F={counts['failed']}\n"
        f"S={counts['skipped']}\n"
        f"O={counts['other']}"
    )


def count_cell_text(counts: dict[str, int] | None) -> str:
    return format_tests_run_counts(counts) if counts else "not-available"


def choose_reference_counts(item: dict[str, Any]) -> dict[str, int] | None:
    candidates = [
        item.get("readmeCounts"),
        item.get("consoleCounts"),
        item.get("ctrfCounts"),
        item.get("htmlCounts"),
    ]
    present = [counts for counts in candidates if counts is not None]
    if not present:
        return None
    tuples = [tuple(sorted(counts.items())) for counts in present]
    most_common, count = Counter(tuples).most_common(1)[0]
    if count >= 2:
        return dict(most_common)
    return present[0]


def build_count_cell(counts: dict[str, int] | None, comparison_item: dict[str, Any]) -> dict[str, str]:
    reference = choose_reference_counts(comparison_item)
    text = count_cell_text(counts)
    count_legend = "T = Total\nP = Passed\nF = Failed\nS = Skipped\nO = Other"
    phase_status = comparison_item.get("status", "")
    if counts is None:
        if phase_status == "partial-match" and not comparison_item.get("expectedSources", {}).get("ctrf", True):
            return {
                "text": "skipped",
                "className": "matrix-tooltip-count ok",
                "title": "Count data for this source was skipped (expected_failure_mismatch is enabled).",
                "ariaLabel": "Count data for this source was skipped.",
            }
        return {
            "text": text,
            "className": "matrix-tooltip-count na",
            "title": "No count data was available for this source.",
            "ariaLabel": "No count data was available for this source.",
        }
    if reference is None or counts == reference:
        return {
            "text": text,
            "className": "matrix-tooltip-count ok",
            "title": count_legend,
            "ariaLabel": count_legend,
        }
    if phase_status == "partial-match":
        return {
            "text": text,
            "className": "matrix-tooltip-count partial",
            "title": f"Total matches but pass/fail counts differ (expected failure mismatch).\n\n{count_legend}",
            "ariaLabel": f"Total matches but pass/fail counts differ. {count_legend}",
        }
    return {
        "text": text,
        "className": "matrix-tooltip-count mismatch",
        "title": f"This count block does not match the other available sources.\n\n{count_legend}",
        "ariaLabel": f"This count block does not match the other available sources. {count_legend}",
    }


def format_tests_run_summary_from_report_json(report_path: Path) -> dict[str, int] | None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if isinstance(report, list):
        passed = sum(1 for item in report if item.get("verdict") == "PASSED")
        failed = sum(1 for item in report if item.get("verdict") == "FAILED")
        return {
            "tests": len(report),
            "passed": passed,
            "failed": failed,
            "skipped": 0,
            "other": 0,
        }
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
        mcp_match = MCP_SUMMARY_RE.search(html_text)
        if not mcp_match:
            return None
        return {
            "tests": int(mcp_match.group("tests")),
            "passed": int(mcp_match.group("passed")),
            "failed": int(mcp_match.group("failed")),
            "skipped": 0,
            "other": 0,
        }
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


def format_mcp_summary_match(match: re.Match[str]) -> str:
    prefix = f"{match.group('prefix').strip()}\n" if match.group("prefix") else ""
    return (
        f"{prefix}Total: {match.group('tests')}\n"
        f"Passed: {match.group('passed')}\n"
        f"Failed: {match.group('failed')}"
    )


def normalize_summary_source_text(text: str) -> str:
    return re.sub(
        r"^[^\n]*\|\s*(?=(?:Total:|Passed:|Failed:|Overall Success Rate:|SUMMARY:))",
        "",
        text,
        flags=re.MULTILINE,
    )


def build_test_count_consistency_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    sections = []
    verdict_items = []
    for lab in labs:
        comparisons = lab["testCountConsistency"].get("phases", [])
        expected_missing_reason = lab["testCountConsistency"].get("expectedMissingReason", "")
        mismatch_phases = [item["phase"] for item in comparisons if item.get("status") == "mismatch"]
        matched_phases = [item["phase"] for item in comparisons if item.get("status") == "match"]
        partial_match_phases = [item["phase"] for item in comparisons if item.get("status") == "partial-match"]
        unavailable_phases = [item["phase"] for item in comparisons if item.get("status") == "not-available"]
        expected_unavailable_phases = [item["phase"] for item in comparisons if item.get("status") == "expected-not-available"]
        if mismatch_phases:
            verdict_items.append(f"{lab['name']}: mismatches in {', '.join(mismatch_phases)}.")
        elif partial_match_phases:
            reason = lab["testCountConsistency"].get("expectedFailureMismatchReason") or "Pass/fail counts differ due to known limitations."
            verdict_items.append(f"{lab['name']}: total test count matches, pass/fail counts differ in {', '.join(partial_match_phases)}. {reason}")
        elif matched_phases:
            verdict_items.append(f"{lab['name']}: matching counts where data is available.")
        elif expected_unavailable_phases:
            reason = expected_missing_reason or "This lab does not publish test-count summaries."
            verdict_items.append(f"{lab['name']}: count data is expected to be not available. **{reason}**")
        elif unavailable_phases:
            verdict_items.append(f"{lab['name']}: count data is not-available for comparison.")
        else:
            verdict_items.append(f"{lab['name']}: no phase data was available to validate.")
        table_note = "Each row compares the README summary, console output, CTRF JSON, and Specmatic HTML for one phase. Missing sources are shown as not-available. When a lab intentionally does not emit count summaries, the row is marked as expected."
        if expected_missing_reason:
            table_note = f"{table_note}\n\nReason: **{expected_missing_reason}**"
        sections.append(
            {
                "type": "table",
                "title": lab["name"],
                "href": lab["href"],
                "note": table_note,
                "headers": ["Phase", "README", "Console", "CTRF", "HTML", "Status"],
                "rows": [
                    [
                        item["phase"],
                        build_count_cell(item.get("readmeCounts"), item),
                        build_count_cell(item.get("consoleCounts"), item),
                        build_count_cell(item.get("ctrfCounts"), item),
                        build_count_cell(item.get("htmlCounts"), item),
                        format_count_status(item.get("status", "not-available")),
                    ]
                    for item in comparisons
                ] or [["(no phase data found)", count_cell_text(None), count_cell_text(None), count_cell_text(None), count_cell_text(None), "Not available"]],
            }
        )
    return {
        "type": "sections",
        "title": "Test count consistency",
        "note": "The README, console, CTRF JSON, and Specmatic HTML should describe the same run wherever those sources are available.",
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


def build_required_phase_details(labs: list[dict[str, Any]]) -> dict[str, Any]:
    """Build details for required phases validation.

    Shows which phases are required vs actual for each lab.

    Args:
        labs: List of lab profiles

    Returns:
        Dictionary with title, note, and sections for each lab
    """
    sections = []

    for lab in labs:
        required = lab.get("phaseRequirements", {}).get("requiredKinds", [])
        actual = lab.get("phaseRequirements", {}).get("actualKinds", [])
        missing = [k for k in required if k not in actual]

        lab_sections = [
            build_bullet_section(
                "Required phases",
                required if required else ["(none - defaults to baseline, final)"],
                tone="ok",
            ),
            build_bullet_section(
                "Missing phases",
                missing,
                tone="attention",
            ) if missing else None,
        ]
        add_lab_section(sections, lab, lab_sections)

    return {
        "title": "Required phase coverage",
        "note": "Baseline and final are always required. Additional phases can be marked as required in the lab configuration.",
        "sections": sections,
    }


def format_count_status(status: str) -> str:
    if status == "match":
        return "Match"
    if status == "mismatch":
        return "Mismatch"
    if status == "expected-not-available":
        return "Expected"
    if status == "partial-match":
        return "Partial Mismatch"
    return "Not available"


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
