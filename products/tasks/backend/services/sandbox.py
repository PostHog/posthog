"""
Sandbox module - provides the Sandbox class for task execution.

This module exports:
- Sandbox: The sandbox class (ModalSandbox in production, DockerSandbox for local dev)
- SandboxConfig: Configuration for creating sandboxes
- SandboxStatus: Enum for sandbox states
- SandboxTemplate: Enum for sandbox templates
- ExecutionResult: Result of command execution
"""

from enum import Enum
from types import TracebackType
from typing import Protocol

from django.conf import settings

from pydantic import BaseModel


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


class SandboxConfig(BaseModel):
    name: str
    template: SandboxTemplate = SandboxTemplate.DEFAULT_BASE
    default_execution_timeout_seconds: int = 10 * 60  # 10 minutes
    environment_variables: dict[str, str] | None = None
    snapshot_id: str | None = None
    ttl_seconds: int = 60 * 30  # 30 minutes
    metadata: dict[str, str] | None = None
    memory_gb: float = 16
    cpu_cores: float = 4
    disk_size_gb: float = 64


class SandboxProtocol(Protocol):
    id: str
    config: SandboxConfig

    @staticmethod
    def create(config: SandboxConfig) -> "SandboxProtocol": ...

    @staticmethod
    def get_by_id(sandbox_id: str) -> "SandboxProtocol": ...

    @staticmethod
    def delete_snapshot(external_id: str) -> None: ...

    def get_status(self) -> SandboxStatus: ...

    def execute(self, command: str, timeout_seconds: int | None = None) -> ExecutionResult: ...

    def clone_repository(self, repository: str, github_token: str | None = "") -> ExecutionResult: ...

    def setup_repository(self, repository: str) -> ExecutionResult: ...

    def is_git_clean(self, repository: str) -> tuple[bool, str]: ...

    def execute_task(self, task_id: str, run_id: str, repository: str, create_pr: bool = True) -> ExecutionResult: ...

    def create_snapshot(self) -> str: ...

    def destroy(self) -> None: ...

    def is_running(self) -> bool: ...

    def __enter__(self) -> "SandboxProtocol": ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...


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
    "Sandbox",
    "SandboxConfig",
    "SandboxStatus",
    "SandboxTemplate",
    "ExecutionResult",
    "SandboxProtocol",
    "get_sandbox_class",
    "get_sandbox_class_for_backend",
]
