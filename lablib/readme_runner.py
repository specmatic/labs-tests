from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import re
import shlex
from types import ModuleType
from typing import Any, Callable

from lablib.readme_expectations import command_output_skip_reason
from lablib.readme_schema import CodeBlock, Heading, extract_code_blocks, extract_headings, parse_readme_document
from lablib.scaffold import ArtifactSpec, LabSpec, PhaseSpec, clear_docker_owned_build_dir, docker_compose_down


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_LABS = ROOT.parent / "labs"
IMPLEMENTATION_HEADING = "Lab Implementation Phases"
POST_IMPLEMENTATION_H2 = {
    "Pass Criteria",
    "Troubleshooting",
    "Cleanup",
    "What you learned",
    "Next step",
}
TEST_COUNTS_RE = re.compile(
    r"Tests run:\s*(?P<tests>\d+),\s*Successes:\s*(?P<successes>\d+),\s*Failures:\s*(?P<failures>\d+)(?:,\s*Errors:\s*(?P<errors>\d+))?",
    re.IGNORECASE,
)
PHASE_TITLE_PREFIXES = {
    "baseline": ("baseline",),
    "final": ("final", "fixed", "re-run", "rerun"),
    "intermediate": ("intermediate", "task "),
    "studio": ("studio",),
}


@dataclass(frozen=True)
class ExpectedTestCounts:
    tests: int
    successes: int
    failures: int
    errors: int = 0


@dataclass(frozen=True)
class ReadmeExecutionPhase:
    id: str
    title: str
    command: list[str]
    expected_output: str
    expected_counts: ExpectedTestCounts | None
    expected_exit_code: int
    output_dir_name: str
    description: str


@dataclass(frozen=True)
class ReadmeExecutionPlan:
    lab_name: str
    upstream_lab: Path
    readme_path: Path
    phases: tuple[ReadmeExecutionPhase, ...]


@dataclass(frozen=True)
class ReadmePhaseSection:
    id: str
    title: str
    heading: Heading
    content: str
    code_blocks: tuple[CodeBlock, ...]


@dataclass(frozen=True)
class LabHooks:
    module: ModuleType | None = None

    def files(self, upstream_lab: Path) -> dict[str, Path]:
        return call_hook(self.module, "files", {}, upstream_lab)

    def common_artifact_specs(self) -> tuple[ArtifactSpec, ...]:
        return tuple(call_hook(self.module, "common_artifact_specs", ()))

    def command_env(self) -> dict[str, str]:
        return call_hook(self.module, "command_env", {})

    def phase_file_transforms(self, phase_id: str, phase_title: str) -> dict[str, Callable[[str], str]]:
        return call_hook(self.module, "phase_file_transforms", {}, phase_id, phase_title)

    def extra_assertions(self, phase_id: str, phase_title: str) -> Callable[[Any], list[dict[str, Any]]] | None:
        return call_hook(self.module, "extra_assertions", None, phase_id, phase_title)

    def fix_summary(self, phase_id: str, phase_title: str) -> tuple[str, ...]:
        return tuple(call_hook(self.module, "fix_summary", (), phase_id, phase_title))


def parse_lab_execution_plan(upstream_lab_path: Path) -> ReadmeExecutionPlan:
    readme_path = upstream_lab_path / "README.md"
    readme_text = readme_path.read_text(encoding="utf-8")
    sections = extract_readme_phase_sections(readme_text)
    phases = tuple(build_execution_phase(section) for section in sections if phase_has_primary_command(section))
    return ReadmeExecutionPlan(
        lab_name=upstream_lab_path.name,
        upstream_lab=upstream_lab_path,
        readme_path=readme_path,
        phases=phases,
    )


