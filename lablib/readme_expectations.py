from __future__ import annotations

from dataclasses import dataclass, field
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

README_V2_H2_SEQUENCE = (
    "Objective",
    "Why this lab matters",
    "Time required to complete this lab",
    "Prerequisites",
    "Architecture",
    "Files in this lab",
    "Lab Rules",
    "Specmatic references",
    "Lab Implementation Phases",
    "Pass Criteria",
    "Troubleshooting",
    "Cleanup",
    "What you learned",
    "Next step",
)


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
    shared_h2=(
        SectionRule(
            title="Files in this lab",
            level=2,
            heading_type="files",
            notes="List the important files the learner will touch or inspect.",
        ),
        SectionRule(
            title="Lab Rules",
            level=2,
            heading_type="rules",
            notes="Document constraints that should remain true while working through the lab.",
        ),
        SectionRule(
            title="Next step",
            level=2,
            heading_type="next-step",
            notes="Point the reader to the next lab or follow-up action.",
        ),
        SectionRule(
            title="Objective",
            level=2,
            heading_type="objective",
            notes="State the concrete learning outcome for this lab.",
        ),
        SectionRule(
            title="Prerequisites",
            level=2,
            heading_type="prerequisites",
            notes="Call out what the learner needs before starting the lab.",
        ),
        SectionRule(
            title="Specmatic references",
            level=2,
            heading_type="references",
            notes="Link relevant Specmatic docs or references that help explain the lab.",
        ),
        SectionRule(
            title="Time required to complete this lab",
            level=2,
            heading_type="time-required",
            notes="Give the expected time to complete the lab.",
        ),
        SectionRule(
            title="Lab Time",
            level=2,
            heading_type="lab-time",
            notes="Reserved for any additional time/context section used across labs.",
        ),
        SectionRule(
            title="What you learned",
            level=2,
            heading_type="what-you-learned",
            notes="Summarize the key takeaways from the lab.",
        ),
        SectionRule(
            title="Why this lab matters",
            level=2,
            heading_type="why-it-matters",
            notes="Explain why this workflow or concept matters in practice.",
        ),
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
    optional_h2=(
        SectionRule(
            title="Troubleshooting",
            level=2,
            heading_type="troubleshooting",
            required=False,
            notes="Optional, but recommended when the lab has non-obvious failure modes.",
        ),
        SectionRule(
            title="Pass criteria",
            level=2,
            heading_type="pass-criteria",
            required=False,
            notes="Optional, but recommended when the README needs explicit verify-the-fix guidance.",
        ),
    ),
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


EXPECTED_README_H2_SEQUENCE = tuple(section.title for section in README_TEMPLATE.shared_h2)


def normalize_heading_title(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.replace("`", "")).strip().lower()
    return normalized.rstrip(":")


def heading_matches(actual: str, expected: str) -> bool:
    return normalize_heading_title(actual) == normalize_heading_title(expected)


def get_lab_readme_override(lab_name: str) -> LabReadmeOverride:
    return LAB_README_OVERRIDES.get(lab_name, LabReadmeOverride())


def shared_h2_titles() -> tuple[str, ...]:
    return tuple(section.title for section in README_TEMPLATE.shared_h2)


def optional_h2_titles() -> tuple[str, ...]:
    return tuple(section.title for section in README_TEMPLATE.optional_h2)


def allowed_h2_titles_for_lab(lab_name: str) -> tuple[str, ...]:
    override = get_lab_readme_override(lab_name)
    return (*shared_h2_titles(), *optional_h2_titles(), *override.allowed_additional_h2_titles, *README_V2_H2_SEQUENCE)


def unexpected_h2_titles_for_lab(lab_name: str, actual_h2_titles: list[str] | tuple[str, ...]) -> list[str]:
    allowed = allowed_h2_titles_for_lab(lab_name)
    return [
        title
        for title in actual_h2_titles
        if not any(heading_matches(title, expected) for expected in allowed)
    ]


def missing_shared_h2_titles(actual_h2_titles: list[str] | tuple[str, ...]) -> list[str]:
    return [
        expected
        for expected in shared_h2_titles()
        if not any(heading_matches(actual, expected) for actual in actual_h2_titles)
    ]


def shared_h2_sequence_matches(actual_h2_titles: list[str] | tuple[str, ...]) -> bool:
    matched_shared = [
        actual
        for actual in actual_h2_titles
        if any(heading_matches(actual, expected) for expected in shared_h2_titles())
    ]
    if len(matched_shared) != len(shared_h2_titles()):
        return False
    return all(
        heading_matches(actual, expected)
        for actual, expected in zip(matched_shared, shared_h2_titles())
    )


def title_present(actual_titles: list[str] | tuple[str, ...], expected_title: str) -> bool:
    return any(heading_matches(actual, expected_title) for actual in actual_titles)
