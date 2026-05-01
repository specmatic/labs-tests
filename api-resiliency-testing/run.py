from __future__ import annotations

import argparse
import json
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
    ValidationContext,
    add_standard_lab_args,
    assert_condition,
    assert_equal,
    clear_docker_owned_build_dir,
    detail,
    detail_table,
    docker_compose_down,
    parse_html_embedded_report,
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "api-resiliency-testing"
README_FILE = UPSTREAM_LAB / "README.md"
SPECMATIC_FILE = UPSTREAM_LAB / "specmatic.yaml"
TIMEOUT_GET_FILE = UPSTREAM_LAB / "examples" / "order-service" / "stub_timeout_get_products.json"
TIMEOUT_POST_FILE = UPSTREAM_LAB / "examples" / "order-service" / "stub_timeout_post_product.json"
OUTPUT_DIR = ROOT / "api-resiliency-testing" / "output"
LAB_COMMAND = ["docker", "compose", "--profile", "test", "up", "--abort-on-container-exit"]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the api-resiliency-testing lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="api-resiliency-testing",
        description="Automates the Specmatic API resiliency lab with staged timeout and schema-resiliency verification.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={
            "specmatic": SPECMATIC_FILE,
            "timeout_get": TIMEOUT_GET_FILE,
            "timeout_post": TIMEOUT_POST_FILE,
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
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the checked-in examples and verify the real 429 and 202 resiliency failures.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(
                    "Scenario: POST /products -> 202/202 with the request from the example 'test_accepted_product_request' has FAILED",
                    "Scenario: GET /findAvailableProducts -> 429 with the request from the example 'test_products_too_many_requests' has FAILED",
                    "Specification expected status 202 but response contained status 201",
                    "Specification expected status 429 but response contained status 200",
                ),
                readme_assertions=tuple(baseline_readme_assertions()),
                include_readme_structure_checks=True,
                extra_assertions=lambda context: build_resiliency_assertions(
                    context,
                    expected_operations=baseline_operation_rows(),
                    expected_html_operations=baseline_html_operation_rows(post_202_status="not implemented", post_202_count=1, get_429_status="not implemented", get_429_count=1),
                ),
            ),
            PhaseSpec(
                name="Load shedding fixed",
                description="Add the transient GET timeout and verify that only the 202 scenario is still failing.",
                expected_exit_code=1,
                output_dir_name="task-a",
                expected_console_phrases=(
                    "[BFF] Products Fetch Request timed out, setting Retry-After to 2",
                    "429 Too Many Requests",
                    "Scenario: GET /findAvailableProducts -> 429 with the request from the example 'test_products_too_many_requests' has SUCCEEDED",
                    "Scenario: POST /products -> 202/202 with the request from the example 'test_accepted_product_request' has FAILED",
                ),
                readme_assertions=tuple(task_a_readme_assertions()),
                fix_summary=(
                    "Added top-level transient timeout settings to examples/order-service/stub_timeout_get_products.json.",
                    "Re-ran the same suite and confirmed the 429 load-shedding flow now passes while the 202 flow still fails.",
                ),
                file_transforms={"timeout_get": set_timeout_get_fixed},
                extra_assertions=lambda context: build_resiliency_assertions(
                    context,
                    expected_operations=baseline_operation_rows(),
                    expected_html_operations=baseline_html_operation_rows(post_202_status="not implemented", post_202_count=1, get_429_status="covered", get_429_count=1),
                ),
            ),
            PhaseSpec(
                name="Async create fixed",
                description="Add the transient POST timeout and verify the base resiliency flow passes.",
                expected_exit_code=0,
                output_dir_name="task-b",
                expected_console_phrases=(
                    "[BFF] Product Creation Request timed out, starting a background monitor with id",
                    "202 Accepted",
                    "Scenario: POST /products -> 202/202 with the request from the example 'test_accepted_product_request' has SUCCEEDED",
                    "Scenario: GET /findAvailableProducts -> 429 with the request from the example 'test_products_too_many_requests' has SUCCEEDED",
                ),
                readme_assertions=tuple(task_b_readme_assertions()),
                fix_summary=(
                    "Added top-level transient timeout settings to examples/order-service/stub_timeout_post_product.json.",
                    "Confirmed the base suite passes with schemaResiliencyTests still set to none.",
                ),
                file_transforms={
                    "timeout_get": set_timeout_get_fixed,
                    "timeout_post": set_timeout_post_fixed,
                },
                extra_assertions=lambda context: build_resiliency_assertions(
                    context,
                    expected_operations=baseline_operation_rows(),
                    expected_html_operations=baseline_html_operation_rows(post_202_status="covered", post_202_count=1, get_429_status="covered", get_429_count=1),
                ),
            ),
            PhaseSpec(
                name="Schema resiliency mismatch",
                description="Enable schema resiliency generation and verify the additional POST /products -> 202 failures.",
                expected_exit_code=1,
                output_dir_name="task-c-mismatch",
                expected_console_phrases=(
                    "Scenario: POST /products -> 202/202 with the request from the example 'test_accepted_product_request' where REQUEST.BODY contains all the keys AND the key type is set to 'food' from enum AND inventory is set to the smallest possible value '1' has FAILED",
                ),
                readme_assertions=tuple(task_c_mismatch_readme_assertions()),
                fix_summary=(
                    "Changed schemaResiliencyTests from none to all in specmatic.yaml.",
                    "Kept the POST timeout stub hard-coded so the generated 202 variants still surface as failures.",
                ),
                file_transforms={
                    "specmatic": set_schema_resiliency_all,
                    "timeout_get": set_timeout_get_fixed,
                    "timeout_post": set_timeout_post_fixed,
                },
                extra_assertions=lambda context: build_resiliency_assertions(
                    context,
                    expected_operations=schema_operation_rows(),
                    expected_html_operations=schema_html_operation_rows(),
                ),
            ),
            PhaseSpec(
                name="Full schema resiliency fixed",
                description="Generalize the transient POST matcher and verify the full generated suite passes.",
                expected_exit_code=0,
                output_dir_name="final",
                expected_console_phrases=(
                    "Scenario: POST /products -> 202/202 with the request from the example 'test_accepted_product_request' where REQUEST.BODY contains all the keys AND the key type is set to 'food' from enum AND inventory is set to the largest possible value has SUCCEEDED",
                ),
                readme_assertions=tuple(final_readme_assertions()),
                fix_summary=(
                    "Kept schemaResiliencyTests set to all.",
                    "Generalized examples/order-service/stub_timeout_post_product.json to use value:each matchers for ProductType and ProductInventory.",
                    "Confirmed the generated 202 resiliency variants now pass alongside the original 429 and 202 examples.",
                ),
                file_transforms={
                    "specmatic": set_schema_resiliency_all,
                    "timeout_get": set_timeout_get_fixed,
                    "timeout_post": set_timeout_post_generalized,
                },
                extra_assertions=lambda context: build_resiliency_assertions(
                    context,
                    expected_operations=schema_operation_rows(),
                    expected_html_operations=schema_html_operation_rows(),
                ),
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "--profile", "test", "down", "-v")


