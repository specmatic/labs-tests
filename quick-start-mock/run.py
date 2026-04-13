from __future__ import annotations

import argparse
from pathlib import Path
import shutil
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
    detail,
    docker_compose_down,
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "quick-start-mock"
README_FILE = UPSTREAM_LAB / "README.md"
MODE_FILE = UPSTREAM_LAB / ".labs-tests-mode"
SERVICE_FILE = UPSTREAM_LAB / "specs" / "service.yaml"
OUTPUT_DIR = ROOT / "quick-start-mock" / "output"
LAB_COMMAND = ["python3", str(ROOT / "lablib" / "quick_start_mock_runner.py")]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the quick-start-mock lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="quick-start-mock",
        description="Automates the quick-start-mock lab by validating the consumer before the provider mock, during the mock-backed run, and after the mock is gone again.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"mode": MODE_FILE, "service": SERVICE_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
            ArtifactSpec("results.json", "build/quick-start-mock/results.json", "build/quick-start-mock/results.json", "json"),
            ArtifactSpec("compose.log", "build/quick-start-mock/compose.log", "build/quick-start-mock/compose.log", "text"),
            ArtifactSpec("service.yaml", "specs/service.yaml", "specs/service.yaml", "text", expected_markers=("SCOOBY_200_OK", "/pets/{petid}")),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Why this lab matters",
                "Time required to complete this lab:",
                "Prerequisites",
                "Files in this lab",
                "Learner task",
                "Lab Rules",
                "Specmatic references",
                "Part A: Baseline run (intentional failure)",
                "Part B: Start contract-generated mock (consumer unblocked)",
                "Part C: Stop only the mock and observe fallback",
                "Part D: Run mock from Studio and inspect traffic",
                "Pass criteria",
                "Common confusion points",
                "Cleanup",
                "What you learned",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the consumer without the provider mock and verify the expected service-unavailable result.",
                expected_exit_code=0,
                output_dir_name="baseline",
                expected_console_phrases=("Observed Service unavailable while calling the provider URL.",),
                include_readme_structure_checks=True,
                readme_assertions=(readme_contains("Status shows `Service unavailable`.", "README documents the baseline service-unavailable behavior.", "README is missing the baseline service-unavailable behavior."),),
                file_transforms={"mode": set_mode_baseline, "service": keep_service_spec},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Mock running",
                description="Start the consumer with the contract-generated mock and verify success, dynamic data, and invalid-id handling.",
                expected_exit_code=0,
                output_dir_name="mock-running",
                expected_console_phrases=("Pet 1 status: 200", "Pet 2 first status: 200", "Pet 2 second status: 200", "Pet abc status: 400"),
                readme_assertions=(readme_contains("Status shows `Success`", "README documents the success state while the mock is running.", "README is missing the success state while the mock is running."),),
                file_transforms={"mode": set_mode_mock_running, "service": keep_service_spec},
                extra_assertions=mock_running_assertions,
            ),
            PhaseSpec(
                name="Fallback after mock stop",
                description="Return to the consumer-only state and verify the service-unavailable fallback again.",
                expected_exit_code=0,
                output_dir_name="fallback",
                expected_console_phrases=("Observed Service unavailable while calling the provider URL.",),
                readme_assertions=(readme_contains("Status returns to `Service unavailable`.", "README documents the fallback after stopping the mock.", "README is missing the fallback after stopping the mock."),),
                file_transforms={"mode": set_mode_fallback, "service": keep_service_spec},
                extra_assertions=fallback_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    results = context.artifacts["results.json"]["json"]
    return [
        assert_condition(
            results.get("mode") == "baseline" and results.get("pet1", {}).get("error"),
            "Baseline run recorded the expected service-unavailable error without the mock.",
            "Baseline run did not record the expected service-unavailable error without the mock.",
            category="console",
            details=[detail("Recorded result", results.get("pet1"))],
        ),
    ]


def mock_running_assertions(context: ValidationContext) -> list[dict]:
    results = context.artifacts["results.json"]["json"]
    pet1 = results.get("pet1", {})
    pet2_first = results.get("pet2_first", {})
    pet2_second = results.get("pet2_second", {})
    pet_abc = results.get("pet_abc", {})
    return [
        assert_condition(
            pet1.get("status") == 200,
            "Mock-backed run returned HTTP 200 for pet ID 1.",
            f"Mock-backed run expected HTTP 200 for pet ID 1, got {pet1.get('status')}.",
            category="console",
            details=[detail("Pet 1 body", pet1.get("body", ""))],
        ),
        assert_condition(
            pet2_first.get("status") == 200 and pet2_second.get("status") == 200,
            "Mock-backed run returned HTTP 200 for repeated pet ID 2 requests.",
            "Mock-backed run did not return HTTP 200 for both repeated pet ID 2 requests.",
            category="console",
            details=[detail("First body", pet2_first.get("body", "")), detail("Second body", pet2_second.get("body", ""))],
        ),
        assert_condition(
            pet2_first.get("body") != pet2_second.get("body"),
            "Repeated pet ID 2 requests produced dynamic contract-generated responses.",
            "Repeated pet ID 2 requests did not produce different dynamic responses.",
            category="report",
            details=[detail("First body", pet2_first.get("body", "")), detail("Second body", pet2_second.get("body", ""))],
        ),
        assert_condition(
            pet_abc.get("status") == 400,
            "Mock-backed run returned HTTP 400 for the invalid non-numeric pet ID.",
            f"Mock-backed run expected HTTP 400 for pet ID abc, got {pet_abc.get('status')}.",
            category="console",
            details=[detail("Pet abc body", pet_abc.get("body", ""))],
        ),
    ]


def fallback_assertions(context: ValidationContext) -> list[dict]:
    results = context.artifacts["results.json"]["json"]
    return [
        assert_condition(
            results.get("mode") == "fallback" and results.get("pet1", {}).get("error"),
            "Fallback run again recorded the expected service-unavailable error after the mock was gone.",
            "Fallback run did not record the expected service-unavailable error after the mock was gone.",
            category="console",
            details=[detail("Recorded result", results.get("pet1"))],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    docker_compose_down(spec, "--profile", "mock", "down", "-v")
    build_dir = spec.upstream_lab / "build" / "quick-start-mock"
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "--profile", "mock", "down", "-v")


def set_mode_baseline(_: str) -> str:
    return "baseline\n"


def set_mode_mock_running(_: str) -> str:
    return "mock-running\n"


def set_mode_fallback(_: str) -> str:
    return "fallback\n"


def keep_service_spec(content: str) -> str:
    return content


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
