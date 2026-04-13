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
    build_coverage_assertions,
    clear_docker_owned_build_dir,
    detail,
    docker_compose_down,
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "filters"
README_FILE = UPSTREAM_LAB / "README.md"
SPECMATIC_FILE = UPSTREAM_LAB / "specmatic.yaml"
OUTPUT_DIR = ROOT / "filters" / "output"
LAB_COMMAND = ["docker", "compose", "up", "--abort-on-container-exit"]
FILTER_EXPR = "PATH!='/health,/monitor/{id},/swagger' && TAGS!='WIP' && STATUS='200,201'"


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the filters lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="filters",
        description="Automates the filters lab with baseline failures and a persisted filtered passing run.",
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
                "Objective",
                "Time required to complete this lab:",
                "Prerequisites",
                "Files in this lab",
                "Reference",
                "Lab Rules",
                "1. Baseline run (intentional failure)",
                "2. Start Studio",
                "3. Run tests in Studio",
                "4. Persist filters to config",
                "5. Verify from CLI (with persisted filters)",
                "Pass Criteria",
                "Why this lab matters",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the suite without persisted filters and verify the high-failure baseline.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=("Tests run: 134, Successes: 20, Failures: 112, Errors: 2",),
                include_readme_structure_checks=True,
                readme_assertions=(readme_contains("Tests run: 20, Successes: 20, Failures: 0, Errors: 0", "README documents the final filtered summary.", "README is missing the final filtered summary."),),
                file_transforms={"specmatic": set_baseline_filter},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Persist a reduced filter expression in specmatic.yaml and verify the filtered suite passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=("Tests run: 20, Successes: 20, Failures: 0, Errors: 0",),
                fix_summary=("Updated specmatic.yaml with a persisted filter expression that keeps only the passing 200/201 scenarios.",),
                file_transforms={"specmatic": set_fixed_filter},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        *build_coverage_assertions(
            context,
            expected_tests={"tests": 134, "passed": 20, "failed": 112, "skipped": 0, "other": 2},
            expected_operations={"/findAvailableProducts": "covered", "/products": "covered", "/orders": "covered"},
        ),
        assert_condition(
            FILTER_EXPR not in context.artifacts["specmatic.yaml"]["text"],
            "Baseline specmatic.yaml does not yet contain the persisted filtered expression.",
            "Baseline specmatic.yaml unexpectedly already contains the persisted filtered expression.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        *build_coverage_assertions(
            context,
            expected_tests={"tests": 20, "passed": 20, "failed": 0, "skipped": 0, "other": 0},
            expected_operations={"/findAvailableProducts": "covered", "/products": "covered", "/orders": "covered"},
        ),
        assert_condition(
            FILTER_EXPR in context.artifacts["specmatic.yaml"]["text"],
            "Fixed specmatic.yaml contains the persisted filtered expression.",
            "Fixed specmatic.yaml does not contain the persisted filtered expression.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_baseline_filter(content: str) -> str:
    return content.replace(FILTER_EXPR, "PATH!='/health,/monitor/{id},/swagger' && TAGS!='WIP'")


def set_fixed_filter(content: str) -> str:
    return content.replace("PATH!='/health,/monitor/{id},/swagger' && TAGS!='WIP'", FILTER_EXPR)


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
