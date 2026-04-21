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

BUILD_DIR = Path.cwd() / "build" / "data-adapters"
COMPOSE_FILE = Path.cwd() / "docker-compose.yaml"
UI_CONTAINER_PORT = 8080
MOCK_CONTAINER_PORT = 9090
CONTAINER_NAMES = ["camel-case-service", "pascal-case-ui"]
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


def perform_request(request_url: str) -> dict[str, object]:
    payload = json.dumps(REQUEST_BODY).encode("utf-8")
    req = request.Request(request_url, data=payload, headers=REQUEST_HEADERS, method="POST")
    try:
        with request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {
                "url": request_url,
                "request": {"headers": REQUEST_HEADERS, "body": REQUEST_BODY},
                "status": response.status,
                "headers": dict(response.headers.items()),
                "body": body,
            }
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {
            "url": request_url,
            "request": {"headers": REQUEST_HEADERS, "body": REQUEST_BODY},
            "status": exc.code,
            "headers": dict(exc.headers.items()),
            "body": body,
        }


def write_artifacts(response_data: dict[str, object], runtime: ComposeRuntime) -> None:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (BUILD_DIR / "http-response.json").write_text(json.dumps(response_data, indent=2), encoding="utf-8")
    logs = subprocess.run(
        runtime.command(COMPOSE_FILE, "logs", "--no-color", "camelCaseService", "ui"),
        check=False,
        text=True,
        capture_output=True,
    )
    (BUILD_DIR / "compose.log").write_text((logs.stdout or "") + (logs.stderr or ""), encoding="utf-8")


def cleanup_stale_containers() -> None:
    subprocess.run(["docker", "rm", "-f", *CONTAINER_NAMES], check=False, text=True, capture_output=True)


def build_runtime() -> ComposeRuntime:
    return create_compose_runtime(
        COMPOSE_FILE,
        {
            "camelCaseService": [MOCK_CONTAINER_PORT],
            "ui": [UI_CONTAINER_PORT],
        },
        prefix="data-adapters",
    )


def print_runtime_notice(runtime: ComposeRuntime) -> None:
    print(f"[runtime] {runtime.runtime_notice()}", flush=True)


def main() -> int:
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR, ignore_errors=True)

    cleanup_stale_containers()
    runtime = build_runtime()
    print_runtime_notice(runtime)
    ui_port = runtime.host_port("ui", UI_CONTAINER_PORT)
    mock_port = runtime.host_port("camelCaseService", MOCK_CONTAINER_PORT)
    ui_url = f"http://127.0.0.1:{ui_port}"
    mock_health_url = f"http://127.0.0.1:{mock_port}/actuator/health"
    request_url = f"{ui_url}/test?RequestQuery=books"

    print("Starting camelCase mock and UI services...", flush=True)
    up_code = run_command(runtime.command(COMPOSE_FILE, "up", "-d", "camelCaseService", "ui"))
    if up_code != 0:
        return up_code

    try:
        print("Waiting for UI and mock health endpoints...", flush=True)
        wait_for_url(ui_url)
        wait_for_url(mock_health_url)

        print("Submitting the PascalCase request through the UI endpoint...", flush=True)
        response_data = perform_request(request_url)
        write_artifacts(response_data, runtime)

        print(f"Observed HTTP {response_data['status']} response from the UI flow.", flush=True)
        print("Response body:", flush=True)
        print(response_data["body"], flush=True)
        return 0
    finally:
        print("Stopping compose services for data-adapters...", flush=True)
        run_command(runtime.command(COMPOSE_FILE, "down", "-v"))


if __name__ == "__main__":
    raise SystemExit(main())
