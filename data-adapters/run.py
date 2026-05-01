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
from lablib.compose_runtime import RUNTIME_NOTICE


UPSTREAM_LAB = ROOT.parent / "labs" / "data-adapters"
README_FILE = UPSTREAM_LAB / "README.md"
SPECMATIC_FILE = UPSTREAM_LAB / "specmatic.yaml"
OUTPUT_DIR = ROOT / "data-adapters" / "output"
LAB_COMMAND = ["python3", str(ROOT / "lablib" / "data_adapters_runner.py")]
ADAPTERS_BLOCK = """
  data:
    adapters:
      pre_specmatic_request_processor: ./hooks/pre_specmatic_request_processor.sh
      post_specmatic_response_processor: ./hooks/post_specmatic_response_processor.sh
"""


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the data-adapters lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="data-adapters",
        description="Automates the data-adapters lab by exercising the UI flow before and after wiring the request and response processor hooks.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"specmatic": SPECMATIC_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
            ArtifactSpec("specmatic.yaml", "specmatic.yaml", "specmatic.yaml", "text", expected_markers=("camelCase.yaml",)),
            ArtifactSpec("http-response.json", "build/data-adapters/http-response.json", "build/data-adapters/http-response.json", "json", ("status", "body", "request")),
            ArtifactSpec("compose.log", "build/data-adapters/compose.log", "build/data-adapters/compose.log", "text"),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Time required to complete this lab",
                "Prerequisites",
                "Architecture",
                "Files in this lab",
                "Reference",
                "Lab Rules",
                "1. Start mock + UI",
                "2. Trigger the mismatch from browser (intentional failure)",
                "3. Cleanup",
                "4. Configure hooks in `specmatic.yaml`",
                "5. Ensure hook scripts are executable",
                "6. Restart mock + UI",
                "7. Trigger the matching request/response from browser",
                "8. Cleanup",
                "Windows Notes",
                "9. Verify in Studio (Optional)",
                "10. Cleanup",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the UI flow without the adapters block and verify the PascalCase request fails with HTTP 400.",
                expected_exit_code=0,
                output_dir_name="baseline",
                expected_console_phrases=("Observed HTTP 400 response from the UI flow.",),
                include_readme_structure_checks=True,
                readme_assertions=(readme_contains("Observe a 400 bad-request response in the result panel.", "README documents the initial HTTP 400 mismatch.", "README is missing the initial HTTP 400 mismatch."),),
                file_transforms={"specmatic": set_baseline_specmatic},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Wire the pre and post processor hooks in specmatic.yaml and verify the UI flow succeeds with HTTP 200.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=("Observed HTTP 200 response from the UI flow.",),
                readme_assertions=(readme_contains("Observe a 200 response in the result panel.", "README documents the final HTTP 200 flow.", "README is missing the final HTTP 200 flow."),),
                fix_summary=(
                    "Added dependencies.data.adapters.pre_specmatic_request_processor to specmatic.yaml.",
                    "Added dependencies.data.adapters.post_specmatic_response_processor to specmatic.yaml.",
                ),
                file_transforms={"specmatic": set_fixed_specmatic},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
        runtime_warnings=(RUNTIME_NOTICE,),
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    response = load_http_response(context)
    return [
        assert_condition(
            response.get("status") == 400,
            "Baseline UI flow returned HTTP 400 as expected before the adapters were configured.",
            f"Baseline UI flow expected HTTP 400, got {response.get('status')}.",
            category="console",
            details=[detail("Response body", response.get("body", ""))],
        ),
        assert_condition(
            "adapters:" not in context.artifacts["specmatic.yaml"]["text"],
            "Baseline specmatic.yaml does not configure request/response adapters.",
            "Baseline specmatic.yaml unexpectedly configures request/response adapters.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    response = load_http_response(context)
    return [
        assert_condition(
            response.get("status") == 200,
            "Fixed UI flow returned HTTP 200 after the adapters were configured.",
            f"Fixed UI flow expected HTTP 200, got {response.get('status')}.",
            category="console",
            details=[detail("Response body", response.get("body", ""))],
        ),
        assert_condition(
            "pre_specmatic_request_processor" in context.artifacts["specmatic.yaml"]["text"]
            and "post_specmatic_response_processor" in context.artifacts["specmatic.yaml"]["text"],
            "Fixed specmatic.yaml wires both data adapter hooks.",
            "Fixed specmatic.yaml does not wire both data adapter hooks.",
            category="report",
            details=[detail("Artifact path", context.artifacts["specmatic.yaml"]["path"])],
        ),
    ]


def load_http_response(context: ValidationContext) -> dict[str, object]:
    return context.artifacts["http-response.json"]["json"]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)
    data_build_dir = spec.upstream_lab / "build" / "data-adapters"
    if data_build_dir.exists():
        import shutil

        shutil.rmtree(data_build_dir, ignore_errors=True)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_baseline_specmatic(content: str) -> str:
    return content.replace(ADAPTERS_BLOCK, "")


def set_fixed_specmatic(content: str) -> str:
    if "pre_specmatic_request_processor" in content:
        return content
    return content.rstrip() + "\n" + ADAPTERS_BLOCK


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
