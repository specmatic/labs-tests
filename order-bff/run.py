from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
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


UPSTREAM_LAB = ROOT.parent / "labs" / "order-bff"
README_FILE = UPSTREAM_LAB / "README.md"
SPECMATIC_FILE = UPSTREAM_LAB / "specmatic.yaml"
OUTPUT_DIR = ROOT / "order-bff" / "output"
LAB_COMMAND = ["docker", "compose", "--profile", "test", "up", "--abort-on-container-exit"]
CONTAINER_NAMES = ["order-bff", "order-bff-contract-suite"]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the order-bff lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="order-bff",
        description="Automates the order-bff lab by running the CI-style suite and validating its generated contract artifacts and README alignment.",
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
            ArtifactSpec("specmatic.yaml", "specmatic.yaml", "specmatic.yaml", "text", expected_markers=("schemaResiliencyTests: all", "post_specmatic_response_processor")),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Background",
                "Time required to complete this lab",
                "Prerequisites",
                "Run Contract Tests",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Contract suite",
                description="Run the order-bff CI-style suite and validate the published summary and generated reports.",
                expected_exit_code=0,
                output_dir_name="suite",
                readme_phase_id="baseline",
                readme_summary_query="Baseline Phase",
                include_readme_structure_checks=True,
                extra_assertions=suite_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def suite_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "schemaResiliencyTests: all" in context.artifacts["specmatic.yaml"]["text"]
            and "post_specmatic_response_processor" in context.artifacts["specmatic.yaml"]["text"],
            "specmatic.yaml keeps the BFF suite's resiliency and response-adapter configuration.",
            "specmatic.yaml does not keep the expected BFF suite configuration.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    cleanup_stale_containers()
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "--profile", "test", "down", "-v")
    cleanup_stale_containers()


def cleanup_stale_containers() -> None:
    subprocess.run(["docker", "rm", "-f", *CONTAINER_NAMES], check=False, text=True, capture_output=True)


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
