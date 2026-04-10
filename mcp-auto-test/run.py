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
    assert_equal,
    clear_docker_owned_build_dir,
    detail,
    docker_compose_down,
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "mcp-auto-test"
README_FILE = UPSTREAM_LAB / "README.md"
ORDER_SERVICE_FILE = UPSTREAM_LAB / "service" / "order_service.py"
OUTPUT_DIR = ROOT / "mcp-auto-test" / "output"
LAB_COMMAND = ["docker", "compose", "up", "mcp-test", "--build", "--abort-on-container-exit"]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the mcp-auto-test lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="mcp-auto-test",
        description="Automates the mcp-auto-test lab with MCP tool failure and fix verification.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"order_service": ORDER_SERVICE_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
            ArtifactSpec(
                label="mcp_test_report.json",
                source_relpath="build/reports/specmatic/mcp/mcp_test_report.json",
                target_relpath="mcp/mcp_test_report.json",
                kind="json",
            ),
            ArtifactSpec(
                label="tools_schema.json",
                source_relpath="build/reports/specmatic/mcp/tools_schema.json",
                target_relpath="mcp/tools_schema.json",
                kind="json",
            ),
            ArtifactSpec(
                label="specmatic-report.html",
                source_relpath="build/reports/specmatic/mcp/specmatic_report.html",
                target_relpath="mcp/specmatic_report.html",
                kind="html",
                expected_markers=("Specmatic MCP Auto-Test Report", "Total:", "<html"),
            ),
            ArtifactSpec(
                label="order_service.py",
                source_relpath="service/order_service.py",
                target_relpath="service/order_service.py",
                kind="text",
                expected_markers=("get_order_summary", "create_return_quote"),
            ),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Why this lab matters",
                "Time required to complete this lab",
                "MCP Auto Test Overview Video",
                "Files in this lab",
                "Who is who in this lab",
                "Learner task",
                "Lab Rules",
                "Specmatic references",
                "Part A: Baseline run",
                "Part B: Fix the provider implementation",
                "Part C: Re-run tests",
                "Optional: Explore resiliency testing",
                "Pass criteria",
                "Troubleshooting",
                "What you learned",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run MCP Auto Test against the intentionally buggy provider and verify both tools fail.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(
                    "Total: 2",
                    "Passed: 0",
                    "Failed: 2",
                    "get_order_summary",
                    "create_return_quote",
                ),
                include_readme_structure_checks=True,
                readme_assertions=(
                    readme_contains(
                        "Total: 2",
                        "README documents the baseline MCP total count.",
                        "README is missing the baseline MCP total count.",
                    ),
                    readme_contains(
                        "Passed: 0",
                        "README documents the baseline MCP pass count.",
                        "README is missing the baseline MCP pass count.",
                    ),
                    readme_contains(
                        "Failed: 2",
                        "README documents the baseline MCP failure count.",
                        "README is missing the baseline MCP failure count.",
                    ),
                ),
                file_transforms={"order_service": set_baseline_provider},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Fix both provider bugs and verify MCP Auto Test passes for both tools.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=("Total: 2", "Passed: 2", "Failed: 0"),
                readme_assertions=(
                    readme_contains(
                        "Passed: 2",
                        "README documents the final MCP pass count.",
                        "README is missing the final MCP pass count.",
                    ),
                    readme_contains(
                        "Failed: 0",
                        "README documents the final MCP zero-failure count.",
                        "README is missing the final MCP zero-failure count.",
                    ),
                ),
                fix_summary=(
                    "Changed get_order_summary() to use order['shipmentStatus'].",
                    "Changed the return-fee multiplier key from damage to damaged in service/order_service.py.",
                ),
                file_transforms={"order_service": set_fixed_provider},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        *build_mcp_assertions(context, expected_total=2, expected_passed=0, expected_failed=2),
        assert_condition(
            'order["shipment"]' in context.artifacts["order_service.py"]["text"]
            and '"damage": 0.0' in context.artifacts["order_service.py"]["text"],
            "Baseline order_service.py kept both intentional provider bugs.",
            "Baseline order_service.py did not keep both intentional provider bugs.",
            category="report",
            details=[detail("Artifact path", context.artifacts["order_service.py"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        *build_mcp_assertions(context, expected_total=2, expected_passed=2, expected_failed=0),
        assert_condition(
            'order["shipmentStatus"]' in context.artifacts["order_service.py"]["text"]
            and '"damaged": 0.0' in context.artifacts["order_service.py"]["text"]
            and 'order["shipment"]' not in context.artifacts["order_service.py"]["text"],
            "Fixed order_service.py restored the correct shipment field and damaged fee key.",
            "Fixed order_service.py did not restore the correct shipment field and damaged fee key.",
            category="report",
            details=[detail("Artifact path", context.artifacts["order_service.py"]["path"])],
        ),
    ]


def build_mcp_assertions(
    context: ValidationContext,
    *,
    expected_total: int,
    expected_passed: int,
    expected_failed: int,
) -> list[dict]:
    report = context.artifacts["mcp_test_report.json"]["json"]
    tools = context.artifacts["tools_schema.json"]["json"]
    total = len(report)
    passed = sum(1 for item in report if item.get("verdict") == "PASSED")
    failed = sum(1 for item in report if item.get("verdict") == "FAILED")
    tool_names = sorted({item.get("toolName") for item in report if item.get("toolName")})
    schema_names = sorted(tool.get("name") for tool in tools if tool.get("name"))

    return [
        assert_equal(
            total,
            expected_total,
            f"MCP JSON report contained {expected_total} test results as expected.",
            f"MCP JSON report expected {expected_total} test results, got {total}.",
            category="report",
            details=[detail("Expected total", expected_total), detail("Actual total", total)],
        ),
        assert_equal(
            passed,
            expected_passed,
            f"MCP JSON report contained {expected_passed} passing results as expected.",
            f"MCP JSON report expected {expected_passed} passing results, got {passed}.",
            category="report",
            details=[detail("Expected passed", expected_passed), detail("Actual passed", passed)],
        ),
        assert_equal(
            failed,
            expected_failed,
            f"MCP JSON report contained {expected_failed} failing results as expected.",
            f"MCP JSON report expected {expected_failed} failing results, got {failed}.",
            category="report",
            details=[detail("Expected failed", expected_failed), detail("Actual failed", failed)],
        ),
        assert_condition(
            tool_names == ["create_return_quote", "get_order_summary"],
            "MCP JSON report covered the expected two tool names.",
            "MCP JSON report did not cover the expected two tool names.",
            category="report",
            details=[detail("Actual tool names", ", ".join(tool_names))],
        ),
        assert_condition(
            schema_names == ["create_return_quote", "get_order_summary"],
            "tools_schema.json contained the expected two tool definitions.",
            "tools_schema.json did not contain the expected two tool definitions.",
            category="report",
            details=[detail("Actual schema tool names", ", ".join(schema_names))],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_baseline_provider(content: str) -> str:
    updated = content.replace('"damaged": 0.0', '"damage": 0.0')
    updated = updated.replace('order["shipmentStatus"]', 'order["shipment"]')
    return updated


def set_fixed_provider(content: str) -> str:
    updated = content.replace('"damage": 0.0', '"damaged": 0.0')
    updated = updated.replace('order["shipment"]', 'order["shipmentStatus"]')
    return updated


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
