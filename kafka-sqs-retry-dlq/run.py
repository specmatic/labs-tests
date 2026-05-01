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
    clear_docker_owned_build_dir,
    detail,
    docker_compose_down,
    run_lab,
)


UPSTREAM_LAB = ROOT.parent / "labs" / "kafka-sqs-retry-dlq"
README_FILE = UPSTREAM_LAB / "README.md"
APP_FILE = UPSTREAM_LAB / "service" / "app.py"
OUTPUT_DIR = ROOT / "kafka-sqs-retry-dlq" / "output"
LAB_COMMAND = ["docker", "compose", "up", "contract-test", "--build", "--abort-on-container-exit"]
RETRY_THREAD_COMMENT = "            # threading.Thread(target=self._run_retry_consumer, name=\"RetryConsumer\", daemon=True),\n"
RETRY_THREAD_ENABLED = "            threading.Thread(target=self._run_retry_consumer, name=\"RetryConsumer\", daemon=True),\n"


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the kafka-sqs-retry-dlq lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="kafka-sqs-retry-dlq",
        description="Automates the kafka-sqs-retry-dlq lab by verifying the incomplete retry pipeline before the fix and the full pass state after enabling the retry consumer.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"app": APP_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
            ArtifactSpec("ctrf-report.json", "build/reports/specmatic/async/test/ctrf/ctrf-report.json", "ctrf-report.json", "json", ("results",)),
            ArtifactSpec("coverage-report.json", "build/reports/specmatic/async/coverage-report.json", "coverage-report.json", "json"),
            ArtifactSpec("specmatic-report.html", "build/reports/specmatic/async/test/html/index.html", "specmatic/test/html/index.html", "html", expected_markers=("const report =", "specmaticConfig", "<html")),
            ArtifactSpec("app.py", "service/app.py", "service/app.py", "text", expected_markers=("RetryConsumer", "_run_retry_consumer", "place-order-retry-topic")),
        ),

        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the async suite with the retry consumer disabled and verify the two retry-path failures.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(),
                include_readme_structure_checks=True,
                readme_assertions=(),
                file_transforms={"app": set_app_baseline},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Enable the retry consumer so retry-success and retry-to-DLQ scenarios are reprocessed correctly.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=(),
                readme_assertions=(),
                fix_summary=("Uncommented the RetryConsumer thread entry in service/app.py so messages from place-order-retry-topic are consumed and reprocessed.",),
                file_transforms={"app": set_app_fixed},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            RETRY_THREAD_COMMENT.strip() in context.artifacts["app.py"]["text"],
            "Baseline app.py still leaves the retry consumer thread commented out.",
            "Baseline app.py does not keep the retry consumer thread commented out.",
            category="report",
            details=[detail("Artifact path", context.artifacts["app.py"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            RETRY_THREAD_ENABLED.strip() in context.artifacts["app.py"]["text"]
            and RETRY_THREAD_COMMENT.strip() not in context.artifacts["app.py"]["text"],
            "Fixed app.py starts the retry consumer thread.",
            "Fixed app.py does not start the retry consumer thread.",
            category="report",
            details=[detail("Artifact path", context.artifacts["app.py"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_app_baseline(content: str) -> str:
    return content.replace(RETRY_THREAD_ENABLED, RETRY_THREAD_COMMENT)


def set_app_fixed(content: str) -> str:
    return content.replace(RETRY_THREAD_COMMENT, RETRY_THREAD_ENABLED)


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
