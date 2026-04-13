from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib import error, request


BUILD_DIR = Path.cwd() / "build" / "data-adapters"
UI_URL = "http://127.0.0.1:8080"
MOCK_HEALTH_URL = "http://127.0.0.1:9090/actuator/health"
REQUEST_URL = f"{UI_URL}/test?RequestQuery=books"
REQUEST_HEADERS = {
    "Content-Type": "application/json",
    "RequestHeader": "header-value",
}
REQUEST_BODY = {"RequestKey": "request-value"}


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


def perform_request() -> dict[str, object]:
    payload = json.dumps(REQUEST_BODY).encode("utf-8")
    req = request.Request(REQUEST_URL, data=payload, headers=REQUEST_HEADERS, method="POST")
    try:
        with request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "url": REQUEST_URL,
                "request": {"headers": REQUEST_HEADERS, "body": REQUEST_BODY},
                "status": response.status,
                "headers": dict(response.headers.items()),
                "body": body,
            }
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "url": REQUEST_URL,
            "request": {"headers": REQUEST_HEADERS, "body": REQUEST_BODY},
            "status": exc.code,
            "headers": dict(exc.headers.items()),
            "body": body,
        }


def write_artifacts(response_data: dict[str, object]) -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (BUILD_DIR / "http-response.json").write_text(json.dumps(response_data, indent=2), encoding="utf-8")
    logs = subprocess.run(
        ["docker", "compose", "logs", "--no-color", "camelCaseService", "ui"],
        check=False,
        text=True,
        capture_output=True,
    )
    (BUILD_DIR / "compose.log").write_text((logs.stdout or "") + (logs.stderr or ""), encoding="utf-8")


def main() -> int:
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    print("Starting camelCase mock and UI services...", flush=True)
    up_code = run_command(["docker", "compose", "up", "-d", "camelCaseService", "ui"])
    if up_code != 0:
        return up_code

    try:
        print("Waiting for UI and mock health endpoints...", flush=True)
        wait_for_url(UI_URL)
        wait_for_url(MOCK_HEALTH_URL)

        print("Submitting the PascalCase request through the UI endpoint...", flush=True)
        response_data = perform_request()
        write_artifacts(response_data)

        print(f"Observed HTTP {response_data['status']} response from the UI flow.", flush=True)
        print("Response body:", flush=True)
        print(response_data["body"], flush=True)
        return 0
    finally:
        print("Stopping compose services for data-adapters...", flush=True)
        run_command(["docker", "compose", "down", "-v"])


if __name__ == "__main__":
    raise SystemExit(main())
