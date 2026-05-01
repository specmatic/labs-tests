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
BASELINE_FILTER = "PATH!='/health,/monitor/{id},/swagger'"
FILTER_EXPR = "PATH!='/health,/monitor/{id},/swagger' && STATUS='200,201'"


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

        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the suite without persisted filters and verify the high-failure baseline.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(),
                include_readme_structure_checks=True,
                readme_assertions=(),
                file_transforms={"specmatic": set_baseline_filter},
                extra_assertions=baseline_assertions,
                notes=(
                    "Studio phases documented in the README are not yet automated in labs-tests. Impact: this run validates the CLI baseline only for the before state. Action required: add Studio automation separately when Studio coverage is implemented.",
                ),
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Persist a reduced filter expression in specmatic.yaml and verify the filtered suite passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=(),
                fix_summary=("Updated specmatic.yaml with a persisted filter expression that keeps only the passing 200/201 scenarios.",),
                file_transforms={"specmatic": set_fixed_filter},
                extra_assertions=fixed_assertions,
                notes=(
                    "README steps for starting Studio and rerunning inside Studio are intentionally not automated yet. Impact: the CLI persistence flow is validated here, but the Studio path remains a documented manual step. Action required: add Studio automation only when that workflow is in scope for labs-tests.",
                ),
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
        known_limitations=(
            "The README includes Studio-only phases that are currently tracked as manual/not-yet-implemented work in labs-tests. They should appear as guidance, not as failures.",
        ),
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
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
    return set_openapi_filter(content, BASELINE_FILTER)


def set_fixed_filter(content: str) -> str:
    return set_openapi_filter(content, FILTER_EXPR)


def set_openapi_filter(content: str, filter_expr: str) -> str:
    lines = content.splitlines()

    openapi_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == "openapi:":
            openapi_idx = idx
            break

    if openapi_idx is None:
        raise ValueError("Could not locate 'openapi:' block in specmatic.yaml")

    openapi_indent = len(lines[openapi_idx]) - len(lines[openapi_idx].lstrip(" "))
    block_end = len(lines)
    for idx in range(openapi_idx + 1, len(lines)):
        stripped = lines[idx].strip()
        if not stripped:
            continue
        current_indent = len(lines[idx]) - len(lines[idx].lstrip(" "))
        if current_indent <= openapi_indent:
            block_end = idx
            break

    filter_indent = openapi_indent + 2
    filter_prefix = (" " * filter_indent) + "filter:"
    for idx in range(openapi_idx + 1, block_end):
        if lines[idx].lstrip(" ").startswith("filter:"):
            lines[idx] = f'{filter_prefix} "{filter_expr}"'
            return "\n".join(lines) + ("\n" if content.endswith("\n") else "")

    insert_at = block_end
    lines.insert(insert_at, f'{filter_prefix} "{filter_expr}"')
    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
