"""
Sandbox module - provides the Sandbox class for task execution.

This module exports:
- Sandbox: The sandbox class (ModalSandbox in production, DockerSandbox for local dev)
- SandboxConfig: Configuration for creating sandboxes
- SandboxStatus: Enum for sandbox states
- SandboxTemplate: Enum for sandbox templates
- ExecutionResult: Result of command execution
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import TYPE_CHECKING, Protocol

from django.conf import settings

import structlog
from pydantic import BaseModel

if TYPE_CHECKING:
    from products.tasks.backend.temporal.process_task.utils import McpServerConfig


@dataclass
class AgentServerResult:
    """Result from starting an agent server in a sandbox."""

    url: str
    token: str | None = None


class SandboxStatus(str, Enum):
    RUNNING = "running"
    SHUTDOWN = "shutdown"


class SandboxTemplate(str, Enum):
    DEFAULT_BASE = "default_base"
    NOTEBOOK_BASE = "notebook_base"


class ExecutionResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    error: str | None = None


class ExecutionStream(Protocol):
    def iter_stdout(self) -> Iterable[str]: ...

    def wait(self) -> ExecutionResult: ...


SANDBOX_TTL_SECONDS = 60 * 30  # 30 minutes


class SandboxConfig(BaseModel):
    name: str
    template: SandboxTemplate = SandboxTemplate.DEFAULT_BASE
    default_execution_timeout_seconds: int = 10 * 60  # 10 minutes
    environment_variables: dict[str, str] | None = None
    snapshot_id: str | None = None
    snapshot_external_id: str | None = None
    ttl_seconds: int = SANDBOX_TTL_SECONDS
    metadata: dict[str, str] | None = None
    memory_gb: float = 16
    cpu_cores: float = 4
    disk_size_gb: float = 64


class SandboxProtocol(Protocol):
    id: str
    config: SandboxConfig

    @property
    def sandbox_url(self) -> str | None:
        """Return the URL for connecting to the agent server, or None if not available."""
        ...

    @staticmethod
    def create(config: SandboxConfig) -> SandboxProtocol: ...

    @staticmethod
    def get_by_id(sandbox_id: str) -> SandboxProtocol: ...

    @staticmethod
    def delete_snapshot(external_id: str) -> None: ...

    def get_status(self) -> SandboxStatus: ...

    def execute(self, command: str, timeout_seconds: int | None = None) -> ExecutionResult: ...

    def execute_stream(self, command: str, timeout_seconds: int | None = None) -> ExecutionStream: ...

    def write_file(self, path: str, payload: bytes) -> ExecutionResult: ...

    def clone_repository(self, repository: str, github_token: str | None = "") -> ExecutionResult: ...

    def setup_repository(self, repository: str) -> ExecutionResult: ...

    def is_git_clean(self, repository: str) -> tuple[bool, str]: ...

    def execute_task(
        self, task_id: str, run_id: str, repository: str | None = None, create_pr: bool = True
    ) -> ExecutionResult: ...

    def get_connect_credentials(self) -> AgentServerResult:
        """Get connect credentials (URL and token) for this sandbox.

        Should be called after sandbox creation to get the URL and authentication
        token needed to connect to the sandbox.
        """
        ...

    def start_agent_server(
        self,
        repository: str | None,
        task_id: str,
        run_id: str,
        mode: str = "background",
        interaction_origin: str | None = None,
        branch: str | None = None,
        mcp_configs: list[McpServerConfig] | None = None,
        allowed_domains: list[str] | None = None,
    ) -> None:
        """Start the agent-server HTTP server in the sandbox.

        The sandbox URL and token should be obtained via get_connect_credentials()
        before calling this method.
        """
        ...

    def create_snapshot(self) -> str: ...

    def destroy(self) -> None: ...

    def is_running(self) -> bool: ...

    def __enter__(self) -> SandboxProtocol: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...


_ExecuteFn = Callable[..., ExecutionResult]

_logger = structlog.get_logger(__name__)


def wait_for_health_check(
    execute: _ExecuteFn,
    sandbox_id: str,
    port: int,
    max_attempts: int = 20,
    poll_interval: float = 0.3,
) -> bool:
    """Poll health endpoint until server is ready (single remote call).

    Runs a bash polling loop inside the sandbox so only one round-trip is
    needed regardless of how many attempts are required.
    """
    health_script = (
        f"for i in $(seq 1 {max_attempts}); do "
        f"  status=$(curl -s -o /dev/null -w '%{{http_code}}' http://localhost:{port}/health); "
        f'  [ "$status" = "200" ] && echo "ok:$i" && exit 0; '
        f"  sleep {poll_interval}; "
        f"done; "
        f"exit 1"
    )
    result = execute(health_script, timeout_seconds=max(30, int(max_attempts * poll_interval) + 5))
    if result.exit_code == 0:
        _logger.info(f"Agent-server health check passed in sandbox {sandbox_id} ({result.stdout.strip()})")
        return True
    return False


SandboxClass = type[SandboxProtocol]


def _get_docker_sandbox_class() -> SandboxClass:
    if not settings.DEBUG:
        raise RuntimeError(
            "DockerSandbox cannot be used in production. "
            "Set DEBUG=True for local development or remove SANDBOX_PROVIDER=docker."
        )
    from .docker_sandbox import DockerSandbox

    return DockerSandbox


def get_sandbox_class() -> SandboxClass:
    provider = getattr(settings, "SANDBOX_PROVIDER", None)

    # Docker is opt-in only, requires DEBUG mode
    if provider == "docker":
        return _get_docker_sandbox_class()

    # Default to Modal everywhere
    from .modal_sandbox import ModalSandbox

    return ModalSandbox


def get_sandbox_class_for_backend(backend: str) -> SandboxClass:
    if backend == "modal":
        from .modal_sandbox import ModalSandbox

        return ModalSandbox
    if backend == "docker":
        return _get_docker_sandbox_class()
    raise RuntimeError(f"Unsupported sandbox backend: {backend}")


Sandbox: SandboxClass = get_sandbox_class()

__all__ = [
    "AgentServerResult",
    "Sandbox",
    "SandboxConfig",
    "SandboxStatus",
    "SandboxTemplate",
    "ExecutionResult",
    "ExecutionStream",
    "SANDBOX_TTL_SECONDS",
    "SandboxProtocol",
    "get_sandbox_class",
    "get_sandbox_class_for_backend",
    "wait_for_health_check",
]
