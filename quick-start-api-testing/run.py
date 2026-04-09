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
    build_test_summary_assertions,
    clear_docker_owned_build_dir,
    detail,
    docker_compose_down,
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "quick-start-api-testing"
README_FILE = UPSTREAM_LAB / "README.md"
FINANCE_FILE = UPSTREAM_LAB / "examples" / "test_finance_user_11.json"
SUPPORT_FILE = UPSTREAM_LAB / "examples" / "test_support_user_55.json"
OUTPUT_DIR = ROOT / "quick-start-api-testing" / "output"
LAB_COMMAND = ["docker", "compose", "up", "api-test", "--build", "--abort-on-container-exit"]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the quick-start-api-testing lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="quick-start-api-testing",
        description="Automates the quick-start-api-testing lab with matcher fixes across two external examples.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"finance_11": FINANCE_FILE, "support_55": SUPPORT_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
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
            ArtifactSpec(
                label="test_finance_user_11.json",
                source_relpath="examples/test_finance_user_11.json",
                target_relpath="examples/test_finance_user_11.json",
                kind="text",
                expected_markers=("decision", "referenceCode", "processedOn"),
            ),
            ArtifactSpec(
                label="test_support_user_55.json",
                source_relpath="examples/test_support_user_55.json",
                target_relpath="examples/test_support_user_55.json",
                kind="text",
                expected_markers=("decision", "referenceCode", "processedOn"),
            ),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Contract Testing vs API Testing",
                "Objective",
                "Why this lab matters",
                "Time required to complete this lab",
                "Prerequisites",
                "Architecture",
                "Files in this lab",
                "Lab Rules",
                "Specmatic references",
                "Problem context",
                "1. Run the baseline contract tests",
                "2. Task A:",
                "3. Task B:",
                "4. Final verification",
                "Pass criteria",
                "Troubleshooting",
                "What you learned",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Recreate the too-strict examples and verify the two expected failures.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=("Tests run: 4, Successes: 2, Failures: 2, Errors: 0",),
                include_readme_structure_checks=True,
                readme_assertions=(readme_contains("Tests run: 4, Successes: 2, Failures: 2, Errors: 0", "README documents the baseline summary.", "README is missing the baseline summary."),),
                file_transforms={"finance_11": set_finance_baseline, "support_55": set_support_baseline},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Task A fixed",
                description="Loosen the finance example with a pattern matcher and verify only one failure remains.",
                expected_exit_code=1,
                output_dir_name="task-a",
                expected_console_phrases=("Tests run: 4, Successes: 3, Failures: 1, Errors: 0",),
                readme_assertions=(readme_contains("Tests run: 4, Successes: 3, Failures: 1, Errors: 0", "README documents the Task A checkpoint summary.", "README is missing the Task A checkpoint summary."),),
                fix_summary=("Changed examples/test_finance_user_11.json so decision uses $match(pattern: approved|verified).",),
                file_transforms={"finance_11": set_finance_task_a, "support_55": set_support_baseline},
                extra_assertions=task_a_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Use dataType and pattern matchers for the support example and verify the full suite passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=("Tests run: 4, Successes: 4, Failures: 0, Errors: 0",),
                readme_assertions=(readme_contains("Tests run: 4, Successes: 4, Failures: 0, Errors: 0", "README documents the final passing summary.", "README is missing the final passing summary."),),
                fix_summary=(
                    "Kept the Task A pattern matcher for the finance decision field.",
                    "Changed examples/test_support_user_55.json so processedOn uses $match(dataType: date) and referenceCode uses $match(pattern: VRF-[0-9]{6}).",
                ),
                file_transforms={"finance_11": set_finance_task_a, "support_55": set_support_final},
                extra_assertions=final_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        *build_test_summary_assertions(context, expected_ctrf={"tests": 4, "passed": 2, "failed": 2, "skipped": 0, "other": 0}, expected_console={"tests": 4, "successes": 2, "failures": 2, "errors": 0}),
        assert_condition(
            "$match(exact: approved)" in context.artifacts["test_finance_user_11.json"]["text"],
            "Baseline finance example kept the exact decision matcher.",
            "Baseline finance example did not keep the exact decision matcher.",
            category="report",
            details=[detail("Artifact path", context.artifacts["test_finance_user_11.json"]["path"])],
        ),
    ]


def task_a_assertions(context: ValidationContext) -> list[dict]:
    return [
        *build_test_summary_assertions(context, expected_ctrf={"tests": 4, "passed": 3, "failed": 1, "skipped": 0, "other": 0}, expected_console={"tests": 4, "successes": 3, "failures": 1, "errors": 0}),
        assert_condition(
            "$match(pattern: approved|verified)" in context.artifacts["test_finance_user_11.json"]["text"],
            "Task A finance example contains the decision pattern matcher.",
            "Task A finance example does not contain the decision pattern matcher.",
            category="report",
            details=[detail("Artifact path", context.artifacts["test_finance_user_11.json"]["path"])],
        ),
        assert_condition(
            "$match(exact: VRF-123456)" in context.artifacts["test_support_user_55.json"]["text"],
            "Task A support example still uses the exact referenceCode matcher.",
            "Task A support example unexpectedly changed the support matcher too early.",
            category="report",
            details=[detail("Artifact path", context.artifacts["test_support_user_55.json"]["path"])],
        ),
    ]


def final_assertions(context: ValidationContext) -> list[dict]:
    return [
        *build_test_summary_assertions(context, expected_ctrf={"tests": 4, "passed": 4, "failed": 0, "skipped": 0, "other": 0}, expected_console={"tests": 4, "successes": 4, "failures": 0, "errors": 0}),
        assert_condition(
            "$match(pattern: VRF-[0-9]{6})" in context.artifacts["test_support_user_55.json"]["text"]
            and "$match(dataType: date)" in context.artifacts["test_support_user_55.json"]["text"],
            "Final support example contains the relaxed matcher combination.",
            "Final support example does not contain the expected relaxed matcher combination.",
            category="report",
            details=[detail("Artifact path", context.artifacts["test_support_user_55.json"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_finance_baseline(content: str) -> str:
    return content.replace("$match(pattern: approved|verified)", "$match(exact: approved)")


def set_finance_task_a(content: str) -> str:
    return content.replace("$match(exact: approved)", "$match(pattern: approved|verified)")


def set_support_baseline(content: str) -> str:
    updated = content.replace("$match(pattern: VRF-[0-9]{6})", "$match(exact: VRF-123456)")
    updated = updated.replace("$match(dataType: date)", "$match(exact: 2026-03-17)")
    return updated


def set_support_final(content: str) -> str:
    updated = content.replace("$match(exact: VRF-123456)", "$match(pattern: VRF-[0-9]{6})")
    updated = updated.replace("$match(exact: 2026-03-17)", "$match(dataType: date)")
    return updated


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
