from __future__ import annotations

import json
import socket
import ipaddress
import subprocess
from contextlib import ExitStack
from uuid import uuid4

from unittest.mock import patch

from .controller import Controller
from .forwarding import forward_local_port


def restrict_egress(stack: ExitStack, controller: Controller) -> None:
    from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox

    network = f"ai-e2e-{uuid4().hex}"
    subprocess.run(["docker", "network", "create", "--internal", network], check=True, capture_output=True)
    stack.callback(subprocess.run, ["docker", "network", "rm", network], check=True, capture_output=True)
    info = json.loads(subprocess.check_output(["docker", "network", "inspect", network]))[0]
    gateway = info["IPAM"]["Config"][0]["Gateway"]
    original_run = DockerSandbox._run
    original_recover_port = DockerSandbox._recover_published_host_port
    ports: dict[str, int] = {}

    def recover_port(container_id: str) -> int | None:
        return ports.get(container_id) or original_recover_port(container_id)

    def isolated(argv: list[str], check: bool = False, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        if argv[:2] == ["docker", "stop"] and controller.attempt:
            controller.attempt.capture()
        if argv[:2] == ["docker", "run"]:
            attempt = controller.attempt
            if attempt is None or not argv[argv.index("--name") + 1].startswith(f"task-sandbox-{attempt.task_id}-"):
                raise ValueError("Sandbox does not belong to the active attempt")
            argv = [arg.replace("host.docker.internal:host-gateway", f"host.docker.internal:{gateway}") for arg in argv]
            argv[2:2] = ["--network", network]
        result = original_run(argv, check=check, timeout=timeout)
        if argv[:2] == ["docker", "run"] and result.returncode == 0:
            assert attempt is not None
            container_id = result.stdout.strip()
            port, target_port = map(int, argv[argv.index("-p") + 1].split(":"))
            details = json.loads(subprocess.check_output(["docker", "inspect", container_id]))[0]
            address = details["NetworkSettings"]["Networks"][network]["IPAddress"]
            ports[container_id] = port
            stop = forward_local_port(port, (address, target_port))
            controller.require_attempt(attempt.id).cleanup_callbacks.append(stop)
        return result

    connect = socket.socket.connect

    def local_connect(sock: socket.socket, address: tuple[str, int] | str) -> None:
        if isinstance(address, tuple):
            resolved = socket.getaddrinfo(address[0], address[1], sock.family, sock.type)
            if any(ipaddress.ip_address(entry[4][0]).is_global for entry in resolved):
                controller.record_error(f"Blocked external connection to {address[0]}:{address[1]}")
                raise ConnectionRefusedError("AI E2E permits only local service connections")
        connect(sock, address)

    stack.enter_context(patch.object(DockerSandbox, "_run", side_effect=isolated))
    stack.enter_context(patch.object(DockerSandbox, "_recover_published_host_port", side_effect=recover_port))
    stack.enter_context(patch.object(socket.socket, "connect", local_connect))
