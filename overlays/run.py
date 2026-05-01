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
    clear_docker_owned_build_dir,
    detail,
    docker_compose_down,
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "overlays"
README_FILE = UPSTREAM_LAB / "README.md"
SPECMATIC_FILE = UPSTREAM_LAB / "specmatic.yaml"
OVERLAY_FILE = UPSTREAM_LAB / "overlays" / "path-prefix.overlay.yaml"
OUTPUT_DIR = ROOT / "overlays" / "output"
LAB_COMMAND = ["docker", "compose", "up", "test", "--abort-on-container-exit"]

OVERLAY_CONTENT = """overlay: 1.0.0
info:
  title: Add /api/v1 prefix for deployed provider compatibility
  version: "1.0"
actions:
  - target: "$.paths"
    update:
      /api/v1/users/{id}:
        get:
          summary: Get user by id
          parameters:
            - $ref: "#/components/parameters/UserIdPathParam"
          responses:
            "200":
              $ref: "#/components/responses/User200"

  - target: "$.paths['/api/users/{id}']"
    remove: true
"""


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the overlays lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="overlays",
        description="Automates the overlays lab with baseline path mismatch and overlay-enabled pass verification.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"specmatic": SPECMATIC_FILE, "overlay": OVERLAY_FILE},
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
                expected_markers=("overlayFilePath",),
            ),
            ArtifactSpec(
                label="path-prefix.overlay.yaml",
                source_relpath="overlays/path-prefix.overlay.yaml",
                target_relpath="overlays/path-prefix.overlay.yaml",
                kind="text",
                expected_markers=("actions:",),
            ),
        ),

        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the contract tests without the overlay and verify the real 404 path mismatch.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(
                    "404 Not Found",
                ),
                include_readme_structure_checks=True,
                readme_assertions=(
                    readme_runtime_detail(
                        "404 Not Found",
                        "README captures the baseline 404 mismatch detail.",
                        "README does not mention the baseline 404 mismatch detail.",
                    ),
                ),
                file_transforms={"specmatic": set_overlay_disabled, "overlay": set_overlay_baseline},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Enable the overlay and verify the same test run passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=(),
                readme_assertions=(),
                fix_summary=(
                    "Replaced the empty overlay actions list with the path-rewrite overlay.",
                    "Enabled overlayFilePath in specmatic.yaml so Specmatic applies the overlay during tests.",
                ),
                file_transforms={"specmatic": set_overlay_enabled, "overlay": set_overlay_fixed},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "actions: []" in context.artifacts["path-prefix.overlay.yaml"]["text"],
            "Baseline overlay file stayed in the empty-actions state.",
            "Baseline overlay file was not reset to the empty-actions state.",
            category="report",
            details=[detail("Artifact path", context.artifacts["path-prefix.overlay.yaml"]["path"])],
        ),
        assert_condition(
            "overlayFilePath: ./overlays/path-prefix.overlay.yaml" not in uncommented_lines(context.artifacts["specmatic.yaml"]["text"]),
            "Baseline specmatic.yaml kept overlayFilePath disabled.",
            "Baseline specmatic.yaml unexpectedly enabled overlayFilePath.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "/api/v1/users/{id}" in context.artifacts["path-prefix.overlay.yaml"]["text"],
            "Fixed overlay file contains the rewritten /api/v1/users/{id} path.",
            "Fixed overlay file does not contain the rewritten /api/v1/users/{id} path.",
            category="report",
            details=[detail("Artifact path", context.artifacts["path-prefix.overlay.yaml"]["path"])],
        ),
        assert_condition(
            "overlayFilePath: ./overlays/path-prefix.overlay.yaml" in uncommented_lines(context.artifacts["specmatic.yaml"]["text"]),
            "Fixed specmatic.yaml enabled overlayFilePath.",
            "Fixed specmatic.yaml did not enable overlayFilePath.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def uncommented_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_overlay_baseline(content: str) -> str:
    return """overlay: 1.0.0
info:
  title: Add /api/v1 prefix for deployed provider compatibility
  version: "1.0"
actions: []
"""


def set_overlay_fixed(content: str) -> str:
    return OVERLAY_CONTENT


def set_overlay_disabled(content: str) -> str:
    return content.replace(
        "            overlayFilePath: ./overlays/path-prefix.overlay.yaml",
        "#            overlayFilePath: ./overlays/path-prefix.overlay.yaml",
    )


def set_overlay_enabled(content: str) -> str:
    return content.replace(
        "#            overlayFilePath: ./overlays/path-prefix.overlay.yaml",
        "            overlayFilePath: ./overlays/path-prefix.overlay.yaml",
    )


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


def readme_runtime_detail(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-runtime-detail", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
