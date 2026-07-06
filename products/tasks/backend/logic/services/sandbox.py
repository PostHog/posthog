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

import os
import re
import json
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

from products.tasks.backend.constants import DEFAULT_SANDBOX_WORKING_DIR, SNAPSHOT_KIND_FILESYSTEM, SnapshotKind
from products.tasks.backend.logic.services.sandbox_config import (
    BURSTABLE_REQUEST_CPU_CORES,
    BURSTABLE_REQUEST_MEMORY_MB,
    SANDBOX_TTL_SECONDS,
)

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
    PI_BASE = "pi_base"
    VM_BASE = "vm_base"

    STREAMLIT_BASE = "streamlit_base"


class ExecutionResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    error: str | None = None


class ExecutionStream(Protocol):
    def iter_stdout(self) -> Iterable[str]: ...

    def wait(self) -> ExecutionResult: ...


@dataclass(frozen=True)
class SandboxResources:
    """Optional compute overrides for a task's sandbox. Unset fields keep the
    `SandboxConfig` defaults — callers pass only what they want to change."""

    cpu_cores: float | None = None
    memory_gb: float | None = None


class SandboxConfig(BaseModel):
    name: str
    template: SandboxTemplate = SandboxTemplate.DEFAULT_BASE
    default_execution_timeout_seconds: int = 10 * 60  # 10 minutes
    environment_variables: dict[str, str] | None = None
    snapshot_id: str | None = None
    snapshot_external_id: str | None = None
    snapshot_kind: SnapshotKind = SNAPSHOT_KIND_FILESYSTEM
    snapshot_mount_path: str | None = None
    snapshot_source: str = "none"
    snapshot_restored: bool = False
    ttl_seconds: int = SANDBOX_TTL_SECONDS
    metadata: dict[str, str] | None = None
    memory_gb: float = 16
    cpu_cores: float = 4
    disk_size_gb: float = 64
    # When True, request a small floor and let the box burst up to `cpu_cores` / `memory_gb`
    # (the limit); Modal bills max(request, actual). When False, request == limit (fixed size).
    burstable_resources: bool = False
    # Request floor used when `burstable_resources` is True: the box reserves this much and bursts
    # up to `cpu_cores` / `memory_gb`. Clamped to the limit at create time so it never exceeds it.
    cpu_request_cores: float = BURSTABLE_REQUEST_CPU_CORES
    memory_request_mb: int = BURSTABLE_REQUEST_MEMORY_MB
    vm_runtime: bool = False
    # gVisor only — Modal rejects this under vm_runtime.
    outbound_domain_allowlist: list[str] | None = None

    @property
    def is_vm(self) -> bool:
        return self.vm_runtime or self.template == SandboxTemplate.VM_BASE


WORKING_DIR = DEFAULT_SANDBOX_WORKING_DIR

REPO_READY_FILE = f"{WORKING_DIR}/.repo-ready"

PUBLIC_SANDBOX_REPOS: frozenset[str] = frozenset({"posthog/hedgebox", "posthog/.github"})
"""Repos the sandbox is allowed to clone unauthenticated, even when the team has no GitHub integration"""
# TODO: Remove `posthog/.github` when we switch repo discovery to repo-less agent (now it works as a lightweight dummy)

SENSITIVE_AGENT_RUNTIME_ENV_NAMES: frozenset[str] = frozenset({"POSTHOG_TASK_RUN_EVENT_INGEST_TOKEN"})
SENSITIVE_AGENT_RUNTIME_ENV_PATTERN = re.compile(
    r"(?P<name>" + "|".join(re.escape(name) for name in SENSITIVE_AGENT_RUNTIME_ENV_NAMES) + r")="
    r"(?P<value>'(?:[^']|'\"'\"')*'|\"(?:\\.|[^\"])*\"|\S+)"
)


def is_public_sandbox_repo(repository: str | None) -> bool:
    return repository is not None and repository.lower() in PUBLIC_SANDBOX_REPOS


def sandbox_repo_path(repository: str) -> str:
    """Absolute path an ``org/repo`` is cloned to inside the sandbox (the agent-server's cwd)."""
    org, repo = repository.lower().split("/")
    return f"{WORKING_DIR}/repos/{org}/{repo}"


