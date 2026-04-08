from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lablib.command_runner import CommandResult, run_command
from lablib.reporting import build_report, write_html, write_json
from lablib.workspace_setup import run_setup


UPSTREAM_LAB = ROOT.parent / "labs" / "api-coverage"
SPEC_FILE = UPSTREAM_LAB / "specs" / "service.yaml"
OUTPUT_DIR = ROOT / "api-coverage" / "output"
BASELINE_DIR = OUTPUT_DIR / "baseline"
FIXED_DIR = OUTPUT_DIR / "fixed"
README_FILE = UPSTREAM_LAB / "README.md"
LAB_COMMAND = ["docker", "compose", "up", "test", "--build", "--abort-on-container-exit"]

BASELINE_PATH = "/pets/search:"
FIXED_PATH = "/pets/find:"
CONSOLE_COVERAGE_ROW_RE = re.compile(
    r"^\|\s*(?P<coverage>\d+%)\s+\|\s*(?P<path>/[^|]+?)\s+\|\s*(?P<method>[A-Z]+)\s+\|\s*(?P<response>\d+)\s+\|\s*(?P<count>\d+)\s+\|\s*(?P<status>[^|]+?)\s+\|$"
)


def main() -> int:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    readme_text = README_FILE.read_text(encoding="utf-8")
    if args.refresh_report:
        print("Refreshing the report from existing captured artifacts...")
        phases = rebuild_phases_from_artifacts(readme_text)
    else:
        original_spec = SPEC_FILE.read_text(encoding="utf-8")
        phases: list[dict[str, Any]] = []

        try:
            if not args.skip_setup:
                print("Running workspace setup before lab execution...")
                setup_result = run_setup(
                    stream_output=True,
                    refresh_labs=args.refresh_labs,
                    target_branch=args.branch,
                    force=args.force,
                )
                if setup_result.status != "passed":
                    print("Workspace setup failed. See setup-output.json from the root setup command for details.")
                    return 1

            print("Preparing baseline lab state...")
            baseline_spec = set_path_value(original_spec, BASELINE_PATH)
            SPEC_FILE.write_text(baseline_spec, encoding="utf-8")
            baseline_result = execute_phase(
                name="Baseline mismatch",
                description="Recreate the broken checked-in contract and verify the real coverage mismatch.",
                target_dir=BASELINE_DIR,
                expected_exit_code=1,
                expected_tests={"tests": 3, "passed": 1, "failed": 1, "other": 1},
                expected_operations={
                    "/pets/{petId}": "covered",
                    "/pets/search": "not implemented",
                    "/pets/find": "missing in spec",
                },
                expected_console_phrases=[
                    "Tests run: 2, Successes: 1, Failures: 1, Errors: 0",
                    "Failed the following API Coverage Report success criteria:",
                    "422 Unprocessable Entity",
                    "not implemented",
                    "missing in spec",
                ],
                readme_text=readme_text,
                readme_assertions=baseline_readme_assertions(),
                stream_prefix="[baseline]",
            )
            phases.append(baseline_result)

            print("Applying the intended spec fix...")
            fixed_spec = set_path_value(baseline_spec, FIXED_PATH)
            SPEC_FILE.write_text(fixed_spec, encoding="utf-8")
            fixed_result = execute_phase(
                name="Fixed contract",
                description="Apply the intended contract fix and verify that tests and coverage both pass.",
                target_dir=FIXED_DIR,
                expected_exit_code=0,
                expected_tests={"tests": 2, "passed": 2, "failed": 0, "other": 0},
                expected_operations={
                    "/pets/{petId}": "covered",
                    "/pets/find": "covered",
                },
                forbidden_operations=["not implemented", "missing in spec"],
                expected_console_phrases=[
                    "Tests run: 2, Successes: 2, Failures: 0, Errors: 0",
                    "Generating HTML report in build/reports/specmatic/test/html/index.html",
                ],
                readme_text=readme_text,
                readme_assertions=fixed_readme_assertions(),
                fix_summary=[
                    "Changed the contract path from GET /pets/search to GET /pets/find in specs/service.yaml.",
                    "Re-ran the same Specmatic test command against the running provider to confirm both operations are covered.",
                ],
                stream_prefix="[fixed]",
            )
            phases.append(fixed_result)
        finally:
            SPEC_FILE.write_text(original_spec, encoding="utf-8")
            run_command(["docker", "compose", "down", "-v"], UPSTREAM_LAB)

    report = build_report(
        lab_name="api-coverage",
        description="Automates the Specmatic API coverage lab with real baseline and fixed-state verification.",
        lab_path=UPSTREAM_LAB,
        spec_path=SPEC_FILE,
        output_path=OUTPUT_DIR,
        phases=phases,
    )
    write_json(OUTPUT_DIR / "report.json", report)
    write_html(OUTPUT_DIR / "report.html", report)

    print(f"Wrote JSON report to {OUTPUT_DIR / 'report.json'}")
    print(f"Wrote HTML report to {OUTPUT_DIR / 'report.html'}")
    return 0 if report["status"] == "passed" else 1


