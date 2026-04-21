from __future__ import annotations

from dataclasses import dataclass
import re
import socket
import tempfile
from pathlib import Path
from typing import Iterable


RUNTIME_NOTICE = (
    "Runtime note: this lab uses a temporary compose rewrite to allocate free host ports and removes stale named "
    "containers before startup. The upstream lab compose file is not modified."
)


@dataclass(frozen=True)
class ComposeRuntime:
    compose_path: Path
    project_directory: Path
    service_ports: dict[str, dict[int, int]]

    def command(self, compose_file: Path, *args: str) -> list[str]:
        return [
            "docker",
            "compose",
            "--project-directory",
            str(self.project_directory),
            "-f",
            str(self.compose_path),
            *args,
        ]

    def host_port(self, service: str, container_port: int) -> int:
        return self.service_ports[service][container_port]

    def runtime_notice(self) -> str:
        return RUNTIME_NOTICE


SERVICE_HEADER_RE = re.compile(r"^  (?P<service>[^\s:#][^:#]*):\s*$")


def create_compose_runtime(compose_file: Path, service_ports: dict[str, Iterable[int]], *, prefix: str) -> ComposeRuntime:
    allocated = {service: allocate_ports(list(ports)) for service, ports in service_ports.items()}
    rewritten_path = Path(tempfile.gettempdir()) / f"{prefix}-compose-runtime.yaml"
    rewrite_compose_file(compose_file, rewritten_path, allocated)
    return ComposeRuntime(compose_path=rewritten_path, project_directory=compose_file.parent, service_ports=allocated)


def allocate_ports(container_ports: list[int]) -> dict[int, int]:
    sockets: list[socket.socket] = []
    host_ports: dict[int, int] = {}
    try:
        for container_port in container_ports:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            sockets.append(sock)
            host_ports[container_port] = sock.getsockname()[1]
        return host_ports
    finally:
        for sock in sockets:
            sock.close()


def rewrite_compose_file(source: Path, destination: Path, service_ports: dict[str, dict[int, int]]) -> None:
    lines = source.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        match = SERVICE_HEADER_RE.match(line)
        if not match:
            output.append(line)
            i += 1
            continue

        service = match.group("service")
        block: list[str] = [line]
        i += 1
        while i < len(lines) and not SERVICE_HEADER_RE.match(lines[i]):
            block.append(lines[i])
            i += 1

        if service in service_ports:
            output.extend(rewrite_service_block(block, service_ports[service]))
        else:
            output.extend(block)
    destination.write_text("\n".join(output) + "\n", encoding="utf-8")


def rewrite_service_block(block: list[str], ports: dict[int, int]) -> list[str]:
    output: list[str] = []
    i = 0
    while i < len(block):
        line = block[i]
        if line.startswith("    ports:"):
            output.append("    ports:")
            for container_port, host_port in ports.items():
                output.append(f'      - "{host_port}:{container_port}"')
            i += 1
            while i < len(block) and block[i].startswith("      "):
                i += 1
            continue
        output.append(line)
        i += 1
    return output
