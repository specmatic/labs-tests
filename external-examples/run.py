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
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "external-examples"
README_FILE = UPSTREAM_LAB / "README.md"
EXAMPLES_DIR = UPSTREAM_LAB / "examples"
LICENSE_FILE = ROOT.parent / "labs" / "license.txt"
OUTPUT_DIR = ROOT / "external-examples" / "output"


def validate_command() -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{UPSTREAM_LAB}:/usr/src/app",
    ]
    if LICENSE_FILE.exists():
        command.extend(["-v", f"{LICENSE_FILE}:/specmatic/specmatic-license.txt:ro"])
    command.extend(["specmatic/enterprise:latest", "validate"])
    return command


def validate_command_windows() -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{UPSTREAM_LAB}:/usr/src/app",
    ]
    if LICENSE_FILE.exists():
        command.extend(["-v", f"{LICENSE_FILE}:/specmatic/specmatic-license.txt:ro"])
    command.extend(["specmatic/enterprise:latest", "validate"])
    return command


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the external-examples lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="external-examples",
        description="Automates the external-examples lab by fixing invalid examples and adding missing create examples.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={
            "book_200": EXAMPLES_DIR / "test_find_available_products_book_200.json",
            "accepted_product": EXAMPLES_DIR / "test_accepted_product_request.json",
            "accepted_order": EXAMPLES_DIR / "test_accepted_order_request.json",
            "too_many": EXAMPLES_DIR / "test_products_too_many_requests.json",
            "created_product": EXAMPLES_DIR / "test_created_product_request_201.json",
            "created_order": EXAMPLES_DIR / "test_created_order_request_201.json",
        },
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=validate_command(),
        common_artifact_specs=(
            ArtifactSpec("test_find_available_products_book_200.json", "examples/test_find_available_products_book_200.json", "examples/test_find_available_products_book_200.json", "text"),
            ArtifactSpec("test_accepted_product_request.json", "examples/test_accepted_product_request.json", "examples/test_accepted_product_request.json", "text"),
            ArtifactSpec("test_accepted_order_request.json", "examples/test_accepted_order_request.json", "examples/test_accepted_order_request.json", "text"),
            ArtifactSpec("test_products_too_many_requests.json", "examples/test_products_too_many_requests.json", "examples/test_products_too_many_requests.json", "text"),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Validate the original external examples and verify the known failures.",
                expected_exit_code=1,
                readme_phase_id="baseline",
                output_dir_name="baseline",
                include_readme_structure_checks=True,
                file_transforms={
                    "book_200": reset_book_200,
                    "accepted_product": reset_accepted_product,
                    "accepted_order": reset_accepted_order,
                    "created_product": remove_generated_example,
                    "created_order": remove_generated_example,
                },
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Baseline mismatch (Windows command parity)",
                description="Run the Windows single-line validate command and verify the same baseline failure shape.",
                expected_exit_code=1,
                readme_phase_id="baseline",
                readme_summary_query="Test Run Cmd (Windows PowerShell or CMD)",
                output_dir_name="baseline-windows",
                file_transforms={
                    "book_200": reset_book_200,
                    "accepted_product": reset_accepted_product,
                    "accepted_order": reset_accepted_order,
                    "created_product": remove_generated_example,
                    "created_order": remove_generated_example,
                },
                extra_assertions=baseline_assertions,
                command=validate_command_windows(),
            ),
            PhaseSpec(
                name="Studio-equivalent fixes",
                description="Apply the deterministic Studio-equivalent fixes, add the two missing 201 examples, and re-run validation to match the documented Studio phase outcome.",
                expected_exit_code=0,
                readme_phase_id="studio",
                output_dir_name="fixed",
                fix_summary=(
                    "Applied the same example fixes the learner would make in Studio.",
                    "Added the two missing 201 create examples that Studio would generate.",
                    "Re-ran validation after the deterministic Studio-equivalent fixes were applied.",
                ),
                file_transforms={
                    "book_200": fix_book_200,
                    "accepted_product": fix_accepted_product,
                    "accepted_order": fix_accepted_order,
                    "created_product": create_product_201_example,
                    "created_order": create_order_201_example,
                },
                artifact_specs=(
                    ArtifactSpec("test_created_product_request_201.json", "examples/test_created_product_request_201.json", "examples/test_created_product_request_201.json", "text"),
                    ArtifactSpec("test_created_order_request_201.json", "examples/test_created_order_request_201.json", "examples/test_created_order_request_201.json", "text"),
                ),
                extra_assertions=studio_fix_assertions,
            ),
            PhaseSpec(
                name="Fixed contract (Windows command parity)",
                description="Run the Windows single-line validate command after the fixes and verify it matches the documented final phase outcome.",
                expected_exit_code=0,
                readme_phase_id="final",
                output_dir_name="fixed-windows",
                file_transforms={
                    "book_200": fix_book_200,
                    "accepted_product": fix_accepted_product,
                    "accepted_order": fix_accepted_order,
                    "created_product": create_product_201_example,
                    "created_order": create_order_201_example,
                },
                artifact_specs=(
                    ArtifactSpec("test_created_product_request_201.json", "examples/test_created_product_request_201.json", "examples/test_created_product_request_201.json", "text"),
                    ArtifactSpec("test_created_order_request_201.json", "examples/test_created_order_request_201.json", "examples/test_created_order_request_201.json", "text"),
                ),
                extra_assertions=studio_fix_assertions,
                command=validate_command_windows(),
            ),
        ),
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition("today" in context.artifacts["test_find_available_products_book_200.json"]["text"], "Baseline book example kept the invalid 'today' date.", "Baseline book example did not keep the invalid 'today' date.", category="implementation"),
        assert_condition('"movie"' in context.artifacts["test_accepted_product_request.json"]["text"], "Baseline product example kept the invalid movie enum.", "Baseline product example did not keep the invalid movie enum.", category="implementation"),
        assert_condition('"productid"' in context.artifacts["test_accepted_order_request.json"]["text"], "Baseline order example kept the missing-count shape.", "Baseline order example did not keep the missing-count shape.", category="implementation"),
    ]


