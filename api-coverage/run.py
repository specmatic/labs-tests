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

BASELINE_PATH = "/pets/search:"
FIXED_PATH = "/pets/find:"


def main() -> int:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    original_spec = SPEC_FILE.read_text(encoding="utf-8")
    readme_text = README_FILE.read_text(encoding="utf-8")
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
            category="runtime",
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
                category="runtime",
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
                category="runtime",
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
                category="runtime",
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
                category="runtime",
                details=[
                    detail("Expected phrase", phrase),
                    detail("Console excerpt", extract_context(result.combined_output, phrase)),
                ],
            )
        )

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
