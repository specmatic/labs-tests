from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import shutil
from typing import Any, Callable

from lablib.command_runner import CommandResult, run_command
from lablib.reporting import build_report, write_html, write_json
from lablib.workspace_setup import run_setup


ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
CONSOLE_COVERAGE_ROW_RE = re.compile(
    r"^\|\s*(?P<coverage>\d+%)\s+\|\s*(?P<path>/[^|]+?)\s+\|\s*(?P<method>[A-Z]+)\s+\|\s*(?P<response>\d+)\s+\|\s*(?P<count>\d+)\s+\|\s*(?P<status>[^|]+?)\s+\|$"
)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class ArtifactSpec:
    label: str
    source_relpath: str
    target_relpath: str
    kind: str = "file"
    expected_top_level_keys: tuple[str, ...] = ()
    expected_markers: tuple[str, ...] = ()


@dataclass
class ReadmeStructureSpec:
    required_h2_prefixes: tuple[str, ...]
    additional_h2_prefixes: tuple[str, ...] = ()
    enforce_required_order: bool = True


@dataclass
class PhaseSpec:
    name: str
    description: str
    expected_exit_code: int
    output_dir_name: str | None = None
    expected_console_phrases: tuple[str, ...] = ()
    readme_assertions: tuple[dict[str, str], ...] = ()
    fix_summary: tuple[str, ...] = ()
    file_transforms: dict[str, Callable[[str], str]] = field(default_factory=dict)
    include_readme_structure_checks: bool = False
    extra_assertions: Callable[["ValidationContext"], list[dict[str, Any]]] | None = None
    artifact_specs: tuple[ArtifactSpec, ...] = ()


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
    common_artifact_specs: tuple[ArtifactSpec, ...] = ()
    readme_structure: ReadmeStructureSpec | None = None
    setup_failure_message: str = "Workspace setup failed. See setup-output.json from the root setup command for details."
    clear_reports: Callable[["LabSpec"], None] | None = None
    post_phase_cleanup: Callable[["LabSpec"], None] | None = None


@dataclass
class ValidationContext:
    lab: LabSpec
    phase: PhaseSpec
    target_dir: Path
    command_result: CommandResult
    readme_text: str
    artifacts: dict[str, dict[str, Any]]
    original_files: dict[str, str]


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
        "--branch",
        default="main",
        help="Branch to use with --refresh-labs. Defaults to main.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required with --refresh-labs when ../labs has local changes. Discards tracked and untracked changes.",
    )
    return parser


def run_lab(spec: LabSpec, args: argparse.Namespace) -> int:
    spec.output_dir.mkdir(parents=True, exist_ok=True)
    readme_text = spec.readme_path.read_text(encoding="utf-8")
    original_files = {alias: path.read_text(encoding="utf-8") for alias, path in spec.files.items()}

    if args.refresh_report:
        print("Refreshing the report from existing captured artifacts...")
        phases = rebuild_phases_from_artifacts(spec, readme_text, original_files)
    else:
        phases = []
        try:
            if not args.skip_setup:
                print("Running workspace setup before lab execution...")
                setup_result = run_setup(
                    stream_output=True,
                    refresh_labs=args.refresh_labs,
                    target_branch=args.branch,
                    force=args.force,
                )
                if setup_result.status != "passed":
                    print(spec.setup_failure_message)
                    return 1

            for phase in spec.phases:
                print(f"Preparing {phase.name.lower()} lab state...")
                apply_phase_files(spec, phase, original_files)
                phase_result = execute_phase(spec, phase, readme_text, original_files)
                phases.append(phase_result)
        finally:
            restore_original_files(spec, original_files)
            if spec.post_phase_cleanup is not None:
                spec.post_phase_cleanup(spec)

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
    print(f"Wrote JSON report to {spec.output_dir / 'report.json'}")
    print(f"Wrote HTML report to {spec.output_dir / 'report.html'}")
    return 0 if report["status"] == "passed" else 1


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
    original_files: dict[str, str],
) -> dict[str, Any]:
    target_dir = spec.output_dir / phase_dir_name(phase)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if spec.clear_reports is not None:
        spec.clear_reports(spec)

    print(f"{phase.name}: starting verification...")
    result = run_command(spec.command, spec.upstream_lab, stream_output=True, stream_prefix=f"[{phase_dir_name(phase)}]")
    try:
        artifacts = capture_artifacts(spec, phase, target_dir)
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
        readme_text=readme_text,
        artifacts=artifacts,
        original_files=original_files,
    )
    return build_phase_result(context)


