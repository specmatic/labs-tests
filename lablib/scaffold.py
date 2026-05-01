from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Callable

from lablib.command_runner import CommandResult, run_command
from lablib.readme_expectations import (
    EXECUTABLE_COMMAND_FENCE_LANGUAGES,
    OUTPUT_FENCE_LANGUAGE,
    optional_h2_titles,
    unexpected_h2_titles_for_lab,
)
from lablib.readme_schema import (
    ALLOWED_PHASE_KINDS,
    BASELINE_PHASE,
    DEFAULT_REQUIRED_PHASES,
    FINAL_PHASE,
    V2_SCHEMA_VERSION,
    command_fence_languages,
    expected_h2_titles_for_document,
    parse_readme_document,
    parse_required_implementation_phases,
    phase_sequence_is_valid,
    validate_external_link,
    validate_internal_link,
)
from lablib.reporting import build_report, write_html, write_json
from lablib.workspace_setup import run_setup


ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
CONSOLE_COVERAGE_ROW_RE = re.compile(
    r"^\|\s*(?P<coverage>\d+%)\s+\|\s*(?P<path>/[^|]+?)\s+\|\s*(?P<method>[A-Z]+)\s+\|\s*(?P<response>\d+)\s+\|\s*(?P<count>\d+)\s+\|\s*(?P<status>[^|]+?)\s+\|$"
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
FENCED_CODE_BLOCK_RE = re.compile(r"```(?P<lang>[a-zA-Z0-9_-]+)?\s*\n(?P<body>.*?)```", re.DOTALL | re.MULTILINE)
HTML_COMMENT_RE = re.compile(r"<!--(?P<body>.*?)-->", re.DOTALL)
SHELL_COMMAND_PREFIXES_RE = re.compile(r"^(docker|python|python3|chmod|git|curl|cd|npm|pnpm|yarn|make|bash|sh)\b")
PATH_LIKE_RE = re.compile(r"([A-Za-z]:\\[^\s`]+|(?:\./|\.\./|/Users/|/usr/|/tmp/|/var/|/home/|/opt/|/etc/)[^\s`]+)")
TESTS_RUN_SUMMARY_RE = re.compile(r"Tests run:\s*\d+,\s*Successes:\s*\d+,\s*Failures:\s*\d+(?:,\s*Errors:\s*\d+)?")
EXAMPLES_SUMMARY_RE = re.compile(r"Examples:\s*(?P<passed>\d+)\s+passed\s+and\s+(?P<failed>\d+)\s+failed\s+out of\s+(?P<tests>\d+)\s+total", re.IGNORECASE)
MCP_SUMMARY_RE = re.compile(
    r"(?:(?P<prefix>SUMMARY:)\s*)?Total:\s*(?P<tests>\d+)\s*(?:\||\n|\r\n)\s*Passed:\s*(?P<passed>\d+)\s*(?:\||\n|\r\n)\s*Failed:\s*(?P<failed>\d+)",
    re.IGNORECASE,
)
CONSOLE_FENCE_LANGUAGES = set(EXECUTABLE_COMMAND_FENCE_LANGUAGES)
TERMINAL_OUTPUT_FENCE_LANGUAGE = OUTPUT_FENCE_LANGUAGE
IGNORED_ARTIFACT_LABELS = {"html", "coverage_report.json", "stub_usage_report.json"}
REPORT_ARTIFACT_LABELS = {"ctrf-report.json", "specmatic-report.html"}
EXTERNAL_LINK_CACHE: dict[str, tuple[bool, str]] = {}


@dataclass
class ArtifactSpec:
    label: str
    source_relpath: str
    target_relpath: str
    kind: str = "file"
    expected_top_level_keys: tuple[str, ...] = ()
    expected_markers: tuple[str, ...] = ()


@dataclass
class PhaseSpec:
    name: str
    description: str
    expected_exit_code: int
    readme_phase_id: str | None = None
    command: list[str] | None = None
    output_dir_name: str | None = None
    expected_console_phrases: tuple[str, ...] = ()
    readme_assertions: tuple[dict[str, str], ...] = ()
    fix_summary: tuple[str, ...] = ()
    file_transforms: dict[str, Callable[[str], str]] = field(default_factory=dict)
    include_readme_structure_checks: bool = False
    extra_assertions: Callable[["ValidationContext"], list[dict[str, Any]]] | None = None
    artifact_specs: tuple[ArtifactSpec, ...] = ()
    notes: tuple[str, ...] = ()
    readme_summary_query: str | None = None
    command_timeout_seconds: float | None = None
    command_idle_timeout_seconds: float | None = None


@dataclass
class LabSpec:
    name: str
    description: str
    root: Path
    upstream_lab: Path
    files: dict[str, Path]
    readme_path: Path
    output_dir: Path
    command: list[str]
    phases: tuple[PhaseSpec, ...]
    command_env: dict[str, str] = field(default_factory=dict)
    common_artifact_specs: tuple[ArtifactSpec, ...] = ()
    setup_failure_message: str = (
        "Workspace setup failed. See output/consolidated-report/setup-output.json from the root setup command for details."
    )
    clear_reports: Callable[["LabSpec"], None] | None = None
    post_phase_cleanup: Callable[["LabSpec"], None] | None = None
    runtime_warnings: tuple[str, ...] = ()
    known_limitations: tuple[str, ...] = ()
    intentional_differences: tuple[str, ...] = ()
    expected_missing_test_counts: bool = False
    expected_missing_test_counts_reason: str = ""
    expected_failure_mismatch: bool = False
    expected_failure_mismatch_reason: str = ""


@dataclass
class ValidationContext:
    lab: LabSpec
    phase: PhaseSpec
    target_dir: Path
    command_result: CommandResult
    executed_command: list[str]
    readme_text: str
    readme_doc: Any
    artifacts: dict[str, dict[str, Any]]
    original_files: dict[str, str | None]


def add_standard_lab_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--refresh-report",
        dest="refresh_report",
        action="store_true",
        help="Rebuild report.json and report.html from the existing captured artifacts without rerunning the lab.",
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip the root-level workspace setup stage.",
    )
    parser.add_argument(
        "--refresh-labs",
        action="store_true",
        help="Destructively reset ../labs to the latest state on the selected branch before running this lab.",
    )
    parser.add_argument(
        "--labs-branch",
        default="main",
        help="Branch of ../labs to use with --refresh-labs. Defaults to main.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required with --refresh-labs when ../labs has local changes. Discards tracked and untracked changes.",
    )
    return parser


def run_lab(spec: LabSpec, args: argparse.Namespace) -> int:
    if not spec.readme_path.exists():
        raise FileNotFoundError(
            f"Missing upstream README for lab '{spec.name}': {spec.readme_path}. "
            "This usually means the sibling ../labs checkout is on a branch that does not contain the expected README. "
            "Action required: switch ../labs to the correct branch or rerun with --labs-branch dynamic-labs."
        )
    readme_text = spec.readme_path.read_text(encoding="utf-8")
    readme_doc = parse_readme_document(readme_text)
    original_files = {
        alias: path.read_text(encoding="utf-8") if path.exists() else None
        for alias, path in spec.files.items()
    }
    if not args.refresh_report:
        clean_lab_output_dir(spec)
    spec.output_dir.mkdir(parents=True, exist_ok=True)

    if args.refresh_report:
        print("Refreshing the report from existing captured artifacts...")
        phases = rebuild_phases_from_artifacts(spec, readme_text, readme_doc, original_files)
    else:
        phases = []
        try:
            if not args.skip_setup:
                print("Running workspace setup before lab execution...")
                setup_result = run_setup(
                    stream_output=True,
                    refresh_labs=args.refresh_labs,
                    target_branch=args.labs_branch,
                    force=args.force,
                )
                if setup_result.status != "passed":
                    print(spec.setup_failure_message)
                    return 1

            run_best_effort_runtime_cleanup(spec, "before lab execution")
            for phase in spec.phases:
                print(f"Preparing {phase.name.lower()} lab state...")
                apply_phase_files(spec, phase, original_files)
                phase_result = execute_phase(spec, phase, readme_text, readme_doc, original_files)
                phases.append(phase_result)
        finally:
            restore_original_files(spec, original_files)
            run_best_effort_runtime_cleanup(spec, "after lab execution")

    report = build_report(
        lab_name=spec.name,
        description=spec.description,
        lab_path=spec.upstream_lab,
        spec_path=next(iter(spec.files.values())),
        readme_path=spec.readme_path,
        output_path=spec.output_dir,
        phases=phases,
    )
    write_json(spec.output_dir / "report.json", report)
    write_html(spec.output_dir / "report.html", report)
    snapshot_lab_output(spec)
    print(f"Wrote JSON report to {spec.output_dir / 'report.json'}")
    print(f"Wrote HTML report to {spec.output_dir / 'report.html'}")
    return 0 if report["status"] == "passed" else 1


def clean_lab_output_dir(spec: LabSpec) -> None:
    if spec.output_dir.exists():
        shutil.rmtree(spec.output_dir, ignore_errors=True)


def run_best_effort_runtime_cleanup(spec: LabSpec, when: str) -> None:
    if spec.post_phase_cleanup is None:
        return
    print(f"Running runtime cleanup {when}...", flush=True)
    try:
        spec.post_phase_cleanup(spec)
    except Exception as exc:
        print(
            f"[warning] Runtime cleanup {when} failed for {spec.name}: {exc}. "
            "Impact: stale containers, networks, or volumes may affect later phases or labs. "
            "Action required: inspect the Docker state and rerun the lab if needed.",
            flush=True,
        )