def studio_fix_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition('"2025-11-28"' in context.artifacts["test_find_available_products_book_200.json"]["text"], "Fixed book example uses a valid ISO to-date.", "Fixed book example does not use a valid ISO to-date.", category="implementation"),
        assert_condition('"type": "book"' in context.artifacts["test_accepted_product_request.json"]["text"] and '"inventory": 5' in context.artifacts["test_accepted_product_request.json"]["text"], "Fixed product example uses valid enum and numeric values.", "Fixed product example does not use valid enum and numeric values.", category="implementation"),
        assert_condition('"count": 2' in context.artifacts["test_accepted_order_request.json"]["text"], "Fixed order example added the missing count field.", "Fixed order example did not add the missing count field.", category="implementation"),
        assert_condition(
            '"name": "Laptop"' in context.artifacts["test_created_product_request_201.json"]["text"]
            and '"type": "gadget"' in context.artifacts["test_created_product_request_201.json"]["text"]
            and '"inventory": 7' in context.artifacts["test_created_product_request_201.json"]["text"]
            and '"id": 2' in context.artifacts["test_created_product_request_201.json"]["text"],
            "Created product 201 example was added with a distinct request body and required response id.",
            "Created product 201 example is missing the distinct request body or required response id.",
            category="implementation",
        ),
        assert_condition(
            '"productid": 2' in context.artifacts["test_created_order_request_201.json"]["text"]
            and '"count": 3' in context.artifacts["test_created_order_request_201.json"]["text"]
            and '"id": 2' in context.artifacts["test_created_order_request_201.json"]["text"],
            "Created order 201 example was added with a distinct request body and required response id.",
            "Created order 201 example is missing the distinct request body or required response id.",
            category="implementation",
        ),
    ]


def reset_book_200(content: str) -> str:
    return content


def fix_book_200(content: str) -> str:
    return content.replace('"to-date": "today"', '"to-date": "2025-11-28"')


def reset_accepted_product(content: str) -> str:
    return content


def fix_accepted_product(content: str) -> str:
    return content.replace('"type": "movie"', '"type": "book"').replace('"inventory": "five"', '"inventory": 5')


def reset_accepted_order(content: str) -> str:
    return content


def fix_accepted_order(content: str) -> str:
    return content.replace('"productid": 1234', '"productid": 1234,\n      "count": 2')


def remove_generated_example(_: str) -> None:
    return None


def create_product_201_example(_: str) -> str:
    return """{
  "http-request": {
    "path": "/products",
    "method": "POST",
    "headers": {
      "Content-Type": "application/json"
    },
    "body": {
      "name": "Laptop",
      "type": "gadget",
      "inventory": 7
    }
  },
  "http-response": {
    "status": 201,
    "body": {
      "id": 2
    },
    "status-text": "Created",
    "headers": {
      "Content-Type": "application/json"
    }
  }
}
"""


def create_order_201_example(_: str) -> str:
    return """{
  "http-request": {
    "path": "/orders",
    "method": "POST",
    "headers": {
      "Content-Type": "application/json"
    },
    "body": {
      "productid": 2,
      "count": 3
    }
  },
  "http-response": {
    "status": 201,
    "body": {
      "id": 2
    },
    "status-text": "Created",
    "headers": {
      "Content-Type": "application/json"
    }
  }
}
"""
if __name__ == "__main__":
    raise SystemExit(main())
