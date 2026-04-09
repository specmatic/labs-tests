from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lablib.command_runner import run_command
from lablib.scaffold import (
    ArtifactSpec,
    LabSpec,
    PhaseSpec,
    ReadmeStructureSpec,
    ValidationContext,
    add_standard_lab_args,
    assert_condition,
    assert_equal,
    detail,
    detail_table,
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
                label="specmatic.html",
                source_relpath="build/reports/specmatic/html/index.html",
                target_relpath="specmatic.html",
                kind="html",
                expected_markers=("Specmatic Report", "Contract Test Results", "<html"),
            ),
            ArtifactSpec(
                label="stub_usage_report.json",
                source_relpath="build/reports/specmatic/stub_usage_report.json",
                target_relpath="stub_usage_report.json",
                kind="json",
                expected_top_level_keys=("stubUsage",),
            ),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Why this lab matters",
                "Time required to complete this lab",
                "Prerequisites",
                "Architecture",
                "Files in this lab",
                "Learner task",
                "Lab Rules",
                "Specmatic references",
                "Troubleshooting",
                "Pass criteria",
                "What you learned",
                "Next step",
            ),
            additional_h2_prefixes=(
                "Baseline run",
                "Task A:",
                "Task B:",
                "Task C:",
                "Run the same flow in Studio",
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
                    expected_tests={"tests": 7, "passed": 3, "failed": 2, "skipped": 2, "other": 0},
                    expected_operations=baseline_operation_rows(),
                    expected_html_operations=baseline_html_operation_rows(),
                    expected_specmatic_summary={"success": 3, "failed": 2, "errors": 0, "skipped": 2, "total": 7},
                    required_stub_usage={
                        ("/products", "POST", 201): 1,
                        ("/products", "GET", 200): 1,
                    },
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
                    expected_tests={"tests": 7, "passed": 4, "failed": 1, "skipped": 2, "other": 0},
                    expected_operations=baseline_operation_rows(),
                    expected_html_operations=baseline_html_operation_rows(),
                    expected_specmatic_summary={"success": 4, "failed": 1, "errors": 0, "skipped": 2, "total": 7},
                    required_stub_usage={
                        ("/products", "POST", 201): 1,
                        ("/products", "GET", 200): 2,
                    },
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
                    expected_tests={"tests": 7, "passed": 5, "failed": 0, "skipped": 2, "other": 0},
                    expected_operations=baseline_operation_rows(),
                    expected_html_operations=baseline_html_operation_rows(),
                    expected_specmatic_summary={"success": 5, "failed": 0, "errors": 0, "skipped": 2, "total": 7},
                    required_stub_usage={
                        ("/products", "POST", 201): 1,
                        ("/products", "GET", 200): 2,
                    },
                ),
            ),
            PhaseSpec(
                name="Schema resiliency mismatch",
                description="Enable schema resiliency generation and verify the additional POST /products -> 202 failures.",
                expected_exit_code=1,
                output_dir_name="task-c-mismatch",
                expected_console_phrases=(
                    "Tests run: 209, Successes: 198, Failures: 11, Errors: 0",
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
                    expected_tests={"tests": 209, "passed": 198, "failed": 11, "skipped": 0, "other": 0},
                    expected_operations=schema_operation_rows(),
                    expected_html_operations=schema_operation_rows(),
                    expected_specmatic_summary={"success": 198, "failed": 11, "errors": 0, "skipped": 0, "total": 209},
                    required_stub_usage={
                        ("/products", "POST", 201): 1,
                        ("/products", "GET", 200): 2,
                    },
                ),
            ),
            PhaseSpec(
                name="Full schema resiliency fixed",
                description="Generalize the transient POST matcher and verify the full generated suite passes.",
                expected_exit_code=0,
                output_dir_name="final",
                expected_console_phrases=(
                    "Tests run: 209, Successes: 209, Failures: 0, Errors: 0",
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
                    expected_tests={"tests": 209, "passed": 209, "failed": 0, "skipped": 0, "other": 0},
                    expected_operations=schema_operation_rows(),
                    expected_html_operations=schema_operation_rows(),
                    expected_specmatic_summary={"success": 209, "failed": 0, "errors": 0, "skipped": 0, "total": 209},
                    required_stub_usage={
                        ("/products", "POST", 201): 12,
                        ("/products", "GET", 200): 2,
                    },
                ),
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def clear_previous_reports(spec: LabSpec) -> None:
    build_dir = spec.upstream_lab / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)


def teardown_compose(spec: LabSpec) -> None:
    run_command(["docker", "compose", "--profile", "test", "down", "-v"], spec.upstream_lab)


