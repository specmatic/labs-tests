from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib import error, request


MODE_FILE = Path.cwd() / ".labs-tests-mode"
BUILD_DIR = Path.cwd() / "build" / "quick-start-mock"
CONSUMER_URL = "http://127.0.0.1:8081"


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


def run_scenario(mode: str) -> dict[str, object]:
    if mode == "mock-running":
        print("Starting consumer and mock services...", flush=True)
        up_code = run_command(["docker", "compose", "--profile", "mock", "up", "-d", "consumer", "mock"])
        if up_code != 0:
            raise RuntimeError("Failed to start consumer and mock services.")
        wait_for_url(CONSUMER_URL)
        wait_for_url("http://127.0.0.1:9100/actuator/health")
        results = {
            "mode": mode,
            "pet1": fetch_text("http://127.0.0.1:9100/pets/1"),
            "pet2_first": fetch_text("http://127.0.0.1:9100/pets/2"),
            "pet2_second": fetch_text("http://127.0.0.1:9100/pets/2"),
            "pet_abc": fetch_text("http://127.0.0.1:9100/pets/abc"),
        }
        return results

    print("Starting consumer without the mock...", flush=True)
    up_code = run_command(["docker", "compose", "up", "-d", "consumer"])
    if up_code != 0:
        raise RuntimeError("Failed to start the consumer service.")
    wait_for_url(CONSUMER_URL)
    return {
        "mode": mode,
        "pet1": fetch_text("http://127.0.0.1:9100/pets/1"),
    }


def main() -> int:
    if not MODE_FILE.exists():
        print("Missing .labs-tests-mode file for quick-start-mock.", flush=True)
        return 2

    mode = MODE_FILE.read_text(encoding="utf-8").strip()
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    try:
        results = run_scenario(mode)
        BUILD_DIR.mkdir(parents=True, exist_ok=True)
        (BUILD_DIR / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        logs = subprocess.run(
            ["docker", "compose", "--profile", "mock", "logs", "--no-color"],
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
        run_command(["docker", "compose", "--profile", "mock", "down", "-v"])


if __name__ == "__main__":
    raise SystemExit(main())