def rebuild_phases_from_artifacts(readme_text: str) -> list[dict[str, Any]]:
    previous_commands = load_previous_phase_commands()
    return [
        rebuild_phase_from_artifacts(
            name="Baseline mismatch",
            description="Recreate the broken checked-in contract and verify the real coverage mismatch.",
            target_dir=BASELINE_DIR,
            expected_exit_code=1,
            expected_tests={"tests": 3, "passed": 1, "failed": 1, "other": 1},
            expected_operations={
                "/pets/{petId}": "covered",
                "/pets/search": "not implemented",
                "/pets/find": "missing in spec",
            },
            expected_console_phrases=[
                "Tests run: 2, Successes: 1, Failures: 1, Errors: 0",
                "Failed the following API Coverage Report success criteria:",
                "422 Unprocessable Entity",
                "not implemented",
                "missing in spec",
            ],
            readme_text=readme_text,
            readme_assertions=baseline_readme_assertions(),
            command_info=previous_commands.get("Baseline mismatch"),
        ),
        rebuild_phase_from_artifacts(
            name="Fixed contract",
            description="Apply the intended contract fix and verify that tests and coverage both pass.",
            target_dir=FIXED_DIR,
            expected_exit_code=0,
            expected_tests={"tests": 2, "passed": 2, "failed": 0, "other": 0},
            expected_operations={
                "/pets/{petId}": "covered",
                "/pets/find": "covered",
            },
            forbidden_operations=["not implemented", "missing in spec"],
            expected_console_phrases=[
                "Tests run: 2, Successes: 2, Failures: 0, Errors: 0",
                "Generating HTML report in build/reports/specmatic/test/html/index.html",
            ],
            readme_text=readme_text,
            readme_assertions=fixed_readme_assertions(),
            fix_summary=[
                "Changed the contract path from GET /pets/search to GET /pets/find in specs/service.yaml.",
                "Re-ran the same Specmatic test command against the running provider to confirm both operations are covered.",
            ],
            command_info=previous_commands.get("Fixed contract"),
        ),
    ]


def set_path_value(content: str, path_value: str) -> str:
    if BASELINE_PATH in content and path_value == BASELINE_PATH:
        return content
    if FIXED_PATH in content and path_value == FIXED_PATH:
        return content
    if BASELINE_PATH in content and path_value == FIXED_PATH:
        return content.replace(BASELINE_PATH, FIXED_PATH, 1)
    if FIXED_PATH in content and path_value == BASELINE_PATH:
        return content.replace(FIXED_PATH, BASELINE_PATH, 1)
    raise ValueError(f"Could not set spec path to {path_value}")