def baseline_operation_rows() -> list[dict[str, object]]:
    return [
        {"path": "/products", "method": "POST", "responseCode": 201, "coverageStatus": "covered", "count": 1},
        {"path": "/products", "method": "POST", "responseCode": 202, "coverageStatus": "covered", "count": 1},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 200, "coverageStatus": "covered", "count": 2},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 429, "coverageStatus": "covered", "count": 1},
    ]


def baseline_html_operation_rows() -> list[dict[str, object]]:
    return [
        *baseline_operation_rows(),
        {"path": "/products", "method": "POST", "responseCode": 400, "coverageStatus": "not covered", "count": 1},
        {"path": "/findAvailableProducts", "method": "GET", "responseCode": 400, "coverageStatus": "not covered", "count": 1},
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


def build_resiliency_assertions(
    context: ValidationContext,
    *,
    expected_tests: dict[str, int],
    expected_operations: list[dict[str, object]],
    expected_html_operations: list[dict[str, object]],
    expected_specmatic_summary: dict[str, int],
    required_stub_usage: dict[tuple[str, str, int], int],
) -> list[dict]:
    ctrf = context.artifacts["ctrf-report.json"]["json"]
    coverage = context.artifacts["coverage_report.json"]["json"]
    stub_usage = context.artifacts["stub_usage_report.json"]["json"]
    test_html = parse_html_embedded_report(context.artifacts["specmatic-report.html"]["text"])
    specmatic_html = context.artifacts["specmatic.html"]["text"]

    assertions: list[dict] = []
    ctrf_summary = ctrf["results"]["summary"]
    test_html_summary = test_html["results"]["summary"]
    specmatic_summary = parse_specmatic_html_summary(specmatic_html)

    for field, expected_value in expected_tests.items():
        actual_value = ctrf_summary.get(field, 0)
        assertions.append(
            assert_equal(
                actual_value,
                expected_value,
                f"CTRF summary field '{field}' matched expected value {expected_value}.",
                f"CTRF summary field '{field}' expected {expected_value}, got {actual_value}.",
                category="report",
                details=[
                    detail("Field", field),
                    detail("Expected", expected_value),
                    detail("Actual", actual_value),
                ],
            )
        )

    for field, expected_value in expected_tests.items():
        actual_value = test_html_summary.get(field, 0)
        assertions.append(
            assert_equal(
                actual_value,
                expected_value,
                f"Embedded Specmatic test HTML summary field '{field}' matched expected value {expected_value}.",
                f"Embedded Specmatic test HTML summary field '{field}' expected {expected_value}, got {actual_value}.",
                category="report",
                details=[
                    detail("Field", field),
                    detail("Expected", expected_value),
                    detail("Actual", actual_value),
                ],
            )
        )

    specmatic_field_map = {
        "passed": "success",
        "failed": "failed",
        "skipped": "skipped",
        "tests": "total",
    }
    for ctrf_field, specmatic_field in specmatic_field_map.items():
        expected_value = expected_specmatic_summary[specmatic_field]
        actual_value = specmatic_summary.get(specmatic_field)
        assertions.append(
            assert_equal(
                actual_value,
                expected_value,
                f"specmatic.html summary field '{specmatic_field}' matched expected value {expected_value}.",
                f"specmatic.html summary field '{specmatic_field}' expected {expected_value}, got {actual_value}.",
                category="report",
                details=[
                    detail("Field", specmatic_field),
                    detail("Expected", expected_value),
                    detail("Actual", actual_value),
                ],
            )
        )
        assertions.append(
            assert_equal(
                actual_value,
                ctrf_summary.get(ctrf_field, 0),
                f"specmatic.html field '{specmatic_field}' matched CTRF '{ctrf_field}'.",
                f"specmatic.html field '{specmatic_field}' did not match CTRF '{ctrf_field}'.",
                category="report",
                details=[
                    detail("specmatic.html value", actual_value),
                    detail("CTRF value", ctrf_summary.get(ctrf_field, 0)),
                ],
            )
        )

    coverage_operations = coverage["apiCoverage"][0]["operations"]
    test_html_operations = test_html["results"]["summary"]["extra"]["executionDetails"][0]["operations"]

    assertions.append(
        assert_equal(
            normalize_operations(coverage_operations),
            normalize_operations(expected_operations),
            "coverage_report.json operations matched the expected runtime results for this phase.",
            "coverage_report.json operations did not match the expected runtime results for this phase.",
            category="report",
            details=[
                detail_table(
                    "Expected coverage operations",
                    headers=["Path", "Method", "Response", "Status", "Count"],
                    rows=operation_rows(expected_operations),
                ),
                detail_table(
                    "Actual coverage operations",
                    headers=["Path", "Method", "Response", "Status", "Count"],
                    rows=operation_rows(coverage_operations),
                ),
            ],
        )
    )
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
    assertions.append(
        assert_equal(
            normalize_operations(coverage_operations),
            normalize_operations(test_html_operations),
            "coverage_report.json and specmatic-report.html listed the same operation rows.",
            "coverage_report.json and specmatic-report.html listed different operation rows.",
            category="report",
            details=[
                detail_table(
                    "coverage_report.json operations",
                    headers=["Path", "Method", "Response", "Status", "Count"],
                    rows=operation_rows(coverage_operations),
                ),
                detail_table(
                    "specmatic-report.html operations",
                    headers=["Path", "Method", "Response", "Status", "Count"],
                    rows=operation_rows(test_html_operations),
                ),
            ],
        )
    )

    coverage_map = operation_map(coverage_operations)
    html_map = operation_map(test_html_operations)
    for operation in expected_operations:
        signature = (operation["path"], operation["method"], operation["responseCode"])
        assertions.append(
            assert_equal(
                coverage_map.get(signature),
                html_map.get(signature),
                f"coverage_report.json and specmatic-report.html agree for {signature[1]} {signature[0]} -> {signature[2]}.",
                f"coverage_report.json and specmatic-report.html disagree for {signature[1]} {signature[0]} -> {signature[2]}.",
                category="report",
                details=[
                    detail("Coverage report entry", coverage_map.get(signature)),
                    detail("HTML report entry", html_map.get(signature)),
                ],
            )
        )

    stub_usage_map = {
        (item["path"], item["method"], item["responseCode"]): item["count"]
        for item in stub_usage["stubUsage"][0]["operations"]
    }
    for signature, expected_count in required_stub_usage.items():
        assertions.append(
            assert_equal(
                stub_usage_map.get(signature),
                expected_count,
                f"stub_usage_report.json matched the expected downstream count for {signature[1]} {signature[0]} -> {signature[2]}.",
                f"stub_usage_report.json did not match the expected downstream count for {signature[1]} {signature[0]} -> {signature[2]}.",
                category="report",
                details=[
                    detail("Expected count", expected_count),
                    detail("Actual count", stub_usage_map.get(signature)),
                ],
            )
        )

    assertions.append(
        assert_condition(
            "Specmatic Report" in specmatic_html and "Contract Test Results" in specmatic_html,
            "specmatic.html rendered the top-level Specmatic summary page.",
            "specmatic.html did not render the expected top-level Specmatic summary page.",
            category="report",
            details=[
                detail("Success count", specmatic_summary.get("success")),
                detail("Failed count", specmatic_summary.get("failed")),
                detail("Skipped count", specmatic_summary.get("skipped")),
                detail("Total count", specmatic_summary.get("total")),
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


def operation_map(operations: list[dict[str, object]]) -> dict[tuple[str, str, int], tuple[str, int]]:
    mapped: dict[tuple[str, str, int], tuple[str, int]] = {}
    for operation in operations:
        mapped[(operation["path"], operation["method"], int(operation["responseCode"]))] = (
            str(operation["coverageStatus"]),
            int(operation.get("count", len(operation.get("testIds", [])))),
        )
    return mapped


def parse_specmatic_html_summary(html_text: str) -> dict[str, int | None]:
    patterns = {
        "success": r"Success:\s*<span>(\d+)</span>",
        "failed": r"Failed:\s*<span>(\d+)</span>",
        "errors": r"Errors:\s*<span>(\d+)</span>",
        "skipped": r"Skipped:\s*<span>(\d+)</span>",
        "total": r"Total:\s*<span>(\d+)</span>",
    }
    summary: dict[str, int | None] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, html_text)
        summary[key] = int(match.group(1)) if match else None
    return summary


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
            "text": "Tests run: 5, Successes: 3, Failures: 2, Errors: 0",
            "success": "README documents the baseline console summary.",
            "failure": "README is missing the documented baseline console summary block.",
        },
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
            "text": "Tests run: 5, Successes: 4, Failures: 1, Errors: 0",
            "success": "README documents the Task A checkpoint summary.",
            "failure": "README is missing the documented Task A checkpoint summary block.",
        },
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
            "text": "Tests run: 5, Successes: 5, Failures: 0, Errors: 0",
            "success": "README documents the Task B checkpoint summary.",
            "failure": "README is missing the documented Task B checkpoint summary block.",
        },
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
            "text": "Tests run: 209, Successes: 198, Failures: 11, Errors: 0",
            "success": "README documents the Task C pre-fix summary.",
            "failure": "README is missing the documented Task C pre-fix summary block.",
        },
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
            "text": "Tests run: 209, Successes: 209, Failures: 0, Errors: 0",
            "success": "README documents the final passing summary.",
            "failure": "README is missing the documented final passing summary block.",
        },
        {
            "kind": "readme-contains",
            "text": "the additional generated `202` scenarios now pass",
            "success": "README documents that the generated 202 scenarios pass after the matcher fix.",
            "failure": "README is missing the documented final matcher-fix outcome.",
        },
    ]


if __name__ == "__main__":
    raise SystemExit(main())
