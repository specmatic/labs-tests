from __future__ import annotations

import argparse
import os
from pathlib import Path
import socket
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


UPSTREAM_LAB = ROOT.parent / "labs" / "api-coverage"
SPEC_FILE = UPSTREAM_LAB / "specs" / "service.yaml"
README_FILE = UPSTREAM_LAB / "README.md"
OUTPUT_DIR = ROOT / "api-coverage" / "output"
LAB_COMMAND = ["docker", "compose", "up", "test", "--build", "--abort-on-container-exit"]

BASELINE_PATH = "/pets/search:"
FIXED_PATH = "/pets/find:"


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the api-coverage lab automation."))
    args = parser.parse_args()
    os.environ["PETSTORE_PORT"] = str(allocate_free_port())
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="api-coverage",
        description="Automates the Specmatic API coverage lab with real baseline and fixed-state verification.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"service_spec": SPEC_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        command_env={"PETSTORE_PORT": os.environ.get("PETSTORE_PORT", "18080")},
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
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Why this lab matters",
                "Time required to complete this lab",
                "Prerequisites",
                "Architecture",
                "Files in this lab",
                "Learner task",
                "Lab Rules",
                "Specmatic references",
                "What you learned",
                "Next step",
            ),
            additional_h2_prefixes=(
                "API Coverage Overview Video",
                "How coverage works in this lab",
                "Verify generated HTML report",
                "Short Studio follow-up",
                "Pass criteria",
                "Troubleshooting",
            ),
        ),
        runtime_warnings=(
            "Runtime note: this lab sets PETSTORE_PORT to a free host port before running Docker Compose so local port conflicts do not block execution. The upstream lab files are not modified.",
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Recreate the broken checked-in contract and verify the real coverage mismatch.",
                expected_exit_code=1,
                expected_console_phrases=(
                    "Failed the following API Coverage Report success criteria:",
                    "422 Unprocessable Entity",
                    "not implemented",
                    "missing in spec",
                ),
                readme_assertions=tuple(baseline_readme_assertions()),
                file_transforms={"service_spec": set_baseline_contract},
                include_readme_structure_checks=True,
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Apply the intended contract fix and verify that tests and coverage both pass.",
                expected_exit_code=0,
                expected_console_phrases=(
                    "Generating HTML report in build/reports/specmatic/test/html/index.html",
                ),
                readme_assertions=tuple(fixed_readme_assertions()),
                fix_summary=(
                    "Changed the contract path from GET /pets/search to GET /pets/find in specs/service.yaml.",
                    "Re-ran the same Specmatic test command against the running provider to confirm both operations are covered.",
                ),
                file_transforms={"service_spec": set_fixed_contract},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def allocate_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            BASELINE_PATH in context.artifacts["service_spec"]["text"] and FIXED_PATH not in context.artifacts["service_spec"]["text"],
            "Baseline spec keeps GET /pets/search and does not include GET /pets/find.",
            "Baseline spec does not match the expected broken /pets/search state.",
            category="report",
            details=[detail("Artifact path", context.artifacts["service_spec"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            FIXED_PATH in context.artifacts["service_spec"]["text"] and BASELINE_PATH not in context.artifacts["service_spec"]["text"],
            "Fixed spec switches to GET /pets/find and removes GET /pets/search.",
            "Fixed spec does not match the expected /pets/find state.",
            category="report",
            details=[detail("Artifact path", context.artifacts["service_spec"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_baseline_contract(content: str) -> str:
    if BASELINE_PATH in content:
        return content
    if FIXED_PATH in content:
        return content.replace(FIXED_PATH, BASELINE_PATH, 1)
    raise ValueError("Could not set api-coverage to the baseline contract state.")


def set_fixed_contract(content: str) -> str:
    if FIXED_PATH in content:
        return content
    if BASELINE_PATH in content:
        return content.replace(BASELINE_PATH, FIXED_PATH, 1)
    raise ValueError("Could not set api-coverage to the fixed contract state.")


def baseline_readme_assertions() -> list[dict[str, str]]:
    return [
        {
            "kind": "readme-contains",
            "text": "Total API coverage: 50% is less than the specified minimum threshold of 100%.",
            "success": "README documents the baseline coverage gate failure.",
            "failure": "README is missing the documented baseline coverage gate failure.",
        },
        {
            "kind": "readme-operation-status",
            "path": "/pets/search",
            "status": "not implemented",
            "success": "README documents /pets/search as not implemented in the baseline run.",
            "failure": "README does not document /pets/search as not implemented in the baseline run.",
        },
        {
            "kind": "readme-operation-status",
            "path": "/pets/find",
            "status": "missing in spec",
            "success": "README documents /pets/find as missing in spec in the baseline run.",
            "failure": "README does not document /pets/find as missing in spec in the baseline run.",
        },
    ]


def fixed_readme_assertions() -> list[dict[str, str]]:
    return [
        {
            "kind": "readme-contains",
            "text": "no paths remain `Missing In Spec`",
            "success": "README documents that no paths remain missing in spec after the fix.",
            "failure": "README is missing the documented post-fix missing-in-spec expectation.",
        },
        {
            "kind": "readme-contains",
            "text": "no paths remain `Not Implemented`",
            "success": "README documents that no paths remain not implemented after the fix.",
            "failure": "README is missing the documented post-fix not-implemented expectation.",
        },
        {
            "kind": "readme-operation-status",
            "path": "/pets/find",
            "status": "covered",
            "success": "README's post-fix narrative aligns with /pets/find being covered.",
            "failure": "README's post-fix narrative does not align with /pets/find being covered.",
        },
    ]


if __name__ == "__main__":
    raise SystemExit(main())
