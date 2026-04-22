from __future__ import annotations

import getpass
import os
import platform
import socket
from typing import Any


def detect_report_provenance() -> dict[str, Any]:
    run_id = os.getenv("GITHUB_RUN_ID")
    repository = os.getenv("GITHUB_REPOSITORY")
    if run_id and repository:
        server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
        run_attempt = os.getenv("GITHUB_RUN_ATTEMPT")
        workflow = os.getenv("GITHUB_WORKFLOW", "GitHub Actions")
        run_label = f"{workflow} run #{run_id}"
        if run_attempt:
            run_label += f" (attempt {run_attempt})"
        return {
            "type": "github-actions",
            "label": run_label,
            "display": f"{repository} / {run_label}",
            "href": f"{server_url}/{repository}/actions/runs/{run_id}",
        }

    hostname = socket.gethostname().split(".")[0]
    system = platform.system()
    os_display = {
        "Darwin": "MacOSX",
        "Windows": "Windows",
        "Linux": "Linux",
    }.get(system, system or "UnknownOS")
    username = getpass.getuser()
    return {
        "type": "local",
        "label": "Local machine",
        "display": f"{hostname}/{os_display}/{username}",
        "href": "",
    }
