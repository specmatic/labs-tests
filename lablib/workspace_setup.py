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
    "api-resiliency-testing",
    "api-security-schemes",
    "async-event-flow",
    "backward-compatibility-testing",
    "continuous-integration",
    "data-adapters",
    "dictionary",
    "external-examples",
    "filters",
    "kafka-avro",
    "kafka-sqs-retry-dlq",
    "mcp-auto-test",
    "overlays",
    "partial-examples",
    "workflow-in-same-spec",
    "quick-start-api-testing",
    "quick-start-async-contract-testing",
    "quick-start-contract-testing",
    "quick-start-mock",
    "schema-resiliency-testing",
    "schema-design",
    "response-templating",
]


@dataclass
class SetupResult:
    status: str
    upstream_labs_path: str
    commands: list[dict[str, Any]]


@dataclass
class LicenseFileState:
    path: Path
    existed: bool
    original_content: str | None
    applied_source: str


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

    for lab_name in LAB_NAMES:
        if lab_name not in selected_labs:
            continue
        upstream_lab_path = UPSTREAM_LABS / lab_name
        compose_file = upstream_lab_path / "docker-compose.yaml"
        if not compose_file.exists():
            continue

        commands.append(
            command_to_dict(
                execute(
                    ["docker", "compose", "pull", "--ignore-buildable"],
                    upstream_lab_path,
                    "setup:docker",
                    stream_output=stream_output,
                ),
                f"Pull referenced Docker images for {lab_name}",
            )
        )
        commands.append(
            command_to_dict(
                execute(
                    ["docker", "compose", "build", "--pull"],
                    upstream_lab_path,
                    "setup:docker",
                    stream_output=stream_output,
                ),
                f"Refresh buildable Docker images for {lab_name}",
            )
        )

    status = "passed" if all(item["exitCode"] == 0 for item in commands) else "failed"
    return SetupResult(
        status=status,
        upstream_labs_path=str(UPSTREAM_LABS),
        commands=commands,
    )


def prepare_upstream_labs_license() -> LicenseFileState:
    if not UPSTREAM_LABS.exists():
        raise RuntimeError(
            f"Upstream labs repository was not found at {UPSTREAM_LABS}. "
            "Action required: run with setup enabled or clone the sibling labs repository first."
        )
    license_path = UPSTREAM_LABS / "license.txt"
    existed = license_path.exists()
    original_content = license_path.read_text(encoding="utf-8") if existed else None
    content, source = resolve_license_txt_content()
    license_path.write_text(content, encoding="utf-8")
    return LicenseFileState(
        path=license_path,
        existed=existed,
        original_content=original_content,
        applied_source=source,
    )


def restore_upstream_labs_license(state: LicenseFileState | None) -> None:
    if state is None:
        return
    if state.existed and state.original_content is not None:
        state.path.write_text(state.original_content, encoding="utf-8")
        return
    if state.path.exists():
        state.path.unlink()


def license_setup_dict(state: LicenseFileState) -> dict[str, Any]:
    return note_to_dict(
        "Prepare upstream labs license.txt",
        (
            f"Wrote {state.path} using {state.applied_source}. "
            + ("An existing license.txt will be restored after the run." if state.original_content is not None else "No previous license.txt existed; the file will be removed after the run.")
        ),
    )


def license_failure_dict(message: str) -> dict[str, Any]:
    return info_to_dict("Prepare upstream labs license.txt", message)


def resolve_license_txt_content() -> tuple[str, str]:
    if os.getenv("GITHUB_ACTIONS") or os.getenv("GITHUB_RUN_ID"):
        license_text = (os.getenv("SPECMATIC_LICENSE_KEY") or "").strip()
        if not license_text:
            raise RuntimeError(
                "SPECMATIC_LICENSE_KEY is not available in the GitHub Actions environment. "
                "Action required: configure the repository secret and rerun the workflow."
            )
        return license_text + ("\n" if not license_text.endswith("\n") else ""), "GitHub Actions secret SPECMATIC_LICENSE_KEY"

    temp_dir = ROOT / "temp"
    candidates = sorted(
        path
        for path in temp_dir.iterdir()
        if path.is_file()
        and path.name.lower().startswith("license-labs-test")
        and path.name.lower().endswith(".txt")
    ) if temp_dir.exists() else []
    if not candidates:
        raise RuntimeError(
            f"Could not find a local labs-test license file in {ROOT / 'temp'} matching 'License-labs-test*.txt' (case-insensitive). "
            "Action required: add exactly one file such as temp/License-labs-test.txt or temp/License-labs-test-Local.txt and rerun."
        )
    if len(candidates) > 1:
        candidate_list = ", ".join(path.name for path in candidates)
        raise RuntimeError(
            f"Found multiple local labs-test license files in {ROOT / 'temp'}: {candidate_list}. "
            "Action required: keep only one file matching 'License-labs-test*.txt' (case-insensitive) and rerun."
        )
    license_path = candidates[0]
    license_text = license_path.read_text(encoding="utf-8")
    if not license_text.strip():
        raise RuntimeError(
            f"Local labs-test license file {license_path} is empty. "
            "Action required: put the full license text into that file and rerun."
        )
    normalized = license_text if license_text.endswith("\n") else license_text + "\n"
    return normalized, f"local labs-test license file at {license_path}"


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


def setup_failure_error_lines(commands: list[dict[str, Any]]) -> list[str]:
    return [f"[error] {summarize_setup_failure(commands)}"]


def setup_failure_action_lines(commands: list[dict[str, Any]]) -> list[str]:
    return ["[Action required]", "", setup_failure_action(commands)]


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