def build_readme_lab_spec(lab_name: str) -> LabSpec:
    upstream_lab = UPSTREAM_LABS / lab_name
    plan = parse_lab_execution_plan(upstream_lab)
    hooks = load_lab_hooks(lab_name)
    readme_path = plan.readme_path
    specmatic_yaml = upstream_lab / "specmatic.yaml"
    default_file = specmatic_yaml if specmatic_yaml.exists() else readme_path
    files = {"default": default_file, **hooks.files(upstream_lab)}
    return LabSpec(
        name=lab_name,
        description=f"README-driven automation for {lab_name}.",
        root=ROOT,
        upstream_lab=upstream_lab,
        files=files,
        readme_path=readme_path,
        output_dir=ROOT / lab_name / "output",
        command=plan.phases[0].command if plan.phases else ["true"],
        command_env=hooks.command_env(),
        phases=tuple(
            PhaseSpec(
                name=phase.title,
                description=phase.description,
                expected_exit_code=phase.expected_exit_code,
                readme_phase_id=phase.id,
                command=phase.command,
                output_dir_name=phase.output_dir_name,
                file_transforms=hooks.phase_file_transforms(phase.id, phase.title),
                extra_assertions=hooks.extra_assertions(phase.id, phase.title),
                fix_summary=hooks.fix_summary(phase.id, phase.title),
            )
            for phase in plan.phases
        ),
        common_artifact_specs=default_specmatic_artifacts() + hooks.common_artifact_specs(),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def load_lab_hooks(lab_name: str) -> LabHooks:
    return load_hooks_from_path(ROOT / lab_name / "hooks.py", module_name=f"labs_tests_hooks_{slug(lab_name)}")


def load_hooks_from_path(path: Path, *, module_name: str = "labs_tests_hooks") -> LabHooks:
    if not path.exists():
        return LabHooks()
    spec = importlib.util.spec_from_file_location(module_name.replace("-", "_"), path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load hooks from {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to import hooks from {path}: {exc}") from exc
    return LabHooks(module)


def call_hook(module: ModuleType | None, name: str, default: Any, *args: Any) -> Any:
    if module is None or not hasattr(module, name):
        return default
    hook = getattr(module, name)
    try:
        return hook(*args)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Hook {module.__name__}.{name} failed: {exc}") from exc


def extract_readme_phase_sections(readme_text: str) -> tuple[ReadmePhaseSection, ...]:
    document = parse_readme_document(readme_text)
    if document.phases:
        return tuple(
            ReadmePhaseSection(
                id=phase.id,
                title=phase.title,
                heading=phase.heading,
                content=phase.content,
                code_blocks=tuple(phase.code_blocks),
            )
            for phase in document.phases
        )

    headings = extract_headings(readme_text)
    implementation_heading = next(
        (heading for heading in headings if heading.level == 2 and heading.title == IMPLEMENTATION_HEADING),
        None,
    )
    if implementation_heading is None:
        return extract_phase_sections_from_heading_range(readme_text, headings, headings[0].start if headings else 0, len(readme_text))

    implementation_end = next(
        (
            heading.start
            for heading in headings
            if heading.level == 2
            and heading.start > implementation_heading.start
            and heading.title in POST_IMPLEMENTATION_H2
        ),
        len(readme_text),
    )
    return extract_phase_sections_from_heading_range(readme_text, headings, implementation_heading.start, implementation_end)


def extract_phase_sections_from_heading_range(
    readme_text: str,
    headings: list[Heading],
    start: int,
    end: int,
) -> tuple[ReadmePhaseSection, ...]:
    phase_headings = [
        heading
        for heading in headings
        if heading.start > start
        and heading.start < end
        and heading.title != IMPLEMENTATION_HEADING
        and infer_phase_id(heading.title) is not None
    ]

    sections: list[ReadmePhaseSection] = []
    for index, heading in enumerate(phase_headings):
        phase_id = infer_phase_id(heading.title)
        if phase_id is None:
            continue
        next_heading = phase_headings[index + 1] if index + 1 < len(phase_headings) else None
        section_end = next_heading.start if next_heading else end
        content = readme_text[heading.start:section_end].strip()
        sections.append(
            ReadmePhaseSection(
                id=phase_id,
                title=heading.title,
                heading=heading,
                content=content,
                code_blocks=tuple(extract_code_blocks(content)),
            )
        )
    return tuple(sections)


def build_execution_phase(section: ReadmePhaseSection) -> ReadmeExecutionPhase:
    command_block, output_block = primary_command_and_output(section)
    expected_counts = parse_expected_test_counts(output_block.body if output_block else "")
    return ReadmeExecutionPhase(
        id=section.id,
        title=section.title,
        command=parse_command(command_block.body),
        expected_output=output_block.body if output_block else "",
        expected_counts=expected_counts,
        expected_exit_code=expected_exit_code(expected_counts),
        output_dir_name=phase_output_dir_name(section),
        description=f"Run README phase: {section.title}.",
    )


def phase_has_primary_command(section: ReadmePhaseSection) -> bool:
    return primary_command_and_output(section)[0] is not None


def primary_command_and_output(section: ReadmePhaseSection) -> tuple[CodeBlock | None, CodeBlock | None]:
    blocks = list(section.code_blocks)
    for index, block in enumerate(blocks):
        if not block.is_command or block.raw_language != "shell":
            continue
        if command_output_skip_reason(block.body):
            continue
        next_block = blocks[index + 1] if index + 1 < len(blocks) else None
        return block, next_block if next_block is not None and next_block.is_output else None
    return None, None


def parse_expected_test_counts(output: str) -> ExpectedTestCounts | None:
    match = TEST_COUNTS_RE.search(output)
    if not match:
        return None
    return ExpectedTestCounts(
        tests=int(match.group("tests")),
        successes=int(match.group("successes")),
        failures=int(match.group("failures")),
        errors=int(match.group("errors") or 0),
    )


def expected_exit_code(counts: ExpectedTestCounts | None) -> int:
    if counts is None:
        return 0
    return 1 if counts.failures or counts.errors else 0


def parse_command(command: str) -> list[str]:
    normalized = command.replace("\\\n", " ")
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    return shlex.split(" ".join(lines))


def infer_phase_id(title: str) -> str | None:
    normalized = normalize_phase_title(title)
    for phase_id, prefixes in PHASE_TITLE_PREFIXES.items():
        if normalized.startswith(prefixes):
            return phase_id
    return None


def normalize_phase_title(title: str) -> str:
    normalized = title.strip().lower()
    normalized = re.sub(r"^\d+[.)]\s*", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def phase_output_dir_name(section: ReadmePhaseSection) -> str:
    if section.id == "baseline":
        return "baseline"
    if section.id == "final":
        return "fixed"
    task_match = re.match(r"task\s+([a-z0-9]+)", normalize_phase_title(section.title))
    if task_match:
        return f"task-{task_match.group(1)}"
    return slug(section.title)


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "phase"


def default_specmatic_artifacts() -> tuple[ArtifactSpec, ...]:
    return (
        ArtifactSpec(
            label="ctrf-report.json",
            source_relpath="build/reports/specmatic/test/ctrf/ctrf-report.json",
            target_relpath="ctrf-report.json",
            kind="json",
            expected_top_level_keys=("results",),
        ),
        ArtifactSpec(
            label="specmatic-report.html",
            source_relpath="build/reports/specmatic/test/html/index.html",
            target_relpath="specmatic/test/html/index.html",
            kind="html",
            expected_markers=("const report =", "specmaticConfig", "<html"),
        ),
    )


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")
