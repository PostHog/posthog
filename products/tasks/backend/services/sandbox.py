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

import shlex
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import TYPE_CHECKING, Protocol, Self

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


SANDBOX_TTL_SECONDS = 60 * 120  # 2 hours (safety net; workflow inactivity timeout handles cleanup)


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


WORKING_DIR = "/tmp/workspace"


class SandboxBase(ABC):
    id: str
    config: SandboxConfig

    @property
    @abstractmethod
    def sandbox_url(self) -> str | None:
        """Return the URL for connecting to the agent server, or None if not available."""
        ...

    @staticmethod
    @abstractmethod
    def create(config: SandboxConfig) -> SandboxBase: ...

    @staticmethod
    @abstractmethod
    def get_by_id(sandbox_id: str) -> SandboxBase: ...

    @staticmethod
    @abstractmethod
    def delete_snapshot(external_id: str) -> None: ...

    @abstractmethod
    def get_status(self) -> SandboxStatus: ...

    @abstractmethod
    def execute(self, command: str, timeout_seconds: int | None = None) -> ExecutionResult: ...

    @abstractmethod
    def execute_stream(self, command: str, timeout_seconds: int | None = None) -> ExecutionStream: ...

    @abstractmethod
    def write_file(self, path: str, payload: bytes) -> ExecutionResult: ...

    def clone_repository(self, repository: str, github_token: str | None = "", shallow: bool = True) -> ExecutionResult:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_url = (
            f"https://x-access-token:{github_token}@github.com/{org}/{repo}.git"
            if github_token
            else f"https://github.com/{org}/{repo}.git"
        )

        target_path = f"{WORKING_DIR}/repos/{org}/{repo}"
        org_path = f"{WORKING_DIR}/repos/{org}"

        depth_flag = f" --depth {shlex.quote('1')}" if shallow else ""
        clone_command = (
            f"rm -rf {shlex.quote(target_path)} && "
            f"mkdir -p {shlex.quote(org_path)} && "
            f"cd {shlex.quote(org_path)} && "
            f"git clone --single-branch{depth_flag} {shlex.quote(repo_url)} {shlex.quote(repo)}"
        )
        _logger.info(f"Cloning repository {repository} to {target_path} in sandbox {self.id} (shallow={shallow})")
        return self.execute(clone_command, timeout_seconds=5 * 60)

    @abstractmethod
    def setup_repository(self, repository: str) -> ExecutionResult: ...

    @abstractmethod
    def is_git_clean(self, repository: str) -> tuple[bool, str]: ...

    @abstractmethod
    def execute_task(
        self, task_id: str, run_id: str, repository: str | None = None, create_pr: bool = True
    ) -> ExecutionResult: ...

    @abstractmethod
    def get_connect_credentials(self) -> AgentServerResult:
        """Get connect credentials (URL and token) for this sandbox.

        Should be called after sandbox creation to get the URL and authentication
        token needed to connect to the sandbox.
        """
        ...

    @abstractmethod
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

    @abstractmethod
    def create_snapshot(self) -> str: ...

    @abstractmethod
    def destroy(self) -> None: ...

    @abstractmethod
    def is_running(self) -> bool: ...

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.destroy()


_ExecuteFn = Callable[..., ExecutionResult]

_logger = structlog.get_logger(__name__)


def wait_for_health_check(
    execute: _ExecuteFn,
    sandbox_id: str,
    port: int,
    max_attempts: int = 60,
    poll_interval: float = 0.5,
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


SandboxClass = type[SandboxBase]


def _get_docker_sandbox_class() -> SandboxClass:
    if not settings.DEBUG:
        raise RuntimeError(
            "DockerSandbox cannot be used in production. "
            "Set DEBUG=True for local development or remove SANDBOX_PROVIDER=docker."
        )
    from .docker_sandbox import DockerSandbox

    return DockerSandbox


def _get_modal_docker_sandbox_class() -> SandboxClass:
    """Modal sandbox with a separate app name for local development.

    Uses a dedicated Modal app (posthog-sandbox-modal-docker-*) so that
    local image builds with LOCAL_POSTHOG_CODE_MONOREPO_ROOT don't
    pollute the production app's image cache.
    """
    if not settings.DEBUG:
        raise RuntimeError("MODAL_DOCKER sandbox is for local development only (DEBUG=True).")
    from .modal_sandbox import ModalSandbox

    class ModalDockerSandbox(ModalSandbox):
        DEFAULT_APP_NAME = "posthog-sandbox-modal-docker-default"
        NOTEBOOK_APP_NAME = "posthog-sandbox-modal-docker-notebook"

    return ModalDockerSandbox


def get_sandbox_class() -> SandboxClass:
    provider = getattr(settings, "SANDBOX_PROVIDER", None)

    if provider == "docker":
        return _get_docker_sandbox_class()

    if provider and provider.upper() == "MODAL_DOCKER":
        return _get_modal_docker_sandbox_class()

    # Default to Modal everywhere
    from .modal_sandbox import ModalSandbox

    return ModalSandbox


def get_sandbox_class_for_backend(backend: str) -> SandboxClass:
    if backend == "modal":
        from .modal_sandbox import ModalSandbox

        return ModalSandbox
    if backend in ("modal_docker", "MODAL_DOCKER"):
        return _get_modal_docker_sandbox_class()
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
    "SandboxBase",
    "WORKING_DIR",
    "get_sandbox_class",
    "get_sandbox_class_for_backend",
    "wait_for_health_check",
]
