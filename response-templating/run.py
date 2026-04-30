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


UPSTREAM_LAB = ROOT.parent / "labs" / "response-templating"
README_FILE = UPSTREAM_LAB / "README.md"
ORDER_MOCK_FILE = UPSTREAM_LAB / "examples" / "mock" / "test_accepted_order_request.json"
LOOKUP_MOCK_FILE = UPSTREAM_LAB / "examples" / "mock" / "test_find_available_products_book_200.json"
LOOKUP_GADGET_MOCK_FILE = UPSTREAM_LAB / "examples" / "mock" / "test_find_available_products_gadget_200.json"
OUTPUT_DIR = ROOT / "response-templating" / "output"
LAB_COMMAND = ["docker", "compose", "up", "--abort-on-container-exit"]

ORDER_TASK_A = """{
  "partial": {
    "http-request": {
      "path": "/orders",
      "method": "POST",
      "headers": {
        "Content-Type": "application/json"
      },
      "body": {
        "productid": "(PRODUCTID:number)",
        "count": "(COUNT:number)"
      }
    },
    "http-response": {
      "status": 201,
      "body": {
        "id": 101,
        "productid": "$(PRODUCTID)",
        "count": "$(COUNT)"
      },
      "status-text": "Created",
      "headers": {
        "Content-Type": "application/json"
      }
    }
  }
}
"""

LOOKUP_BOOK_FINAL = """{
  "http-request": {
    "path": "/findAvailableProducts",
    "method": "GET",
    "query": {
      "from-date": "2026-02-15",
      "to-date": "2026-02-15",
      "type": "book"
    },
    "headers": {
      "pageSize": "10"
    }
  },
  "http-response": {
    "status": 200,
    "body": {
      "id": 1,
      "name": "Larry Potter",
      "type": "book",
      "inventory": 100,
      "createdOn": "2026-02-15"
    },
    "status-text": "OK",
    "headers": {
      "Content-Type": "application/json"
    }
  }
}
"""

LOOKUP_GADGET_FINAL = """{
  "http-request": {
    "path": "/findAvailableProducts",
    "method": "GET",
    "query": {
      "from-date": "2026-02-15",
      "to-date": "2026-02-15",
      "type": "gadget"
    },
    "headers": {
      "pageSize": "10"
    }
  },
  "http-response": {
    "status": 200,
    "body": {
      "id": 2,
      "name": "iPhone",
      "type": "gadget",
      "inventory": 500,
      "createdOn": "2026-02-15"
    },
    "status-text": "OK",
    "headers": {
      "Content-Type": "application/json"
    }
  }
}
"""


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the response-templating lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="response-templating",
        description="Automates the response-templating lab with direct substitution and data lookup fixes.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={
            "order_mock": ORDER_MOCK_FILE,
            "lookup_mock": LOOKUP_MOCK_FILE,
            "lookup_gadget_mock": LOOKUP_GADGET_MOCK_FILE,
        },
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
                label="test_accepted_order_request.json",
                source_relpath="examples/mock/test_accepted_order_request.json",
                target_relpath="examples/mock/test_accepted_order_request.json",
                kind="text",
                expected_markers=("http-response",),
            ),
            ArtifactSpec(
                label="test_find_available_products_book_200.json",
                source_relpath="examples/mock/test_find_available_products_book_200.json",
                target_relpath="examples/mock/test_find_available_products_book_200.json",
                kind="text",
                expected_markers=("http-response",),
            ),
            ArtifactSpec(
                label="test_find_available_products_gadget_200.json",
                source_relpath="examples/mock/test_find_available_products_gadget_200.json",
                target_relpath="examples/mock/test_find_available_products_gadget_200.json",
                kind="text",
                expected_markers=("http-response",),
            ),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Problem Statement",
                "Time required to complete this lab",
                "Prerequisites",
                "Files in this lab",
                "Reference",
                "Lab Rules",
                "1. Run baseline test",
                "2. Task A:",
                "3. Task B:",
                "4. Final verification",
                "Specmatic Types to OpenAPI Types Mapping",
                "Pass Criteria",
                "Why this lab matters",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the static mock examples and verify the three expected failures.",
                expected_exit_code=1,
                output_dir_name="baseline",
                include_readme_structure_checks=True,
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Task A fixed",
                description="Add direct substitution for order echoes and verify only the lookup failures remain.",
                expected_exit_code=1,
                output_dir_name="task-a",
                fix_summary=("Updated examples/mock/test_accepted_order_request.json to echo productid and count from the request using direct substitution.",),
                file_transforms={"order_mock": set_order_task_a},
                extra_assertions=task_a_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Add lookup-driven product responses and verify the full suite passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                fix_summary=(
                    "Kept the direct substitution fix for accepted orders.",
                    "Updated examples/mock/test_find_available_products_book_200.json to return the expected book response.",
                    "Added examples/mock/test_find_available_products_gadget_200.json to return the expected gadget response.",
                ),
                file_transforms={
                    "order_mock": set_order_task_a,
                    "lookup_mock": set_lookup_book_final,
                    "lookup_gadget_mock": set_lookup_gadget_final,
                },
                extra_assertions=final_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "\"Harry Potter\"" in context.artifacts["test_find_available_products_book_200.json"]["text"],
            "Baseline lookup mock kept the static Harry Potter response.",
            "Baseline lookup mock did not stay in the expected static state.",
            category="report",
            details=[detail("Artifact path", context.artifacts["test_find_available_products_book_200.json"]["path"])],
        ),
    ]


def task_a_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "$(PRODUCTID)" in context.artifacts["test_accepted_order_request.json"]["text"]
            and "$(COUNT)" in context.artifacts["test_accepted_order_request.json"]["text"],
            "Task A order mock contains direct substitution placeholders.",
            "Task A order mock does not contain the expected direct substitution placeholders.",
            category="report",
            details=[detail("Artifact path", context.artifacts["test_accepted_order_request.json"]["path"])],
        ),
    ]


def final_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            '"name": "Larry Potter"' in context.artifacts["test_find_available_products_book_200.json"]["text"]
            and '"type": "book"' in context.artifacts["test_find_available_products_book_200.json"]["text"],
            "Final book lookup mock contains the expected book response values.",
            "Final book lookup mock does not contain the expected book response values.",
            category="report",
            details=[detail("Artifact path", context.artifacts["test_find_available_products_book_200.json"]["path"])],
        ),
        assert_condition(
            '"name": "iPhone"' in context.artifacts["test_find_available_products_gadget_200.json"]["text"]
            and '"type": "gadget"' in context.artifacts["test_find_available_products_gadget_200.json"]["text"],
            "Final gadget lookup mock contains the expected gadget response values.",
            "Final gadget lookup mock does not contain the expected gadget response values.",
            category="report",
            details=[detail("Artifact path", context.artifacts["test_find_available_products_gadget_200.json"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_order_task_a(content: str) -> str:
    return ORDER_TASK_A


def set_lookup_book_final(content: str) -> str:
    return LOOKUP_BOOK_FINAL


def set_lookup_gadget_final(content: str) -> str:
    return LOOKUP_GADGET_FINAL


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