def redact_sandbox_command(command: str) -> str:
    return SENSITIVE_AGENT_RUNTIME_ENV_PATTERN.sub(r"\g<name>=<redacted>", command)


def build_agent_runtime_env_prefix(
    *,
    interaction_origin: str | None = None,
    runtime_adapter: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    event_ingest_token: str | None = None,
    event_ingest_url: str | None = None,
    event_ingest_keep_stream_open: bool = False,
) -> str:
    env_vars = {
        "POSTHOG_CODE_INTERACTION_ORIGIN": interaction_origin,
        "POSTHOG_CODE_RUNTIME_ADAPTER": runtime_adapter,
        "POSTHOG_CODE_PROVIDER": provider,
        "POSTHOG_CODE_MODEL": model,
        "POSTHOG_CODE_REASONING_EFFORT": reasoning_effort,
        "POSTHOG_TASK_RUN_EVENT_INGEST_TOKEN": event_ingest_token,
        "POSTHOG_TASK_RUN_EVENT_INGEST_URL": event_ingest_url,
        "POSTHOG_TASK_RUN_EVENT_INGEST_KEEP_STREAM_OPEN": "true" if event_ingest_keep_stream_open else None,
    }
    assignments = " ".join(
        f"{name}={shlex.quote(value)}" for name, value in env_vars.items() if value is not None and value != ""
    )
    return f"env {assignments} " if assignments else ""


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

        target_path = sandbox_repo_path(repository)
        org_path = f"{WORKING_DIR}/repos/{org}"

        depth_flag = f" --depth {shlex.quote('1')}" if shallow else ""
        # Skip blobs over 128kB during full clones — large test snapshots and auto-generated
        # files get fetched on demand. Shallow clones are already small enough.
        blob_filter = "" if shallow else " --filter=blob:limit=128k"
        clone_command = (
            f"rm -rf {shlex.quote(target_path)} && "
            f"mkdir -p {shlex.quote(org_path)} && "
            f"cd {shlex.quote(org_path)} && "
            f"git clone --single-branch{blob_filter}{depth_flag} {shlex.quote(repo_url)} {shlex.quote(repo)}"
        )
        _logger.info(f"Cloning repository {repository} to {target_path} in sandbox {self.id} (shallow={shallow})")
        return self.execute(clone_command, timeout_seconds=5 * 60)

    @abstractmethod
    def setup_repository(self, repository: str) -> ExecutionResult: ...

    @abstractmethod
    def is_git_clean(self, repository: str) -> tuple[bool, str]: ...

    @abstractmethod
    def execute_task(
        self,
        task_id: str,
        run_id: str,
        repository: str | None = None,
        create_pr: bool = True,
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
        create_pr: bool = True,
        interaction_origin: str | None = None,
        branch: str | None = None,
        runtime_adapter: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        mcp_configs: list[McpServerConfig] | None = None,
        allowed_domains: list[str] | None = None,
        event_ingest_token: str | None = None,
        event_ingest_url: str | None = None,
        event_ingest_keep_stream_open: bool = False,
        repo_ready_file: str | None = None,
        wait_for_health: bool = True,
    ) -> None:
        """Start the agent-server HTTP server in the sandbox.

        The sandbox URL and token should be obtained via get_connect_credentials()
        before calling this method.
        """
        ...

    @abstractmethod
    def wait_for_agent_server_ready(self, allowed_domains: list[str] | None = None) -> None: ...

    @abstractmethod
    def mark_repo_ready(self, repo_ready_file: str) -> None: ...

    @abstractmethod
    def create_snapshot(self) -> str: ...

    @abstractmethod
    def create_directory_snapshot(self, path: str) -> str: ...

    @abstractmethod
    def destroy(self) -> None: ...

    @abstractmethod
    def is_running(self) -> bool: ...

    def read_agent_server_session_init_ms(self) -> int | None:
        return None

    def _read_health_session_init_ms(self, port: int) -> int | None:
        try:
            result = self.execute(f"curl -s --max-time 5 http://localhost:{port}/health", timeout_seconds=10)
            payload = json.loads(result.stdout or "{}")
            session_init_ms = payload.get("sessionInitMs")
            return int(session_init_ms) if isinstance(session_init_ms, int | float) else None
        except Exception:
            return None

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