def baseline_operation_rows() -> list[dict[str, object]]:
    return [
        {"path": "/products", "method": "POST", "responseCode": 201, "coverageStatus": "covered", "count": 1},
        {"path": "/products", "method": "POST", "responseCode": 202, "coverageStatus": "covered", "count": 1},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 200, "coverageStatus": "covered", "count": 2},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 429, "coverageStatus": "covered", "count": 1},
    ]


def baseline_html_operation_rows(*, post_202_status: str, post_202_count: int, get_429_status: str, get_429_count: int) -> list[dict[str, object]]:
    return [
        {"path": "/products", "method": "POST", "responseCode": 201, "coverageStatus": "covered", "count": 1},
        {"path": "/products", "method": "POST", "responseCode": 202, "coverageStatus": post_202_status, "count": post_202_count},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 200, "coverageStatus": "covered", "count": 2},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 429, "coverageStatus": get_429_status, "count": get_429_count},
        {"path": "/products", "method": "POST", "responseCode": 400, "coverageStatus": "not tested", "count": 0},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 400, "coverageStatus": "not tested", "count": 0},
        {"path": "/monitor/{id}", "method": "GET", "responseCode": 200, "coverageStatus": "not tested", "count": 0},
        {"path": "/monitor/{id}", "method": "GET", "responseCode": 400, "coverageStatus": "not tested", "count": 0},
    ]