def execute_phase(
    *,
    name: str,
    description: str,
    target_dir: Path,
    expected_exit_code: int,
    expected_tests: dict[str, int],
    expected_operations: dict[str, str],
    expected_console_phrases: list[str],
    forbidden_operations: list[str] | None = None,
    readme_text: str = "",
    readme_assertions: list[dict[str, str]] | None = None,
    fix_summary: list[str] | None = None,
    stream_prefix: str = "",
) -> dict[str, Any]:
    forbidden_operations = forbidden_operations or []
    readme_assertions = readme_assertions or []
    fix_summary = fix_summary or []
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    clear_previous_reports()

    print(f"{name}: starting docker-based verification...")
    command = ["docker", "compose", "up", "test", "--build", "--abort-on-container-exit"]
    result = run_command(command, UPSTREAM_LAB, stream_output=True, stream_prefix=stream_prefix)
    try:
        coverage = load_json(UPSTREAM_LAB / "build/reports/specmatic/coverage_report.json")
        ctrf = load_json(UPSTREAM_LAB / "build/reports/specmatic/test/ctrf/ctrf-report.json")
        html_report_text = (UPSTREAM_LAB / "build/reports/specmatic/test/html/index.html").read_text(encoding="utf-8")
        copy_artifacts(target_dir)
    finally:
        run_command(["docker", "compose", "down", "-v"], UPSTREAM_LAB)

    assertions: list[dict[str, Any]] = []
    assertions.append(
        assert_equal(
            result.exit_code,
            expected_exit_code,
            f"Command exit code was {expected_exit_code} as expected.",
            f"Expected exit code {expected_exit_code}, got {result.exit_code}.",
            category="command",
            details=[
                detail("Expected exit code", expected_exit_code),
                detail("Actual exit code", result.exit_code),
                detail("Command", " ".join(command)),
            ],
        )
    )

    summary = ctrf["results"]["summary"]
    for field, expected_value in expected_tests.items():
        actual_value = summary.get(field, 0)
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

    operations = coverage["apiCoverage"][0]["operations"]
    by_path = {item["path"]: item["coverageStatus"] for item in operations}
    for path, expected_status in expected_operations.items():
        actual_status = by_path.get(path)
        assertions.append(
            assert_equal(
                actual_status,
                expected_status,
                f"{path} was reported as '{expected_status}'.",
                f"{path} expected coverage status '{expected_status}', got '{actual_status}'.",
                category="report",
                details=[
                    detail("Path", path),
                    detail("Expected status", expected_status),
                    detail("Actual status", actual_status),
                ],
            )
        )

    operation_statuses = [item["coverageStatus"] for item in operations]
    for forbidden_status in forbidden_operations:
        assertions.append(
            assert_condition(
                forbidden_status not in operation_statuses,
                f"No operation was marked '{forbidden_status}'.",
                f"Coverage still contains forbidden status '{forbidden_status}'.",
                category="report",
                details=[
                    detail("Forbidden status", forbidden_status),
                    detail("Actual statuses", ", ".join(operation_statuses)),
                ],
            )
        )

    html_report = target_dir / "specmatic" / "test" / "html" / "index.html"
    assertions.append(
        assert_condition(
            html_report.exists(),
            "Specmatic HTML report was copied into the lab output folder.",
            "Specmatic HTML report is missing from the lab output folder.",
            category="artifacts",
            details=[
                detail("Expected report path", html_report),
                detail("Exists", html_report.exists()),
            ],
        )
    )

    for phrase in expected_console_phrases:
        assertions.append(
            assert_condition(
                phrase in result.combined_output,
                f"Console output contained '{phrase}'.",
                f"Console output did not contain '{phrase}'.",
                category="console",
                details=[
                    detail("Expected phrase", phrase),
                    detail("Console excerpt", extract_context(result.combined_output, phrase)),
                ],
            )
        )

    assertions.extend(compare_console_coverage_with_reports(result.combined_output, coverage, html_report_text))
    assertions.extend(evaluate_readme_assertions(readme_text, readme_assertions, result, operations))

    phase_status = "passed" if all(item["status"] == "passed" for item in assertions) else "failed"
    write_text(target_dir / "command.log", result.combined_output)

    return {
        "name": name,
        "description": description,
        "status": phase_status,
        "command": {
            "display": " ".join(command),
            "exitCode": result.exit_code,
            "durationSeconds": round(result.duration_seconds, 2),
        },
        "assertions": assertions,
        "artifacts": [
            {"label": "coverage_report.json", "href": f"{target_dir.name}/coverage_report.json"},
            {"label": "ctrf-report.json", "href": f"{target_dir.name}/ctrf-report.json"},
            {"label": "specmatic-html", "href": f"{target_dir.name}/specmatic/test/html/index.html"},
            {"label": "command.log", "href": f"{target_dir.name}/command.log"},
        ],
        "consoleSnippet": shorten_console_output(result),
        "fixSummary": fix_summary,
    }


