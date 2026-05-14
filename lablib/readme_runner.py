from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil

from lablib.readme_expectations import command_execution_skip_reason
from lablib.readme_schema import ReadmeDocument, ReadmePhase, parse_readme_document
from lablib.scaffold import (
    LabSpec,
    PhaseSpec,
    add_standard_lab_args,
    docker_compose_down,
    extract_tests_run_summaries,
    parse_console_test_summary,
    run_lab,
)


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_LABS = ROOT.parent / "labs"
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
COMPOSE_UP_RE = re.compile(
    r"^(?P<prefix>\s*(?:docker compose|docker-compose)(?:\s+--profile\s+\S+)*)\s+up\b(?P<suffix>.*)$"
)


def upstream_lab_path(lab_name: str) -> Path:
    return UPSTREAM_LABS / lab_name


def readme_path_for_lab(lab_name: str) -> Path:
    return upstream_lab_path(lab_name) / "README.md"


def load_readme_document(readme_path: Path) -> ReadmeDocument:
    return parse_readme_document(readme_path.read_text(encoding="utf-8"))


def executable_shell_blocks(phase_doc: ReadmePhase) -> list[str]:
    return [
        execution_command_body(block.body.strip())
        for block in phase_doc.command_blocks
        if (block.raw_language or "").lower() == "shell"
        and block.body.strip()
        and should_execute_command(phase_doc, block.body.strip())
    ]


def phase_expected_exit_code(phase_doc: ReadmePhase) -> int:
    summary_entries = extract_tests_run_summaries(phase_doc.content)
    summary_text = summary_entries[0]["summary"] if summary_entries else None
    summary_counts = parse_console_test_summary(summary_text)
    if summary_counts is None:
        return 0
    return 1 if (summary_counts["failed"] > 0 or summary_counts["other"] > 0) else 0


def should_execute_command(phase_doc: ReadmePhase, body: str) -> bool:
    if phase_doc.id == "studio":
        return False
    return command_execution_skip_reason(body) is None


def tracked_command_exit_code(body: str) -> bool:
    return command_execution_skip_reason(body) is None


def execution_command_body(body: str) -> str:
    if is_background_startup_compose_command(body):
        return detached_compose_command(body)
    return body


def is_background_startup_compose_command(body: str) -> bool:
    normalized = " ".join(body.strip().lower().split())
    if not normalized:
        return False
    if ("docker compose" not in normalized and "docker-compose" not in normalized) or " up" not in f" {normalized}":
        return False
    return "--abort-on-container-exit" not in normalized and "--exit-code-from" not in normalized and " -d" not in f" {normalized} "


def detached_compose_command(body: str) -> str:
    match = COMPOSE_UP_RE.match(body.strip())
    if match is None:
        if "docker compose up" in body:
            return body.replace("docker compose up", "docker compose up -d", 1)
        if "docker-compose up" in body:
            return body.replace("docker-compose up", "docker-compose up -d", 1)
        return body

    prefix = match.group("prefix")
    suffix = match.group("suffix")
    return "\n".join(
        [
            f"{prefix} down -v --remove-orphans >/dev/null 2>&1 || true",
            f"{prefix} up -d{suffix}",
        ]
    )


def build_phase_script_from_blocks(command_bodies: list[str]) -> str:
    if not command_bodies:
        return ""

    script_lines = ["phase_status=0", "phase_status_set=0"]
    for body in command_bodies:
        script_lines.extend(build_script_lines_for_command(body))
    script_lines.extend(final_phase_exit_lines())
    return "\n".join(script_lines)


def build_script_lines_for_command(body: str) -> list[str]:
    lines = ["{", body, "}"]
    if tracked_command_exit_code(body):
        lines.extend(
            [
                "block_status=$?",
                "phase_status=$block_status",
                "phase_status_set=1",
            ]
        )
    return lines


def final_phase_exit_lines() -> list[str]:
    return [
        'if [ "$phase_status_set" -eq 1 ]; then',
        "  exit $phase_status",
        "fi",
        "exit 0",
    ]


def slugify_phase_title(title: str) -> str:
    normalized = NON_ALNUM_RE.sub("-", title.lower()).strip("-")
    return normalized or "phase"


def phase_output_dir_name(phase_doc: ReadmePhase) -> str:
    if phase_doc.id and (phase_doc.id.startswith("task-") or phase_doc.id.startswith("ad-hoc-")):
        return slugify_phase_title(phase_doc.title)
    return phase_doc.id or slugify_phase_title(phase_doc.title)


def build_phase_spec(phase_doc: ReadmePhase) -> PhaseSpec | None:
    if phase_doc.id == "studio":
        return None
    command_bodies = executable_shell_blocks(phase_doc)
    if not command_bodies:
        return None

    combined_script = build_phase_script_from_blocks(command_bodies)
    if not combined_script:
        return None

    return PhaseSpec(
        name=phase_doc.title,
        description=phase_doc.title,
        expected_exit_code=phase_expected_exit_code(phase_doc),
        readme_phase_id=phase_doc.id,
        command=["/bin/sh", "-lc", combined_script],
        output_dir_name=phase_output_dir_name(phase_doc),
    )


def build_phase_specs(document: ReadmeDocument) -> tuple[PhaseSpec, ...]:
    phases: list[PhaseSpec] = []
    for phase_doc in document.phases:
        phase_spec = build_phase_spec(phase_doc)
        if phase_spec is not None:
            phases.append(phase_spec)
    if not phases:
        raise ValueError(
            "README does not contain any executable shell-command phases under a recognizable heading."
        )
    return tuple(phases)


def build_readme_lab_spec(lab_name: str) -> LabSpec:
    upstream_lab = upstream_lab_path(lab_name)
    readme_path = readme_path_for_lab(lab_name)
    document = load_readme_document(readme_path)
    phases = build_phase_specs(document)
    runtime_cleanup = readme_lab_runtime_cleanup if (upstream_lab / "docker-compose.yaml").exists() else None

    return LabSpec(
        name=lab_name,
        description=f"README-driven automation for {lab_name}.",
        root=ROOT,
        upstream_lab=upstream_lab,
        files={},
        readme_path=readme_path,
        output_dir=ROOT / "output" / "labs-output" / f"{lab_name}-output",
        command=phases[0].command or ["true"],
        phases=phases,
        clear_reports=runtime_cleanup,
        post_phase_cleanup=runtime_cleanup,
    )


def build_readme_lab_parser(description: str) -> argparse.ArgumentParser:
    parser = add_standard_lab_args(argparse.ArgumentParser(description=description))
    parser.set_defaults(labs_branch="auto-labs-tests")
    return parser


def run_readme_lab(lab_name: str, description: str) -> int:
    parser = build_readme_lab_parser(description)
    args = parser.parse_args()
    return run_lab(build_readme_lab_spec(lab_name), args)


def readme_lab_runtime_cleanup(spec: LabSpec) -> None:
    compose_file = spec.upstream_lab / "docker-compose.yaml"
    if compose_file.exists():
        docker_compose_down(spec, "down", "-v", "--remove-orphans")

    build_dir = spec.upstream_lab / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)
