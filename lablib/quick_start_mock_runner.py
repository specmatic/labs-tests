from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lablib.compose_runtime import ComposeRuntime, create_compose_runtime

MODE_FILE = Path.cwd() / ".labs-tests-mode"
BUILD_DIR = Path.cwd() / "build" / "quick-start-mock"
COMPOSE_FILE = Path.cwd() / "docker-compose.yaml"
CONSUMER_CONTAINER_PORT = 8081
MOCK_CONTAINER_PORT = 9100
CONTAINER_NAMES = ["quick-start-mock-consumer", "quick-start-mock-server"]


def run_command(command: list[str]) -> int:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
    return process.wait()


def wait_for_url(url: str, *, timeout_seconds: int = 90) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    return
        except Exception:
            time.sleep(1)
            continue
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for {url}")


def fetch_text(url: str) -> dict[str, object]:
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {"status": response.status, "body": body, "error": None}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": exc.code, "body": body, "error": None}
    except Exception as exc:
        return {"status": None, "body": "", "error": str(exc)}


def build_runtime() -> ComposeRuntime:
    return create_compose_runtime(
        COMPOSE_FILE,
        {
            "consumer": [CONSUMER_CONTAINER_PORT],
            "mock": [MOCK_CONTAINER_PORT],
        },
        prefix="quick-start-mock",
    )


def print_runtime_notice(runtime: ComposeRuntime) -> None:
    print(f"[runtime] {runtime.runtime_notice()}", flush=True)


def cleanup_stale_containers() -> None:
    subprocess.run(["docker", "rm", "-f", *CONTAINER_NAMES], check=False, text=True, capture_output=True)


def run_scenario(mode: str, runtime: ComposeRuntime) -> dict[str, object]:
    consumer_url = f"http://127.0.0.1:{runtime.host_port('consumer', CONSUMER_CONTAINER_PORT)}"
    mock_url = f"http://127.0.0.1:{runtime.host_port('mock', MOCK_CONTAINER_PORT)}"
    if mode == "mock-running":
        print("Starting consumer and mock services...", flush=True)
        up_code = run_command(runtime.command(COMPOSE_FILE, "--profile", "mock", "up", "-d", "consumer", "mock"))
        if up_code != 0:
            raise RuntimeError("Failed to start consumer and mock services.")
        wait_for_url(consumer_url)
        wait_for_url(f"{mock_url}/actuator/health")
        results = {
            "mode": mode,
            "pet1": fetch_text(f"{mock_url}/pets/1"),
            "pet2_first": fetch_text(f"{mock_url}/pets/2"),
            "pet2_second": fetch_text(f"{mock_url}/pets/2"),
            "pet_abc": fetch_text(f"{mock_url}/pets/abc"),
        }
        return results

    print("Starting consumer without the mock...", flush=True)
    up_code = run_command(runtime.command(COMPOSE_FILE, "up", "-d", "consumer"))
    if up_code != 0:
        raise RuntimeError("Failed to start the consumer service.")
    wait_for_url(consumer_url)
    return {
        "mode": mode,
        "pet1": fetch_text(f"{mock_url}/pets/1"),
    }


def main() -> int:
    if not MODE_FILE.exists():
        print("Missing .labs-tests-mode file for quick-start-mock.", flush=True)
        return 2

    mode = MODE_FILE.read_text(encoding="utf-8").strip()
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    cleanup_stale_containers()
    runtime = build_runtime()
    print_runtime_notice(runtime)
    try:
        results = run_scenario(mode, runtime)
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        (BUILD_DIR / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        logs = subprocess.run(
            runtime.command(COMPOSE_FILE, "--profile", "mock", "logs", "--no-color"),
            check=False,
            text=True,
            capture_output=True,
        )
        (BUILD_DIR / "compose.log").write_text((logs.stdout or "") + (logs.stderr or ""), encoding="utf-8")

        if mode == "mock-running":
            print(f"Pet 1 status: {results['pet1']['status']}", flush=True)
            print(f"Pet 2 first status: {results['pet2_first']['status']}", flush=True)
            print(f"Pet 2 second status: {results['pet2_second']['status']}", flush=True)
            print(f"Pet abc status: {results['pet_abc']['status']}", flush=True)
        else:
            if results["pet1"]["error"]:
                print("Observed Service unavailable while calling the provider URL.", flush=True)
                print(results["pet1"]["error"], flush=True)
            else:
                print(f"Observed HTTP {results['pet1']['status']} without the mock.", flush=True)
                print(results["pet1"]["body"], flush=True)
        return 0
    finally:
        print("Stopping compose services for quick-start-mock...", flush=True)
        run_command(runtime.command(COMPOSE_FILE, "--profile", "mock", "down", "-v"))


if __name__ == "__main__":
    raise SystemExit(main())
