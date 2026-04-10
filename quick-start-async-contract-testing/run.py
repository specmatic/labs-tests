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


UPSTREAM_LAB = ROOT.parent / "labs" / "quick-start-async-contract-testing"
README_FILE = UPSTREAM_LAB / "README.md"
PROCESSOR_FILE = UPSTREAM_LAB / "service" / "processor.py"
OUTPUT_DIR = ROOT / "quick-start-async-contract-testing" / "output"
LAB_COMMAND = ["docker", "compose", "up", "contract-test", "--build", "--abort-on-container-exit"]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the quick-start-async-contract-testing lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="quick-start-async-contract-testing",
        description="Automates the quick-start-async-contract-testing lab with the async status mismatch and fix flow.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"processor": PROCESSOR_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
            ArtifactSpec(
                label="ctrf-report.json",
                source_relpath="build/reports/specmatic/async/test/ctrf/ctrf-report.json",
                target_relpath="ctrf-report.json",
                kind="json",
                expected_top_level_keys=("results",),
            ),
            ArtifactSpec(
                label="specmatic-report.html",
                source_relpath="build/reports/specmatic/async/test/html/index.html",
                target_relpath="specmatic/test/html/index.html",
                kind="html",
                expected_markers=("const report =", "specmaticConfig", "<html"),
            ),
            ArtifactSpec(
                label="coverage-report.json",
                source_relpath="build/reports/specmatic/async/coverage-report.json",
                target_relpath="coverage-report.json",
                kind="json",
            ),
            ArtifactSpec(
                label="processor.py",
                source_relpath="service/processor.py",
                target_relpath="service/processor.py",
                kind="text",
                expected_markers=("process_message", '"status"'),
            ),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Time required to complete this lab",
                "Prerequisites",
                "Files in this lab",
                "Learner task",
                "Lab Rules",
                "Architecture mental model",
                "Intentional failure",
                "Fix path",
                "Pass criteria",
                "Run the same suite in Studio",
                "Troubleshooting",
                "What you learned",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the async provider with status STARTED and verify the contract failure.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(
                    "STARTED",
                    "INITIATED",
                ),
                include_readme_structure_checks=True,
                readme_assertions=(
                    readme_contains(
                        "actual is `\"STARTED\"` and expected is one of the enum values in the contract (including `\"INITIATED\"`).",
                        "README documents the baseline async status mismatch.",
                        "README is missing the baseline async status mismatch detail.",
                    ),
                ),
                file_transforms={"processor": set_baseline_processor},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Change the emitted async status to INITIATED and verify the contract test passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=("Tests run: 1, Successes: 1, Failures: 0, Errors: 0",),
                readme_assertions=(
                    readme_contains(
                        "Tests run: 1, Successes: 1, Failures: 0, Errors: 0",
                        "README documents the final async passing summary.",
                        "README is missing the final async passing summary.",
                    ),
                ),
                fix_summary=("Changed the emitted async response status from STARTED to INITIATED in service/processor.py.",),
                file_transforms={"processor": set_fixed_processor},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        *build_test_summary_assertions(
            context,
            expected_ctrf={"tests": 1, "passed": 0, "failed": 1, "skipped": 0, "other": 0},
            expected_console={"tests": 1, "successes": 0, "failures": 1, "errors": 0},
        ),
        assert_condition(
            '"status": "STARTED"' in context.artifacts["processor.py"]["text"],
            "Baseline processor.py kept the intentional STARTED status.",
            "Baseline processor.py did not keep the intentional STARTED status.",
            category="report",
            details=[detail("Artifact path", context.artifacts["processor.py"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        *build_test_summary_assertions(
            context,
            expected_ctrf={"tests": 1, "passed": 1, "failed": 0, "skipped": 0, "other": 0},
            expected_console={"tests": 1, "successes": 1, "failures": 0, "errors": 0},
        ),
        assert_condition(
            '"status": "INITIATED"' in context.artifacts["processor.py"]["text"]
            and '"status": "STARTED"' not in context.artifacts["processor.py"]["text"],
            "Fixed processor.py emits the contract-compliant INITIATED status.",
            "Fixed processor.py does not emit the contract-compliant INITIATED status.",
            category="report",
            details=[detail("Artifact path", context.artifacts["processor.py"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_baseline_processor(content: str) -> str:
    return content.replace('"status": "INITIATED"', '"status": "STARTED"')


def set_fixed_processor(content: str) -> str:
    return content.replace('"status": "STARTED"', '"status": "INITIATED"')


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
