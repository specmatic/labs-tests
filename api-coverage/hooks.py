from __future__ import annotations

from lablib.scaffold import ValidationContext, assert_condition, detail


BASELINE_PATH = "/pets/search:"
FIXED_PATH = "/pets/find:"


def baseline_assertions(context: ValidationContext) -> list[dict]:
    if not context.command_result.started_at:
        return []
    service_spec_path = context.lab.files["service_spec"]
    service_spec_text = service_spec_path.read_text(encoding="utf-8")
    return [
        assert_condition(
            BASELINE_PATH in service_spec_text and FIXED_PATH not in service_spec_text,
            "Baseline spec keeps GET /pets/search and does not include GET /pets/find.",
            "Baseline spec does not match the expected broken /pets/search state.",
            category="report",
            details=[detail("Spec path", service_spec_path)],
        ),
    ]


def fixed_assertions(context: ValidationContext) -> list[dict]:
    if not context.command_result.started_at:
        return []
    service_spec_path = context.lab.files["service_spec"]
    service_spec_text = service_spec_path.read_text(encoding="utf-8")
    return [
        assert_condition(
            FIXED_PATH in service_spec_text and BASELINE_PATH not in service_spec_text,
            "Fixed spec switches to GET /pets/find and removes GET /pets/search.",
            "Fixed spec does not match the expected /pets/find state.",
            category="report",
            details=[detail("Spec path", service_spec_path)],
        ),
    ]


def set_baseline_contract(content: str) -> str:
    if BASELINE_PATH in content:
        return content
    if FIXED_PATH in content:
        return content.replace(FIXED_PATH, BASELINE_PATH, 1)
    raise ValueError("Could not set api-coverage to the baseline contract state.")


def set_fixed_contract(content: str) -> str:
    if FIXED_PATH in content:
        return content
    if BASELINE_PATH in content:
        return content.replace(BASELINE_PATH, FIXED_PATH, 1)
    raise ValueError("Could not set api-coverage to the fixed contract state.")
