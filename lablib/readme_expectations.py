from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


EXECUTABLE_COMMAND_FENCE_LANGUAGES = (
    "shell",
)

MAC_LINUX_COMMAND_FENCE_LANGUAGES = (
    "shell",
)

WINDOWS_COMMAND_FENCE_LANGUAGES = (
    "shell",
)

OUTPUT_FENCE_LANGUAGE = "terminaloutput"
STRUCTURED_FILE_DISPLAY_FENCE_LANGUAGES = (
    "yaml",
    "json",
)


def is_structured_file_display_language(language: str) -> bool:
    return (language or "").lower() in STRUCTURED_FILE_DISPLAY_FENCE_LANGUAGES


def command_output_skip_reason(command: str) -> str | None:
    normalized = " ".join(command.strip().lower().split())
    if not normalized:
        return None
    if (
        ("docker compose" in normalized or "docker-compose" in normalized)
        and " down" in f" {normalized}"
    ):
        return "terminaloutput is not required for teardown commands"
    if (
        ("docker compose" in normalized or "docker-compose" in normalized)
        and normalized.endswith(" pull")
    ):
        return "terminaloutput is not required for docker image pull commands"
    if (
        ("docker compose" in normalized or "docker-compose" in normalized)
        and " stop " in f" {normalized} "
    ):
        return "terminaloutput is not required for service stop commands"
    if (
        ("docker compose" in normalized or "docker-compose" in normalized)
        and " up" in f" {normalized}"
        and "--abort-on-container-exit" not in normalized
        and "--exit-code-from" not in normalized
    ):
        return "terminaloutput is not required for service startup commands"
    teardown_prefixes = ("docker stop", "docker rm")
    if normalized.startswith(teardown_prefixes):
        return "terminaloutput is not required for teardown commands"
    if normalized.startswith("chmod "):
        return "terminaloutput is not required for file-permission setup commands"
    if normalized.startswith("git update-index "):
        return "terminaloutput is not required for git index setup commands"
    return None

def load_h2_sequence() -> tuple[str, ...]:
    sequence_file = Path(__file__).with_name("readme_h2_sequence.yaml")
    lines = sequence_file.read_text(encoding="utf-8").splitlines()
    items: list[str] = []
    inside_sequence = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "shared_h2_sequence:":
            inside_sequence = True
            continue
        if inside_sequence:
            if stripped.startswith("- "):
                items.append(stripped[2:].strip())
                continue
            if not raw_line.startswith(" "):
                break
    if not items:
        raise ValueError(f"No shared_h2_sequence entries found in {sequence_file}")
    return tuple(items)


CANONICAL_README_H2_SEQUENCE = load_h2_sequence()


@dataclass(frozen=True)
class SectionContentRule:
    """Declarative content expectations for a section."""

    requires_executable_command_block: bool = False
    requires_terminal_output_block: bool = False
    requires_os_specific_commands: bool = False
    requires_matching_os_specific_output: bool = False
    allowed_command_fence_languages: tuple[str, ...] = EXECUTABLE_COMMAND_FENCE_LANGUAGES
    allowed_output_fence_languages: tuple[str, ...] = (OUTPUT_FENCE_LANGUAGE,)
    ignore_leading_datetime_in_output: bool = True


@dataclass(frozen=True)
class SectionRule:
    """
    Schema rule for an expected heading.

    `heading_type` is semantic rather than presentational so validation can stay
    stable even when heading text changes slightly.
    """

    title: str
    level: int
    heading_type: str
    required: bool = True
    ordered: bool = True
    repeatable: bool = False
    allow_additional_children: bool = True
    content_rule: SectionContentRule = field(default_factory=SectionContentRule)
    notes: str = ""


@dataclass(frozen=True)
class ReadmeTemplate:
    """
    Canonical README template for Specmatic labs.

    This schema is intentionally declarative so:
    - validators can consume one shared source of truth
    - comparison reports can explain requirements from the same schema
    - the expected H2 sequence can still be derived from the richer template
    """

    version: str
    h1_mode: str
    h1_notes: str
    shared_h2: tuple[SectionRule, ...]
    implementation_h3_rule: SectionRule
    studio_h3_rule: SectionRule
    optional_h2: tuple[SectionRule, ...] = ()


@dataclass(frozen=True)
class LabReadmeOverride:
    """
    Per-lab schema adjustments.

    These are for real structural differences we want to model centrally rather
    than hiding in ad hoc ignore annotations.
    """

    allowed_manual_h3_titles: tuple[str, ...] = ()
    allowed_additional_h2_titles: tuple[str, ...] = ()
    allowed_additional_h3_titles: tuple[str, ...] = ()
    studio_steps_are_manual_only: bool = False
    notes: tuple[str, ...] = ()


def command_blocks_have_any_language(command_blocks, allowed_languages) -> bool:
    return any(command_block_language(block) in allowed_languages for block in command_blocks)


def command_block_language(command_block) -> str:
    return (command_block.language or "").lower()


