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


UPSTREAM_LAB = ROOT.parent / "labs" / "quick-start-contract-testing"
README_FILE = UPSTREAM_LAB / "README.md"
SERVICE_FILE = UPSTREAM_LAB / "service" / "server.py"
OUTPUT_DIR = ROOT / "quick-start-contract-testing" / "output"
LAB_COMMAND = ["docker", "compose", "up", "test", "--build", "--abort-on-container-exit"]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the quick-start-contract-testing lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="quick-start-contract-testing",
        description="Automates the quick-start-contract-testing lab with the real provider mismatch and fix flow.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"server": SERVICE_FILE},
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
                label="server.py",
                source_relpath="service/server.py",
                target_relpath="service/server.py",
                kind="text",
                expected_markers=("def do_GET", "Golden Retriever"),
            ),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Why this lab matters",
                "Time required to complete this lab",
                "Prerequisites",
                "Files in this lab",
                "Learner task",
                "Lab Rules",
                "Specmatic references",
                "Part A: Baseline run",
                "Part B: Fix the provider implementation",
                "Part C: Re-run tests",
                "Optional: Run the same check in Studio",
                "Pass criteria",
                "Common confusion points",
                "What you learned",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the provider with the intentional petType/type mismatch and verify the failing contract test.",
                expected_exit_code=1,
                output_dir_name="baseline",
                command_timeout_seconds=180,
                command_idle_timeout_seconds=120,
                expected_console_phrases=(
                    "Scenario: GET /pets/(petid:number) -> 200 with the request from the example 'SCOOBY_200_OK' has FAILED",
                    "petType",
                ),
                include_readme_structure_checks=True,
                readme_assertions=(
                    readme_contains(
                        "Service currently returns `petType`.",
                        "README documents the petType mismatch reason.",
                        "README is missing the petType mismatch reason.",
                    ),
                ),
                file_transforms={"server": set_baseline_server},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Change the provider response field to type and verify the contract test passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                command_timeout_seconds=180,
                command_idle_timeout_seconds=120,
                expected_console_phrases=(),
                readme_assertions=(),
                fix_summary=("Changed the provider response field from petType to type in service/server.py.",),
                file_transforms={"server": set_fixed_server},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            '"petType": "Golden Retriever"' in context.artifacts["server.py"]["text"],
            "Baseline service/server.py kept the intentional petType field.",
            "Baseline service/server.py did not keep the intentional petType field.",
            category="report",
            details=[detail("Artifact path", context.artifacts["server.py"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            '"type": "Golden Retriever"' in context.artifacts["server.py"]["text"]
            and '"petType": "Golden Retriever"' not in context.artifacts["server.py"]["text"],
            "Fixed service/server.py restored the contract-compliant type field.",
            "Fixed service/server.py did not restore the contract-compliant type field.",
            category="report",
            details=[detail("Artifact path", context.artifacts["server.py"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_baseline_server(content: str) -> str:
    return content.replace('"type": "Golden Retriever"', '"petType": "Golden Retriever"')


def set_fixed_server(content: str) -> str:
    return content.replace('"petType": "Golden Retriever"', '"type": "Golden Retriever"')


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
