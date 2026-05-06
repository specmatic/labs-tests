from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_LABS = ROOT.parent / "labs"
UPSTREAM_LAB = UPSTREAM_LABS / "backward-compatibility-testing"
TARGET_PATH = Path("backward-compatibility-testing") / "products.yaml"
BASE_BRANCH = "origin/main"


def main() -> int:
    temp_repo = Path(tempfile.mkdtemp(prefix="backward-compatibility-testing-"))
    try:
        prepare_temp_repo(temp_repo)
        return run_backward_compatibility_check(temp_repo)
    finally:
        shutil.rmtree(temp_repo, ignore_errors=True)


def prepare_temp_repo(repo_root: Path) -> None:
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
    git(["checkout", "-b", "labs-tests-check"], cwd=repo_root)
    repo_target.write_text(current, encoding="utf-8")


def read_baseline_contract() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(UPSTREAM_LABS), "show", f"refs/remotes/origin/main:{TARGET_PATH.as_posix()}"],
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Could not read backward-compatibility baseline from refs/remotes/origin/main. "
            "Ensure the upstream labs repo has fetched main before running this lab."
        ) from exc


def run_backward_compatibility_check(repo_root: Path) -> int:
    license_file = UPSTREAM_LABS / "license.txt"
    command = [
        "docker",
        "run",
        "--rm",
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
            BASE_BRANCH,
            "--target-path",
            TARGET_PATH.as_posix(),
        ]
    )
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
    return process.wait()


def git(args: list[str], *, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    raise SystemExit(main())
