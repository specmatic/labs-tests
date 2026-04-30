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


UPSTREAM_LAB = ROOT.parent / "labs" / "dictionary"
README_FILE = UPSTREAM_LAB / "README.md"
SPECMATIC_FILE = UPSTREAM_LAB / "specmatic.yaml"
DICTIONARY_FILE = UPSTREAM_LAB / "specs" / "dictionary.yaml"
OUTPUT_DIR = ROOT / "dictionary" / "output"
LAB_COMMAND = ["docker", "compose", "up", "suite", "--abort-on-container-exit"]
GENERATED_DICTIONARY = """ProductBase:
  name:
  - Harry Potter
ProductType:
- book
ProductInventory:
- 100
Id:
  id:
  - 1
PARAMETERS:
  HEADER:
    pageSize:
    - 10
  QUERY:
    type:
    - book
    from-date:
    - '2026-02-15'
    to-date:
    - '2026-02-15'
Product:
  id:
  - 1
  name:
  - Larry Potter
  createdOn:
  - '2026-02-15'
OrderBase:
  productid:
  - 1
  count:
  - 100
"""


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the dictionary lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="dictionary",
        description="Automates the dictionary lab with baseline random mock mismatch and dictionary-driven pass verification.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"specmatic": SPECMATIC_FILE, "dictionary": DICTIONARY_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
            ArtifactSpec(
                label="coverage_report.json",
                source_relpath="build/reports/specmatic/coverage_report.json",
                target_relpath="coverage_report.json",
                kind="json",
                expected_top_level_keys=("apiCoverage",),
            ),
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
                expected_markers=("examples", "simple-openapi-spec.yaml"),
            ),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Time required to complete this lab:",
                "Prerequisites",
                "Files in this lab",
                "1. Run the suite using Docker (intentional failure)",
                "2. Learner task: configure dictionary-based mock data",
                "3. Re-run the suite after configuring dictionary",
                "Pass Criteria",
                "Additional Resources",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the suite without dictionary data and verify the deterministic examples fail against random mock data.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(),
                include_readme_structure_checks=True,
                readme_assertions=(),
                file_transforms={"specmatic": set_baseline_specmatic, "dictionary": remove_dictionary_file},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Add generated dictionary data to the mock configuration and verify the suite passes deterministically.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=(),
                readme_assertions=(),
                fix_summary=(
                    "Added the generated dictionary file at specs/dictionary.yaml.",
                    "Configured dependencies.services[0].service.data.dictionary.path in specmatic.yaml.",
                ),
                file_transforms={"specmatic": set_fixed_specmatic, "dictionary": set_fixed_dictionary},
                artifact_specs=(
                    ArtifactSpec(
                        label="dictionary.yaml",
                        source_relpath="specs/dictionary.yaml",
                        target_relpath="specs/dictionary.yaml",
                        kind="text",
                        expected_markers=("ProductBase:", "PARAMETERS:", "OrderBase:"),
                    ),
                ),
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "dictionary:" not in context.artifacts["specmatic.yaml"]["text"],
            "Baseline specmatic.yaml does not configure dictionary-based mock data.",
            "Baseline specmatic.yaml unexpectedly configured dictionary-based mock data.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "dictionary:" in context.artifacts["specmatic.yaml"]["text"]
            and "specs/dictionary.yaml" in context.artifacts["specmatic.yaml"]["text"],
            "Fixed specmatic.yaml points to the generated dictionary file.",
            "Fixed specmatic.yaml does not point to the generated dictionary file.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_baseline_specmatic(content: str) -> str:
    return content.replace(
        "\n    data:\n      dictionary:\n        path: specs/dictionary.yaml",
        "",
    )


def set_fixed_specmatic(content: str) -> str:
    if "dictionary:" in content and "specs/dictionary.yaml" in content:
        return content
    marker = "        runOptions:\n          openapi:\n            type: mock\n            baseUrl: \"${APP_URL:http://localhost:8080}\"\n"
    replacement = marker + "        data:\n          dictionary:\n            path: specs/dictionary.yaml\n"
    return content.replace(marker, replacement, 1)


def remove_dictionary_file(_: str) -> None:
    return None


def set_fixed_dictionary(_: str) -> str:
    return GENERATED_DICTIONARY


if __name__ == "__main__":
    raise SystemExit(main())