def snapshot_lab_output(spec: LabSpec) -> Path:
    target_dir = spec.root / "output" / "labs-output" / f"{spec.name}-output"
    legacy_dir = spec.root / "output" / f"{spec.name}-output"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    if spec.output_dir.exists():
        shutil.copytree(spec.output_dir, target_dir)
        rewrite_consolidated_report_link(target_dir / "report.html", spec.root)
    if legacy_dir.exists():
        shutil.rmtree(legacy_dir)
    return target_dir


def rewrite_consolidated_report_link(report_path: Path, root: Path) -> None:
    if not report_path.exists():
        return
    text = report_path.read_text(encoding="utf-8")
    source_hrefs = (
        "../../output/consolidated-report/consolidated-report.html",
        "../../output/consolidated-report/report.html",
    )
    target_href = os.path.relpath(root / "output" / "consolidated-report" / "consolidated-report.html", start=report_path.parent)
    target_href = target_href.replace("output/", "", 1) if target_href.startswith("output/") else target_href
    for source_href in source_hrefs:
        if source_href in text:
            report_path.write_text(text.replace(source_href, target_href), encoding="utf-8")
            return


def docker_compose_down(spec: LabSpec, *compose_args: str) -> CommandResult:
    return run_command(["docker", "compose", *compose_args], spec.upstream_lab)


def clear_docker_owned_build_dir(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")
    build_dir = spec.upstream_lab / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)


def execute_phase(
    spec: LabSpec,
    phase: PhaseSpec,
    readme_text: str,
    readme_doc: Any,
    original_files: dict[str, str | None],
) -> dict[str, Any]:
    target_dir = spec.output_dir / phase_dir_name(phase)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if spec.clear_reports is not None:
        spec.clear_reports(spec)

    print(f"{phase.name}: starting verification...")
    phase_command = phase.command or spec.command
    result = run_command(
        phase_command,
        spec.upstream_lab,
        env=spec.command_env,
        stream_output=True,
        stream_prefix=f"[{phase_dir_name(phase)}]",
        timeout_seconds=phase.command_timeout_seconds,
        idle_timeout_seconds=phase.command_idle_timeout_seconds,
    )
    try:
        artifacts = capture_artifacts(spec, phase, target_dir)
    except FileNotFoundError as exc:
        write_text(target_dir / "command.log", result.combined_output)
        command_info = {
            "exitCode": result.exit_code,
            "durationSeconds": round(result.duration_seconds, 2),
        }
        phase_result = build_missing_artifact_phase_result(spec, phase, target_dir, command_info, exc)
        return phase_result
    finally:
        if spec.post_phase_cleanup is not None:
            spec.post_phase_cleanup(spec)

    write_text(target_dir / "command.log", result.combined_output)
    artifacts["command.log"] = {"path": target_dir / "command.log", "text": result.combined_output, "kind": "text"}
    context = ValidationContext(
        lab=spec,
        phase=phase,
        target_dir=target_dir,
        command_result=result,
        executed_command=phase_command,
        readme_text=readme_text,
        readme_doc=readme_doc,
        artifacts=artifacts,
        original_files=original_files,
    )
    return build_phase_result(context)


def rebuild_phases_from_artifacts(spec: LabSpec, readme_text: str, readme_doc: Any, original_files: dict[str, str | None]) -> list[dict[str, Any]]:
    previous_commands = load_previous_phase_commands(spec.output_dir)
    phases: list[dict[str, Any]] = []
    for phase in spec.phases:
        target_dir = spec.output_dir / phase_dir_name(phase)
        command_info = previous_commands.get(phase.name, {})
        try:
            ensure_artifact_set_exists(spec, phase, target_dir)
            artifacts = load_copied_artifacts(spec, phase, target_dir)
            command_output = (target_dir / "command.log").read_text(encoding="utf-8")
            result = CommandResult(
                command=phase.command or spec.command,
                cwd=str(spec.upstream_lab),
                exit_code=command_info.get("exitCode", phase.expected_exit_code),
                stdout=command_output,
                stderr="",
                started_at="",
                finished_at="",
                duration_seconds=command_info.get("durationSeconds", 0.0),
            )
            artifacts["command.log"] = {"path": target_dir / "command.log", "text": command_output, "kind": "text"}
            context = ValidationContext(
                lab=spec,
                phase=phase,
                target_dir=target_dir,
                command_result=result,
                executed_command=phase.command or spec.command,
                readme_text=readme_text,
                readme_doc=readme_doc,
                artifacts=artifacts,
                original_files=original_files,
            )
            phases.append(build_phase_result(context))
        except FileNotFoundError as exc:
            phases.append(build_missing_artifact_phase_result(spec, phase, target_dir, command_info, exc))
    return phases


def build_phase_result(context: ValidationContext) -> dict[str, Any]:
    spec = context.lab
    phase = context.phase
    command_result = context.command_result
    readme_phase = context.readme_doc.phase_by_id(phase.readme_phase_id) if getattr(context.readme_doc, "is_v2", False) else None
    assertions: list[dict[str, Any]] = []

    assertions.append(
        assert_equal(
            command_result.exit_code,
            phase.expected_exit_code,
            f"Command exit code was {phase.expected_exit_code} as expected.",
            f"Expected exit code {phase.expected_exit_code}, got {command_result.exit_code}.",
            category="command",
            details=[
                detail("Expected exit code", phase.expected_exit_code),
                detail("Actual exit code", command_result.exit_code),
                detail("Command", " ".join(context.executed_command)),
            ],
        )
    )
    if command_result.timed_out:
        assertions.append(
            assert_condition(
                False,
                "Command completed within the allowed timeout.",
                f"Command timed out. {command_result.timeout_reason}",
                category="command",
                details=[
                    detail("Command", " ".join(spec.command)),
                    detail("Executed command", " ".join(context.executed_command)),
                    detail("Timeout reason", command_result.timeout_reason),
                    detail("Exit code", command_result.exit_code),
                ],
            )
        )

    assertions.extend(build_artifact_assertions(context))

    for phrase in phase.expected_console_phrases:
        assertions.append(
            assert_condition(
                phrase in command_result.combined_output,
                f"Console output contained '{phrase}'.",
                f"Console output did not contain '{phrase}'.",
                category="console",
                details=[
                    detail("Expected phrase", phrase),
                    detail("Console excerpt", extract_context(command_result.combined_output, phrase)),
                ],
            )
        )

    if phase.extra_assertions is not None:
        assertions.extend(filter_relevant_lab_assertions(phase.extra_assertions(context), context))

    assertions.extend(evaluate_readme_assertions(context))
    assertions.extend(evaluate_v2_phase_readme_alignment(context))
    assertions.extend(evaluate_readme_console_structure(context))
    assertions.extend(evaluate_readme_os_documentation(context))
    assertions.extend(evaluate_runtime_summary_drift(context))
    if phase.include_readme_structure_checks:
        assertions.extend(validate_readme_structure(context))
        assertions.extend(evaluate_readme_links(context))
    assertions = apply_readme_annotation_overrides(assertions, context.readme_text)

    phase_status = "passed" if all(item["status"] != "failed" for item in assertions) else "failed"
    return {
        "name": phase.name,
        "description": phase.description,
        "status": phase_status,
        "readmePhase": {
            "id": phase.readme_phase_id,
            "title": readme_phase.title if readme_phase is not None else "",
        },
        "command": {
            "display": " ".join(context.executed_command),
            "exitCode": command_result.exit_code,
            "durationSeconds": round(command_result.duration_seconds, 2),
        },
        "assertions": assertions,
        "artifacts": build_artifact_links(spec, phase, context.target_dir),
        "consoleSnippet": shorten_console_output(command_result),
        "fixSummary": list(phase.fix_summary),
        "warnings": build_warning_messages(spec, phase),
    }


def build_artifact_links(spec: LabSpec, phase: PhaseSpec, target_dir: Path) -> list[dict[str, str]]:
    links = [{"label": "command.log", "href": f"{target_dir.name}/command.log"}]
    for artifact in all_artifact_specs(spec, phase):
        links.append({"label": artifact.label, "href": f"{target_dir.name}/{artifact.target_relpath}"})
    return links


