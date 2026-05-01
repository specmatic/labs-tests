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
    detail,
    docker_compose_down,
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "continuous-integration"
README_FILE = UPSTREAM_LAB / "README.md"
ORDER_API_FILE = UPSTREAM_LAB / "contracts" / "order_api.yaml"
OUTPUT_DIR = ROOT / "continuous-integration" / "output"
LAB_COMMAND = ["docker", "compose", "up", "contract-repo-ci", "--build", "--abort-on-container-exit"]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the continuous-integration lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="continuous-integration",
        description="Automates the continuous-integration lab with CI gate fail/pass verification.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"order_api": ORDER_API_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
            ArtifactSpec(
                label="order_api.yaml",
                source_relpath="contracts/order_api.yaml",
                target_relpath="contracts/order_api.yaml",
                kind="text",
                expected_markers=("priority", "productId", "quantity"),
            ),
        ),

        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the simulated contract-repo CI gate with the backward-incompatible required field.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(
                    "==> Linting contracts with Spectral",
                    "==> Validating external examples",
                    "==> Checking backward compatibility against baseline main branch",
                    "(INCOMPATIBLE)",
                    "Backward compatibility gate failed.",
                ),
                include_readme_structure_checks=True,
                readme_assertions=(
                    readme_contains(
                        "(INCOMPATIBLE) This spec contains breaking changes to the API",
                        "README documents the incompatible CI gate failure.",
                        "README is missing the incompatible CI gate failure.",
                    ),
                ),
                file_transforms={"order_api": set_baseline_contract},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Remove priority from the required list and verify the CI gate passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=(
                    "==> Linting contracts with Spectral",
                    "==> Validating external examples",
                    "==> Checking backward compatibility against baseline main branch",
                    "(COMPATIBLE)",
                ),
                readme_assertions=(
                    readme_contains(
                        "(COMPATIBLE) The spec is backward compatible",
                        "README documents the compatible CI gate result.",
                        "README is missing the compatible CI gate result.",
                    ),
                ),
                fix_summary=(
                    "Removed priority from the POST /orders request required list in contracts/order_api.yaml.",
                    "Kept version 1.1.0 and the optional priority property itself.",
                ),
                file_transforms={"order_api": set_fixed_contract},
                extra_assertions=fixed_assertions,
            ),
        ),
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "- priority" in required_block(context.artifacts["order_api.yaml"]["text"]),
            "Baseline order_api.yaml kept priority in the request required list.",
            "Baseline order_api.yaml did not keep priority in the request required list.",
            category="report",
            details=[detail("Artifact path", context.artifacts["order_api.yaml"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "- priority" not in required_block(context.artifacts["order_api.yaml"]["text"]),
            "Fixed order_api.yaml removed priority from the request required list.",
            "Fixed order_api.yaml did not remove priority from the request required list.",
            category="report",
            details=[detail("Artifact path", context.artifacts["order_api.yaml"]["path"])],
        ),
    ]


def required_block(text: str) -> str:
    start = text.find("required:")
    end = text.find("properties:", start)
    return text[start:end] if start != -1 and end != -1 else text


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_baseline_contract(content: str) -> str:
    if "- priority" in required_block(content):
        return content
    return content.replace("                - quantity\n", "                - quantity\n                - priority\n", 1)


def set_fixed_contract(content: str) -> str:
    return content.replace("                - priority\n", "", 1)


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