def rebuild_phases_from_artifacts(spec: LabSpec, readme_text: str, original_files: dict[str, str]) -> list[dict[str, Any]]:
    previous_commands = load_previous_phase_commands(spec.output_dir)
    phases: list[dict[str, Any]] = []
    for phase in spec.phases:
        target_dir = spec.output_dir / phase_dir_name(phase)
        ensure_artifact_set_exists(spec, phase, target_dir)
        artifacts = load_copied_artifacts(spec, phase, target_dir)
        command_output = (target_dir / "command.log").read_text(encoding="utf-8")
        command_info = previous_commands.get(phase.name, {})
        result = CommandResult(
            command=spec.command,
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
            readme_text=readme_text,
            artifacts=artifacts,
            original_files=original_files,
        )
        phases.append(build_phase_result(context))
    return phases


def build_phase_result(context: ValidationContext) -> dict[str, Any]:
    spec = context.lab
    phase = context.phase
    command_result = context.command_result
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
                detail("Command", " ".join(spec.command)),
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
        assertions.extend(phase.extra_assertions(context))

    assertions.extend(evaluate_readme_assertions(context))
    assertions.extend(evaluate_runtime_summary_drift(context))
    if phase.include_readme_structure_checks and spec.readme_structure is not None:
        assertions.extend(validate_readme_structure(context.readme_text, spec.readme_structure))

    phase_status = "passed" if all(item["status"] == "passed" for item in assertions) else "failed"
    return {
        "name": phase.name,
        "description": phase.description,
        "status": phase_status,
        "command": {
            "display": " ".join(spec.command),
            "exitCode": command_result.exit_code,
            "durationSeconds": round(command_result.duration_seconds, 2),
        },
        "assertions": assertions,
        "artifacts": build_artifact_links(spec, phase, context.target_dir),
        "consoleSnippet": shorten_console_output(command_result),
        "fixSummary": list(phase.fix_summary),
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
        artifacts[artifact.label] = load_artifact(target, artifact.kind)
    return artifacts


def load_copied_artifacts(spec: LabSpec, phase: PhaseSpec, target_dir: Path) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for artifact in all_artifact_specs(spec, phase):
        artifacts[artifact.label] = load_artifact(target_dir / artifact.target_relpath, artifact.kind)
    return artifacts


def load_artifact(path: Path, kind: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": path, "kind": kind}
    if kind == "json":
        payload["json"] = load_json(path)
        payload["text"] = path.read_text(encoding="utf-8")
    elif kind in {"html", "text"}:
        payload["text"] = path.read_text(encoding="utf-8")
    return payload


def all_artifact_specs(spec: LabSpec, phase: PhaseSpec) -> tuple[ArtifactSpec, ...]:
    return tuple(spec.common_artifact_specs) + tuple(phase.artifact_specs)


def apply_phase_files(spec: LabSpec, phase: PhaseSpec, original_files: dict[str, str]) -> None:
    for alias, path in spec.files.items():
        transform = phase.file_transforms.get(alias)
        content = original_files[alias] if transform is None else transform(original_files[alias])
        path.write_text(content, encoding="utf-8")


def restore_original_files(spec: LabSpec, original_files: dict[str, str]) -> None:
    for alias, path in spec.files.items():
        path.write_text(original_files[alias], encoding="utf-8")


def ensure_artifact_set_exists(spec: LabSpec, phase: PhaseSpec, target_dir: Path) -> None:
    required_paths = [target_dir / "command.log"] + [target_dir / artifact.target_relpath for artifact in all_artifact_specs(spec, phase)]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Cannot refresh the report because required artifacts are missing: " + ", ".join(missing)
        )


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
    lines = [line for line in result.combined_output.splitlines() if line.strip()]
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
    statuses_by_path = {item["path"]: item["coverageStatus"] for item in operations}
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
            }
        )

    return evaluated