README_TEMPLATE = ReadmeTemplate(
    version="1.0",
    h1_mode="lab-specific-title",
    h1_notes="Every lab README should start with one H1. The title text is lab-specific, but the single-H1 structure is shared.",
    shared_h2=tuple(
        SectionRule(
            title=title,
            level=2,
            heading_type=re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
            notes=(
                "List the important files the learner will touch or inspect."
                if title == "Files in this lab"
                else "Document constraints that should remain true while working through the lab."
                if title == "Lab Rules"
                else "Point the reader to the next lab or follow-up action."
                if title == "Next step"
                else "State the concrete learning outcome for this lab."
                if title == "Objective"
                else "Call out what the learner needs before starting the lab."
                if title == "Prerequisites"
                else "Link relevant Specmatic docs or references that help explain the lab."
                if title == "Specmatic references"
                else "Give the expected time to complete the lab."
                if title == "Time required to complete this lab"
                else "Explain why this workflow or concept matters in practice."
                if title == "Why this lab matters"
                else "Document the main lab implementation phases in order."
                if title == "Lab Implementation Phases"
                else "Spell out how the learner knows the lab is complete."
                if title == "Pass Criteria"
                else "Help the reader recover from non-obvious issues."
                if title == "Troubleshooting"
                else "Explain how to clean up local state after the lab."
                if title == "Cleanup"
                else "Summarize the key takeaways from the lab."
                if title == "What you learned"
                else "Describe the high-level system or flow before implementation."
                if title == "Architecture"
                else ""
            ),
        )
        for title in CANONICAL_README_H2_SEQUENCE
    ),
    implementation_h3_rule=SectionRule(
        title="Implementation step",
        level=3,
        heading_type="implementation-step",
        required=False,
        repeatable=True,
        content_rule=SectionContentRule(
            requires_executable_command_block=True,
            requires_terminal_output_block=True,
            requires_os_specific_commands=True,
            requires_matching_os_specific_output=True,
        ),
        notes="Lab-specific walkthrough steps should be H3 sections. Each documented command should be followed by terminaloutput. When commands differ by OS, outputs should differ by OS too.",
    ),
    studio_h3_rule=SectionRule(
        title="Studio step",
        level=3,
        heading_type="studio-step",
        required=False,
        repeatable=True,
        content_rule=SectionContentRule(
            requires_executable_command_block=False,
            requires_terminal_output_block=False,
            requires_os_specific_commands=False,
            requires_matching_os_specific_output=False,
        ),
        notes="Studio-specific steps may be documented as H3 sections. They can be tracked as manual/not-yet-automated without failing labs-tests.",
    ),
    optional_h2=(),
)


LAB_README_OVERRIDES: dict[str, LabReadmeOverride] = {
    "filters": LabReadmeOverride(
        allowed_manual_h3_titles=(
            "Start Studio",
            "Run tests in Studio",
        ),
        studio_steps_are_manual_only=True,
        notes=(
            "The upstream README currently documents a Studio path after the baseline CLI run.",
            "labs-tests should report that Studio path as manual/not-yet-automated guidance rather than a runtime failure.",
        ),
    ),
}


def normalize_heading_title(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.replace("`", "")).strip().lower()
    return normalized.rstrip(":")


def heading_matches(actual: str, expected: str) -> bool:
    return normalize_heading_title(actual) == normalize_heading_title(expected)


def get_lab_readme_override(lab_name: str) -> LabReadmeOverride:
    return LAB_README_OVERRIDES.get(lab_name, LabReadmeOverride())


def canonical_h2_titles() -> tuple[str, ...]:
    return CANONICAL_README_H2_SEQUENCE


def optional_h2_titles() -> tuple[str, ...]:
    return tuple(section.title for section in README_TEMPLATE.optional_h2)


def allowed_h2_titles_for_lab(lab_name: str) -> tuple[str, ...]:
    override = get_lab_readme_override(lab_name)
    return (*CANONICAL_README_H2_SEQUENCE, *optional_h2_titles(), *override.allowed_additional_h2_titles)


def unexpected_h2_titles_for_lab(lab_name: str, actual_h2_titles: list[str] | tuple[str, ...]) -> list[str]:
    allowed = allowed_h2_titles_for_lab(lab_name)
    return [
        title
        for title in actual_h2_titles
        if not any(heading_matches(title, expected) for expected in allowed)
    ]


def missing_canonical_h2_titles(actual_h2_titles: list[str] | tuple[str, ...]) -> list[str]:
    return [
        expected
        for expected in canonical_h2_titles()
        if not any(heading_matches(actual, expected) for actual in actual_h2_titles)
    ]


def canonical_h2_sequence_matches(actual_h2_titles: list[str] | tuple[str, ...]) -> bool:
    matched_shared = [
        actual
        for actual in actual_h2_titles
        if any(heading_matches(actual, expected) for expected in canonical_h2_titles())
    ]
    if len(matched_shared) != len(canonical_h2_titles()):
        return False
    return all(
        heading_matches(actual, expected)
        for actual, expected in zip(matched_shared, canonical_h2_titles())
    )


def title_present(actual_titles: list[str] | tuple[str, ...], expected_title: str) -> bool:
    return any(heading_matches(actual, expected_title) for actual in actual_titles)
