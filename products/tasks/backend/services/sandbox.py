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

from django.conf import settings

from pydantic import BaseModel


class SandboxStatus(str, Enum):
    RUNNING = "running"
    SHUTDOWN = "shutdown"


class SandboxTemplate(str, Enum):
    DEFAULT_BASE = "default_base"


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
    memory_gb: int = 16
    cpu_cores: int = 4
    disk_size_gb: int = 64


def get_sandbox_class():
    provider = getattr(settings, "SANDBOX_PROVIDER", None)

    # Docker is opt-in only, requires DEBUG mode
    if provider == "docker":
        if not settings.DEBUG:
            raise RuntimeError(
                "DockerSandbox cannot be used in production. "
                "Set DEBUG=True for local development or remove SANDBOX_PROVIDER=docker."
            )
        from .docker_sandbox import DockerSandbox

        return DockerSandbox

    # Default to Modal everywhere
    from .modal_sandbox import ModalSandbox

    return ModalSandbox


Sandbox = get_sandbox_class()

__all__ = [
    "Sandbox",
    "SandboxConfig",
    "SandboxStatus",
    "SandboxTemplate",
    "ExecutionResult",
    "get_sandbox_class",
]