def build_artifact_assertions(context: ValidationContext) -> list[dict[str, Any]]:
    assertions: list[dict[str, Any]] = []
    command_log = context.target_dir / "command.log"
    assertions.append(
        assert_condition(
            command_log.exists(),
            "Command log was written into the lab output folder.",
            "Command log is missing from the lab output folder.",
            category="artifacts",
            details=[
                detail("Expected log path", command_log),
                detail("Exists", command_log.exists()),
            ],
        )
    )
    assertions.append(
        assert_condition(
            bool(context.command_result.combined_output.strip()),
            "Command log contained captured console output.",
            "Command log did not contain any captured console output.",
            category="artifacts",
            details=[
                detail("Output length", len(context.command_result.combined_output)),
            ],
        )
    )

    for artifact in all_artifact_specs(context.lab, context.phase):
        loaded = context.artifacts[artifact.label]
        artifact_path = loaded["path"]
        if loaded.get("origin") == "source":
            continue
        assertions.append(
            assert_condition(
                artifact_path.exists(),
                f"{artifact.label} was copied into the lab output folder.",
                f"{artifact.label} is missing from the lab output folder.",
                category="artifacts",
                details=[
                    detail("Expected artifact path", artifact_path),
                    detail("Exists", artifact_path.exists()),
                ],
            )
        )
        if artifact.label == "specmatic-report.html":
            assertions.append(
                assert_condition(
                    artifact_path.exists(),
                    "Specmatic HTML report was generated.",
                    "Specmatic HTML report was not generated.",
                    category="report",
                    details=[
                        detail("Artifact label", artifact.label),
                        detail("Expected artifact path", artifact_path),
                        detail("Exists", artifact_path.exists()),
                    ],
                )
            )
        if artifact.kind == "json":
            assertions.append(
                assert_condition(
                    "json" in loaded,
                    f"{artifact.label} was valid JSON.",
                    f"{artifact.label} could not be parsed as JSON.",
                    category="artifacts",
                    details=[detail("Artifact path", artifact_path)],
                )
            )
            for key in artifact.expected_top_level_keys:
                assertions.append(
                    assert_condition(
                        key in loaded["json"],
                        f"{artifact.label} contained top-level key '{key}'.",
                        f"{artifact.label} is missing top-level key '{key}'.",
                        category="artifacts",
                        details=[detail("Artifact path", artifact_path)],
                    )
                )
        if artifact.kind in {"html", "text"}:
            assertions.append(
                assert_condition(
                    bool(loaded.get("text", "").strip()),
                    f"{artifact.label} contained text content.",
                    f"{artifact.label} did not contain text content.",
                    category="artifacts",
                    details=[detail("Artifact path", artifact_path)],
                )
            )
            for marker in artifact.expected_markers:
                assertions.append(
                    assert_condition(
                        marker in loaded.get("text", ""),
                        f"{artifact.label} contained marker '{marker}'.",
                        f"{artifact.label} did not contain marker '{marker}'.",
                        category="artifacts",
                        details=[
                            detail("Expected marker", marker),
                            detail("Artifact path", artifact_path),
                        ],
                    )
                )
    return assertions


def capture_artifacts(spec: LabSpec, phase: PhaseSpec, target_dir: Path) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for artifact in all_artifact_specs(spec, phase):
        source = spec.upstream_lab / artifact.source_relpath
        target = target_dir / artifact.target_relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)
        artifacts[artifact.label] = load_artifact(
            target,
            artifact.kind,
            label=artifact.label,
            source_relpath=artifact.source_relpath,
            target_relpath=artifact.target_relpath,
        )
    return artifacts


def load_copied_artifacts(spec: LabSpec, phase: PhaseSpec, target_dir: Path) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for artifact in all_artifact_specs(spec, phase):
        artifacts[artifact.label] = load_artifact(
            target_dir / artifact.target_relpath,
            artifact.kind,
            label=artifact.label,
            source_relpath=artifact.source_relpath,
            target_relpath=artifact.target_relpath,
        )
    return artifacts


def load_artifact(
    path: Path,
    kind: str,
    *,
    label: str | None = None,
    source_relpath: str | None = None,
    target_relpath: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": path,
        "kind": kind,
        "label": label,
        "sourceRelpath": source_relpath,
        "targetRelpath": target_relpath,
        "origin": classify_artifact_origin(source_relpath),
    }
    if kind == "json":
        payload["json"] = load_json(path)
        payload["text"] = path.read_text(encoding="utf-8")
    elif kind in {"html", "text"}:
        payload["text"] = path.read_text(encoding="utf-8")
    return payload


def classify_artifact_origin(source_relpath: str | None) -> str:
    if not source_relpath:
        return "unknown"
    normalized = source_relpath.replace("\\", "/")
    return "generated" if normalized.startswith("build/") else "source"


def filter_relevant_lab_assertions(assertions: list[dict[str, Any]], context: ValidationContext) -> list[dict[str, Any]]:
    return [
        assertion
        for assertion in assertions
        if not assertion_targets_only_source_snapshots(assertion, context)
    ]


def assertion_targets_only_source_snapshots(assertion: dict[str, Any], context: ValidationContext) -> bool:
    if assertion.get("category") != "report":
        return False
    referenced_paths = {
        item.get("value", "")
        for item in assertion.get("details", [])
        if item.get("label") == "Artifact path"
    }
    if not referenced_paths:
        return False
    matched_origins = {
        artifact.get("origin")
        for artifact in context.artifacts.values()
        if str(artifact.get("path", "")) in referenced_paths
    }
    return bool(matched_origins) and matched_origins == {"source"}


def all_artifact_specs(spec: LabSpec, phase: PhaseSpec) -> tuple[ArtifactSpec, ...]:
    return tuple(spec.common_artifact_specs) + tuple(phase.artifact_specs)


def apply_phase_files(spec: LabSpec, phase: PhaseSpec, original_files: dict[str, str | None]) -> None:
    for alias, path in spec.files.items():
        transform = phase.file_transforms.get(alias)
        original_content = original_files[alias]
        content = original_content if transform is None else transform(original_content or "")
        if content is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def restore_original_files(spec: LabSpec, original_files: dict[str, str | None]) -> None:
    for alias, path in spec.files.items():
        original_content = original_files[alias]
        if original_content is None:
            if path.exists():
                path.unlink()
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(original_content, encoding="utf-8")


def ensure_artifact_set_exists(spec: LabSpec, phase: PhaseSpec, target_dir: Path) -> None:
    required_paths = [target_dir / "command.log"] + [target_dir / artifact.target_relpath for artifact in all_artifact_specs(spec, phase)]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Cannot refresh the report because required artifacts are missing: " + ", ".join(missing)
        )


def build_missing_artifact_phase_result(
    spec: LabSpec,
    phase: PhaseSpec,
    target_dir: Path,
    command_info: dict[str, Any],
    error: FileNotFoundError,
) -> dict[str, Any]:
    available_artifacts = build_existing_artifact_links(spec, phase, target_dir)
    command_log_path = target_dir / "command.log"
    console_snippet = command_log_path.read_text(encoding="utf-8") if command_log_path.exists() else ""
    return {
        "name": phase.name,
        "description": phase.description,
        "status": "failed",
        "command": {
            "display": " ".join(phase.command or spec.command),
            "exitCode": command_info.get("exitCode", "n/a"),
            "durationSeconds": round(command_info.get("durationSeconds", 0.0), 2),
        },
        "assertions": [
            {
                "status": "failed",
                "message": "This phase could not be reported because the required artifacts were not generated.",
                "category": "artifacts",
                "details": [
                    detail("Impact", "The phase cannot be validated or rebuilt until the missing artifacts are generated."),
                    detail("Reason", str(error)),
                    detail(
                        "How to fix",
                        f"Rerun `python3 {spec.name}/run.py` without `--refresh-report` to regenerate the missing artifacts, then rerun `python3 rebuild_reports.py` or `python3 run_all.py --refresh-report`.",
                    ),
                    detail("Phase output folder", target_dir),
                ],
            }
        ],
        "artifacts": available_artifacts,
        "consoleSnippet": shorten_text_block(console_snippet),
        "fixSummary": list(phase.fix_summary),
    }


def build_existing_artifact_links(spec: LabSpec, phase: PhaseSpec, target_dir: Path) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    command_log = target_dir / "command.log"
    if command_log.exists():
        links.append({"label": "command.log", "href": f"{target_dir.name}/command.log"})
    for artifact in all_artifact_specs(spec, phase):
        artifact_path = target_dir / artifact.target_relpath
        if artifact_path.exists():
            links.append({"label": artifact.label, "href": f"{target_dir.name}/{artifact.target_relpath}"})
    return links


def load_previous_phase_commands(output_dir: Path) -> dict[str, dict[str, Any]]:
    report_path = output_dir / "report.json"
    if not report_path.exists():
        return {}
    existing_report = load_json(report_path)
    commands: dict[str, dict[str, Any]] = {}
    for phase in existing_report.get("phases", []):
        if "name" in phase and "command" in phase:
            commands[phase["name"]] = phase["command"]
    return commands


def phase_dir_name(phase: PhaseSpec) -> str:
    if phase.output_dir_name:
        return phase.output_dir_name
    return "baseline" if "baseline" in phase.name.lower() else "fixed"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def shorten_console_output(result: CommandResult) -> str:
    return shorten_text_block(result.combined_output)


