from __future__ import annotations

from dataclasses import dataclass
import filecmp
import os
from pathlib import Path
import shutil
import stat
import tempfile
from typing import Any

from lablib.command_runner import CommandResult, run_command
from lablib.readme_schema import parse_simple_yaml


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_LABS = ROOT.parent / "labs"
LAB_DISCOVERY_CONFIG = ROOT / "labs-discovery.yaml"


@dataclass
class SetupResult:
    status: str
    upstream_labs_path: str
    commands: list[dict[str, Any]]


@dataclass
class UpstreamLabSnapshot:
    lab_name: str
    original_path: Path
    snapshot_path: Path


def run_setup(
    *,
    stream_output: bool = True,
    refresh_labs: bool = False,
    target_branch: str = "main",
    force: bool = False,
    lab_names: list[str] | None = None,
) -> SetupResult:
    commands: list[dict[str, Any]] = []
    del lab_names

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


def discover_available_labs() -> list[str]:
    if not UPSTREAM_LABS.exists():
        return []
    skipped_labs = set(load_ignored_lab_names())
    return sorted(
        path.name
        for path in UPSTREAM_LABS.iterdir()
        if path.is_dir()
        and not path.name.startswith(".")
        and (path / "README.md").exists()
        and path.name not in skipped_labs
    )


def load_ignored_lab_names() -> list[str]:
    if not LAB_DISCOVERY_CONFIG.exists():
        return []
    config = parse_simple_yaml(LAB_DISCOVERY_CONFIG.read_text(encoding="utf-8"))
    ignored = config.get("ignored_labs", [])
    if isinstance(ignored, str):
        return [ignored]
    if isinstance(ignored, list):
        return [str(item) for item in ignored]
    return []


def create_upstream_lab_snapshot(lab_name: str) -> UpstreamLabSnapshot:
    original_path = UPSTREAM_LABS / lab_name
    if not original_path.exists():
        raise FileNotFoundError(
            f"Upstream lab directory was not found: {original_path}. "
            "Action required: ensure the sibling labs repository contains this lab before running."
        )
    snapshot_root = Path(tempfile.mkdtemp(prefix="labs-tests-snapshot-"))
    snapshot_path = snapshot_root / lab_name
    shutil.copytree(original_path, snapshot_path)
    return UpstreamLabSnapshot(
        lab_name=lab_name,
        original_path=original_path,
        snapshot_path=snapshot_path,
    )


def restore_upstream_lab_snapshot(snapshot: UpstreamLabSnapshot) -> None:
    restore_errors: list[str] = []
    for attempt in range(2):
        restore_errors.clear()
        if snapshot.original_path.exists():
            force_remove_tree(snapshot.original_path)
        shutil.copytree(snapshot.snapshot_path, snapshot.original_path)
        if trees_match(snapshot.snapshot_path, snapshot.original_path, restore_errors):
            return
    raise RuntimeError(
        f"Failed to restore upstream lab '{snapshot.lab_name}' to its pre-run state. "
        "Action required: inspect the sibling labs directory for leftover changes.\n"
        + "\n".join(restore_errors[:20])
    )


def cleanup_upstream_lab_snapshot(snapshot: UpstreamLabSnapshot) -> None:
    snapshot_root = snapshot.snapshot_path.parent
    if snapshot_root.exists():
        force_remove_tree(snapshot_root, ignore_errors=True)


def force_remove_tree(path: Path, *, ignore_errors: bool = False) -> None:
    if not path.exists():
        return
    make_tree_writable(path)
    shutil.rmtree(path, ignore_errors=ignore_errors, onerror=handle_remove_readonly)


def make_tree_writable(path: Path) -> None:
    if not path.exists():
        return
    for current_root, dirnames, filenames in os.walk(path):
        current_path = Path(current_root)
        make_path_writable(current_path)
        for dirname in dirnames:
            make_path_writable(current_path / dirname)
        for filename in filenames:
            make_path_writable(current_path / filename)


def make_path_writable(path: Path) -> None:
    try:
        current_mode = path.stat().st_mode
        path.chmod(current_mode | stat.S_IWUSR)
    except FileNotFoundError:
        return


def handle_remove_readonly(function, target, excinfo) -> None:
    del function, excinfo
    target_path = Path(target)
    make_path_writable(target_path)
    if target_path.is_dir():
        shutil.rmtree(target_path, ignore_errors=False, onerror=handle_remove_readonly)
    else:
        target_path.unlink(missing_ok=True)


def trees_match(expected_root: Path, actual_root: Path, errors: list[str]) -> bool:
    if not expected_root.exists():
        errors.append(f"Expected snapshot root is missing: {expected_root}")
        return False
    if not actual_root.exists():
        errors.append(f"Restored lab root is missing: {actual_root}")
        return False

    comparison = filecmp.dircmp(expected_root, actual_root, ignore=[])
    return compare_dircmp(comparison, errors)


def compare_dircmp(comparison: filecmp.dircmp, errors: list[str]) -> bool:
    matched = True

    if comparison.left_only:
        matched = False
        errors.append(
            f"Missing after restore in {comparison.right}: {', '.join(sorted(comparison.left_only))}"
        )
    if comparison.right_only:
        matched = False
        errors.append(
            f"Unexpected after restore in {comparison.right}: {', '.join(sorted(comparison.right_only))}"
        )
    if comparison.diff_files:
        matched = False
        errors.append(
            f"Content differs after restore in {comparison.right}: {', '.join(sorted(comparison.diff_files))}"
        )
    if comparison.funny_files:
        matched = False
        errors.append(
            f"Uncomparable files after restore in {comparison.right}: {', '.join(sorted(comparison.funny_files))}"
        )

    for subdir in comparison.subdirs.values():
        matched = compare_dircmp(subdir, errors) and matched

    return matched
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