def parse_sandbox_repo_mount_map() -> dict[str, str]:
    """Parse SANDBOX_REPO_MOUNT_MAP into {lower(org/repo): expanded_local_path}.

    Used by Docker sandbox for bind mounts and by task activities for user-facing logs.
    Format: ``org/repo:/local/path,org2/repo2:~/other/path``
    """
    raw = os.environ.get("SANDBOX_REPO_MOUNT_MAP", "")
    if not raw:
        return {}

    result: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 1)
        if len(parts) != 2 or "/" not in parts[0]:
            _logger.warning(f"Ignoring malformed SANDBOX_REPO_MOUNT_MAP entry: {entry}")
            continue
        repo_key = parts[0].strip().lower()
        local_path = os.path.expanduser(parts[1].strip())
        if not os.path.isdir(local_path):
            _logger.warning(f"SANDBOX_REPO_MOUNT_MAP: path does not exist, skipping: {local_path}")
            continue
        result[repo_key] = os.path.abspath(local_path)
    return result


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
        f"  body=$(curl -s http://localhost:{port}/health); "
        "  status=$?; "
        '  if [ "$status" = "0" ]; then '
        "    python3 -c '"
        "import json, sys; "
        "payload = json.loads(sys.argv[1]); "
        'sys.exit(0 if payload.get("status") == "ok" and payload.get("hasSession") is True else 1)'
        f'\' "$body" && echo "ok:$i" && exit 0; '
        "  fi; "
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
    # Allow TEST too: the guard runs at module import, and pytest loads settings with
    # DEBUG off in some paths — blocking there would kill collection, not production.
    if not (settings.DEBUG or settings.TEST):
        raise RuntimeError(
            "DockerSandbox is for local development only. Set DEBUG=1 (the flox env sets this "
            "automatically — are you outside 'flox activate'?) or unset SANDBOX_PROVIDER "
            "(check .env/.env.local and your shell)."
        )
    from .docker_sandbox import DockerSandbox

    return DockerSandbox


def _get_modal_docker_sandbox_class() -> SandboxClass:
    """Modal sandbox with a separate app name for local development.

    Uses a dedicated Modal app (posthog-sandbox-modal-docker-*) so that
    local image builds with LOCAL_POSTHOG_CODE_MONOREPO_ROOT don't
    pollute the production app's image cache.
    """
    # Allow TEST too: the guard runs at module import, and pytest loads settings with
    # DEBUG off in some paths — blocking there would kill collection, not production.
    if not (settings.DEBUG or settings.TEST):
        raise RuntimeError(
            "MODAL_DOCKER sandbox is for local development only. Set DEBUG=1 (the flox env sets "
            "this automatically — are you outside 'flox activate'?) or unset SANDBOX_PROVIDER "
            "(check .env/.env.local and your shell)."
        )
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


if TYPE_CHECKING:
    # Resolved at runtime by get_sandbox_class(); for type-checkers it is the base class.
    Sandbox: SandboxClass = SandboxBase
else:

    def __getattr__(name: str) -> object:
        # Resolve `Sandbox` lazily. Computing it at import time calls get_sandbox_class(),
        # which for the docker / modal_docker providers imports a sibling module
        # (docker_sandbox / modal_sandbox). When that sibling is the first of the pair to be
        # imported (e.g. test_docker_sandbox.py imports docker_sandbox, which imports this
        # module), the eager call reaches back into the still-initializing sibling and fails
        # as a circular import. Deferring to first attribute access breaks the cycle.
        if name == "Sandbox":
            sandbox_class = get_sandbox_class()
            globals()["Sandbox"] = sandbox_class  # cache so later lookups skip __getattr__
            return sandbox_class
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    "parse_sandbox_repo_mount_map",
    "sandbox_repo_path",
    "get_sandbox_class",
    "get_sandbox_class_for_backend",
    "wait_for_health_check",
]