def shorten_text_block(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= 80:
        return "\n".join(lines)
    head = "\n".join(lines[:45])
    tail = "\n".join(lines[-30:])
    return f"{head}\n...\n{tail}"


def evaluate_readme_assertions(context: ValidationContext) -> list[dict[str, Any]]:
    readme_text = context.readme_text
    readme_assertions = context.phase.readme_assertions
    result = context.command_result
    operations = extract_operations(context)

    normalized_readme = normalize_space(readme_text)
    normalized_console = normalize_space(result.combined_output)
    statuses_by_path = {
        operation_identity(item): item.get("coverageStatus")
        for item in operations
        if operation_identity(item) is not None
    }
    evaluated: list[dict[str, Any]] = []

    for item in readme_assertions:
        kind = item["kind"]
        if kind == "readme-contains":
            condition = normalize_space(item["text"]) in normalized_readme
            details = [
                detail("Expected README text", item["text"]),
                detail("README contains text", condition),
            ]
        elif kind == "readme-runtime-detail":
            condition = (
                normalize_space(item["text"]) in normalized_console
                and normalize_space(item["text"]) in normalized_readme
            )
            details = [
                detail("Runtime detail", item["text"]),
                detail("Seen in console", normalize_space(item["text"]) in normalized_console),
                detail("Seen in README", normalize_space(item["text"]) in normalized_readme),
                detail("Console excerpt", extract_context(result.combined_output, item["text"])),
            ]
        elif kind == "readme-operation-status":
            readme_has_path = normalize_space(item["path"]) in normalized_readme
            readme_has_status = normalize_space(item["status"]) in normalized_readme
            runtime_matches = statuses_by_path.get(item["path"]) == item["status"]
            condition = readme_has_path and readme_has_status and runtime_matches
            details = [
                detail("Path", item["path"]),
                detail("Expected status", item["status"]),
                detail("Runtime status", statuses_by_path.get(item["path"])),
                detail("README mentions path", readme_has_path),
                detail("README mentions status", readme_has_status),
            ]
        else:
            raise ValueError(f"Unknown README assertion kind: {kind}")

        evaluated.append(
            {
                "status": "passed" if condition else "failed",
                "message": item["success"] if condition else item["failure"],
                "category": "readme",
                "details": details,
                "code": item.get("code"),
            }
        )

    return evaluated


def evaluate_readme_console_structure(context: ValidationContext) -> list[dict[str, Any]]:
    readme_text = context.readme_text
    blocks = extract_console_blocks(readme_text)
    command_blocks = [block for block in blocks if block["is_console"]]

    assertions: list[dict[str, Any]] = []
    assertions.append(
        assert_condition(
            len(command_blocks) >= 2,
            "README contained at least two executable command sections.",
            "README did not contain at least two executable command sections.",
            category="readme",
            code="readme.commands.minimum_count",
            details=[
                detail("Executable command sections", len(command_blocks)),
            ],
        )
    )
    assertions.append(
        assert_condition(
            bool(command_blocks) and all(block["rawLanguage"] == "shell" for block in command_blocks),
            "All executable command sections use ```shell``` fenced blocks.",
            "Some executable command sections do not use ```shell``` fenced blocks.",
            category="readme",
            code="readme.commands.executable_fences",
            details=[
                detail("Executable command section count", len(command_blocks)),
                detail(
                    "Command sections with non-shell fence languages",
                    ", ".join(
                        f"{block['preview']} -> ```{block['rawLanguage'] or '(none)'}```"
                        for block in command_blocks
                        if block["rawLanguage"] != "shell"
                    ) or "(none)",
                ),
            ],
        )
    )
    return assertions


def evaluate_readme_os_documentation(context: ValidationContext) -> list[dict[str, Any]]:
    if getattr(context.readme_doc, "is_v2", False):
        return []
    profile = analyze_readme_os_documentation(context.readme_text)
    assertions: list[dict[str, Any]] = []

    if profile["hasCommands"]:
        assertions.append(
            assert_condition(
                not profile["missingCommandOs"],
                "README provides OS-specific command sections for Windows, macOS, and Linux.",
                "README does not provide OS-specific command sections for every OS. Impact: readers on some platforms will not know which command to run. Action required: add command sections for the missing OS variants in appropriate fenced code blocks.",
                category="readme",
                code="readme.os_commands.coverage",
                details=[detail("Missing OS command sections", ", ".join(profile["missingCommandOs"]) or "(none)")],
            )
        )
        assertions.append(
            assert_condition(
                not profile["commandLanguageIssues"],
                "README uses OS-appropriate fenced block languages for documented commands.",
                "README uses non-standard fenced block languages for some OS-specific commands. Impact: readers may not understand which shell to use and syntax highlighting becomes misleading. Action required: use shell/bash for macOS and Linux commands, and powershell/cmd for Windows commands.",
                category="readme",
                code="readme.os_commands.fence_languages",
                details=[
                    detail(
                        "Fence language issues",
                        ", ".join(
                            f"{item['os']} -> {item['heading']} uses {item['language']}"
                            for item in profile["commandLanguageIssues"]
                        )
                        or "(none)",
                    )
                ],
            )
        )

    if profile["hasPathOutputs"]:
        assertions.append(
            assert_condition(
                not profile["missingOutputOs"],
                "README provides OS-specific output sections when console output shows paths.",
                "README does not provide OS-specific output sections for path-based console output. Impact: readers may not know what equivalent output should look like on their OS. Action required: add Windows, macOS, and Linux output examples when paths are shown.",
                category="readme",
                code="readme.os_output.path_coverage",
                details=[detail("Missing OS output sections", ", ".join(profile["missingOutputOs"]) or "(none)")],
            )
        )

    assertions.append(
        assert_condition(
            not profile["commandsMissingOutput"],
            "Every documented command section is followed by a console output snippet.",
            "Some documented command sections are not followed by a console output snippet. Impact: readers cannot see what the command should produce before moving to the next step. Action required: add a console output fenced block immediately after each command section.",
            category="readme",
            code="readme.command_output.followup",
            details=[
                detail(
                    "Commands missing console output",
                    ", ".join(profile["commandsMissingOutput"]) or "(none)",
                )
            ],
        )
    )
    assertions.append(
        assert_condition(
            not profile["outputLanguageIssues"],
            "All README console output snippets use ```terminaloutput``` fenced blocks.",
            "Some README console output snippets do not use ```terminaloutput``` fenced blocks. Impact: commands and output are harder to distinguish, and OS-specific output examples are less readable. Action required: change those output snippets to ```terminaloutput``` fenced blocks.",
            category="readme",
            code="readme.output.terminaloutput_fence",
            details=[
                detail(
                    "Output fence issues",
                    ", ".join(profile["outputLanguageIssues"]) or "(none)",
                )
            ],
        )
    )
    if profile["hasCommands"]:
        assertions.append(
            assert_condition(
                not profile["missingOutputForCommandOs"],
                "OS-specific command sections include matching OS-specific console output snippets.",
                "Some OS-specific command sections do not include matching OS-specific console output snippets. Impact: readers cannot see the expected output for every OS-specific command variant. Action required: add a terminaloutput block for each Windows, macOS, and Linux command section.",
                category="readme",
                code="readme.os_output.command_coverage",
                details=[
                    detail(
                        "Missing OS-specific command outputs",
                        ", ".join(profile["missingOutputForCommandOs"]) or "(none)",
                    )
                ],
            )
        )

    return assertions


def evaluate_runtime_summary_drift(context: ValidationContext) -> list[dict[str, Any]]:
    phase_doc = context.readme_doc.phase_by_id(context.phase.readme_phase_id) if getattr(context.readme_doc, "is_v2", False) else None
    phase_metadata = phase_doc.metadata if phase_doc is not None else {}

    # Use global report settings, not phase-level
    global_reports = context.readme_doc.metadata.get("reports", {})
    expect_ctrf = bool(global_reports.get("ctrf", False))
    expect_html = bool(global_reports.get("html", False))
    expect_readme_summary = bool(phase_metadata.get("test_counts", False) or global_reports.get("readme_summary", False))
    if not any((expect_ctrf, expect_html, expect_readme_summary)):
        has_report_artifacts = (
            "ctrf-report.json" in context.artifacts
            or first_html_artifact(context.artifacts) is not None
        )
        if not has_report_artifacts:
            return []

    readme_summaries = extract_tests_run_summaries(phase_doc.content if phase_doc is not None else context.readme_text)
    phase_index = next((index for index, phase in enumerate(context.lab.phases) if phase is context.phase), 0)
    selected_summary = readme_summaries[0] if phase_doc is not None and readme_summaries else select_readme_summary_for_phase(readme_summaries, context.phase, phase_index)
    readme_summary = selected_summary["summary"] if selected_summary else None
    console_summary = extract_tests_run_summary(context.command_result.combined_output)
    assertions: list[dict[str, Any]] = []

    assertions.append(
        assert_condition(
            console_summary is not None,
            "Console output included a test summary block.",
            "Console output did not include a test summary block. Impact: the README and report counts cannot be compared. Action required: ensure the lab prints a final 'Tests run: ...' summary before exit.",
            category="console",
            code="console.tests_run_summary.present",
            details=[
                detail("Console summary", console_summary or "(missing)"),
                detail("README summary", readme_summary or "(missing)"),
            ],
        )
    )
    if console_summary is None:
        return assertions

    if expect_readme_summary or readme_summary is not None:
        assertions.append(
            assert_equal(
                readme_summary,
                console_summary,
                "README test summary matched the console test summary.",
                "README test summary did not match the console test summary. Impact: the README is no longer describing the actual runtime result. Action required: update the README test summary block or fix the lab so the console output matches the documented counts.",
                category="readme",
                code="readme.tests_run_summary.matches_console",
                details=[
                    detail("README summary", readme_summary or "(missing)"),
                    detail("Console summary", console_summary),
                ],
            )
        )

    console_counts = parse_console_test_summary(console_summary)
    if console_counts is None:
        return assertions

    report_summaries: list[tuple[str, dict[str, int]]] = []
    ctrf_artifact = context.artifacts.get("ctrf-report.json")
    if expect_ctrf and ctrf_artifact and "json" in ctrf_artifact:
        report_summary = ctrf_artifact["json"].get("results", {}).get("summary", {})
        report_summaries.append(("CTRF", normalize_report_test_summary(report_summary)))

    html_artifact = first_html_artifact(context.artifacts)
    if expect_html and html_artifact is not None:
        try:
            html_report = parse_html_embedded_report(html_artifact["text"])
        except ValueError as exc:
            assertions.append(
                assert_condition(
                    False,
                    "Embedded Specmatic HTML report contained a parseable summary block.",
                    "Embedded Specmatic HTML report could not be parsed for its summary block.",
                    category="artifacts",
                    code="artifacts.html_summary.parseable",
                    details=[detail("Reason", str(exc))],
                )
            )
        else:
            report_summaries.append(("Specmatic HTML", normalize_report_test_summary(html_report["results"]["summary"])))

    for label, report_counts in report_summaries:
        console_counts_comparable = {key: console_counts[key] for key in ("tests", "passed", "failed", "other")}
        report_counts_comparable = {key: report_counts[key] for key in ("tests", "passed", "failed", "other")}
        assertions.append(
            assert_equal(
                report_counts_comparable,
                console_counts_comparable,
                f"{label} summary matched the console test counts.",
                f"{label} summary did not match the console test counts. Impact: the generated {label} artifact is out of sync with the observed runtime counts. Action required: regenerate the lab so the console output and report artifacts are produced from the same execution.",
                category="report",
                code=f"report.tests_run_summary.matches_{label.lower().replace(' ', '_')}",
                details=[
                    detail_table(
                        "Test count comparison",
                        headers=["Source", "Tests", "Passed/Successes", "Failed", "Skipped", "Other/Errors"],
                        rows=[
                            ["Console", console_counts["tests"], console_counts["passed"], console_counts["failed"], console_counts["skipped"], console_counts["other"]],
                            [label, report_counts["tests"], report_counts["passed"], report_counts["failed"], report_counts["skipped"], report_counts["other"]],
                        ],
                    ),
                    detail(
                        "Impact",
                        f"The README, console output, and {label} report no longer describe the same run.",
                    ),
                    detail(
                        "Action required",
                        "Re-run the lab, confirm the README documents the same final counts, and rebuild the reports from the refreshed artifacts.",
                    ),
                ],
            )
        )

    return assertions


def select_readme_summary_for_phase(
    readme_summaries: list[dict[str, str]],
    phase: PhaseSpec,
    phase_index: int,
) -> dict[str, str] | None:
    if phase.readme_summary_query:
        query = phase.readme_summary_query.strip().lower()
        for summary in readme_summaries:
            label = (summary.get("label") or "").strip().lower()
            heading = (summary.get("heading") or "").strip().lower()
            heading_path = (summary.get("headingPath") or "").strip().lower()
            if (
                query == label
                or query == heading
                or query in label
                or query in heading
                or query in heading_path
            ):
                return summary
    if phase_index < len(readme_summaries):
        return readme_summaries[phase_index]
    return None


def evaluate_v2_phase_readme_alignment(context: ValidationContext) -> list[dict[str, Any]]:
    document = context.readme_doc
    if not getattr(document, "is_v2", False):
        return []

    phase_doc = document.phase_by_id(context.phase.readme_phase_id)
    if phase_doc is None:
        return [
            assert_condition(
                False,
                "README contains the mapped implementation phase.",
                "README is missing the implementation phase mapped to this automated phase.",
                category="readme",
                code="readme.v2.phase_mapping.present",
                details=[detail("Expected phase id", context.phase.readme_phase_id or "(missing)")],
            )
        ]

    commands = phase_doc.command_blocks
    outputs = phase_doc.output_blocks
    command_blocks_missing_following_output: list[str] = []
    skipped_command_blocks: list[str] = []
    invalid_output_fence_languages: list[str] = []
    for index, block in enumerate(phase_doc.code_blocks):
        if not block.is_command:
            continue
        skipped_reason = skipped_command_output_reason(block.body)
        if skipped_reason:
            skipped_command_blocks.append(f"line {block.line} ({skipped_reason})")
            continue
        next_block = phase_doc.code_blocks[index + 1] if index + 1 < len(phase_doc.code_blocks) else None
        if next_block is None or not next_block.is_output:
            command_blocks_missing_following_output.append(f"line {block.line}")
            continue
        if next_block.raw_language != TERMINAL_OUTPUT_FENCE_LANGUAGE:
            invalid_output_fence_languages.append(f"line {next_block.line}: {next_block.raw_language or '(none)'}")
    assertions = [
        assert_condition(
            bool(commands),
            "README phase documents at least one executable command.",
            "README phase does not document any executable command.",
            category="readme",
            code="readme.v2.phase.commands",
            details=[detail("Phase title", phase_doc.title)],
        ),
        assert_condition(
            not command_blocks_missing_following_output,
            "README phase includes a following terminaloutput block for each command block.",
            "README phase is missing a following terminaloutput block for one or more command blocks.",
            category="readme",
            code="readme.v2.phase.outputs",
            details=[
                detail("Phase title", phase_doc.title),
                detail("Commands missing following output", ", ".join(command_blocks_missing_following_output) or "(none)"),
                detail("Skipped command blocks", ", ".join(skipped_command_blocks) or "(none)"),
            ],
        ),
        assert_condition(
            all(block.raw_language == "shell" for block in commands),
            "README phase command blocks use ```shell``` fences.",
            "README phase command blocks do not consistently use ```shell``` fences.",
            category="readme",
            code="readme.v2.phase.command_fences",
            details=[
                detail(
                    "Invalid command fence languages",
                    ", ".join(sorted({block.raw_language or "(none)" for block in commands if block.raw_language != "shell"})) or "(none)",
                )
            ],
        ),
        assert_condition(
            not invalid_output_fence_languages and all(block.raw_language == TERMINAL_OUTPUT_FENCE_LANGUAGE for block in outputs),
            "README phase output blocks use terminaloutput fences.",
            "README phase output blocks do not consistently use terminaloutput fences.",
            category="readme",
            code="readme.v2.phase.output_fences",
            details=[
                detail(
                    "Invalid output fence languages",
                    ", ".join(sorted({block.raw_language or "(none)" for block in outputs if block.raw_language != TERMINAL_OUTPUT_FENCE_LANGUAGE} | set(invalid_output_fence_languages))) or "(none)",
                )
            ],
        ),
    ]

    # Always validate summary (test_counts is always True now)
    assertions.append(
        assert_condition(
            bool(extract_tests_run_summaries(phase_doc.content)),
            "README phase includes a summary block for runtime count validation.",
            "README phase is missing the documented summary block required for runtime count validation.",
            category="readme",
            code="readme.v2.phase.summary",
            details=[detail("Phase title", phase_doc.title)],
        )
    )

    return assertions


def evaluate_readme_links(context: ValidationContext) -> list[dict[str, Any]]:
    assertions: list[dict[str, Any]] = []
    for link in context.readme_doc.links:
        if link.target.startswith("mailto:"):
            continue
        if link.is_external:
            cached = EXTERNAL_LINK_CACHE.get(link.target)
            if cached is None:
                cached = validate_external_link(link.target)
                EXTERNAL_LINK_CACHE[link.target] = cached
            ok, detail_value = cached
            assertions.append(
                assert_condition(
                    ok,
                    f"External README link resolved successfully: {link.target}",
                    f"External README link did not resolve successfully: {link.target}",
                    category="readme",
                    code="readme.links.external",
                    details=[
                        detail("Line", link.line),
                        detail("Target", link.target),
                        detail("Result", detail_value),
                    ],
                )
            )
            continue

        ok, detail_value = validate_internal_link(link, readme_path=context.lab.readme_path, headings=context.readme_doc.headings)
        assertions.append(
            assert_condition(
                ok,
                f"Internal README link resolved successfully: {link.target}",
                f"Internal README link did not resolve successfully: {link.target}",
                category="readme",
                code="readme.links.internal",
                details=[
                    detail("Line", link.line),
                    detail("Target", link.target),
                    detail("Result", detail_value),
                ],
            )
        )
    return assertions


def validate_readme_structure(context: ValidationContext) -> list[dict[str, Any]]:
    return validate_canonical_readme_structure(context)


def validate_canonical_readme_structure(context: ValidationContext) -> list[dict[str, Any]]:
    document = context.readme_doc
    actual_h2 = document.h2_titles
    expected_h2 = list(expected_h2_titles_for_document(document))
    # Get phase IDs from global config
    phase_ids = document.metadata.get("phases", [])
    sequence_ok, sequence_message = phase_sequence_is_valid(document.phases, phase_ids)
    runner_phase_ids = [phase.readme_phase_id for phase in context.lab.phases if phase.readme_phase_id]
    readme_phase_ids = [phase.id for phase in document.phases if phase.id]
    assertions: list[dict[str, Any]] = [
        assert_equal(
            document.schema_version,
            V2_SCHEMA_VERSION,
            "README declares schema version v2.",
            f"README does not declare schema version {V2_SCHEMA_VERSION}.",
            category="readme",
            code="readme.v2.schema_version",
            details=[detail("Declared schema version", document.schema_version or "(missing)")],
        ),
        assert_condition(
            bool(document.h1_title),
            "README contains one top-level H1 title.",
            "README is missing the top-level H1 title.",
            category="readme",
            code="readme.v2.h1.present",
            details=[detail("H1 title", document.h1_title or "(missing)")],
        ),
        assert_equal(
            actual_h2,
            expected_h2,
            "README H2 sections match the canonical v2 sequence.",
            "README H2 sections do not match the canonical v2 sequence.",
            category="readme",
            code="readme.v2.h2_sequence",
            details=[
                detail("Expected H2 sequence", " -> ".join(expected_h2)),
                detail("Actual H2 sequence", " -> ".join(actual_h2) or "(none)"),
            ],
        ),
        assert_condition(
            sequence_ok,
            "README lab implementation phases follow the required baseline-to-final flow.",
            f"README lab implementation phases do not follow the required baseline-to-final flow: {sequence_message}",
            category="readme",
            code="readme.v2.phase_sequence",
            details=[
                detail("Phase ids", ", ".join(phase.id for phase in document.phases) or "(none)"),
            ],
        ),
        assert_equal(
            runner_phase_ids,
            readme_phase_ids,
            "Automated lab phases align with the README phase ids.",
            "Automated lab phases do not align with the README phase ids.",
            category="readme",
            code="readme.v2.phase_mapping.sequence",
            details=[
                detail("README phase ids", ", ".join(readme_phase_ids) or "(none)"),
                detail("Automated phase ids", ", ".join(runner_phase_ids) or "(none)"),
            ],
        ),
    ]
    return assertions


def extract_console_blocks(readme_text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for match in FENCED_CODE_BLOCK_RE.finditer(readme_text):
        raw_language = (match.group("lang") or "").strip()
        language = raw_language.lower()
        body = match.group("body").strip()
        lines = [line.strip() for line in body.splitlines() if line.strip()]
        preview = lines[0] if lines else ""
        is_console = bool(lines and SHELL_COMMAND_PREFIXES_RE.match(lines[0]))
        heading_text = heading_before_line_text(readme_text, line_number_for_index(readme_text, match.start()))
        context_text = " ".join(filter(None, [heading_text, collect_preceding_context(readme_text, line_number_for_index(readme_text, match.start()))]))
        blocks.append(
            {
                "rawLanguage": raw_language,
                "language": language,
                "body": body,
                "preview": preview,
                "normalizedPreview": normalize_output_preview(preview),
                "is_console": is_console,
                "line": line_number_for_index(readme_text, match.start()),
                "heading": heading_text,
                "contextText": context_text,
                "osTargets": sorted(os_targets_from_text(context_text)),
            }
        )
    return blocks


def line_number_for_index(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def heading_before_line_text(readme_text: str, line_number: int) -> str:
    headings = [(m.group(2).strip(), line_number_for_index(readme_text, m.start())) for m in HEADING_RE.finditer(readme_text)]
    before = [text for text, line in headings if line <= line_number]
    return before[-1] if before else ""


def heading_path_before_line_text(readme_text: str, line_number: int) -> str:
    headings = [
        (len(m.group(1)), m.group(2).strip(), line_number_for_index(readme_text, m.start()))
        for m in HEADING_RE.finditer(readme_text)
    ]
    path: list[tuple[int, str]] = []
    for level, text, line in headings:
        if line > line_number:
            break
        while path and path[-1][0] >= level:
            path.pop()
        path.append((level, text))
    return " > ".join(text for _, text in path)


def collect_preceding_context(readme_text: str, line_number: int, window: int = 4) -> str:
    lines = readme_text.splitlines()
    start = max(0, line_number - 1 - window)
    return "\n".join(line.strip() for line in lines[start : max(0, line_number - 1)] if line.strip())


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


def is_output_block_with_paths(block: dict[str, Any], context_text: str) -> bool:
    if block["is_console"] or not PATH_LIKE_RE.search(block["body"]):
        return False
    lowered_context = context_text.lower()
    output_languages = {TERMINAL_OUTPUT_FENCE_LANGUAGE, "output", "text", "log"}
    output_markers = ("expected output", "output", "result", "console output", "example output")
    return block["language"] in output_languages or any(marker in lowered_context for marker in output_markers)


def is_command_language_appropriate(os_name: str, language: str) -> bool:
    return language == "shell"


def skipped_command_output_reason(command: str) -> str | None:
    normalized = " ".join(command.strip().lower().split())
    if (
        ("docker compose" in normalized or "docker-compose" in normalized)
        and " down" in f" {normalized}"
    ):
        return "terminaloutput is not required for teardown commands"
    if (
        ("docker compose" in normalized or "docker-compose" in normalized)
        and "--profile studio" in normalized
        and " up" in f" {normalized}"
        and "--build" in normalized
    ):
        return "terminaloutput is not required for Studio startup/build commands"
    if (
        ("docker compose" in normalized or "docker-compose" in normalized)
        and normalized.endswith(" pull")
    ):
        return "terminaloutput is not required for docker image pull commands"
    teardown_prefixes = ("docker stop", "docker rm")
    if normalized.startswith(teardown_prefixes):
        return "terminaloutput is not required for teardown commands"
    return None


def analyze_readme_os_documentation(readme_text: str) -> dict[str, Any]:
    command_coverage = {os_name: [] for os_name in ("Windows", "macOS", "Linux")}
    output_coverage = {os_name: [] for os_name in ("Windows", "macOS", "Linux")}
    command_language_issues: list[dict[str, str]] = []
    output_language_issues: list[str] = []
    commands_missing_output: list[str] = []
    has_commands = False
    has_path_outputs = False
    blocks = extract_console_blocks(readme_text)

    for index, block in enumerate(blocks):
        heading_text = block["heading"]
        context_text = block["contextText"]
        os_targets = set(block["osTargets"])
        if block["is_console"]:
            has_commands = True
            skipped_reason = skipped_command_output_reason(block["preview"] or "")
            for os_name in os_targets:
                command_coverage[os_name].append(
                    {
                        "heading": heading_text or "(no heading)",
                        "language": block["language"] or "(none)",
                        "preview": block["preview"] or "(blank)",
                    }
                )
                if not is_command_language_appropriate(os_name, block["rawLanguage"] or ""):
                    command_language_issues.append({"os": os_name, "heading": heading_text or "(no heading)", "language": block["rawLanguage"] or "(none)"})
            if skipped_reason:
                continue
            next_block = blocks[index + 1] if index + 1 < len(blocks) else None
            if (
                next_block is None
                or next_block["is_console"]
                or next_block["heading"] != heading_text
            ):
                commands_missing_output.append(f"{heading_text or '(no heading)'} -> {block['normalizedPreview'] or '(blank)'}")
                continue
            output_targets = set(next_block["osTargets"]) or os_targets
            for os_name in output_targets:
                output_coverage[os_name].append(
                    {
                        "heading": next_block["heading"] or heading_text or "(no heading)",
                        "language": next_block["language"] or "(none)",
                        "preview": next_block["normalizedPreview"] or "(blank)",
                    }
                )
            if next_block["rawLanguage"] != TERMINAL_OUTPUT_FENCE_LANGUAGE:
                output_language_issues.append(
                    f"{heading_text or '(no heading)'} -> {block['normalizedPreview'] or '(blank)'} uses ```{next_block['rawLanguage'] or '(none)'}``` for output"
                )
        elif is_output_block_with_paths(block, context_text):
            has_path_outputs = True
            for os_name in os_targets:
                output_coverage[os_name].append(
                    {
                        "heading": heading_text or "(no heading)",
                        "language": block["language"] or "(none)",
                        "preview": block["normalizedPreview"] or "(blank)",
                    }
                )
            if block["rawLanguage"] != TERMINAL_OUTPUT_FENCE_LANGUAGE:
                output_language_issues.append(
                    f"{heading_text or '(no heading)'} uses ```{block['rawLanguage'] or '(none)'}``` for output"
                )

    return {
        "hasCommands": has_commands,
        "missingCommandOs": [os_name for os_name, entries in command_coverage.items() if has_commands and not entries],
        "commandLanguageIssues": command_language_issues,
        "hasPathOutputs": has_path_outputs,
        "missingOutputOs": [os_name for os_name, entries in output_coverage.items() if has_path_outputs and not entries],
        "commandsMissingOutput": commands_missing_output,
        "outputLanguageIssues": output_language_issues,
        "missingOutputForCommandOs": [os_name for os_name, entries in command_coverage.items() if entries and not output_coverage[os_name]],
    }


def normalize_output_preview(text: str) -> str:
    if not text:
        return ""
    normalized = re.sub(
        r"^\s*(?:\[\d{4}-\d{2}-\d{2}[^\]]*\]\s*|\d{4}-\d{1,2}-\d{1,2}[ T]\d{1,2}:\d{2}:\d{2}(?:\.\d+)?\s*|[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}\s+\d{1,2}:\d{2}:\d{2}\s*)",
        "",
        text,
    )
    return normalized.strip()


def build_warning_messages(spec: LabSpec, phase: PhaseSpec) -> list[str]:
    warnings = list(spec.runtime_warnings)
    warnings.extend(spec.known_limitations)
    warnings.extend(spec.intentional_differences)
    warnings.extend(phase.notes)
    artifact_labels = {artifact.label for artifact in all_artifact_specs(spec, phase)}
    additional = sorted(
        label for label in artifact_labels if label not in REPORT_ARTIFACT_LABELS and label not in IGNORED_ARTIFACT_LABELS
    )
    if not additional:
        return warnings
    warnings.append(f"Additional artifacts found: {', '.join(additional)}")
    return warnings


def parse_readme_ignore_codes(readme_text: str) -> set[str]:
    codes: set[str] = set()
    for match in HTML_COMMENT_RE.finditer(readme_text):
        body = " ".join(match.group("body").split())
        directive_match = re.search(r"labs-tests:\s*ignore\s+(.+)", body, re.IGNORECASE)
        if not directive_match:
            continue
        raw_codes = directive_match.group(1)
        for raw_code in re.split(r"[,\s]+", raw_codes):
            code = raw_code.strip()
            if code:
                codes.add(code)
    return codes


def apply_readme_annotation_overrides(assertions: list[dict[str, Any]], readme_text: str) -> list[dict[str, Any]]:
    ignored_codes = parse_readme_ignore_codes(readme_text)
    if not ignored_codes:
        return assertions

    updated: list[dict[str, Any]] = []
    for assertion in assertions:
        code = assertion.get("code")
        if code and code in ignored_codes:
            original_message = assertion["message"]
            updated.append(
                {
                    **assertion,
                    "status": "skipped",
                    "message": f"Validation ignored by README annotation: {code}.",
                    "details": [
                        *(assertion.get("details") or []),
                        detail("Ignored validation code", code),
                        detail("Original result", original_message),
                    ],
                }
            )
        else:
            updated.append(assertion)
    return updated


def extract_tests_run_summary(console_output: str) -> str | None:
    clean_output = normalize_summary_source_text(strip_ansi(console_output))
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


def extract_tests_run_summaries(readme_text: str) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    matches = (
        list(TESTS_RUN_SUMMARY_RE.finditer(readme_text))
        + list(EXAMPLES_SUMMARY_RE.finditer(readme_text))
        + list(MCP_SUMMARY_RE.finditer(readme_text))
    )
    matches.sort(key=lambda match: match.start())
    for match in matches:
        line = line_number_for_index(readme_text, match.start())
        if match.re is MCP_SUMMARY_RE:
            summary_text = format_mcp_summary_match(match)
        else:
            summary_text = match.group(0)
        summaries.append(
            {
                "heading": heading_before_line_text(readme_text, line),
                "headingPath": heading_path_before_line_text(readme_text, line),
                "label": summary_label_before_line(readme_text, line),
                "summary": summary_text,
            }
        )
    return summaries


def summary_label_before_line(readme_text: str, line_number: int) -> str:
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
    return heading_before_line_text(readme_text, line_number)


def parse_console_test_summary(summary_text: str | None) -> dict[str, int] | None:
    if summary_text is None:
        return None
    clean_summary = normalize_summary_source_text(strip_ansi(summary_text))
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
    failures = int(match.group("failures"))
    errors = int(match.group("errors") or 0)
    return {
        "tests": int(match.group("tests")),
        "passed": int(match.group("successes")),
        "failed": failures + errors,
        "skipped": 0,
        "other": 0,
    }


def normalize_report_test_summary(summary: dict[str, Any]) -> dict[str, int]:
    failed = int(summary.get("failed", 0))
    errors = int(summary.get("error", 0))
    other = int(summary.get("other", 0))
    return {
        "tests": int(summary.get("tests", 0)),
        "passed": int(summary.get("passed", 0)),
        "failed": failed + errors,
        "skipped": int(summary.get("skipped", 0)),
        "other": other,
    }


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


def extract_operations(context: ValidationContext) -> list[dict[str, Any]]:
    coverage_artifact = context.artifacts.get("coverage_report.json")
    if coverage_artifact and "json" in coverage_artifact:
        return coverage_artifact["json"].get("apiCoverage", [{}])[0].get("operations", [])
    html_artifact = first_html_artifact(context.artifacts)
    if html_artifact is None:
        return []
    try:
        report = parse_html_embedded_report(html_artifact["text"])
    except ValueError:
        return []
    return report["results"]["summary"]["extra"]["executionDetails"][0]["operations"]


def operation_identity(operation: dict[str, Any]) -> str | None:
    if "path" in operation:
        return operation["path"]
    if "channel" in operation:
        action = operation.get("action")
        channel = operation.get("channel")
        return f"{channel}:{action}" if action else str(channel)
    if "operation" in operation:
        return str(operation["operation"])
    return None


def first_html_artifact(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for artifact in artifacts.values():
        if artifact.get("kind") == "html":
            return artifact
    return None


def build_coverage_assertions(
    context: ValidationContext,
    *,
    expected_tests: dict[str, int],
    expected_operations: dict[str, str],
    forbidden_operation_statuses: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    ctrf = context.artifacts["ctrf-report.json"]["json"]
    html_text = first_html_artifact(context.artifacts)["text"]
    html_report = parse_html_embedded_report(html_text)
    command_output = context.command_result.combined_output

    assertions: list[dict[str, Any]] = []
    summary = ctrf["results"]["summary"]
    for field, expected_value in expected_tests.items():
        actual_value = summary.get(field, 0)
        assertions.append(
            assert_equal(
                actual_value,
                expected_value,
                f"CTRF summary field '{field}' matched expected value {expected_value}.",
                f"CTRF summary field '{field}' expected {expected_value}, got {actual_value}.",
                category="report",
                details=[
                    detail("Field", field),
                    detail("Expected", expected_value),
                    detail("Actual", actual_value),
                ],
            )
        )

    assertions.append(
        assert_equal(
            len(ctrf["results"].get("tests", [])),
            expected_tests["tests"],
            f"CTRF test list contained {expected_tests['tests']} entries as expected.",
            f"CTRF test list expected {expected_tests['tests']} entries, got {len(ctrf['results'].get('tests', []))}.",
            category="artifacts",
            details=[
                detail("Expected CTRF tests", expected_tests["tests"]),
                detail("Actual CTRF tests", len(ctrf["results"].get("tests", []))),
            ],
        )
    )
    assertions.append(
        assert_equal(
            len(html_report["results"].get("tests", [])),
            expected_tests["tests"],
            f"Embedded Specmatic HTML report contained {expected_tests['tests']} test entries as expected.",
            f"Embedded Specmatic HTML report expected {expected_tests['tests']} test entries, got {len(html_report['results'].get('tests', []))}.",
            category="artifacts",
            details=[
                detail("Expected HTML tests", expected_tests["tests"]),
                detail("Actual HTML tests", len(html_report["results"].get("tests", []))),
            ],
        )
    )
    assertions.append(
        assert_equal(
            len(html_report["results"]["summary"]["extra"]["executionDetails"][0]["operations"]),
            len(expected_operations),
            f"Embedded Specmatic HTML report contained {len(expected_operations)} operations as expected.",
            f"Embedded Specmatic HTML report expected {len(expected_operations)} operations, got {len(html_report['results']['summary']['extra']['executionDetails'][0]['operations'])}.",
            category="artifacts",
            details=[
                detail("Expected HTML operations", len(expected_operations)),
                detail("Actual HTML operations", len(html_report["results"]["summary"]["extra"]["executionDetails"][0]["operations"])),
            ],
        )
    )

    operations = html_report["results"]["summary"]["extra"]["executionDetails"][0]["operations"]
    by_path = {item["path"]: item["coverageStatus"] for item in operations}
    for path, expected_status in expected_operations.items():
        actual_status = by_path.get(path)
        assertions.append(
            assert_equal(
                actual_status,
                expected_status,
                f"{path} was reported as '{expected_status}'.",
                f"{path} expected coverage status '{expected_status}', got '{actual_status}'.",
                category="report",
                details=[
                    detail("Path", path),
                    detail("Expected status", expected_status),
                    detail("Actual status", actual_status),
                ],
            )
        )

    operation_statuses = [item["coverageStatus"] for item in operations]
    for forbidden_status in forbidden_operation_statuses:
        assertions.append(
            assert_condition(
                forbidden_status not in operation_statuses,
                f"No operation was marked '{forbidden_status}'.",
                f"Coverage still contains forbidden status '{forbidden_status}'.",
                category="report",
                details=[
                    detail("Forbidden status", forbidden_status),
                    detail("Actual statuses", ", ".join(operation_statuses)),
                ],
            )
        )

    assertions.extend(compare_console_coverage_with_reports(command_output, html_text))
    return assertions


def build_test_summary_assertions(
    context: ValidationContext,
    *,
    expected_ctrf: dict[str, int],
    expected_console: dict[str, int],
) -> list[dict[str, Any]]:
    ctrf = context.artifacts["ctrf-report.json"]["json"]
    html_text = first_html_artifact(context.artifacts)["text"]
    html_report = parse_html_embedded_report(html_text)
    ctrf_summary = ctrf["results"]["summary"]
    html_summary = html_report["results"]["summary"]
    console_summary = extract_tests_run_summary(context.command_result.combined_output)
    expected_console_summary = (
        f"Tests run: {expected_console['tests']}, "
        f"Successes: {expected_console['successes']}, "
        f"Failures: {expected_console['failures']}, "
        f"Errors: {expected_console['errors']}"
    )

    assertions: list[dict[str, Any]] = []
    for field, expected_value in expected_ctrf.items():
        actual_ctrf = ctrf_summary.get(field, 0)
        actual_html = html_summary.get(field, 0)
        assertions.append(
            assert_equal(
                actual_ctrf,
                expected_value,
                f"CTRF summary field '{field}' matched expected value {expected_value}.",
                f"CTRF summary field '{field}' expected {expected_value}, got {actual_ctrf}.",
                category="report",
                details=[
                    detail("Field", field),
                    detail("Expected", expected_value),
                    detail("Actual", actual_ctrf),
                ],
            )
        )
        assertions.append(
            assert_equal(
                actual_html,
                expected_value,
                f"Embedded Specmatic HTML summary field '{field}' matched expected value {expected_value}.",
                f"Embedded Specmatic HTML summary field '{field}' expected {expected_value}, got {actual_html}.",
                category="report",
                details=[
                    detail("Field", field),
                    detail("Expected", expected_value),
                    detail("Actual", actual_html),
                ],
            )
        )

    assertions.append(
        assert_equal(
            console_summary,
            expected_console_summary,
            f"Console summary matched '{expected_console_summary}'.",
            f"Console summary did not match '{expected_console_summary}'.",
            category="console",
            details=[
                detail("Expected console summary", expected_console_summary),
                detail("Actual console summary", console_summary or "(missing)"),
            ],
        )
    )
    assertions.append(
        assert_equal(
            len(ctrf["results"].get("tests", [])),
            expected_ctrf["tests"],
            f"CTRF test list contained {expected_ctrf['tests']} entries as expected.",
            f"CTRF test list expected {expected_ctrf['tests']} entries, got {len(ctrf['results'].get('tests', []))}.",
            category="artifacts",
            details=[
                detail("Expected CTRF tests", expected_ctrf["tests"]),
                detail("Actual CTRF tests", len(ctrf["results"].get("tests", []))),
            ],
        )
    )
    assertions.append(
        assert_equal(
            len(html_report["results"].get("tests", [])),
            expected_ctrf["tests"],
            f"Embedded Specmatic HTML report contained {expected_ctrf['tests']} test entries as expected.",
            f"Embedded Specmatic HTML report expected {expected_ctrf['tests']} test entries, got {len(html_report['results'].get('tests', []))}.",
            category="artifacts",
            details=[
                detail("Expected HTML tests", expected_ctrf["tests"]),
                detail("Actual HTML tests", len(html_report["results"].get("tests", []))),
            ],
        )
    )
    return assertions


def compare_console_coverage_with_reports(
    console_output: str,
    html_report_text: str,
) -> list[dict[str, Any]]:
    console_rows = parse_console_coverage_rows(console_output)
    html_rows = parse_html_report_rows(normalize_html_report_text(html_report_text))
    normalized_html = normalize_html_report_text(html_report_text)
    console_summary = parse_console_coverage_summary(console_output)
    html_summary = parse_html_coverage_summary(normalized_html)

    assertions: list[dict[str, Any]] = []
    assertions.append(
        assert_equal(
            console_summary,
            html_summary,
            "Console coverage totals matched the generated Specmatic HTML report totals.",
            "Console coverage totals did not match the generated Specmatic HTML report totals.",
            category="report",
            details=[
                detail_table(
                    "Coverage comparison",
                    headers=["Metric", "Console", "Specmatic HTML"],
                    rows=[
                        ["Coverage", console_summary.get("coverage"), html_summary.get("coverage")],
                        ["Operations", console_summary.get("operations"), html_summary.get("operations")],
                    ],
                ),
                detail(
                    "What this means",
                    "This check compares the coverage summary printed in the console with the coverage visible in the generated Specmatic HTML report for the same run.",
                ),
            ],
        )
    )
    assertions.append(
        assert_equal(
            extract_row_counts(console_rows),
            extract_row_counts(html_rows),
            "Console exercised counts matched the generated Specmatic HTML results counts for every operation.",
            "Console exercised counts did not match the generated Specmatic HTML results counts for one or more operations.",
            category="report",
            details=[
                detail_table(
                    "Exercised count comparison",
                    headers=["Path", "Method", "Response", "Console #exercised", "Specmatic HTML Results"],
                    rows=build_count_comparison_rows(console_rows, html_rows),
                ),
            ],
        )
    )
    assertions.append(
        assert_equal(
            sum(row["count"] for row in console_rows),
            sum(row["count"] for row in html_rows),
            "Total console exercised count matched the total number of Specmatic HTML results.",
            "Total console exercised count did not match the total number of Specmatic HTML results.",
            category="report",
            details=[
                detail("Console total exercised count", sum(row["count"] for row in console_rows)),
                detail("Specmatic HTML total results", sum(row["count"] for row in html_rows)),
            ],
        )
    )
    for row in console_rows:
        row_signature = f'{row["path"]} {row["method"]} {row["status"]}'
        assertions.append(
            assert_condition(
                row["path"] in normalized_html and row["status"] in normalized_html,
                f"HTML report contains the console coverage row for {row_signature}.",
                f"HTML report does not contain the console coverage row for {row_signature}.",
                category="report",
                details=[
                    detail("Console coverage row", json.dumps(row, indent=2)),
                    detail("HTML evidence", extract_html_context(normalized_html, row["path"])),
                ],
            )
        )
    return assertions


def parse_console_coverage_rows(console_output: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in strip_ansi(console_output).splitlines():
        if "| covered" not in line and "| not implemented" not in line and "| missing in spec" not in line:
            continue
        cleaned = line.split("| |", 1)[-1] if "| |" in line else line
        parts = [part.strip() for part in cleaned.split("|")]
        if len(parts) < 9:
            continue
        coverage = parts[0]
        path = parts[1]
        method = parts[2]
        response = parts[4]
        status = parts[6].replace("*", "").strip()
        result = parts[7]
        count = 0
        match = re.match(r"(?P<count>\d+)[a-z]+$", result)
        if match:
            count = int(match.group("count"))
        if not coverage.endswith("%") or not path.startswith("/") or method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            continue
        try:
            response_code = int(response)
        except ValueError:
            continue
        rows.append(
            {
                "coverage": coverage,
                "path": path,
                "method": method,
                "response": response_code,
                "count": count,
                "status": status,
            }
        )
    return rows


def parse_coverage_report_rows(coverage_report: dict[str, Any]) -> list[dict[str, Any]]:
    operations = coverage_report["apiCoverage"][0]["operations"]
    rows: list[dict[str, Any]] = []
    for operation in operations:
        rows.append(
            {
                "coverage": "100%" if operation["coverageStatus"] == "covered" else "0%",
                "path": operation["path"],
                "method": operation["method"],
                "response": operation["responseCode"],
                "count": operation["count"],
                "status": operation["coverageStatus"],
            }
        )
    return rows


def parse_html_report_rows(html_text: str) -> list[dict[str, Any]]:
    report = parse_html_embedded_report(html_text)
    operations = report["results"]["summary"]["extra"]["executionDetails"][0]["operations"]
    rows: list[dict[str, Any]] = []
    for operation in operations:
        rows.append(
            {
                "coverage": "100%" if operation["coverageStatus"] == "covered" else "0%",
                "path": operation["path"],
                "method": operation["method"],
                "response": operation["responseCode"],
                "count": len(operation.get("testIds", [])),
                "status": operation["coverageStatus"],
            }
        )
    return rows


def parse_console_coverage_summary(console_output: str) -> dict[str, Any]:
    clean_output = strip_ansi(console_output)
    match = re.search(r"\|\s*(\d+%) API Coverage reported from (\d+) operations eligible for coverage\s*\|", clean_output, re.IGNORECASE)
    if not match:
        return {"coverage": None, "operations": None}
    return {"coverage": match.group(1), "operations": int(match.group(2))}


def parse_html_coverage_summary(html_text: str) -> dict[str, Any]:
    report = parse_html_embedded_report(html_text)
    operations = report["results"]["summary"]["extra"]["executionDetails"][0]["operations"]
    eligible_operations = [operation for operation in operations if operation["coverageStatus"] != "missing in spec"]
    total_operations = len(eligible_operations)
    covered_operations = sum(1 for operation in eligible_operations if operation["coverageStatus"] == "covered")
    return {
        "coverage": f"{int((covered_operations / total_operations) * 100)}%" if total_operations else None,
        "operations": total_operations if total_operations else None,
    }


def parse_html_embedded_report(html_text: str) -> dict[str, Any]:
    match = re.search(r"const report = (\{.*?\});\s*const specmaticConfig =", html_text, re.DOTALL)
    if not match:
        raise ValueError("Could not find the embedded Specmatic report payload inside the HTML report.")
    return json.loads(match.group(1))


def extract_row_counts(rows: list[dict[str, Any]]) -> list[tuple[str, str, int, int]]:
    return [(row["path"], row["method"], row["response"], row["count"]) for row in rows]


def build_count_comparison_rows(left_rows: list[dict[str, Any]], right_rows: list[dict[str, Any]]) -> list[list[Any]]:
    right_map = {(row["path"], row["method"], row["response"]): row["count"] for row in right_rows}
    return [
        [row["path"], row["method"], row["response"], row["count"], right_map.get((row["path"], row["method"], row["response"]))]
        for row in left_rows
    ]


def format_coverage_rows(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, indent=2)


def extract_html_context(html_text: str, phrase: str, window: int = 220) -> str:
    if phrase not in html_text:
        return "Phrase not found in HTML report."
    index = html_text.index(phrase)
    start = max(0, index - window)
    end = min(len(html_text), index + len(phrase) + window)
    return html_text[start:end].strip()


def normalize_html_report_text(html_text: str) -> str:
    return html_text.replace("\\/", "/")


def normalize_space(value: str) -> str:
    return " ".join(value.split())


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def extract_context(text: str, phrase: str, window: int = 240) -> str:
    clean_text = strip_ansi(text)
    clean_phrase = strip_ansi(phrase)
    if clean_phrase not in clean_text:
        return "Phrase not found in captured output."
    index = clean_text.index(clean_phrase)
    start = max(0, index - window)
    end = min(len(clean_text), index + len(clean_phrase) + window)
    snippet = clean_text[start:end].strip()
    return snippet if snippet else clean_phrase


def detail(label: str, value: Any) -> dict[str, str]:
    return {"label": label, "value": "" if value is None else str(value)}


def detail_table(label: str, headers: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"type": "table", "label": label, "headers": headers, "rows": rows}


def assert_equal(
    actual: Any,
    expected: Any,
    success_message: str,
    failure_message: str,
    *,
    category: str,
    details: list[dict[str, Any]] | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "passed" if actual == expected else "failed",
        "message": success_message if actual == expected else failure_message,
        "category": category,
        "details": details or [],
        "code": code,
    }


def assert_condition(
    condition: bool,
    success_message: str,
    failure_message: str,
    *,
    category: str,
    details: list[dict[str, Any]] | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "passed" if condition else "failed",
        "message": success_message if condition else failure_message,
        "category": category,
        "details": details or [],
        "code": code,
    }


def assert_skipped(
    message: str,
    *,
    category: str,
    details: list[dict[str, Any]] | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "skipped",
        "message": message,
        "category": category,
        "details": details or [],
        "code": code,
    }


def assert_expected(
    message: str,
    *,
    category: str,
    details: list[dict[str, Any]] | None = None,
    code: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "expected",
        "message": message,
        "category": category,
        "details": details or [],
        "code": code,
    }
