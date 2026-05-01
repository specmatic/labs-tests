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


UPSTREAM_LAB = ROOT.parent / "labs" / "schema-design"
README_FILE = UPSTREAM_LAB / "README.md"
SPEC_FILE = UPSTREAM_LAB / "specs" / "payment-api.yaml"
OUTPUT_DIR = ROOT / "schema-design" / "output"
LAB_COMMAND = ["docker", "compose", "up", "contract-test", "--build", "--abort-on-container-exit"]

FIXED_SCHEMA = """openapi: 3.0.0
info:
  title: Payment API
  version: "1.0"
servers:
  - url: http://localhost:8080
paths:
  /payments:
    post:
      summary: Create a payment
      operationId: createPayment
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: "#/components/schemas/PaymentRequest"
      responses:
        "201":
          description: Payment accepted
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/PaymentAccepted"
        "400":
          description: Bad request
          content:
            application/json:
              schema:
                $ref: "#/components/schemas/ErrorResponse"
components:
  schemas:
    CardPaymentRequest:
      type: object
      required:
        - paymentType
        - cardNumber
        - cardExpiry
        - cardCvv
      properties:
        paymentType:
          type: string
          enum: [ card ]
        cardNumber:
          type: string
        cardExpiry:
          type: string
        cardCvv:
          type: string
    BankTransferPaymentRequest:
      type: object
      required:
        - paymentType
        - bankAccountNumber
        - bankRoutingNumber
        - bankAccountHolder
      properties:
        paymentType:
          type: string
          enum: [ bank_transfer ]
        bankAccountNumber:
          type: string
        bankRoutingNumber:
          type: string
        bankAccountHolder:
          type: string
    PaymentRequest:
      oneOf:
        - $ref: "#/components/schemas/CardPaymentRequest"
        - $ref: "#/components/schemas/BankTransferPaymentRequest"
      discriminator:
        propertyName: paymentType
        mapping:
          card: "#/components/schemas/CardPaymentRequest"
          bank_transfer: "#/components/schemas/BankTransferPaymentRequest"
    PaymentAccepted:
      type: object
      additionalProperties: false
      properties:
        id:
          type: integer
        status:
          type: string
      required:
        - id
        - status
    ErrorResponse:
      type: object
      additionalProperties: false
      properties:
        message:
          type: string
      required:
        - message
"""


def main() -> int:
    parser = add_standard_lab_args(argparse.ArgumentParser(description="Run the schema-design lab automation."))
    args = parser.parse_args()
    return run_lab(build_lab_spec(), args)


def build_lab_spec() -> LabSpec:
    return LabSpec(
        name="schema-design",
        description="Automates the schema-design lab with baseline optional-group failures and oneOf fix verification.",
        root=ROOT,
        upstream_lab=UPSTREAM_LAB,
        files={"payment_spec": SPEC_FILE},
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
            ArtifactSpec(
                label="payment-api.yaml",
                source_relpath="specs/payment-api.yaml",
                target_relpath="specs/payment-api.yaml",
                kind="text",
                expected_markers=("PaymentRequest", "/payments"),
            ),
        ),
        phases=(
            PhaseSpec(
                name="Baseline mismatch",
                description="Run the baseline schema and verify the invalidly modeled requests fail with 400 vs 201 mismatches.",
                expected_exit_code=1,
                output_dir_name="baseline",
                expected_console_phrases=(
                    "Specification expected status 201 but response contained status 400",
                ),
                include_readme_structure_checks=True,
                readme_assertions=(
                    readme_runtime_detail(
                        "response contained `400` instead of expected `201`",
                        "README captures the baseline 400 vs 201 mismatch detail.",
                        "README does not mention the baseline 400 vs 201 mismatch detail.",
                    ),
                ),
                extra_assertions=baseline_assertions,
            ),
            PhaseSpec(
                name="Fixed contract",
                description="Replace PaymentRequest with oneOf plus discriminator and verify the suite passes.",
                expected_exit_code=0,
                output_dir_name="fixed",
                expected_console_phrases=(),
                readme_assertions=(),
                fix_summary=(
                    "Replaced the single optional-group PaymentRequest with oneOf over CardPaymentRequest and BankTransferPaymentRequest.",
                    "Added discriminator.propertyName and mapping for paymentType so generated requests stay shape-correct.",
                ),
                file_transforms={"payment_spec": set_fixed_schema},
                extra_assertions=fixed_assertions,
            ),
        ),
        clear_reports=clear_previous_reports,
        post_phase_cleanup=teardown_compose,
    )


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "oneOf:" not in context.artifacts["payment-api.yaml"]["text"],
            "Baseline payment-api.yaml still uses the pre-oneOf PaymentRequest model.",
            "Baseline payment-api.yaml unexpectedly already contains oneOf.",
            category="report",
            details=[detail("Artifact path", context.artifacts["payment-api.yaml"]["path"])],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "oneOf:" in context.artifacts["payment-api.yaml"]["text"] and "discriminator:" in context.artifacts["payment-api.yaml"]["text"],
            "Fixed payment-api.yaml contains oneOf and discriminator.",
            "Fixed payment-api.yaml does not contain the expected oneOf plus discriminator structure.",
            category="report",
            details=[detail("Artifact path", context.artifacts["payment-api.yaml"]["path"])],
        ),
    ]


def clear_previous_reports(spec: LabSpec) -> None:
    clear_docker_owned_build_dir(spec)


def teardown_compose(spec: LabSpec) -> None:
    docker_compose_down(spec, "down", "-v")


def set_fixed_schema(content: str) -> str:
    return FIXED_SCHEMA


def readme_runtime_detail(text: str, success: str, failure: str) -> dict[str, str]:
    return {"kind": "readme-runtime-detail", "text": text, "success": success, "failure": failure}


if __name__ == "__main__":
    raise SystemExit(main())
