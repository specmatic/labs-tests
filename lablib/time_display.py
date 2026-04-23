from __future__ import annotations

from datetime import datetime


WEEKDAY_ABBREVIATIONS = {
    0: "Mon",
    1: "Tue",
    2: "Wed",
    3: "Thr",
    4: "Fri",
    5: "Sat",
    6: "Sun",
}


def format_report_datetime(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    local_value = parsed.astimezone()
    weekday = WEEKDAY_ABBREVIATIONS.get(local_value.weekday(), local_value.strftime("%a"))
    return (
        f"Generated on {weekday}, "
        f"{local_value.day:02d} {local_value.strftime('%B %Y')}, "
        f"at {local_value.strftime('%H:%M:%S %Z')}"
    )
