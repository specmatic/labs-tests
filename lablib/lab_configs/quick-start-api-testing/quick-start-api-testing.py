from __future__ import annotations

from lablib.scaffold import ValidationContext, assert_condition, detail


def baseline_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "$match(exact: approved)" in context.artifacts["test_finance_user_11.json"]["text"],
            "Baseline finance example kept the exact decision matcher.",
            "Baseline finance example did not keep the exact decision matcher.",
            category="implementation",
            details=[detail("Artifact path", context.artifacts["test_finance_user_11.json"]["path"])],
        ),
    ]


def task_a_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "$match(pattern: approved|verified)" in context.artifacts["test_finance_user_11.json"]["text"],
            "Task A finance example contains the decision pattern matcher.",
            "Task A finance example does not contain the decision pattern matcher.",
            category="implementation",
            details=[detail("Artifact path", context.artifacts["test_finance_user_11.json"]["path"])],
        ),
        assert_condition(
            "$match(exact: VRF-123456)" in context.artifacts["test_support_user_55.json"]["text"],
            "Task A support example still uses the exact referenceCode matcher.",
            "Task A support example unexpectedly changed the support matcher too early.",
            category="implementation",
            details=[detail("Artifact path", context.artifacts["test_support_user_55.json"]["path"])],
        ),
    ]


def final_assertions(context: ValidationContext) -> list[dict]:
    return [
        assert_condition(
            "$match(pattern: VRF-[0-9]{6})" in context.artifacts["test_support_user_55.json"]["text"]
            and "$match(dataType: date)" in context.artifacts["test_support_user_55.json"]["text"],
            "Final support example contains the relaxed matcher combination.",
            "Final support example does not contain the expected relaxed matcher combination.",
            category="implementation",
            details=[detail("Artifact path", context.artifacts["test_support_user_55.json"]["path"])],
        ),
    ]


def set_finance_baseline(content: str) -> str:
    return content.replace("$match(pattern: approved|verified)", "$match(exact: approved)")


def set_finance_task_a(content: str) -> str:
    return content.replace("$match(exact: approved)", "$match(pattern: approved|verified)")


def set_support_baseline(content: str) -> str:
    updated = content.replace("$match(pattern: VRF-[0-9]{6})", "$match(exact: VRF-123456)")
    updated = updated.replace("$match(dataType: date)", "$match(exact: 2026-03-17)")
    return updated


def set_support_final(content: str) -> str:
    updated = content.replace("$match(exact: VRF-123456)", "$match(pattern: VRF-[0-9]{6})")
    updated = updated.replace("$match(exact: 2026-03-17)", "$match(dataType: date)")
    return updated
