from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from lablib.command_runner import CommandResult, run_command


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_LABS = ROOT.parent / "labs"
LAB_NAMES = [
    "api-coverage",
]


@dataclass
class SetupResult:
    status: str
    upstream_labs_path: str
    commands: list[dict[str, Any]]


def run_setup(
    *,
    stream_output: bool = True,
    refresh_labs: bool = False,
    target_branch: str = "main",
    force: bool = False,
    lab_names: list[str] | None = None,
) -> SetupResult:
    commands: list[dict[str, Any]] = []
    selected_labs = set(lab_names or LAB_NAMES)

    if not UPSTREAM_LABS.exists():
        clone_result = execute(
            ["git", "clone", "https://github.com/specmatic/labs.git", str(UPSTREAM_LABS)],
            ROOT,
            "setup:clone",
            stream_output=stream_output,
        )
        commands.append(command_to_dict(clone_result, "Clone upstream labs repository"))
        if refresh_labs:
            commands.extend(refresh_upstream_labs(stream_output=stream_output, target_branch=target_branch))
    else:
        if refresh_labs:
            dirty_state = execute(
                ["git", "status", "--short"],
                UPSTREAM_LABS,
                "setup:git",
                stream_output=stream_output,
            )
            commands.append(command_to_dict(dirty_state, "Inspect local changes in upstream labs repository"))
            if dirty_state.stdout.strip() and not force:
                commands.append(
                    info_to_dict(
                        summary="Blocked destructive refresh of upstream labs repository",
                        detail=(
                            "Local changes were detected in ../labs. Re-run with --refresh-labs --force "
                            "to discard tracked and untracked changes."
                        ),
                    )
                )
                return SetupResult(
                    status="failed",
                    upstream_labs_path=str(UPSTREAM_LABS),
                    commands=commands,
                )
            commands.extend(refresh_upstream_labs(stream_output=stream_output, target_branch=target_branch))
        else:
            commands.append(
                command_to_dict(
                    execute(
                        ["git", "status", "--short"],
                        UPSTREAM_LABS,
                        "setup:git",
                        stream_output=stream_output,
                    ),
                    "Inspect local changes in upstream labs repository",
                )
            )
            commands.append(
                command_to_dict(
                    execute(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        UPSTREAM_LABS,
                        "setup:git",
                        stream_output=stream_output,
                    ),
                    "Inspect current branch in upstream labs repository",
                )
            )
    commands.append(
        note_to_dict(
            "Skip shared Docker setup for upstream labs",
            "Each lab is responsible for its own docker compose or docker build flow during phase execution.",
        )
    )

    status = "passed" if all(item["exitCode"] == 0 for item in commands) else "failed"
    return SetupResult(
        status=status,
        upstream_labs_path=str(UPSTREAM_LABS),
        commands=commands,
    )
def summarize_setup_failure(commands: list[dict[str, Any]]) -> str:
    for command in reversed(commands):
        if command.get("exitCode", 0) == 0:
            continue
        text = "\n".join(
            str(part)
            for part in (
                command.get("summary", ""),
                command.get("stdout", ""),
                command.get("stderr", ""),
            )
            if part
        )
        if "docker.sock" in text or "failed to connect to the docker API" in text or "Cannot connect to the Docker daemon" in text:
            return (
                "Docker is not running or the Docker socket is unavailable. "
                "Start Docker Desktop, or otherwise bring up the Docker daemon so "
                "the socket at ~/.docker/run/docker.sock exists, then rerun the labs."
            )
        if "No services to build" in text:
            return (
                "Docker Compose could not find any buildable services for the selected labs. "
                "Check the selected lab list and the upstream docker-compose files, then rerun."
            )
        if text.strip():
            return (
                "Workspace setup failed during: "
                f"{command.get('summary', 'an unknown setup step')}. "
                "Inspect output/consolidated-report/setup-output.json for the full command log and rerun after fixing the issue."
            )
    return "Workspace setup failed. Inspect output/consolidated-report/setup-output.json for details."


