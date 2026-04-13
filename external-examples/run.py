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
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Time required to complete this lab",
                "Prerequisites",
                "External Examples Overview Video",
                "Files in this lab",
                "Learner task",
                "Lab Rules",
                "1. Intentional failure (baseline run)",
                "2. Start Studio",
                "3. Auto-Fix the 3 failing external examples (tiny actions)",
                "4. Generate missing examples in the same Studio flow",
                "5. Re-run validation and verify pass state",
                "Pass Criteria",
                "Reference",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Validate the original external examples and verify the known failures.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=("1 passed and 3 failed out of 4 total",),
                include_readme_structure_checks=True,
                readme_assertions=(
                    readme_contains(
                        "[FAIL] Examples: 1 passed and 3 failed out of 4 total",
                        "README documents the baseline validation failure count.",
                        "README is missing the baseline validation failure count.",
                    ),
                ),
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
                name="Fixed contract",
                description="Fix the invalid examples and add the two missing 201 create examples.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=("6 passed and 0 failed out of 6 total",),
                readme_assertions=(
                    readme_contains(
                        "[OK] Examples: 6 passed and 0 failed out of 6 total",
                        "README documents the final validation pass count.",
                        "README is missing the final validation pass count.",
                    ),
                ),
                fix_summary=(
                    "Fixed the invalid date, enum, numeric, and missing count fields in the existing examples.",
                    "Added two new 201 create examples for POST /products and POST /orders.",
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
                extra_assertions=fixed_assertions,
            ),
        ),
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition("today" in context.artifacts["test_find_available_products_book_200.json"]["text"], "Baseline book example kept the invalid 'today' date.", "Baseline book example did not keep the invalid 'today' date.", category="report"),
        assert_condition('"movie"' in context.artifacts["test_accepted_product_request.json"]["text"], "Baseline product example kept the invalid movie enum.", "Baseline product example did not keep the invalid movie enum.", category="report"),
        assert_condition('"productid"' in context.artifacts["test_accepted_order_request.json"]["text"], "Baseline order example kept the missing-count shape.", "Baseline order example did not keep the missing-count shape.", category="report"),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition('"2025-11-28"' in context.artifacts["test_find_available_products_book_200.json"]["text"], "Fixed book example uses a valid ISO to-date.", "Fixed book example does not use a valid ISO to-date.", category="report"),
        assert_condition('"type": "book"' in context.artifacts["test_accepted_product_request.json"]["text"] and '"inventory": 5' in context.artifacts["test_accepted_product_request.json"]["text"], "Fixed product example uses valid enum and numeric values.", "Fixed product example does not use valid enum and numeric values.", category="report"),
        assert_condition('"count": 2' in context.artifacts["test_accepted_order_request.json"]["text"], "Fixed order example added the missing count field.", "Fixed order example did not add the missing count field.", category="report"),
        assert_condition(context.artifacts["test_created_product_request_201.json"]["text"].strip() != "", "Created product 201 example was added.", "Created product 201 example was not added.", category="report"),
        assert_condition(context.artifacts["test_created_order_request_201.json"]["text"].strip() != "", "Created order 201 example was added.", "Created order 201 example was not added.", category="report"),
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
      "name": "Harry Potter",
      "type": "book",
      "inventory": 5
    }
  },
  "http-response": {
    "status": 201,
    "body": {},
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
      "productid": 1234,
      "count": 2
    }
  },
  "http-response": {
    "status": 201,
    "body": {},
    "status-text": "Created",
    "headers": {
      "Content-Type": "application/json"
    }
  }
}
"""


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