def evaluate_runtime_summary_drift(context: ValidationContext) -> list[dict[str, Any]]:
    readme_text = context.readme_text
    console_output = strip_ansi(context.command_result.combined_output)
    normalized_readme = normalize_space(readme_text)
    assertions: list[dict[str, Any]] = []

    runtime_summary = extract_tests_run_summary(console_output)
    if runtime_summary is not None:
        assertions.append(
            assert_condition(
                normalize_space(runtime_summary) in normalized_readme,
                "README includes the exact observed runtime test summary.",
                "README does not include the exact observed runtime test summary.",
                category="readme",
                details=[
                    detail("Observed runtime summary", runtime_summary),
                    detail("Seen in README", normalize_space(runtime_summary) in normalized_readme),
                ],
            )
        )

    return assertions


def validate_readme_structure(readme_text: str, structure: ReadmeStructureSpec) -> list[dict[str, Any]]:
    headings = [(len(m.group(1)), m.group(2).strip()) for m in HEADING_RE.finditer(readme_text)]
    assertions: list[dict[str, Any]] = []
    h1_headings = [text for level, text in headings if level == 1]
    assertions.append(
        assert_equal(
            len(h1_headings),
            1,
            "README contained exactly one level-1 heading.",
            f"README expected exactly one level-1 heading, found {len(h1_headings)}.",
            category="readme",
            details=[detail("H1 headings", ", ".join(h1_headings) or "(none)")],
        )
    )

    for prefix in (*structure.required_h2_prefixes, *structure.additional_h2_prefixes):
        at_level = [text for level, text in headings if level == 2 and text.startswith(prefix)]
        wrong_level = [f"h{level} {text}" for level, text in headings if level != 2 and text.startswith(prefix)]
        assertions.append(
            assert_condition(
                bool(at_level),
                f"README contains the '{prefix}' section at level 2.",
                f"README is missing the '{prefix}' section at level 2.",
                category="readme",
                details=[
                    detail("Matching h2 headings", ", ".join(at_level) or "(none)"),
                    detail("Matching headings at wrong levels", ", ".join(wrong_level) or "(none)"),
                ],
            )
        )

    if structure.enforce_required_order:
        required_positions: list[tuple[str, int]] = []
        for prefix in structure.required_h2_prefixes:
            for index, (level, text) in enumerate(headings):
                if level == 2 and text.startswith(prefix):
                    required_positions.append((prefix, index))
                    break

        actual_prefixes = [prefix for prefix, _ in required_positions]
        actual_positions = [position for _, position in required_positions]
        order_is_correct = actual_positions == sorted(actual_positions) and actual_prefixes == list(structure.required_h2_prefixes)
        assertions.append(
            assert_condition(
                order_is_correct,
                "README required sections appear in the expected order.",
                "README required sections do not appear in the expected order.",
                category="readme",
                details=[
                    detail("Expected order", " -> ".join(structure.required_h2_prefixes)),
                    detail("Actual found order", " -> ".join(actual_prefixes) or "(none)"),
                ],
            )
        )
    return assertions


def extract_tests_run_summary(console_output: str) -> str | None:
    match = re.search(r"Tests run:\s*\d+,\s*Successes:\s*\d+,\s*Failures:\s*\d+,\s*Errors:\s*\d+", console_output)
    if not match:
        return None
    return match.group(0)


