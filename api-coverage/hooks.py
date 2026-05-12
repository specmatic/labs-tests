from __future__ import annotations

import os
from pathlib import Path
import socket

from lablib.scaffold import ValidationContext, assert_condition, detail


BASELINE_PATH = "/pets/search:"
FIXED_PATH = "/pets/find:"


def files(upstream_lab: Path) -> dict[str, Path]:
    return {"service_spec": upstream_lab / "specs" / "service.yaml"}


def command_env() -> dict[str, str]:
    return {"PETSTORE_PORT": str(allocate_free_port())}


def phase_file_transforms(phase_id: str, phase_title: str) -> dict:
    if phase_id == "baseline":
        return {"service_spec": set_baseline_contract}
    if phase_id == "final":
        return {"service_spec": set_fixed_contract}
    return {}


def extra_assertions(phase_id: str, phase_title: str):
    if phase_id == "baseline":
        return baseline_assertions
    if phase_id == "final":
        return fixed_assertions
    return None


def fix_summary(phase_id: str, phase_title: str) -> tuple[str, ...]:
    if phase_id == "final":
        return (
            "Changed the contract path from GET /pets/search to GET /pets/find in specs/service.yaml.",
            "Re-ran the same Specmatic test command against the running provider to confirm both operations are covered.",
        )
    return ()


def allocate_free_port() -> int:
    configured = os.getenv("PETSTORE_PORT")
    if configured:
        return int(configured)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError:
            return 18080
        sock.listen(1)
        return int(sock.getsockname()[1])


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
