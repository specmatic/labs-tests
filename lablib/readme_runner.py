from __future__ import annotations

import argparse
from pathlib import Path
import re

from lablib.readme_expectations import command_output_skip_reason
from lablib.readme_schema import ReadmeDocument, ReadmePhase, parse_readme_document
from lablib.scaffold import LabSpec, PhaseSpec, add_standard_lab_args, extract_tests_run_summaries, parse_console_test_summary, run_lab


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_LABS = ROOT.parent / "labs"
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def upstream_lab_path(lab_name: str) -> Path:
    return UPSTREAM_LABS / lab_name


def readme_path_for_lab(lab_name: str) -> Path:
    return upstream_lab_path(lab_name) / "README.md"


def load_readme_document(readme_path: Path) -> ReadmeDocument:
    return parse_readme_document(readme_path.read_text(encoding="utf-8"))


def executable_shell_blocks(phase_doc: ReadmePhase) -> list[str]:
    return [
        block.body.strip()
        for block in phase_doc.command_blocks
        if (block.raw_language or "").lower() == "shell"
        and block.body.strip()
        and tracked_command_exit_code(block.body.strip())
    ]


def phase_expected_exit_code(phase_doc: ReadmePhase) -> int:
    summary_entries = extract_tests_run_summaries(phase_doc.content)
    summary_text = summary_entries[0]["summary"] if summary_entries else None
    summary_counts = parse_console_test_summary(summary_text)
    if summary_counts is None:
        return 0
    return 1 if (summary_counts["failed"] > 0 or summary_counts["other"] > 0) else 0


def tracked_command_exit_code(body: str) -> bool:
    return command_output_skip_reason(body) is None


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
        clear_reports=None,
        post_phase_cleanup=None,
    )


def build_readme_lab_parser(description: str) -> argparse.ArgumentParser:
    parser = add_standard_lab_args(argparse.ArgumentParser(description=description))
    parser.set_defaults(labs_branch="auto-labs-tests")
    return parser


def run_readme_lab(lab_name: str, description: str) -> int:
    parser = build_readme_lab_parser(description)
    args = parser.parse_args()
    return run_lab(build_readme_lab_spec(lab_name), args)
