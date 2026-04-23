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


def build_run_metadata(command: str = "") -> dict[str, str]:
    run_id = os.getenv("GITHUB_RUN_ID")
    repository = os.getenv("GITHUB_REPOSITORY")
    server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    workflow_url = (
        f"{server_url}/{repository}/actions/runs/{run_id}"
        if run_id and repository
        else ""
    )

    ref_name = (
        os.getenv("GITHUB_HEAD_REF")
        or os.getenv("GITHUB_REF_NAME")
        or os.getenv("GITHUB_REF")
        or ""
    )
    trigger = os.getenv("GITHUB_EVENT_NAME", "")
    actor = os.getenv("GITHUB_ACTOR", "")
    sha = os.getenv("GITHUB_SHA", "")

    if run_id and repository:
        return {
            "Execution": "GitHub Actions",
            "Repository": repository,
            "Workflow": os.getenv("GITHUB_WORKFLOW", "GitHub Actions"),
            "Run number": os.getenv("GITHUB_RUN_NUMBER", ""),
            "Run ID": run_id,
            "Run attempt": os.getenv("GITHUB_RUN_ATTEMPT", ""),
            "Workflow URL": workflow_url,
            "Branch / ref": ref_name,
            "Trigger": trigger,
            "Actor": actor,
            "Commit": sha,
            "Command": command,
        }

    hostname = socket.gethostname().split(".")[0]
    system = platform.system() or "UnknownOS"
    username = getpass.getuser()
    return {
        "Execution": "Local",
        "Host": hostname,
        "OS": system,
        "User": username,
        "Branch / ref": ref_name,
        "Trigger": trigger or "manual",
        "Actor": actor or username,
        "Commit": sha,
        "Command": command,
    }