def setup_failure_action(commands: list[dict[str, Any]]) -> str:
    for command in reversed(commands):
        if command.get("exitCode", 0) == 0:
            continue
        text = "\n".join(
            str(part)
            for part in (
                command.get("summary", ""),
                command.get("stdout", ""),
                command.get("stderr", ""),
            )
            if part
        )
        if "docker.sock" in text or "failed to connect to the docker API" in text or "Cannot connect to the Docker daemon" in text:
            return "Start Docker Desktop, or otherwise bring up the Docker daemon so the socket at ~/.docker/run/docker.sock exists, then rerun the labs."
        if "No services to build" in text:
            return "Check the selected lab list and the upstream docker-compose files, then rerun."
        if text.strip():
            return "Inspect output/consolidated-report/setup-output.json for the full command log and rerun after fixing the issue."
    return "Inspect output/consolidated-report/setup-output.json for details."
def refresh_upstream_labs(*, stream_output: bool, target_branch: str) -> list[dict[str, Any]]:
    branches_to_fetch = [target_branch] if target_branch == "main" else [target_branch, "main"]
    commands: list[dict[str, Any]] = []
    for branch in branches_to_fetch:
        commands.append(
            command_to_dict(
                execute(
                    ["git", "fetch", "origin", f"refs/heads/{branch}:refs/remotes/origin/{branch}"],
                    UPSTREAM_LABS,
                    "setup:git",
                    stream_output=stream_output,
                ),
                f"Fetch latest upstream refs for {branch}",
            )
        )
    commands.extend([
        command_to_dict(
            execute(
                ["git", "checkout", "-B", target_branch, f"origin/{target_branch}"],
                UPSTREAM_LABS,
                "setup:git",
                stream_output=stream_output,
            ),
            f"Switch upstream labs repository to origin/{target_branch}",
        ),
        command_to_dict(
            execute(
                ["git", "reset", "--hard", f"origin/{target_branch}"],
                UPSTREAM_LABS,
                "setup:git",
                stream_output=stream_output,
            ),
            f"Reset upstream labs repository to origin/{target_branch}",
        ),
        command_to_dict(
            execute(
                ["git", "clean", "-fd"],
                UPSTREAM_LABS,
                "setup:git",
                stream_output=stream_output,
            ),
            "Remove untracked files in upstream labs repository",
        ),
        command_to_dict(
            execute(
                ["git", "pull", "--ff-only", "origin", target_branch],
                UPSTREAM_LABS,
                "setup:git",
                stream_output=stream_output,
            ),
            f"Pull latest upstream labs changes from {target_branch}",
        ),
        command_to_dict(
            execute(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                UPSTREAM_LABS,
                "setup:git",
                stream_output=stream_output,
            ),
            "Verify selected upstream labs branch after refresh",
        ),
    ])
    return commands


def execute(
    command: list[str],
    cwd: Path,
    prefix: str,
    *,
    stream_output: bool,
) -> CommandResult:
    return run_command(command, cwd, stream_output=stream_output, stream_prefix=f"[{prefix}]")


def command_to_dict(result: CommandResult, summary: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "command": result.command,
        "cwd": result.cwd,
        "exitCode": result.exit_code,
        "startedAt": result.started_at,
        "finishedAt": result.finished_at,
        "durationSeconds": round(result.duration_seconds, 2),
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def info_to_dict(summary: str, detail: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "command": [],
        "cwd": str(UPSTREAM_LABS),
        "exitCode": 1,
        "startedAt": "",
        "finishedAt": "",
        "durationSeconds": 0,
        "stdout": detail,
        "stderr": "",
    }


def note_to_dict(summary: str, detail: str) -> dict[str, Any]:
    return {
        "summary": summary,
        "command": [],
        "cwd": str(UPSTREAM_LABS),
        "exitCode": 0,
        "startedAt": "",
        "finishedAt": "",
        "durationSeconds": 0,
        "stdout": detail,
        "stderr": "",
    }
