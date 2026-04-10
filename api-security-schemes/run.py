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
    parse_html_embedded_report,
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "api-security-schemes"
README_FILE = UPSTREAM_LAB / "README.md"
SPECMATIC_FILE = UPSTREAM_LAB / "specmatic.yaml"
OUTPUT_DIR = ROOT / "api-security-schemes" / "output"
LAB_COMMAND = ["docker", "compose", "up", "specmatic-test", "--abort-on-container-exit"]


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the api-security-schemes lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="api-security-schemes",
        description="Automates the api-security-schemes lab with auth failure and auth fix verification.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"specmatic": SPECMATIC_FILE},
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
                label="specmatic-report.html",
                source_relpath="build/reports/specmatic/test/html/index.html",
                target_relpath="specmatic/test/html/index.html",
                kind="html",
                expected_markers=("const report =", "specmaticConfig", "<html"),
            ),
            ArtifactSpec(
                label="specmatic.yaml",
                source_relpath="specmatic.yaml",
                target_relpath="specmatic.yaml",
                kind="text",
                expected_markers=("securitySchemes:", "oAuth2AuthCode:", "basicAuth:", "apiKeyAuth:"),
            ),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Time required to complete this lab",
                "Prerequisites",
                "Architecture",
                "Security Schemes",
                "Lab Rules",
                "Intentional Failure",
                "Run the failing tests",
                "Your Task",
                "Verify the fix",
                "Troubleshooting",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the suite with intentionally invalid OAuth, Basic Auth, and API key settings.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=("401 Unauthorized", "Fetching OAuth token from Keycloak..."),
                include_readme_structure_checks=True,
                readme_assertions=(
                    readme_contains(
                        "401 Unauthorized",
                        "README documents the baseline unauthorized result.",
                        "README is missing the baseline unauthorized result.",
                    ),
                    readme_contains(
                        "docker compose up specmatic-test --abort-on-container-exit",
                        "README documents the baseline compose command.",
                        "README is missing the baseline compose command.",
                    ),
                ),
                file_transforms={"specmatic": set_baseline_tokens},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Restore valid token values and verify the secured suite passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=("Failures: 0",),
                readme_assertions=(
                    readme_contains(
                        "All 167 tests pass.",
                        "README documents the final all-tests-pass expectation.",
                        "README is missing the final all-tests-pass expectation.",
                    ),
                    readme_contains(
                        "Failures: 0",
                        "README documents the zero-failure summary.",
                        "README is missing the zero-failure summary.",
                    ),
                ),
                fix_summary=(
                    "Changed INVALID_OAUTH_TOKEN to OAUTH_TOKEN in specmatic.yaml.",
                    "Changed the Basic Auth fallback token to dXNlcjpwYXNzd29yZA== and the API key fallback token to APIKEY1234.",
                ),
                file_transforms={"specmatic": set_fixed_tokens},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        *build_security_summary_assertions(context, expected_total=167, expected_passed=0, expected_failed=167),
        assert_condition(
            "${INVALID_OAUTH_TOKEN:OAUTH1234}" in context.artifacts["specmatic.yaml"]["text"],
            "Baseline specmatic.yaml kept the intentionally invalid OAuth fallback.",
            "Baseline specmatic.yaml did not keep the intentionally invalid OAuth fallback.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
        assert_condition(
            "dXNlcjppbnZhbGlkcGFzcw==" in context.artifacts["specmatic.yaml"]["text"]
            and "INVALID_APIKEY1234" in context.artifacts["specmatic.yaml"]["text"],
            "Baseline specmatic.yaml kept the intentionally invalid Basic Auth and API key fallbacks.",
            "Baseline specmatic.yaml did not keep the intentionally invalid Basic Auth and API key fallbacks.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        *build_security_summary_assertions(context, expected_total=167, expected_passed=167, expected_failed=0),
        assert_condition(
            "${OAUTH_TOKEN:OAUTH1234}" in context.artifacts["specmatic.yaml"]["text"],
            "Fixed specmatic.yaml uses the correct OAuth environment variable name.",
            "Fixed specmatic.yaml does not use the correct OAuth environment variable name.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
        assert_condition(
            "dXNlcjpwYXNzd29yZA==" in context.artifacts["specmatic.yaml"]["text"]
            and "APIKEY1234" in context.artifacts["specmatic.yaml"]["text"],
            "Fixed specmatic.yaml uses the correct Basic Auth and API key fallbacks.",
            "Fixed specmatic.yaml does not use the correct Basic Auth and API key fallbacks.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def build_security_summary_assertions(
    context: ValidationContext,
    *,
    expected_total: int,
    expected_passed: int,
    expected_failed: int,
) -> list[dict]:
    coverage_report = context.artifacts["coverage_report.json"]["json"]
    html_report = parse_html_embedded_report(context.artifacts["specmatic-report.html"]["text"])
    html_summary = html_report["results"]["summary"]
    html_total = html_summary.get("tests", 0)
    html_failures = html_summary.get("failed", 0)
    operations = coverage_report.get("apiCoverage", [{}])[0].get("operations", [])
    missing_in_spec = sum(1 for operation in operations if operation.get("coverageStatus") == "missing in spec")
    covered = sum(1 for operation in operations if operation.get("coverageStatus") == "covered")

    return [
        assert_equal(
            html_total,
            expected_total,
            f"Specmatic HTML summary reported {expected_total} tests as expected.",
            f"Specmatic HTML summary expected {expected_total} tests, got {html_total}.",
            category="report",
            details=[detail("Expected total", expected_total), detail("Actual total", html_total)],
        ),
        assert_equal(
            html_summary.get("passed", 0),
            expected_passed,
            f"Specmatic HTML passing count matched expected value {expected_passed}.",
            f"Specmatic HTML passing count expected {expected_passed}, got {html_summary.get('passed', 0)}.",
            category="report",
            details=[detail("Expected passed", expected_passed), detail("Actual passed", html_summary.get("passed", 0))],
        ),
        assert_equal(
            html_failures,
            expected_failed,
            f"Specmatic HTML failure count matched expected value {expected_failed}.",
            f"Specmatic HTML failure count expected {expected_failed}, got {html_failures}.",
            category="report",
            details=[detail("Expected failed", expected_failed), detail("Actual failed", html_failures)],
        ),
        assert_condition(
            len(operations) > 0,
            "Coverage report listed API operations.",
            "Coverage report did not list any API operations.",
            category="report",
            details=[detail("Operations listed", len(operations))],
        ),
        assert_condition(
            missing_in_spec > 0 if expected_failed > 0 else missing_in_spec == 0,
            "Coverage report reflected the expected missing-in-spec status for this phase.",
            "Coverage report missing-in-spec status did not match the expected phase behavior.",
            category="report",
            details=[
                detail("Expected failures", expected_failed),
                detail("Missing in spec operations", missing_in_spec),
                detail("Covered operations", covered),
            ],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_baseline_tokens(content: str) -> str:
    updated = content.replace("${OAUTH_TOKEN:OAUTH1234}", "${INVALID_OAUTH_TOKEN:OAUTH1234}")
    updated = updated.replace("dXNlcjpwYXNzd29yZA==", "dXNlcjppbnZhbGlkcGFzcw==")
    updated = updated.replace("APIKEY1234", "INVALID_APIKEY1234")
    return updated


def set_fixed_tokens(content: str) -> str:
    updated = content.replace("${INVALID_OAUTH_TOKEN:OAUTH1234}", "${OAUTH_TOKEN:OAUTH1234}")
    updated = updated.replace("dXNlcjppbnZhbGlkcGFzcw==", "dXNlcjpwYXNzd29yZA==")
    updated = updated.replace("INVALID_APIKEY1234", "APIKEY1234")
    return updated


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
