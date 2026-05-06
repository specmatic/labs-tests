from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_LABS = ROOT.parent / "labs"
UPSTREAM_LAB = UPSTREAM_LABS / "backward-compatibility-testing"
TARGET_PATH = Path("backward-compatibility-testing") / "products.yaml"
BASELINE_SOURCE_REF = "refs/remotes/origin/main"
BASE_BRANCH = "main"
TEMP_REPO_ROOT = ROOT / "backward-compatibility-testing" / ".tmp" / "bc-repo"


def main() -> int:
    temp_repo = TEMP_REPO_ROOT
    if temp_repo.exists():
        shutil.rmtree(temp_repo, ignore_errors=True)
    try:
        temp_repo.mkdir(parents=True, exist_ok=True)
        base_revision = prepare_temp_repo(temp_repo)
        run_git_preflight(temp_repo, base_revision)
        run_container_git_preflight(temp_repo, base_revision)
        return run_backward_compatibility_check(temp_repo, base_revision)
    finally:
        shutil.rmtree(temp_repo, ignore_errors=True)


def prepare_temp_repo(repo_root: Path) -> str:
    repo_target = repo_root / TARGET_PATH
    repo_target.parent.mkdir(parents=True, exist_ok=True)
    baseline = read_baseline_contract()
    current = (UPSTREAM_LAB / "products.yaml").read_text(encoding="utf-8")
    repo_target.write_text(baseline, encoding="utf-8")

    git(["init", "-q"], cwd=repo_root)
    git(["config", "user.name", "Specmatic Labs Test"], cwd=repo_root)
    git(["config", "user.email", "specmatic-labs-tests@example.com"], cwd=repo_root)
    git(["remote", "add", "origin", "https://github.com/specmatic/labs.git"], cwd=repo_root)
    git(["checkout", "-b", BASE_BRANCH], cwd=repo_root)
    git(["add", str(TARGET_PATH)], cwd=repo_root)
    git(["commit", "-q", "-m", "Baseline contract from origin/main"], cwd=repo_root)
    base_revision = git_output(["rev-parse", "HEAD"], cwd=repo_root).strip()
    git(["checkout", "-b", "labs-tests-check"], cwd=repo_root)
    repo_target.write_text(current, encoding="utf-8")
    return base_revision


def read_baseline_contract() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(UPSTREAM_LABS), "show", f"{BASELINE_SOURCE_REF}:{TARGET_PATH.as_posix()}"],
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"Could not read backward-compatibility baseline from {BASELINE_SOURCE_REF}. "
            "Ensure the upstream labs repo has fetched main before running this lab."
        ) from exc


def run_backward_compatibility_check(repo_root: Path, base_revision: str) -> int:
    license_file = UPSTREAM_LABS / "license.txt"
    command = [
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "sh",
        "-e",
        "GIT_CONFIG_COUNT=1",
        "-e",
        "GIT_CONFIG_KEY_0=safe.directory",
        "-e",
        "GIT_CONFIG_VALUE_0=/workspace",
        "-v",
        f"{repo_root}:/workspace",
    ]
    if license_file.exists():
        command.extend(["-v", f"{license_file}:/specmatic/specmatic-license.txt:ro"])
    command.extend(
        [
            "-w",
            "/workspace",
            "specmatic/enterprise:latest",
            "backward-compatibility-check",
            "--base-branch",
            base_revision,
            "--target-path",
            TARGET_PATH.as_posix(),
        ]
    )
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
    return process.wait()


def run_git_preflight(repo_root: Path, base_revision: str) -> None:
    print("[preflight] Verifying temporary backward-compatibility repo...", flush=True)
    print(f"[preflight] Repo path: {repo_root}", flush=True)
    head_revision = git_output(["rev-parse", "HEAD"], cwd=repo_root).strip()
    print(f"[preflight] git rev-parse HEAD -> {head_revision}", flush=True)
    base_type = git_output(["cat-file", "-t", base_revision], cwd=repo_root).strip()
    print(f"[preflight] git cat-file -t {base_revision} -> {base_type}", flush=True)
    diff_output = git_output(["diff", base_revision, "HEAD", "--name-status"], cwd=repo_root).strip()
    print(f"[preflight] git diff {base_revision} HEAD --name-status", flush=True)
    if diff_output:
        print(diff_output, flush=True)
    else:
        print("[preflight] (no diff output)", flush=True)


def run_container_git_preflight(repo_root: Path, base_revision: str) -> None:
    print("[preflight] Verifying git visibility inside container...", flush=True)
    license_file = UPSTREAM_LABS / "license.txt"
    command = [
        "docker",
        "run",
        "--rm",
        "-e",
        "GIT_CONFIG_COUNT=1",
        "-e",
        "GIT_CONFIG_KEY_0=safe.directory",
        "-e",
        "GIT_CONFIG_VALUE_0=/workspace",
        "--entrypoint",
        "/bin/sh",
        "-v",
        f"{repo_root}:/workspace",
    ]
    if license_file.exists():
        command.extend(["-v", f"{license_file}:/specmatic/specmatic-license.txt:ro"])
    command.extend(
        [
            "-w",
            "/workspace",
            "specmatic/enterprise:latest",
            "-lc",
            (
                "pwd; "
                "git rev-parse --show-toplevel; "
                "git rev-parse HEAD; "
                f"git cat-file -t {base_revision}; "
                f"git diff {base_revision} HEAD --name-status"
            ),
        ]
    )
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        print(f"[preflight:container] {line}", end="", flush=True)
    exit_code = process.wait()
    if exit_code != 0:
        raise RuntimeError(
            "Container git preflight failed. The mounted /workspace repo could not resolve the base revision "
            f"{base_revision}."
        )


def git(args: list[str], *, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def git_output(args: list[str], *, cwd: Path) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True)


if __name__ == "__main__":
    raise SystemExit(main())