def schema_operation_rows() -> list[dict[str, object]]:
    return [
        {"path": "/products", "method": "POST", "responseCode": 201, "coverageStatus": "covered", "count": 12},
        {"path": "/products", "method": "POST", "responseCode": 202, "coverageStatus": "covered", "count": 12},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 200, "coverageStatus": "covered", "count": 10},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 429, "coverageStatus": "covered", "count": 1},
        {"path": "/products", "method": "POST", "responseCode": 400, "coverageStatus": "covered", "count": 136},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 400, "coverageStatus": "covered", "count": 38},
    ]


def schema_html_operation_rows() -> list[dict[str, object]]:
    return [
        {"path": "/products", "method": "POST", "responseCode": 201, "coverageStatus": "covered", "count": 12},
        {"path": "/products", "method": "POST", "responseCode": 202, "coverageStatus": "covered", "count": 12},
        {"path": "/products", "method": "POST", "responseCode": 400, "coverageStatus": "covered", "count": 138},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 200, "coverageStatus": "covered", "count": 10},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 429, "coverageStatus": "covered", "count": 1},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 400, "coverageStatus": "covered", "count": 76},
        {"path": "/monitor/{id}", "method": "GET", "responseCode": 200, "coverageStatus": "not tested", "count": 0},
        {"path": "/monitor/{id}", "method": "GET", "responseCode": 400, "coverageStatus": "not tested", "count": 0},
    ]


def build_resiliency_assertions(
    context: ValidationContext,
    *,
    expected_operations: list[dict[str, object]],
    expected_html_operations: list[dict[str, object]],
) -> list[dict]:
    ctrf = context.artifacts["ctrf-report.json"]["json"]
    test_html = parse_html_embedded_report(context.artifacts["specmatic-report.html"]["text"])

    assertions: list[dict] = []
    test_html_operations = test_html["results"]["summary"]["extra"]["executionDetails"][0]["operations"]
    assertions.append(
        assert_equal(
            normalize_operations(test_html_operations),
            normalize_operations(expected_html_operations),
            "Embedded Specmatic test HTML operations matched the expected runtime results for this phase.",
            "Embedded Specmatic test HTML operations did not match the expected runtime results for this phase.",
            category="report",
            details=[
                detail_table(
                    "Expected HTML operations",
                    headers=["Path", "Method", "Response", "Status", "Count"],
                    rows=operation_rows(expected_html_operations),
                ),
                detail_table(
                    "Actual HTML operations",
                    headers=["Path", "Method", "Response", "Status", "Count"],
                    rows=operation_rows(test_html_operations),
                ),
            ],
        )
    )

    return assertions


def normalize_operations(operations: list[dict[str, object]]) -> list[tuple[object, ...]]:
    normalized = []
    for operation in operations:
        test_ids = operation.get("testIds", [])
        count = operation.get("count", len(test_ids))
        normalized.append(
            (
                operation["path"],
                operation["method"],
                int(operation["responseCode"]),
                operation["coverageStatus"],
                int(count),
            )
        )
    return sorted(normalized)


def operation_rows(operations: list[dict[str, object]]) -> list[list[object]]:
    rows = []
    for operation in operations:
        count = operation.get("count", len(operation.get("testIds", [])))
        rows.append(
            [
                operation["path"],
                operation["method"],
                operation["responseCode"],
                operation["coverageStatus"],
                count,
            ]
        )
    return rows


def set_schema_resiliency_all(content: str) -> str:
    return re.sub(r"(schemaResiliencyTests:\s*)none\b", r"\1all", content)


