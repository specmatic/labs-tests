from __future__ import annotations

import argparse
from pathlib import Path
import re
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
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "backward-compatibility-testing"
PRODUCTS_FILE = UPSTREAM_LAB / "products.yaml"
README_FILE = UPSTREAM_LAB / "README.md"
OUTPUT_DIR = ROOT / "backward-compatibility-testing" / "output"
LAB_COMMAND = [
    "docker",
    "run",
    "--rm",
    "-v",
    "..:/workspace",
    "-v",
    "../license.txt:/specmatic/specmatic-license.txt:ro",
    "-w",
    "/workspace",
    "specmatic/enterprise:latest",
    "backward-compatibility-check",
    "--base-branch",
    "origin/main",
    "--target-path",
    "backward-compatibility-testing/products.yaml",
]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the backward-compatibility-testing lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="backward-compatibility-testing",
        description="Automates the Specmatic backward compatibility lab with real incompatible and compatible checks.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"products": PRODUCTS_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
            ArtifactSpec(
                label="products.yaml",
                source_relpath="products.yaml",
                target_relpath="products.yaml",
                kind="text",
                expected_markers=("openapi:", "info:", "paths:"),
            ),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Why this lab matters",
                "Time required to complete this lab",
                "Prerequisites",
                "Files in this lab",
                "Architecture",
                "Learner task",
                "Lab Rules",
                "Specmatic references",
                "What you learned",
                "Next step",
            ),
            additional_h2_prefixes=(
                "Backward Compatibility Overview Video",
                "Part A: Create the intentional breaking change",
                "Part B: Run the backward compatibility check",
                "Part C: Fix the contract",
                "Part D: Re-run the check",
                "Clean up",
                "Check backward compatibility in Specmatic Studio before saving",
                "Common confusion points",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Create the intentional breaking change and verify that Specmatic reports it as incompatible.",
                expected_exit_code=1,
                expected_console_phrases=(
                    "The Incompatibility Report:",
                    ">> RESPONSE.BODY.name",
                    "(INCOMPATIBLE) This spec contains breakingg changes to the API",
                ),
                readme_assertions=tuple(baseline_readme_assertions()),
                file_transforms={"products": set_baseline_contract},
                include_readme_structure_checks=True,
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Keep the additive category field, restore backward compatibility, and verify the check passes.",
                expected_exit_code=0,
                expected_console_phrases=(
                    "Verdict for spec /workspace/backward-compatibility-testing/products.yaml:",
                    "(COMPATIBLE) The spec is backward compatible with the corresponding spec from origin/main",
                ),
                readme_assertions=tuple(fixed_readme_assertions()),
                file_transforms={"products": set_fixed_contract},
                fix_summary=(
                    "Kept version 1.1.0 and the additive category field in products.yaml.",
                    "Changed the response field 'name' back from number to string so the evolved contract becomes backward compatible again.",
                ),
                extra_assertions=fixed_assertions,
            ),
        ),
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    products_text = context.artifacts["products.yaml"]["text"]
    return [
        assert_condition(
            "version: 1.1.0" in products_text,
            "Baseline products.yaml snapshot shows version 1.1.0.",
            "Baseline products.yaml snapshot does not show version 1.1.0.",
            category="report",
            details=[detail("Artifact path", context.artifacts["products.yaml"]["path"])],
        ),
        assert_condition(
            re.search(r"name:\s*\n\s*type:\s*number", products_text) is not None,
            "Baseline products.yaml snapshot shows name as number.",
            "Baseline products.yaml snapshot does not show name as number.",
            category="report",
            details=[detail("Artifact path", context.artifacts["products.yaml"]["path"])],
        ),
        assert_condition(
            re.search(r"category:\s*\n\s*type:\s*string", products_text) is not None,
            "Baseline products.yaml snapshot shows the additive category field.",
            "Baseline products.yaml snapshot does not show the additive category field.",
            category="report",
            details=[detail("Artifact path", context.artifacts["products.yaml"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    products_text = context.artifacts["products.yaml"]["text"]
    return [
        assert_condition(
            "version: 1.1.0" in products_text,
            "Fixed products.yaml snapshot keeps version 1.1.0.",
            "Fixed products.yaml snapshot does not keep version 1.1.0.",
            category="report",
            details=[detail("Artifact path", context.artifacts["products.yaml"]["path"])],
        ),
        assert_condition(
            re.search(r"name:\s*\n\s*type:\s*string", products_text) is not None,
            "Fixed products.yaml snapshot shows name restored to string.",
            "Fixed products.yaml snapshot does not show name restored to string.",
            category="report",
            details=[detail("Artifact path", context.artifacts["products.yaml"]["path"])],
        ),
        assert_condition(
            re.search(r"category:\s*\n\s*type:\s*string", products_text) is not None,
            "Fixed products.yaml snapshot keeps the additive category field.",
            "Fixed products.yaml snapshot does not keep the additive category field.",
            category="report",
            details=[detail("Artifact path", context.artifacts["products.yaml"]["path"])],
        ),
    ]


def set_baseline_contract(content: str) -> str:
    updated = re.sub(r"^(\s*version:\s*)1\.0\.0(\s*)$", r"\g<1>1.1.0\2", content, count=1, flags=re.MULTILINE)
    updated = re.sub(r"(\n\s*name:\s*\n\s*type:\s*)string\b", r"\1number", updated, count=1)
    if re.search(r"\n\s*category:\s*\n\s*type:\s*string", updated) is None:
        updated = re.sub(
            r"(\n\s*sku:\s*\n\s*type:\s*string)",
            r"\1\n                  category:\n                    type: string",
            updated,
            count=1,
        )
    return updated


def set_fixed_contract(content: str) -> str:
    updated = re.sub(r"^(\s*version:\s*)1\.0\.0(\s*)$", r"\g<1>1.1.0\2", content, count=1, flags=re.MULTILINE)
    if re.search(r"\n\s*category:\s*\n\s*type:\s*string", updated) is None:
        updated = re.sub(
            r"(\n\s*sku:\s*\n\s*type:\s*string)",
            r"\1\n                  category:\n                    type: string",
            updated,
            count=1,
        )
    updated = re.sub(r"(\n\s*name:\s*\n\s*type:\s*)(?:number|string)\b", r"\1string", updated, count=1)
    return updated


def baseline_readme_assertions() -> list[dict[str, str]]:
    return [
        {
            "kind": "readme-contains",
            "text": "The Incompatibility Report:",
            "success": "README documents the incompatible report heading.",
            "failure": "README is missing the incompatible report heading.",
        },
        {
            "kind": "readme-contains",
            "text": ">> RESPONSE.BODY.name",
            "success": "README documents the breaking field location.",
            "failure": "README is missing the documented breaking field location.",
        },
        {
            "kind": "readme-contains",
            "text": "(INCOMPATIBLE) This spec contains breaking changes to the API",
            "success": "README documents the incompatible verdict.",
            "failure": "README is missing the incompatible verdict.",
        },
        {
            "kind": "readme-runtime-detail",
            "text": "This is number in the new specification response but string in the old specification",
            "success": "README captures the actual backward compatibility mismatch detail.",
            "failure": "README does not mention the actual backward compatibility mismatch detail for RESPONSE.BODY.name.",
        },
    ]


def fixed_readme_assertions() -> list[dict[str, str]]:
    return [
        {
            "kind": "readme-contains",
            "text": "Verdict for spec /workspace/backward-compatibility-testing/products.yaml:",
            "success": "README documents the fixed-run verdict heading.",
            "failure": "README is missing the fixed-run verdict heading.",
        },
        {
            "kind": "readme-contains",
            "text": "(COMPATIBLE) The spec is backward compatible with the corresponding spec from origin/main",
            "success": "README documents the compatible verdict.",
            "failure": "README is missing the compatible verdict.",
        },
    ]


if __name__ == "__main__":
    raise SystemExit(main())
