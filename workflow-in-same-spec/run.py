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


UPSTREAM_LAB = ROOT.parent / "labs" / "workflow-in-same-spec"
README_FILE = UPSTREAM_LAB / "README.md"
SPECMATIC_FILE = UPSTREAM_LAB / "specmatic.yaml"
OUTPUT_DIR = ROOT / "workflow-in-same-spec" / "output"
LAB_COMMAND = ["docker", "compose", "--profile", "test", "up", "test", "--build", "--abort-on-container-exit"]

WORKFLOW_BLOCK = """
        workflow:
          ids:
            "POST /tasks -> 200":
              extract: "BODY.tasks.[0].id"
            "GET /tasks/(task_id:string) -> 200":
              use: "PATH.task_id"
            "PUT /tasks/(task_id:string) -> 200":
              use: "PATH.task_id"
            "DELETE /tasks/(task_id:string) -> 204":
              use: "PATH.task_id"
"""


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the workflow-in-same-spec lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="workflow-in-same-spec",
        description="Automates the workflow-in-same-spec lab with missing-workflow baseline and mapped-ID pass verification.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"specmatic": SPECMATIC_FILE},
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
                label="specmatic.yaml",
                source_relpath="specmatic.yaml",
                target_relpath="specmatic.yaml",
                kind="text",
                expected_markers=("baseUrl:",),
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
                "Baseline run",
                "Check in Studio",
                "Fix path",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the suite with workflow mapping missing and verify GET/PUT/DELETE failures.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(
                    "GET /tasks/(task_id:string) -> 200",
                    "PUT /tasks/(task_id:string) -> 200",
                    "DELETE /tasks/(task_id:string) -> 204",
                ),
                include_readme_structure_checks=True,
                readme_assertions=(),
                file_transforms={"specmatic": remove_workflow_block},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Add the workflow mapping and verify all four tests pass.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=(),
                readme_assertions=(),
                fix_summary=(
                    "Added workflow ID extraction and reuse mapping under systemUnderTest.service.runOptions.openapi.",
                    "Re-ran the suite to confirm GET, PUT, and DELETE reuse the created task ID and pass.",
                ),
                file_transforms={"specmatic": add_workflow_block},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "workflow:" not in context.artifacts["specmatic.yaml"]["text"],
            "Baseline specmatic.yaml kept the workflow block absent.",
            "Baseline specmatic.yaml unexpectedly contains a workflow block.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            'extract: "BODY.tasks.[0].id"' in context.artifacts["specmatic.yaml"]["text"],
            "Fixed specmatic.yaml contains the workflow extract mapping.",
            "Fixed specmatic.yaml does not contain the workflow extract mapping.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "--profile", "test", "down", "-v")


def remove_workflow_block(content: str) -> str:
    start = content.find("        workflow:")
    if start == -1:
        return content
    end = content.find("\nspecmatic:", start)
    return content[:start] + content[end:]


def add_workflow_block(content: str) -> str:
    content = remove_workflow_block(content)
    marker = '        baseUrl: "${TASKS_BASE_URL:http://127.0.0.1:8090}"\n'
    return content.replace(marker, marker + WORKFLOW_BLOCK, 1)


if __name__ == "__main__":
    raise SystemExit(main())
