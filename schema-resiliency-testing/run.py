from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lablib.scaffold import (
    ArtifactSpec,
    LabSpec,
    PhaseSpec,
    ReadmeStructureSpec,
    ValidationContext,
    add_standard_lab_args,
    assert_condition,
    clear_docker_owned_build_dir,
    detail,
    docker_compose_down,
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "schema-resiliency-testing"
README_FILE = UPSTREAM_LAB / "README.md"
SPECMATIC_FILE = UPSTREAM_LAB / "specmatic.yaml"
OUTPUT_DIR = ROOT / "schema-resiliency-testing" / "output"
LAB_COMMAND = ["docker", "compose", "up", "--abort-on-container-exit"]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the schema-resiliency-testing lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="schema-resiliency-testing",
        description="Automates the schema-resiliency-testing lab across none, positiveOnly, and all schema resiliency levels.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"specmatic": SPECMATIC_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
            ArtifactSpec("coverage_report.json", "build/reports/specmatic/coverage_report.json", "coverage_report.json", "json", ("apiCoverage",)),
            ArtifactSpec("ctrf-report.json", "build/reports/specmatic/test/ctrf/ctrf-report.json", "ctrf-report.json", "json", ("results",)),
            ArtifactSpec("specmatic-report.html", "build/reports/specmatic/test/html/index.html", "specmatic/test/html/index.html", "html", expected_markers=("const report =", "specmaticConfig", "<html")),
            ArtifactSpec("specmatic.yaml", "specmatic.yaml", "specmatic.yaml", "text"),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Time required to complete this lab",
                "Prerequisites",
                "Files in this lab",
                "Start Studio using Docker Compose",
                "Loop Test",
                "Goal of this lab",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Loop test baseline",
                description="Run the suite with schemaResiliencyTests set to none and verify the loop-test baseline.",
                expected_exit_code=0,
                output_dir_name="baseline",
                readme_summary_query="2. Loop Test using CLI",
                expected_console_phrases=(),
                include_readme_structure_checks=True,
                readme_assertions=(),
                file_transforms={"specmatic": set_none},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Positive only",
                description="Set schemaResiliencyTests to positiveOnly and verify the expanded positive test count.",
                expected_exit_code=0,
                output_dir_name="positive-only",
                readme_summary_query="Positive Only Tests",
                expected_console_phrases=(),
                readme_assertions=(),
                file_transforms={"specmatic": set_positive_only},
                extra_assertions=positive_only_assertions,
            ),
            PhaseSpec(
                name="All resiliency",
                description="Set schemaResiliencyTests to all and verify the full resiliency matrix.",
                expected_exit_code=0,
                output_dir_name="all",
                readme_summary_query="Positive and Negative Tests (ALL)",
                expected_console_phrases=(),
                readme_assertions=(),
                file_transforms={"specmatic": set_all},
                extra_assertions=all_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return common_resiliency_assertions(context, mode="none")


def positive_only_assertions(context: ValidationContext) -> list[dict]:
    return common_resiliency_assertions(context, mode="positiveOnly")


def all_assertions(context: ValidationContext) -> list[dict]:
    return common_resiliency_assertions(context, mode="all")


def common_resiliency_assertions(context: ValidationContext, *, mode: str) -> list[dict]:
    return [
        assert_condition(
            f"schemaResiliencyTests: {mode}" in context.artifacts["specmatic.yaml"]["text"],
            f"specmatic.yaml is configured for schemaResiliencyTests={mode}.",
            f"specmatic.yaml is not configured for schemaResiliencyTests={mode}.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_mode(content: str, mode: str) -> str:
    return content.replace("schemaResiliencyTests: none", f"schemaResiliencyTests: {mode}").replace("schemaResiliencyTests: positiveOnly", f"schemaResiliencyTests: {mode}").replace("schemaResiliencyTests: all", f"schemaResiliencyTests: {mode}")


def set_none(content: str) -> str:
    return set_mode(content, "none")


def set_positive_only(content: str) -> str:
    return set_mode(content, "positiveOnly")


def set_all(content: str) -> str:
    return set_mode(content, "all")


if __name__ == "__main__":
    raise SystemExit(main())
