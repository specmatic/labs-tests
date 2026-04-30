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


UPSTREAM_LAB = ROOT.parent / "labs" / "kafka-avro"
README_FILE = UPSTREAM_LAB / "README.md"
NEW_ORDERS_FILE = UPSTREAM_LAB / "docker-config" / "avro" / "NewOrders.avsc"
WIP_ORDERS_FILE = UPSTREAM_LAB / "docker-config" / "avro" / "WipOrders.avsc"
IPHONE_FILE = UPSTREAM_LAB / "api-specs" / "order-service-async-avro-v3_0_0_examples" / "PLACE_IPHONE_ORDER.json"
MACBOOK_FILE = UPSTREAM_LAB / "api-specs" / "order-service-async-avro-v3_0_0_examples" / "PLACE_MACBOOK_ORDER.json"
OUTPUT_DIR = ROOT / "kafka-avro" / "output"
LAB_COMMAND = ["docker", "compose", "up", "specmatic-test", "--abort-on-container-exit"]
FIXED_NEW_ORDERS = """{
  "type": "record",
  "name": "OrderRequest",
  "namespace": "order",
  "fields": [
    {
      "name": "id",
      "type": "int",
      "x-minimum": 1,
      "x-maximum": 100
    },
    {
      "name": "orderItems",
      "type": {
        "type": "array",
        "items": {
          "type": "record",
          "name": "Item",
          "fields": [
            { "name": "id", "type": "int" },
            {
              "name": "name",
              "type": "string",
              "x-minLength": 2,
              "x-maxLength": 10,
              "x-regex": "^[A-Za-z]{2,10}$"
            },
            { "name": "quantity", "type": "int" },
            {
              "name": "price",
              "type": "int",
              "x-minimum": 1000
            }
          ]
        }
      }
    }
  ]
}
"""
FIXED_WIP_ORDERS = """{
  "type": "record",
  "name": "OrderToProcess",
  "namespace": "order",
  "fields": [
    {
      "name": "id",
      "type": "int",
      "x-minimum": 1,
      "x-maximum": 100
    },
    {
      "name": "status",
      "type": {
        "type": "enum",
        "name": "OrderStatus",
        "symbols": ["PENDING", "PROCESSING", "COMPLETED", "CANCELLED"]
      }
    }
  ]
}
"""
FIXED_IPHONE = """{
  "name": "PLACE_IPHONE_ORDER",
  "receive": {
    "topic": "new-orders",
    "key": 1,
    "payload": {
      "id": 1,
      "orderItems": [
        {
          "id": 1,
          "name": "iPhone",
          "quantity": 10,
          "price": 5000
        }
      ]
    }
  },
  "send": {
    "topic": "wip-orders",
    "key": 1,
    "payload": {
      "id": "$match(exact:1)",
      "status": "$match(exact:PROCESSING)"
    }
  }
}
"""
FIXED_MACBOOK = """{
  "name": "PLACE_MACBOOK_ORDER",
  "receive": {
    "topic": "new-orders",
    "key": 2,
    "payload": {
      "id": 2,
      "orderItems": [
        {
          "id": 1,
          "name": "Macbook",
          "quantity": 50,
          "price": 6000
        }
      ]
    }
  },
  "send": {
    "topic": "wip-orders",
    "key": 2,
    "payload": {
      "id": "$match(exact:2)",
      "status": "$match(exact:PROCESSING)"
    }
  }
}
"""


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the kafka-avro lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="kafka-avro",
        description="Automates the kafka-avro lab by validating the baseline async timeout and the fixed schema-and-example pass state.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={
            "new_orders": NEW_ORDERS_FILE,
            "wip_orders": WIP_ORDERS_FILE,
            "iphone": IPHONE_FILE,
            "macbook": MACBOOK_FILE,
        },
        readme_path=README_FILE,
        output_dir=OUTPUT_DIR,
        command=LAB_COMMAND,
        common_artifact_specs=(
            ArtifactSpec("ctrf-report.json", "build/reports/specmatic/async/test/ctrf/ctrf-report.json", "ctrf-report.json", "json", ("results",)),
            ArtifactSpec("coverage-report.json", "build/reports/specmatic/async/coverage-report.json", "coverage-report.json", "json"),
            ArtifactSpec("specmatic-report.html", "build/reports/specmatic/async/test/html/index.html", "specmatic/test/html/index.html", "html", expected_markers=("const report =", "specmaticConfig", "<html")),
            ArtifactSpec("NewOrders.avsc", "docker-config/avro/NewOrders.avsc", "docker-config/avro/NewOrders.avsc", "text", expected_markers=("OrderRequest", "orderItems")),
            ArtifactSpec("WipOrders.avsc", "docker-config/avro/WipOrders.avsc", "docker-config/avro/WipOrders.avsc", "text", expected_markers=("OrderToProcess", "OrderStatus")),
            ArtifactSpec("PLACE_IPHONE_ORDER.json", "api-specs/order-service-async-avro-v3_0_0_examples/PLACE_IPHONE_ORDER.json", "api-specs/order-service-async-avro-v3_0_0_examples/PLACE_IPHONE_ORDER.json", "text", expected_markers=("PLACE_IPHONE_ORDER", "new-orders", "wip-orders")),
            ArtifactSpec("PLACE_MACBOOK_ORDER.json", "api-specs/order-service-async-avro-v3_0_0_examples/PLACE_MACBOOK_ORDER.json", "api-specs/order-service-async-avro-v3_0_0_examples/PLACE_MACBOOK_ORDER.json", "text", expected_markers=("PLACE_MACBOOK_ORDER", "new-orders", "wip-orders")),
        ),
        readme_structure=ReadmeStructureSpec(
            required_h2_prefixes=(
                "Objective",
                "Time required to complete this lab",
                "Prerequisites",
                "AsyncAPI and Avro Overview Video",
                "Files in this lab",
                "Lab Rules",
                "Architecture mental model",
                "Run the baseline and observe the failure",
                "Learner task",
                "Fix path",
                "Verify the fix",
                "What changed and why",
                "Troubleshooting",
                "Optional extension",
                "Next step",
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the async suite with permissive schemas and invalid examples and verify the timeout failure.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(
                    "Timeout waiting for a message on topic 'wip-orders'.",
                ),
                include_readme_structure_checks=True,
                readme_assertions=(),
                file_transforms={
                    "new_orders": set_new_orders_baseline,
                    "wip_orders": set_wip_orders_baseline,
                    "iphone": set_iphone_baseline,
                    "macbook": set_macbook_baseline,
                },
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Tighten the Avro schemas and align the examples so the async suite passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=(),
                readme_assertions=(),
                fix_summary=(
                    "Added id, name, and price constraints to docker-config/avro/NewOrders.avsc.",
                    "Added id constraints to docker-config/avro/WipOrders.avsc.",
                    "Updated both external examples so their payload values satisfy the tightened Avro constraints.",
                ),
                file_transforms={
                    "new_orders": set_new_orders_fixed,
                    "wip_orders": set_wip_orders_fixed,
                    "iphone": set_iphone_fixed,
                    "macbook": set_macbook_fixed,
                },
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            '"x-minimum"' not in context.artifacts["NewOrders.avsc"]["text"] and '"x-regex"' not in context.artifacts["NewOrders.avsc"]["text"],
            "Baseline NewOrders.avsc remains permissive and lacks the additional constraints.",
            "Baseline NewOrders.avsc unexpectedly contains the fixed constraints.",
            category="report",
            details=[detail("Artifact path", context.artifacts["NewOrders.avsc"]["path"])],
        ),
        assert_condition(
            '"id": 101' in context.artifacts["PLACE_IPHONE_ORDER.json"]["text"]
            and '"iPhone 14 Pro Max"' in context.artifacts["PLACE_IPHONE_ORDER.json"]["text"]
            and '"price": 500.00' in context.artifacts["PLACE_IPHONE_ORDER.json"]["text"],
            "Baseline iPhone example still contains invalid values that the service rejects.",
            "Baseline iPhone example no longer contains the invalid values.",
            category="report",
            details=[detail("Artifact path", context.artifacts["PLACE_IPHONE_ORDER.json"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            '"x-minimum": 1' in context.artifacts["NewOrders.avsc"]["text"]
            and '"x-regex": "^[A-Za-z]{2,10}$"' in context.artifacts["NewOrders.avsc"]["text"],
            "Fixed NewOrders.avsc contains the expected explicit constraints.",
            "Fixed NewOrders.avsc does not contain the expected explicit constraints.",
            category="report",
            details=[detail("Artifact path", context.artifacts["NewOrders.avsc"]["path"])],
        ),
        assert_condition(
            '"id": 1' in context.artifacts["PLACE_IPHONE_ORDER.json"]["text"]
            and '"iPhone"' in context.artifacts["PLACE_IPHONE_ORDER.json"]["text"]
            and '"price": 5000' in context.artifacts["PLACE_IPHONE_ORDER.json"]["text"],
            "Fixed iPhone example uses values that satisfy the explicit Avro constraints.",
            "Fixed iPhone example does not use the expected valid values.",
            category="report",
            details=[detail("Artifact path", context.artifacts["PLACE_IPHONE_ORDER.json"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v", "--remove-orphans")


def set_new_orders_baseline(content: str) -> str:
    return content


def set_new_orders_fixed(_: str) -> str:
    return FIXED_NEW_ORDERS


def set_wip_orders_baseline(content: str) -> str:
    return content


def set_wip_orders_fixed(_: str) -> str:
    return FIXED_WIP_ORDERS


def set_iphone_baseline(content: str) -> str:
    return content


def set_iphone_fixed(_: str) -> str:
    return FIXED_IPHONE


def set_macbook_baseline(content: str) -> str:
    return content


def set_macbook_fixed(_: str) -> str:
    return FIXED_MACBOOK


def readme_contains(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-contains", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
