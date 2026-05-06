from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import os
import queue
import signal
import subprocess
import threading
import time
from typing import Mapping, Sequence


@dataclass
class CommandResult:
    command: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    started_at: str
    finished_at: str
    duration_seconds: float
    timed_out: bool = False
    timeout_reason: str = ""

    @property
    def combined_output(self) -> str:
        if self.stderr:
            return f"{self.stdout}\n{self.stderr}".strip()
        return self.stdout


def run_command(
    command: Sequence[str],
    cwd: Path,
    *,
    env: Mapping[str, str] | None = None,
    stream_output: bool = False,
    stream_prefix: str = "",
    idle_heartbeat_seconds: float = 30.0,
    timeout_seconds: float | None = None,
    idle_timeout_seconds: float | None = None,
) -> CommandResult:
    started = datetime.now(UTC)
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    if not stream_output:
        completed = subprocess.run(
            list(command),
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            env=process_env,
        )
        finished = datetime.now(UTC)
        return CommandResult(
            command=list(command),
            cwd=str(cwd),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            duration_seconds=(finished - started).total_seconds(),
        )

    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=process_env,
        start_new_session=True,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()

    def reader(pipe: subprocess.PIPE, label: str) -> None:
        try:
            assert pipe is not None
            for line in pipe:
                output_queue.put((label, line))
        finally:
            output_queue.put((label, None))

    stdout_thread = threading.Thread(target=reader, args=(process.stdout, "stdout"))
    stderr_thread = threading.Thread(target=reader, args=(process.stderr, "stderr"))
    stdout_thread.start()
    stderr_thread.start()

    completed_streams = 0
    prefix = f"{stream_prefix} " if stream_prefix else ""
    started_monotonic = time.monotonic()
    last_output_at = time.monotonic()
    timed_out = False
    timeout_reason = ""
    while completed_streams < 2:
        try:
            label, line = output_queue.get(timeout=idle_heartbeat_seconds)
        except queue.Empty:
            elapsed = int(time.monotonic() - last_output_at)
            print(f"{prefix}[idle] waiting for command output for {elapsed}s...", flush=True)
            overall_elapsed = time.monotonic() - started_monotonic
            idle_elapsed = time.monotonic() - last_output_at
            if timeout_seconds is not None and overall_elapsed >= timeout_seconds and not timed_out:
                timed_out = True
                timeout_reason = f"Command exceeded the {int(timeout_seconds)}s timeout."
                print(f"{prefix}[error] Command timed out: {timeout_reason}", flush=True)
                terminate_process(process)
            elif idle_timeout_seconds is not None and idle_elapsed >= idle_timeout_seconds and not timed_out:
                timed_out = True
                timeout_reason = f"Command produced no output for {int(idle_timeout_seconds)}s."
                print(f"{prefix}[error] Command timed out due to no output: {timeout_reason}", flush=True)
                terminate_process(process)
            continue
        if line is None:
            completed_streams += 1
            continue
        last_output_at = time.monotonic()
        if label == "stdout":
            stdout_lines.append(line)
        else:
            stderr_lines.append(line)
        print(f"{prefix}{line}", end="", flush=True)

    stdout_thread.join()
    stderr_thread.join()
    exit_code = process.wait()
    if timed_out:
        exit_code = 124
        stderr_lines.append(f"{timeout_reason}\n")
    finished = datetime.now(UTC)
    return CommandResult(
        command=list(command),
        cwd=str(cwd),
        exit_code=exit_code,
        stdout="".join(stdout_lines),
        stderr="".join(stderr_lines),
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        duration_seconds=(finished - started).total_seconds(),
        timed_out=timed_out,
        timeout_reason=timeout_reason,
    )


def terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except Exception:
        process.terminate()
    try:
        process.wait(timeout=10)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        process.kill()
