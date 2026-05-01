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
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "partial-examples"
README_FILE = UPSTREAM_LAB / "README.md"
EXAMPLES_DIR = UPSTREAM_LAB / "examples"
LICENSE_FILE = ROOT.parent / "labs" / "license.txt"
OUTPUT_DIR = ROOT / "partial-examples" / "output"
VALIDATE_COMMAND = ["docker", "run", "--rm", "-v", f"{UPSTREAM_LAB}:/usr/src/app"]
if LICENSE_FILE.exists():
    VALIDATE_COMMAND.extend(["-v", f"{LICENSE_FILE}:/specmatic/specmatic-license.txt:ro"])
VALIDATE_COMMAND.extend(["specmatic/enterprise:latest", "validate"])
LOOP_COMMAND = ["docker", "compose", "up", "--abort-on-container-exit"]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the partial-examples lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="partial-examples",
        description="Automates the partial-examples lab by converting incomplete examples into valid partial examples.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={
            "order": EXAMPLES_DIR / "test_accepted_order_request.json",
            "product": EXAMPLES_DIR / "test_accepted_product_request.json",
            "search": EXAMPLES_DIR / "test_find_available_products_book_200.json",
        },
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=VALIDATE_COMMAND,
        common_artifact_specs=(
            ArtifactSpec("test_accepted_order_request.json", "examples/test_accepted_order_request.json", "examples/test_accepted_order_request.json", "text"),
            ArtifactSpec("test_accepted_product_request.json", "examples/test_accepted_product_request.json", "examples/test_accepted_product_request.json", "text"),
            ArtifactSpec("test_find_available_products_book_200.json", "examples/test_find_available_products_book_200.json", "examples/test_find_available_products_book_200.json", "text"),
        ),

        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Validate the original incomplete examples and verify they fail.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(),
                include_readme_structure_checks=True,
                readme_assertions=(),
                file_transforms={"order": keep_content, "product": keep_content, "search": keep_content},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Convert the incomplete examples into valid partial examples and verify validation passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=(),
                readme_assertions=(),
                fix_summary=(
                    "Converted the create request examples into partial examples.",
                    "Updated the search example to a contract-compliant example shape used by loop tests.",
                ),
                file_transforms={"order": fixed_order_example, "product": fixed_product_example, "search": fixed_search_example},
                extra_assertions=fixed_assertions,
            ),
        ),
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition('"partial"' not in context.artifacts["test_accepted_order_request.json"]["text"], "Baseline order example is not yet a partial example.", "Baseline order example unexpectedly already uses partial example syntax.", category="report"),
        assert_condition('"partial"' not in context.artifacts["test_accepted_product_request.json"]["text"], "Baseline product example is not yet a partial example.", "Baseline product example unexpectedly already uses partial example syntax.", category="report"),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition('"partial"' in context.artifacts["test_accepted_order_request.json"]["text"], "Fixed order example now uses partial example syntax.", "Fixed order example does not use partial example syntax.", category="report"),
        assert_condition('"partial"' in context.artifacts["test_accepted_product_request.json"]["text"], "Fixed product example now uses partial example syntax.", "Fixed product example does not use partial example syntax.", category="report"),
        assert_condition('"to-date": "2025-10-15"' in context.artifacts["test_find_available_products_book_200.json"]["text"], "Fixed search example uses the contract-compliant query/date shape.", "Fixed search example does not use the contract-compliant query/date shape.", category="report"),
    ]


def keep_content(content: str) -> str:
    return content


def fixed_order_example(_: str) -> str:
    return """{
  "partial": {
    "http-request": {
      "path": "/orders",
      "method": "POST",
      "headers": {
        "Content-Type": "application/json"
      },
      "body": {
        "productid": 1234
      }
    },
    "http-response": {
      "status": 202,
      "status-text": "Accepted"
    }
  }
}
"""


def fixed_product_example(_: str) -> str:
    return """{
  "partial": {
    "http-request": {
      "path": "/products",
      "method": "POST",
      "headers": {
        "Content-Type": "application/json"
      },
      "body": {
        "name": "UniqueName"
      }
    },
    "http-response": {
      "status": 202,
      "status-text": "Accepted"
    }
  }
}
"""


def fixed_search_example(_: str) -> str:
    return """{
  "http-request": {
    "path": "/findAvailableProducts?type=book",
    "method": "GET",
    "headers": {
      "pageSize": "10"
    },
    "query": {
      "from-date": "2025-10-01",
      "to-date": "2025-10-15"
    }
  },
  "http-response": {
    "status": 200,
    "body": [],
    "headers": {
      "Content-Type": "application/json"
    }
  }
}
"""


if __name__ == "__main__":
    raise SystemExit(main())