def set_timeout_get_fixed(content: str) -> str:
    document = json.loads(content)
    document.pop("transient", None)
    document.pop("delay-in-seconds", None)
    document.get("http-response", {}).pop("transient", None)
    document.get("http-response", {}).pop("delay-in-seconds", None)
    fixed = {
        "transient": True,
        "delay-in-seconds": 2,
        "http-request": document["http-request"],
        "http-response": document["http-response"],
    }
    return json.dumps(fixed, indent=2) + "\n"


def set_timeout_post_fixed(content: str) -> str:
    document = json.loads(content)
    document.pop("transient", None)
    document.pop("delay-in-seconds", None)
    document.pop("body", None)
    document.get("http-response", {}).pop("transient", None)
    document.get("http-response", {}).pop("delay-in-seconds", None)
    fixed = {
        "transient": True,
        "delay-in-seconds": 2,
        "http-request": document["http-request"],
        "http-response": document["http-response"],
    }
    return json.dumps(fixed, indent=2) + "\n"


def set_timeout_post_generalized(content: str) -> str:
    document = json.loads(set_timeout_post_fixed(content))
    document["http-request"]["body"] = {
        "name": "UniqueName",
        "type": "$match(dataType:ProductType, value:each, times:1)",
        "inventory": "$match(dataType:ProductInventory, value:each, times:1)",
    }
    return json.dumps(document, indent=2) + "\n"


def baseline_readme_assertions() -> list[dict[str, str]]:
    return [
        {
            "kind": "readme-contains",
            "text": "GET /findAvailableProducts -> 429",
            "success": "README documents the baseline 429 failure scenario.",
            "failure": "README is missing the documented baseline 429 failure scenario.",
        },
        {
            "kind": "readme-contains",
            "text": "POST /products -> 202",
            "success": "README documents the baseline 202 failure scenario.",
            "failure": "README is missing the documented baseline 202 failure scenario.",
        },
        {
            "kind": "readme-runtime-detail",
            "text": "Specification expected status 202 but response contained status 201",
            "success": "README captures the actual baseline 202 mismatch detail.",
            "failure": "README does not mention the actual baseline 202 mismatch detail.",
        },
    ]


def task_a_readme_assertions() -> list[dict[str, str]]:
    return [
        {
            "kind": "readme-contains",
            "text": "the `429` scenario passes",
            "success": "README documents that the 429 scenario should pass after Task A.",
            "failure": "README is missing the documented Task A 429 pass expectation.",
        },
        {
            "kind": "readme-contains",
            "text": "the `202` scenario still fails",
            "success": "README documents that the 202 scenario should still fail after Task A.",
            "failure": "README is missing the documented Task A 202 failure expectation.",
        },
    ]


def task_b_readme_assertions() -> list[dict[str, str]]:
    return [
        {
            "kind": "readme-contains",
            "text": "the baseline `429` and `202` resilience flow passes",
            "success": "README documents that the base resiliency flow passes after Task B.",
            "failure": "README is missing the documented Task B pass expectation.",
        },
    ]


def task_c_mismatch_readme_assertions() -> list[dict[str, str]]:
    return [
        {
            "kind": "readme-contains",
            "text": "additional generated `POST /products -> 202` requests now appear",
            "success": "README documents the generated 202 scenarios in Task C.",
            "failure": "README is missing the documented generated 202 scenarios in Task C.",
        },
        {
            "kind": "readme-contains",
            "text": "value:each",
            "success": "README documents the matcher strategy needed for Task C.",
            "failure": "README is missing the documented value:each matcher guidance for Task C.",
        },
    ]


def final_readme_assertions() -> list[dict[str, str]]:
    return [
        {
            "kind": "readme-contains",
            "text": "the additional generated `202` scenarios now pass",
            "success": "README documents that the generated 202 scenarios pass after the matcher fix.",
            "failure": "README is missing the documented final matcher-fix outcome.",
        },
    ]


if __name__ == "__main__":
    raise SystemExit(main())