def rebuild_phase_from_artifacts(
    *,
    name: str,
    description: str,
    target_dir: Path,
    expected_exit_code: int,
    expected_tests: dict[str, int],
    expected_operations: dict[str, str],
    expected_console_phrases: list[str],
    forbidden_operations: list[str] | None = None,
    readme_text: str = "",
    readme_assertions: list[dict[str, str]] | None = None,
    fix_summary: list[str] | None = None,
    command_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    forbidden_operations = forbidden_operations or []
    readme_assertions = readme_assertions or []
    fix_summary = fix_summary or []
    ensure_artifact_set_exists(target_dir)

    coverage = load_json(target_dir / "coverage_report.json")
    ctrf = load_json(target_dir / "ctrf-report.json")
    html_report_text = (target_dir / "specmatic/test/html/index.html").read_text(encoding="utf-8")
    command_output = (target_dir / "command.log").read_text(encoding="utf-8")
    stored_exit_code = expected_exit_code if command_info is None else command_info.get("exitCode", expected_exit_code)
    stored_duration = 0.0 if command_info is None else command_info.get("durationSeconds", 0.0)

    return build_phase_result(
        name=name,
        description=description,
        target_dir=target_dir,
        expected_exit_code=expected_exit_code,
        expected_tests=expected_tests,
        expected_operations=expected_operations,
        expected_console_phrases=expected_console_phrases,
        forbidden_operations=forbidden_operations,
        readme_text=readme_text,
        readme_assertions=readme_assertions,
        fix_summary=fix_summary,
        command_output=command_output,
        actual_exit_code=stored_exit_code,
        duration_seconds=stored_duration,
        coverage=coverage,
        ctrf=ctrf,
        html_report_text=html_report_text,
    )


def build_phase_result(
    *,
    name: str,
    description: str,
    target_dir: Path,
    expected_exit_code: int,
    expected_tests: dict[str, int],
    expected_operations: dict[str, str],
    expected_console_phrases: list[str],
    forbidden_operations: list[str],
    readme_text: str,
    readme_assertions: list[dict[str, str]],
    fix_summary: list[str],
    command_output: str,
    actual_exit_code: int,
    duration_seconds: float,
    coverage: dict[str, Any],
    ctrf: dict[str, Any],
    html_report_text: str,
) -> dict[str, Any]:
    assertions: list[dict[str, Any]] = []
    assertions.append(
        assert_equal(
            actual_exit_code,
            expected_exit_code,
            f"Command exit code was {expected_exit_code} as expected.",
            f"Expected exit code {expected_exit_code}, got {actual_exit_code}.",
            category="command",
            details=[
                detail("Expected exit code", expected_exit_code),
                detail("Actual exit code", actual_exit_code),
                detail("Command", " ".join(LAB_COMMAND)),
            ],
        )
    )

    summary = ctrf["results"]["summary"]
    for field, expected_value in expected_tests.items():
        actual_value = summary.get(field, 0)
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

    operations = coverage["apiCoverage"][0]["operations"]
    by_path = {item["path"]: item["coverageStatus"] for item in operations}
    for path, expected_status in expected_operations.items():
        actual_status = by_path.get(path)
        assertions.append(
            assert_equal(
                actual_status,
                expected_status,
                f"{path} was reported as '{expected_status}'.",
                f"{path} expected coverage status '{expected_status}', got '{actual_status}'.",
                category="report",
                details=[
                    detail("Path", path),
                    detail("Expected status", expected_status),
                    detail("Actual status", actual_status),
                ],
            )
        )

    operation_statuses = [item["coverageStatus"] for item in operations]
    for forbidden_status in forbidden_operations:
        assertions.append(
            assert_condition(
                forbidden_status not in operation_statuses,
                f"No operation was marked '{forbidden_status}'.",
                f"Coverage still contains forbidden status '{forbidden_status}'.",
                category="report",
                details=[
                    detail("Forbidden status", forbidden_status),
                    detail("Actual statuses", ", ".join(operation_statuses)),
                ],
            )
        )

    html_report = target_dir / "specmatic" / "test" / "html" / "index.html"
    assertions.append(
        assert_condition(
            html_report.exists(),
            "Specmatic HTML report was copied into the lab output folder.",
            "Specmatic HTML report is missing from the lab output folder.",
            category="artifacts",
            details=[
                detail("Expected report path", html_report),
                detail("Exists", html_report.exists()),
            ],
        )
    )

    for phrase in expected_console_phrases:
        assertions.append(
            assert_condition(
                phrase in command_output,
                f"Console output contained '{phrase}'.",
                f"Console output did not contain '{phrase}'.",
                category="console",
                details=[
                    detail("Expected phrase", phrase),
                    detail("Console excerpt", extract_context(command_output, phrase)),
                ],
            )
        )

    assertions.extend(compare_console_coverage_with_reports(command_output, coverage, html_report_text))
    result = CommandResult(
        command=LAB_COMMAND,
        cwd=str(UPSTREAM_LAB),
        exit_code=actual_exit_code,
        stdout=command_output,
        stderr="",
        started_at="",
        finished_at="",
        duration_seconds=duration_seconds,
    )
    assertions.extend(evaluate_readme_assertions(readme_text, readme_assertions, result, operations))

    phase_status = "passed" if all(item["status"] == "passed" for item in assertions) else "failed"
    return {
        "name": name,
        "description": description,
        "status": phase_status,
        "command": {
            "display": " ".join(LAB_COMMAND),
            "exitCode": actual_exit_code,
            "durationSeconds": round(duration_seconds, 2),
        },
        "assertions": assertions,
        "artifacts": [
            {"label": "coverage_report.json", "href": f"{target_dir.name}/coverage_report.json"},
            {"label": "ctrf-report.json", "href": f"{target_dir.name}/ctrf-report.json"},
            {"label": "specmatic-html", "href": f"{target_dir.name}/specmatic/test/html/index.html"},
            {"label": "command.log", "href": f"{target_dir.name}/command.log"},
        ],
        "consoleSnippet": shorten_console_output(result),
        "fixSummary": fix_summary,
    }


def ensure_artifact_set_exists(target_dir: Path) -> None:
    required_paths = [
        target_dir / "coverage_report.json",
        target_dir / "ctrf-report.json",
        target_dir / "command.log",
        target_dir / "specmatic/test/html/index.html",
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        missing_list = ", ".join(missing)
        raise FileNotFoundError(f"Cannot refresh the report because required artifacts are missing: {missing_list}")


def load_previous_phase_commands() -> dict[str, dict[str, Any]]:
    report_path = OUTPUT_DIR / "report.json"
    if not report_path.exists():
        return {}
    existing_report = load_json(report_path)
    commands: dict[str, dict[str, Any]] = {}
    for phase in existing_report.get("phases", []):
        if "name" in phase and "command" in phase:
            commands[phase["name"]] = phase["command"]
    return commands


def clear_previous_reports() -> None:
    build_dir = UPSTREAM_LAB / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)


def copy_artifacts(target_dir: Path) -> None:
    coverage_src = UPSTREAM_LAB / "build/reports/specmatic/coverage_report.json"
    ctrf_src = UPSTREAM_LAB / "build/reports/specmatic/test/ctrf/ctrf-report.json"
    html_src = UPSTREAM_LAB / "build/reports/specmatic/test/html"

    shutil.copy2(coverage_src, target_dir / "coverage_report.json")
    shutil.copy2(ctrf_src, target_dir / "ctrf-report.json")
    shutil.copytree(html_src, target_dir / "specmatic/test/html", dirs_exist_ok=True)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def shorten_console_output(result: CommandResult) -> str:
    lines = [line for line in result.combined_output.splitlines() if line.strip()]
    if len(lines) <= 80:
        return "\n".join(lines)
    head = "\n".join(lines[:45])
    tail = "\n".join(lines[-30:])
    return f"{head}\n...\n{tail}"


def baseline_readme_assertions() -> list[dict[str, str]]:
    return [
        {
            "kind": "readme-contains",
            "text": "Tests run: 2, Successes: 1, Failures: 1, Errors: 0",
            "success": "README documents the baseline console summary.",
            "failure": "README is missing the documented baseline console summary block.",
        },
        {
            "kind": "readme-contains",
            "text": "Total API coverage: 50% is less than the specified minimum threshold of 100%.",
            "success": "README documents the baseline coverage gate failure.",
            "failure": "README is missing the documented baseline coverage gate failure.",
        },
        {
            "kind": "readme-operation-status",
            "path": "/pets/search",
            "status": "not implemented",
            "success": "README documents /pets/search as not implemented in the baseline run.",
            "failure": "README does not document /pets/search as not implemented in the baseline run.",
        },
        {
            "kind": "readme-operation-status",
            "path": "/pets/find",
            "status": "missing in spec",
            "success": "README documents /pets/find as missing in spec in the baseline run.",
            "failure": "README does not document /pets/find as missing in spec in the baseline run.",
        },
        {
            "kind": "readme-runtime-detail",
            "text": "422 Unprocessable Entity",
            "success": "README captures the actual baseline HTTP failure detail.",
            "failure": "README does not mention the actual baseline HTTP failure detail '422 Unprocessable Entity'.",
        },
    ]


def fixed_readme_assertions() -> list[dict[str, str]]:
    return [
        {
            "kind": "readme-contains",
            "text": "Tests run: 2, Successes: 2, Failures: 0, Errors: 0",
            "success": "README documents the fixed-run console summary.",
            "failure": "README is missing the documented fixed-run console summary block.",
        },
        {
            "kind": "readme-contains",
            "text": "no paths remain `Missing In Spec`",
            "success": "README documents that no paths remain missing in spec after the fix.",
            "failure": "README is missing the documented post-fix missing-in-spec expectation.",
        },
        {
            "kind": "readme-contains",
            "text": "no paths remain `Not Implemented`",
            "success": "README documents that no paths remain not implemented after the fix.",
            "failure": "README is missing the documented post-fix not-implemented expectation.",
        },
        {
            "kind": "readme-operation-status",
            "path": "/pets/find",
            "status": "covered",
            "success": "README's post-fix narrative aligns with /pets/find being covered.",
            "failure": "README's post-fix narrative does not align with /pets/find being covered.",
        },
    ]


def compare_console_coverage_with_reports(
    console_output: str,
    coverage_report: dict[str, Any],
    html_report_text: str,
) -> list[dict[str, Any]]:
    console_rows = parse_console_coverage_rows(console_output)
    report_rows = parse_coverage_report_rows(coverage_report)
    html_rows = parse_html_report_rows(normalize_html_report_text(html_report_text))
    normalized_html = normalize_html_report_text(html_report_text)
    console_summary = parse_console_coverage_summary(console_output)
    html_summary = parse_html_coverage_summary(normalized_html)

    assertions: list[dict[str, Any]] = []
    assertions.append(
        assert_equal(
            console_rows,
            report_rows,
            "Console coverage summary matched the JSON coverage report summary.",
            "Console coverage summary did not match the JSON coverage report summary.",
            category="report",
            details=[
                detail("Console coverage rows", format_coverage_rows(console_rows)),
                detail("Coverage report rows", format_coverage_rows(report_rows)),
            ],
        )
    )
    assertions.append(
        assert_equal(
            console_summary,
            html_summary,
            "Console coverage totals matched the generated Specmatic HTML report totals.",
            "Console coverage totals did not match the generated Specmatic HTML report totals.",
            category="report",
            details=[
                detail_table(
                    "Coverage comparison",
                    headers=["Metric", "Console", "Specmatic HTML"],
                    rows=[
                        [
                            "Coverage",
                            console_summary.get("coverage"),
                            html_summary.get("coverage"),
                        ],
                        [
                            "Operations",
                            console_summary.get("operations"),
                            html_summary.get("operations"),
                        ],
                    ],
                ),
                detail(
                    "What this means",
                    "This check compares the coverage summary printed in the console with the coverage visible in the generated Specmatic HTML report for the same run.",
                ),
            ],
        )
    )
    assertions.append(
        assert_equal(
            extract_row_counts(console_rows),
            extract_row_counts(html_rows),
            "Console exercised counts matched the generated Specmatic HTML results counts for every operation.",
            "Console exercised counts did not match the generated Specmatic HTML results counts for one or more operations.",
            category="report",
            details=[
                detail_table(
                    "Exercised count comparison",
                    headers=["Path", "Method", "Response", "Console #exercised", "Specmatic HTML Results"],
                    rows=build_count_comparison_rows(console_rows, html_rows),
                ),
            ],
        )
    )
    assertions.append(
        assert_equal(
            extract_row_counts(report_rows),
            extract_row_counts(html_rows),
            "Coverage report counts matched the generated Specmatic HTML results counts for every operation.",
            "Coverage report counts did not match the generated Specmatic HTML results counts for one or more operations.",
            category="report",
            details=[
                detail_table(
                    "Coverage report vs HTML results",
                    headers=["Path", "Method", "Response", "coverage_report.json count", "Specmatic HTML Results"],
                    rows=build_count_comparison_rows(report_rows, html_rows),
                ),
            ],
        )
    )
    assertions.append(
        assert_equal(
            sum(row["count"] for row in console_rows),
            sum(row["count"] for row in html_rows),
            "Total console exercised count matched the total number of Specmatic HTML results.",
            "Total console exercised count did not match the total number of Specmatic HTML results.",
            category="report",
            details=[
                detail("Console total exercised count", sum(row["count"] for row in console_rows)),
                detail("Specmatic HTML total results", sum(row["count"] for row in html_rows)),
            ],
        )
    )

    for row in console_rows:
        row_signature = f'{row["path"]} {row["method"]} {row["status"]}'
        assertions.append(
            assert_condition(
                row["path"] in normalized_html and row["status"] in normalized_html,
                f"HTML report contains the console coverage row for {row_signature}.",
                f"HTML report does not contain the console coverage row for {row_signature}.",
                category="report",
                details=[
                    detail("Console coverage row", json.dumps(row, indent=2)),
                    detail("HTML evidence", extract_html_context(normalized_html, row["path"])),
                ],
            )
        )

    return assertions


def parse_console_coverage_rows(console_output: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in strip_ansi(console_output).splitlines():
        cleaned = line
        if "| |" in cleaned:
            cleaned = cleaned.split("| ", 1)[1]
        cleaned = cleaned.strip()
        match = CONSOLE_COVERAGE_ROW_RE.match(cleaned)
        if not match:
            continue
        rows.append(
            {
                "coverage": match.group("coverage"),
                "path": match.group("path").strip(),
                "method": match.group("method").strip(),
                "response": int(match.group("response")),
                "count": int(match.group("count")),
                "status": match.group("status").strip(),
            }
        )
    return rows


def parse_coverage_report_rows(coverage_report: dict[str, Any]) -> list[dict[str, Any]]:
    operations = coverage_report["apiCoverage"][0]["operations"]
    rows: list[dict[str, Any]] = []
    for operation in operations:
        percentage = "100%" if operation["coverageStatus"] == "covered" else "0%"
        rows.append(
            {
                "coverage": percentage,
                "path": operation["path"],
                "method": operation["method"],
                "response": operation["responseCode"],
                "count": operation["count"],
                "status": operation["coverageStatus"],
            }
        )
    return rows


def parse_html_report_rows(html_text: str) -> list[dict[str, Any]]:
    report = parse_html_embedded_report(html_text)
    operations = report["results"]["summary"]["extra"]["executionDetails"][0]["operations"]
    rows: list[dict[str, Any]] = []
    for operation in operations:
        percentage = "100%" if operation["coverageStatus"] == "covered" else "0%"
        rows.append(
            {
                "coverage": percentage,
                "path": operation["path"],
                "method": operation["method"],
                "response": operation["responseCode"],
                "count": len(operation.get("testIds", [])),
                "status": operation["coverageStatus"],
            }
        )
    return rows


def format_coverage_rows(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, indent=2)


def extract_row_counts(rows: list[dict[str, Any]]) -> list[tuple[str, str, int, int]]:
    return [
        (row["path"], row["method"], row["response"], row["count"])
        for row in rows
    ]


def build_count_comparison_rows(left_rows: list[dict[str, Any]], right_rows: list[dict[str, Any]]) -> list[list[Any]]:
    right_map = {
        (row["path"], row["method"], row["response"]): row["count"]
        for row in right_rows
    }
    rows: list[list[Any]] = []
    for row in left_rows:
        key = (row["path"], row["method"], row["response"])
        rows.append([row["path"], row["method"], row["response"], row["count"], right_map.get(key)])
    return rows


def parse_console_coverage_summary(console_output: str) -> dict[str, Any]:
    clean_output = strip_ansi(console_output)
    match = re.search(r"\|\s*(\d+%) API Coverage reported from (\d+) Operations\s*\|", clean_output)
    if not match:
        return {"coverage": None, "operations": None}
    return {"coverage": match.group(1), "operations": int(match.group(2))}


def parse_html_coverage_summary(html_text: str) -> dict[str, Any]:
    report = parse_html_embedded_report(html_text)
    operations = report["results"]["summary"]["extra"]["executionDetails"][0]["operations"]
    total_operations = len(operations)
    covered_operations = sum(1 for operation in operations if operation["coverageStatus"] == "covered")
    return {
        "coverage": f"{int((covered_operations / total_operations) * 100)}%" if total_operations else None,
        "operations": total_operations if total_operations > 0 else None,
    }


def extract_html_context(html_text: str, phrase: str, window: int = 220) -> str:
    if phrase not in html_text:
        return "Phrase not found in HTML report."
    index = html_text.index(phrase)
    start = max(0, index - window)
    end = min(len(html_text), index + len(phrase) + window)
    return html_text[start:end].strip()


def normalize_html_report_text(html_text: str) -> str:
    return html_text.replace("\\/", "/")


def parse_html_embedded_report(html_text: str) -> dict[str, Any]:
    match = re.search(r"const report = (\{.*?\});\s*const specmaticConfig =", html_text, re.DOTALL)
    if not match:
        raise ValueError("Could not find the embedded Specmatic report payload inside the HTML report.")
    return json.loads(match.group(1))


def evaluate_readme_assertions(
    readme_text: str,
    readme_assertions: list[dict[str, str]],
    result: CommandResult,
    operations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized_readme = normalize_space(readme_text)
    normalized_console = normalize_space(result.combined_output)
    statuses_by_path = {item["path"]: item["coverageStatus"] for item in operations}
    evaluated: list[dict[str, Any]] = []

    for item in readme_assertions:
        kind = item["kind"]
        if kind == "readme-contains":
            condition = normalize_space(item["text"]) in normalized_readme
            details = [
                detail("Expected README text", item["text"]),
                detail("README contains text", condition),
            ]
        elif kind == "readme-runtime-detail":
            condition = (
                normalize_space(item["text"]) in normalized_console
                and normalize_space(item["text"]) in normalized_readme
            )
            details = [
                detail("Runtime detail", item["text"]),
                detail("Seen in console", normalize_space(item["text"]) in normalized_console),
                detail("Seen in README", normalize_space(item["text"]) in normalized_readme),
                detail("Console excerpt", extract_context(result.combined_output, item["text"])),
            ]
        elif kind == "readme-operation-status":
            readme_has_path = normalize_space(item["path"]) in normalized_readme
            readme_has_status = normalize_space(item["status"]) in normalized_readme
            runtime_matches = statuses_by_path.get(item["path"]) == item["status"]
            condition = readme_has_path and readme_has_status and runtime_matches
            details = [
                detail("Path", item["path"]),
                detail("Expected status", item["status"]),
                detail("Runtime status", statuses_by_path.get(item["path"])),
                detail("README mentions path", readme_has_path),
                detail("README mentions status", readme_has_status),
            ]
        else:
            raise ValueError(f"Unknown README assertion kind: {kind}")

        evaluated.append(
            {
                "status": "passed" if condition else "failed",
                "message": item["success"] if condition else item["failure"],
                "category": "readme",
                "details": details,
            }
        )

    return evaluated


def normalize_space(value: str) -> str:
    return " ".join(value.split())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the api-coverage lab automation.")
    parser.add_argument(
        "--refresh-report",
        dest="refresh_report",
        action="store_true",
        help="Rebuild report.json and report.html from the existing captured artifacts without rerunning the lab.",
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip the root-level workspace setup stage.",
    )
    parser.add_argument(
        "--refresh-labs",
        action="store_true",
        help="Destructively reset ../labs to the latest state on the selected branch before running this lab.",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Branch to use with --refresh-labs. Defaults to main.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Required with --refresh-labs when ../labs has local changes. Discards tracked and untracked changes.",
    )
    return parser.parse_args()


def assert_equal(
    actual: Any,
    expected: Any,
    success_message: str,
    failure_message: str,
    *,
    category: str = "runtime",
    details: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "status": "passed" if actual == expected else "failed",
        "message": success_message if actual == expected else failure_message,
        "category": category,
        "details": details or [],
    }


def assert_condition(
    condition: bool,
    success_message: str,
    failure_message: str,
    *,
    category: str = "runtime",
    details: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "status": "passed" if condition else "failed",
        "message": success_message if condition else failure_message,
        "category": category,
        "details": details or [],
    }


def detail(label: str, value: Any) -> dict[str, str]:
    return {"label": label, "value": "" if value is None else str(value)}


def detail_table(label: str, headers: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {
        "type": "table",
        "label": label,
        "headers": headers,
        "rows": rows,
    }


def extract_context(text: str, phrase: str, window: int = 240) -> str:
    clean_text = strip_ansi(text)
    clean_phrase = strip_ansi(phrase)
    if clean_phrase not in clean_text:
        return "Phrase not found in captured output."
    index = clean_text.index(clean_phrase)
    start = max(0, index - window)
    end = min(len(clean_text), index + len(clean_phrase) + window)
    snippet = clean_text[start:end].strip()
    return snippet if snippet else clean_phrase


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


if __name__ == "__main__":
    raise SystemExit(main())