def extract_operations(context: ValidationContext) -> list[dict[str, Any]]:
    coverage_artifact = context.artifacts.get("coverage_report.json")
    if coverage_artifact and "json" in coverage_artifact:
        return coverage_artifact["json"].get("apiCoverage", [{}])[0].get("operations", [])
    html_artifact = first_html_artifact(context.artifacts)
    if html_artifact is None:
        return []
    report = parse_html_embedded_report(html_artifact["text"])
    return report["results"]["summary"]["extra"]["executionDetails"][0]["operations"]


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
    coverage = context.artifacts["coverage_report.json"]["json"]
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
            len(coverage["apiCoverage"][0]["operations"]),
            len(expected_operations),
            f"coverage_report.json contained {len(expected_operations)} operations as expected.",
            f"coverage_report.json expected {len(expected_operations)} operations, got {len(coverage['apiCoverage'][0]['operations'])}.",
            category="artifacts",
            details=[
                detail("Expected operations", len(expected_operations)),
                detail("Actual operations", len(coverage["apiCoverage"][0]["operations"])),
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

    operations = coverage["apiCoverage"][0]["operations"]
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

    assertions.extend(compare_console_coverage_with_reports(command_output, coverage, html_text))
    return assertions


def compare_console_coverage_with_reports(
    console_output: str,
    coverage_report: dict[str, Any],
    html_report_text: str,
) -> list[dict[str, Any]]:
    console_rows = parse_console_coverage_rows(console_output)
    report_rows = parse_coverage_report_rows(coverage_report)
    html_rows = parse_html_report_rows(normalize_html_report_text(html_report_text))
    normalized_html = normalize_html_report_text(html_report_text)
    console_summary = parse_console_coverage_summary(console_output)
    html_summary = parse_html_coverage_summary(normalized_html)

    assertions: list[dict[str, Any]] = []
    assertions.append(
        assert_equal(
            console_rows,
            report_rows,
            "Console coverage summary matched the JSON coverage report summary.",
            "Console coverage summary did not match the JSON coverage report summary.",
            category="report",
            details=[
                detail("Console coverage rows", format_coverage_rows(console_rows)),
                detail("Coverage report rows", format_coverage_rows(report_rows)),
            ],
        )
    )
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
            extract_row_counts(report_rows),
            extract_row_counts(html_rows),
            "Coverage report counts matched the generated Specmatic HTML results counts for every operation.",
            "Coverage report counts did not match the generated Specmatic HTML results counts for one or more operations.",
            category="report",
            details=[
                detail_table(
                    "Coverage report vs HTML results",
                    headers=["Path", "Method", "Response", "coverage_report.json count", "Specmatic HTML Results"],
                    rows=build_count_comparison_rows(report_rows, html_rows),
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
        cleaned = line
        if "| |" in cleaned:
            cleaned = cleaned.split("| ", 1)[1]
        cleaned = cleaned.strip()
        match = CONSOLE_COVERAGE_ROW_RE.match(cleaned)
        if not match:
            continue
        rows.append(
            {
                "coverage": match.group("coverage"),
                "path": match.group("path").strip(),
                "method": match.group("method").strip(),
                "response": int(match.group("response")),
                "count": int(match.group("count")),
                "status": match.group("status").strip(),
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
    match = re.search(r"\|\s*(\d+%) API Coverage reported from (\d+) Operations\s*\|", clean_output)
    if not match:
        return {"coverage": None, "operations": None}
    return {"coverage": match.group(1), "operations": int(match.group(2))}


def parse_html_coverage_summary(html_text: str) -> dict[str, Any]:
    report = parse_html_embedded_report(html_text)
    operations = report["results"]["summary"]["extra"]["executionDetails"][0]["operations"]
    total_operations = len(operations)
    covered_operations = sum(1 for operation in operations if operation["coverageStatus"] == "covered")
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
) -> dict[str, Any]:
    return {
        "status": "passed" if actual == expected else "failed",
        "message": success_message if actual == expected else failure_message,
        "category": category,
        "details": details or [],
    }


def assert_condition(
    condition: bool,
    success_message: str,
    failure_message: str,
    *,
    category: str,
    details: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": "passed" if condition else "failed",
        "message": success_message if condition else failure_message,
        "category": category,
        "details": details or [],
    }
