from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
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


UPSTREAM_LAB = ROOT.parent / "labs" / "async-event-flow"
README_FILE = UPSTREAM_LAB / "README.md"
ACCEPT_ORDER_FILE = UPSTREAM_LAB / "examples" / "async-order-service" / "acceptOrder.json"
OUT_FOR_DELIVERY_FILE = UPSTREAM_LAB / "examples" / "async-order-service" / "outForDeliveryOrder.json"
OUTPUT_DIR = ROOT / "async-event-flow" / "output"
LAB_COMMAND = ["/bin/sh", "-lc", "docker compose up -d && docker compose exec -T studio specmatic run-suite"]
CONTAINER_NAMES = ["studio", "order-service-sut", "kafka-init", "kafka"]
BEFORE_FIXTURE = """  "before": [
    {
      "type": "http",
      "wait": "PT1S",
      "http-request": {
        "baseUrl": "http://sut:8080",
        "path": "/orders",
        "method": "PUT",
        "headers": {
          "Content-Type": "application/json"
        },
        "body": {
          "id": 123,
          "status": "ACCEPTED",
          "timestamp": "2025-04-12T14:30:00Z"
        }
      },
      "http-response": {
        "status": 200
      },
      "timeout": "PT30S"
    }
  ],
"""


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the async-event-flow lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="async-event-flow",
        description="Automates the async-event-flow lab by verifying the missing before fixture and incorrect after assertion before and after fixing the examples.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"accept_order": ACCEPT_ORDER_FILE, "out_for_delivery": OUT_FOR_DELIVERY_FILE},
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
            ArtifactSpec("ctrf-report.json", "build/reports/specmatic/async/test/ctrf/ctrf-report.json", "ctrf-report.json", "json", ("results",)),
            ArtifactSpec("coverage-report.json", "build/reports/specmatic/async/coverage-report.json", "coverage-report.json", "json"),
            ArtifactSpec("specmatic-report.html", "build/reports/specmatic/async/test/html/index.html", "specmatic/test/html/index.html", "html", expected_markers=("const report =", "specmaticConfig", "<html")),
            ArtifactSpec("acceptOrder.json", "examples/async-order-service/acceptOrder.json", "examples/async-order-service/acceptOrder.json", "text", expected_markers=("ACCEPT_ORDER", "accepted-orders")),
            ArtifactSpec("outForDeliveryOrder.json", "examples/async-order-service/outForDeliveryOrder.json", "examples/async-order-service/outForDeliveryOrder.json", "text", expected_markers=("ORDER_OUT_FOR_DELIVERY", "tax-invoice-for-order-456")),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Background",
                "Time required to complete this lab",
                "Objective",
                "Prerequisites",
                "Lab Rules",
                "How to test these event flows",
                "Run the contract tests using Specmatic Studio",
                "Troubleshooting",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the async suite with the missing before fixture and wrong tax verification count.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(),
                include_readme_structure_checks=True,
                readme_assertions=(),
                file_transforms={"accept_order": set_accept_baseline, "out_for_delivery": set_delivery_baseline},
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Add the before fixture and correct the after assertion so the async suite passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=(),
                readme_assertions=(),
                fix_summary=(
                    "Added the missing before HTTP fixture to examples/async-order-service/acceptOrder.json.",
                    "Changed the TaxService verification count in examples/async-order-service/outForDeliveryOrder.json from 2 to 1.",
                ),
                file_transforms={"accept_order": set_accept_fixed, "out_for_delivery": set_delivery_fixed},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            '"before"' not in context.artifacts["acceptOrder.json"]["text"],
            "Baseline acceptOrder.json still omits the before fixture.",
            "Baseline acceptOrder.json unexpectedly includes the before fixture.",
            category="report",
            details=[detail("Artifact path", context.artifacts["acceptOrder.json"]["path"])],
        ),
        assert_condition(
            "$match(exact: 2)" in context.artifacts["outForDeliveryOrder.json"]["text"],
            "Baseline outForDeliveryOrder.json still expects the incorrect tax verification count of 2.",
            "Baseline outForDeliveryOrder.json does not keep the incorrect tax verification count of 2.",
            category="report",
            details=[detail("Artifact path", context.artifacts["outForDeliveryOrder.json"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            '"before"' in context.artifacts["acceptOrder.json"]["text"] and '"path": "/orders"' in context.artifacts["acceptOrder.json"]["text"],
            "Fixed acceptOrder.json includes the before HTTP fixture.",
            "Fixed acceptOrder.json does not include the before HTTP fixture.",
            category="report",
            details=[detail("Artifact path", context.artifacts["acceptOrder.json"]["path"])],
        ),
        assert_condition(
            "$match(exact: 1)" in context.artifacts["outForDeliveryOrder.json"]["text"]
            and "$match(exact: 2)" not in context.artifacts["outForDeliveryOrder.json"]["text"],
            "Fixed outForDeliveryOrder.json expects the corrected tax verification count of 1.",
            "Fixed outForDeliveryOrder.json does not expect the corrected tax verification count of 1.",
            category="report",
            details=[detail("Artifact path", context.artifacts["outForDeliveryOrder.json"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    cleanup_stale_containers()
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")
    cleanup_stale_containers()


def cleanup_stale_containers() -> None:
    subprocess.run(["docker", "rm", "-f", *CONTAINER_NAMES], check=False, text=True, capture_output=True)


def set_accept_baseline(content: str) -> str:
    return content.replace(BEFORE_FIXTURE, "")


def set_accept_fixed(content: str) -> str:
    if '"before"' in content:
        return content
    return content.replace('  "send": {\n', BEFORE_FIXTURE + '  "send": {\n', 1)


def set_delivery_baseline(content: str) -> str:
    return content.replace("$match(exact: 1)", "$match(exact: 2)")


def set_delivery_fixed(content: str) -> str:
    return content.replace("$match(exact: 2)", "$match(exact: 1)")


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
