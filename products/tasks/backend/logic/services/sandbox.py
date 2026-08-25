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
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from enum import Enum
from types import TracebackType
from typing import TYPE_CHECKING, Protocol, Self

from django.conf import settings

import structlog
from pydantic import BaseModel, model_validator

from products.tasks.backend.constants import (
    DEFAULT_SANDBOX_WORKING_DIR,
    DEV_STACK_IMAGE_NAME,
    SNAPSHOT_KIND_DIRECTORY,
    SNAPSHOT_KIND_FILESYSTEM,
    SnapshotKind,
)
from products.tasks.backend.logic.services.sandbox_config import (
    BURSTABLE_REQUEST_CPU_CORES,
    BURSTABLE_REQUEST_MEMORY_MB,
    SANDBOX_TTL_SECONDS,
    VM_SANDBOX_CPU_CORES,
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
    AUTORESEARCH_BASE = "autoresearch_base"
    VM_BASE = "vm_base"

    STREAMLIT_BASE = "streamlit_base"
    # Minimal template (git, node, uv — no agent server, no skills). For review/exec
    # sandboxes like stamphog that never run the agent server. See
    # Dockerfile.sandbox-slim and modal_sandbox.py's SLIM_BASE image definition.
    SLIM_BASE = "slim_base"
    CANVAS_BUILD = "canvas_build"


class SandboxWorkload(str, Enum):
    """Which provider-side project a sandbox is booked against, independent of its image.

    Modal groups sandboxes and their cost by app. The template already picks an app for the
    product-specific images; this picks one for workloads that share an image but should be
    metered apart.
    """

    DEFAULT = "default"
    SELF_DRIVING = "self_driving"


SELF_DRIVING_ORIGIN_PRODUCTS: frozenset[str] = frozenset(
    {
        # Signals report research + repo selection
        "signal_report",
        # Headless Signals scouts
        "signals_scout",
        # ReviewHog's per-chunk review, blind-spot, and validation sandboxes
        "review_hog",
    }
)
"""Origin products whose sandboxes are booked against the self-driving provider project.

Wider than the self-driving *quota* gate (`enforce_self_driving_quota.py`), which only covers the
billable implementation-PR run: this is every sandbox the fleet opens, research and review included.
Held as strings rather than ``Task.OriginProduct`` members to keep the model layer off this module's
import path; a test pins them to the enum so a rename can't drop a product off the fleet.
"""


def workload_for_origin_product(origin_product: str | None) -> SandboxWorkload:
    if origin_product in SELF_DRIVING_ORIGIN_PRODUCTS:
        return SandboxWorkload.SELF_DRIVING
    return SandboxWorkload.DEFAULT


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
    # Decides which Modal app owns the box, and with it how its cost is attributed. Changes
    # nothing about the box itself — same image, same resources, same isolation.
    workload: SandboxWorkload = SandboxWorkload.DEFAULT
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
    # up to `cpu_cores` / `memory_gb`. Read through the `effective_*_request` properties, which
    # apply the limit clamp and the VM memory pin.
    cpu_request_cores: float = BURSTABLE_REQUEST_CPU_CORES
    memory_request_mb: int = BURSTABLE_REQUEST_MEMORY_MB
    vm_runtime: bool = False
    outbound_domain_allowlist: list[str] | None = None
    network_policy_fingerprint: str | None = None
    # gVisor only. An empty domain allowlist means unrestricted network in
    # Modal, so callers that require no egress must state it explicitly.
    block_network: bool = False
    # VM runtime only — custom images layer on the VM base; snapshot restores take precedence.
    custom_image_name: str | None = None
    # Set by the provider when the sandbox could not be created from the intended image and a
    # downgraded one was used instead (e.g. published custom image -> plain base). Human-readable,
    # surfaced in the run log so image downgrades are never silent.
    image_fallback: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _default_vm_cpu(cls, data: object) -> object:
        if (
            isinstance(data, dict)
            and "cpu_cores" not in data
            and (
                data.get("vm_runtime")
                or data.get("template") in (SandboxTemplate.VM_BASE, SandboxTemplate.VM_BASE.value)
            )
        ):
            return {**data, "cpu_cores": VM_SANDBOX_CPU_CORES}
        return data

    @property
    def is_vm(self) -> bool:
        return self.vm_runtime or self.template == SandboxTemplate.VM_BASE

    @property
    def effective_cpu_request_cores(self) -> float:
        """CPU floor the provider actually reserves when burstable: the configured request,
        clamped to the limit."""
        return min(float(self.cpu_request_cores), float(self.cpu_cores))

    @property
    def effective_memory_request_mb(self) -> int:
        """Memory floor the provider actually reserves when burstable. VM memory can't burst,
        so a VM's request is pinned to its limit; gVisor requests are clamped to the limit."""
        memory_limit_mb = int(self.memory_gb * 1024)
        if self.is_vm:
            return memory_limit_mb
        return min(int(self.memory_request_mb), memory_limit_mb)


WORKING_DIR = DEFAULT_SANDBOX_WORKING_DIR

REPO_READY_FILE = f"{WORKING_DIR}/.repo-ready"

PUBLIC_SANDBOX_REPOS: frozenset[str] = frozenset({"posthog/hedgebox", "posthog/.github"})
"""Repos the sandbox is allowed to clone unauthenticated, even when the team has no GitHub integration"""
# TODO: Remove `posthog/.github` when we switch repo discovery to repo-less agent (now it works as a lightweight dummy)

SENSITIVE_AGENT_RUNTIME_ENV_NAMES: frozenset[str] = frozenset(
    {"POSTHOG_TASK_RUN_EVENT_INGEST_TOKEN", "POSTHOG_TASK_RUN_SESSION_TOKEN"}
)
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
    agent_runtime: str | None = None,
    sandbox_id: str | None = None,
    runtime_adapter: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    reasoning_effort: str | None = None,
    context_window: str | None = None,
    fast_mode: bool | None = None,
    initial_permission_mode: str | None = None,
    event_ingest_token: str | None = None,
    task_run_session_token: str | None = None,
    event_ingest_url: str | None = None,
    event_ingest_keep_stream_open: bool = False,
    rtk_enabled: bool = True,
    peer_messaging: bool = False,
) -> str:
    env_vars = {
        "POSTHOG_CODE_INTERACTION_ORIGIN": interaction_origin,
        "POSTHOG_AGENT_RUNTIME": agent_runtime,
        "POSTHOG_SANDBOX_ID": sandbox_id,
        "POSTHOG_CODE_RUNTIME_ADAPTER": runtime_adapter,
        "POSTHOG_CODE_PROVIDER": provider,
        "POSTHOG_CODE_MODEL": model,
        "POSTHOG_CODE_REASONING_EFFORT": reasoning_effort,
        "POSTHOG_CODE_CONTEXT_WINDOW": context_window,
        # Explicit false pins fast mode off even if a stale env value survives in a resumed sandbox.
        "POSTHOG_CODE_FAST_MODE": None if fast_mode is None else ("true" if fast_mode else "false"),
        "POSTHOG_CODE_INITIAL_PERMISSION_MODE": initial_permission_mode,
        "POSTHOG_TASK_RUN_EVENT_INGEST_TOKEN": event_ingest_token,
        "POSTHOG_TASK_RUN_SESSION_TOKEN": task_run_session_token,
        "POSTHOG_TASK_RUN_EVENT_INGEST_URL": event_ingest_url,
        "POSTHOG_TASK_RUN_EVENT_INGEST_KEEP_STREAM_OPEN": "true" if event_ingest_keep_stream_open else None,
        # Set explicitly in both states: "0" opts the run out, "1" pins auto-detection on
        # even if a stale env value survives in a resumed sandbox.
        "POSTHOG_RTK": "1" if rtk_enabled else "0",
        # Exposure gate for the peer-messaging tools (PR: agent peer messaging). Set in
        # both states so a stale "1" in a resumed sandbox can't outlive a flag rollback;
        # the peers endpoints re-check authorization server-side regardless.
        "POSTHOG_AGENT_PEER_MESSAGING": "1" if peer_messaging else "0",
    }
    assignments = " ".join(
        f"{name}={shlex.quote(value)}" for name, value in env_vars.items() if value is not None and value != ""
    )
    return f"env {assignments} " if assignments else ""


class SandboxBase(ABC):
    id: str
    config: SandboxConfig
    supports_creation_cancellation = False
    creation_timeout_seconds = 300

    @staticmethod
    def creation_cancellation_scope(cancel_event: threading.Event) -> AbstractContextManager[None]:
        return nullcontext()

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

    def stop_agent_server(self) -> ExecutionResult:
        """Stop the agent server gracefully so it can flush terminal events."""
        return self.execute(
            "pkill -TERM -f '[a]gent-server' 2>/dev/null || true; "
            "for _ in $(seq 1 80); do "
            "pgrep -f '[a]gent-server' >/dev/null || exit 0; "
            "sleep 0.5; "
            "done; "
            "exit 1",
            timeout_seconds=45,
        )

    def launch_dev_stack_bootstrap(self) -> bool:
        """Fire-and-forget the baked dev-stack bootstrap helper when this image carries it.

        The prebaked dev-stack image ships /usr/local/bin/bootstrap-dev-stack (see
        bake-posthog-dev-stack.sh): it restores the compose /etc/hosts aliases the sandbox
        boot wiped and starts dockerd. Launching it detached at provision time overlaps
        that warmup with the repo clone and agent-server boot, so a task-time `hogli start`
        finds dockerd already up. The helper is idempotent — an agent running it again per
        AGENTS.md just blocks until the warmup completes.

        Best-effort by design: returns whether the helper was found and launched, and never
        raises. A missed warmup only costs the overlap; the agent-side bootstrap still works.
        """
        # Only a sandbox that actually booted the PostHog-published dev-stack image gets
        # its bootstrap run by the backend. This hook runs after credentials land in the
        # sandbox env, so executing a script from any less-trusted filesystem would hand
        # its author code execution with another member's secrets. Two checks:
        #   - the reserved name (user images always publish as posthog-sandbox-custom-*),
        #     with the absolute path below avoiding PATH shadowing;
        #   - not a filesystem-snapshot restore: such a resume boots a mutable snapshot
        #     of a prior run — one that processed untrusted repo content and could have
        #     replaced the helper file itself. Directory restores only mount the workspace
        #     dir (ALLOWED_DIRECTORY_RESUME_SNAPSHOT_MOUNT_PATHS), leaving the helper the
        #     vetted image's own binary, so the warmup stays on for them — but the
        #     workspace is still attacker-controlled, so the launcher below scrubs the
        #     environment (fixed PATH, no credentials) rather than trusting it. Anything
        #     not explicitly a directory restore is treated as filesystem — fail closed.
        restored_untrusted_filesystem = (
            self.config.snapshot_restored and self.config.snapshot_kind != SNAPSHOT_KIND_DIRECTORY
        )
        if (
            not self.config.is_vm
            or self.config.custom_image_name != DEV_STACK_IMAGE_NAME
            or restored_untrusted_filesystem
        ):
            return False
        try:
            # Exit 3 = helper not present (downgraded to the plain VM base, or a pre-helper
            # image) — an expected skip, not a failure. setsid + redirects detach the helper
            # from this exec, which the sandbox runtime reaps as soon as the command returns.
            #
            # Run the helper through `/usr/bin/env -i` (absolute — a user PATH cannot shadow
            # the launcher) with a fixed system PATH and no other environment. This is what
            # makes the directory-restore case above safe: a directory resume mounts the
            # untrusted workspace at /tmp/workspace, and PATH is a settable sandbox env var,
            # so without scrubbing the helper's `start-dockerd`/`docker` lookups could resolve
            # an attacker binary from the workspace — and would run it with the injected
            # POSTHOG_PERSONAL_API_KEY / GITHUB_TOKEN. `env -i` drops those credentials and the
            # user PATH; the fixed PATH resolves only real system binaries (start-dockerd lives
            # in /usr/local/bin). HOME=/root covers tooling that needs it (dockerd runs as root).
            result = self.execute(
                "[ -x /usr/local/bin/bootstrap-dev-stack ] || exit 3; "
                "/usr/bin/env -i HOME=/root PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "
                "setsid /usr/local/bin/bootstrap-dev-stack >/var/log/bootstrap-dev-stack.log 2>&1 </dev/null &",
                timeout_seconds=30,
            )
        except Exception as e:
            _logger.warning("dev_stack_bootstrap_launch_failed", sandbox_id=self.id, error=str(e))
            return False
        if result.exit_code == 0:
            return True
        if result.exit_code != 3:
            _logger.warning(
                "dev_stack_bootstrap_launch_failed",
                sandbox_id=self.id,
                exit_code=result.exit_code,
                stderr=result.stderr,
            )
        return False

    def agent_server_supports_auto_publish(self) -> bool:
        """Sandboxes restored from old snapshots can carry an agent-server that rejects unknown
        CLI options, so probe the installed binary before passing --autoPublish; unsupported
        binaries degrade to review-first instead of crashing at launch."""
        result = self.execute("grep -q autoPublish /scripts/node_modules/.bin/agent-server", timeout_seconds=10)
        return result.exit_code == 0

    def agent_server_supports_exec_permission_regex(self) -> bool:
        """Same probe as --autoPublish: check the installed binary before passing
        --posthogExecPermissionRegex; unsupported binaries degrade to server-side auto-approval of
        exec sub-tools instead of crashing at launch."""
        result = self.execute(
            "grep -q posthogExecPermissionRegex /scripts/node_modules/.bin/agent-server", timeout_seconds=10
        )
        return result.exit_code == 0

    def agent_server_supports_pi_runtime(self) -> bool:
        result = self.execute(
            "grep -q POSTHOG_AGENT_RUNTIME /scripts/node_modules/.bin/agent-server",
            timeout_seconds=10,
        )
        return result.exit_code == 0

    def clone_repository(
        self,
        repository: str,
        github_token: str | None = "",
        shallow: bool = True,
        branch: str | None = None,
        blobless: bool = False,
    ) -> ExecutionResult:
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
        branch_flag = f" --branch {shlex.quote(branch)}" if branch else ""
        blob_filter = ""
        if not shallow:
            blob_filter = " --filter=blob:none" if blobless else " --filter=blob:limit=128k"
        clone_command = (
            f"rm -rf {shlex.quote(target_path)} && "
            f"mkdir -p {shlex.quote(org_path)} && "
            f"cd {shlex.quote(org_path)} && "
            f"git clone --single-branch{blob_filter}{depth_flag}{branch_flag} "
            f"{shlex.quote(repo_url)} {shlex.quote(repo)}"
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
        auto_publish: bool = False,
        interaction_origin: str | None = None,
        branch: str | None = None,
        agent_runtime: str | None = None,
        runtime_adapter: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        context_window: str | None = None,
        fast_mode: bool | None = None,
        initial_permission_mode: str | None = None,
        mcp_configs: list[McpServerConfig] | None = None,
        relayed_mcp_servers: list[str] | None = None,
        allowed_domains: list[str] | None = None,
        event_ingest_token: str | None = None,
        task_run_session_token: str | None = None,
        event_ingest_url: str | None = None,
        event_ingest_keep_stream_open: bool = False,
        repo_ready_file: str | None = None,
        wait_for_health: bool = True,
        rtk_enabled: bool = True,
        peer_messaging: bool = False,
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
    def create_snapshot(self, *, timeout_seconds: int | None = None) -> str: ...

    @abstractmethod
    def create_directory_snapshot(self, path: str) -> str: ...

    @abstractmethod
    def prune_snapshot_heavy_dirs(self, path: str) -> None: ...

    @abstractmethod
    def destroy(self) -> None: ...

    @abstractmethod
    def is_running(self) -> bool: ...

    def read_agent_server_session_init_ms(self) -> int | None:
        return None

    def read_agent_server_boot_phases_ms(self) -> dict[str, int]:
        return {}

    def read_agent_server_boot_metrics(self) -> tuple[int | None, dict[str, int]]:
        return None, {}

    def agent_server_health_url(self) -> str:
        return "http://127.0.0.1:8080/health"

    def read_cpu_usage_usec(self) -> int | None:
        return None

    def start_cpu_billing_sampler(self) -> bool:
        return False

    def read_billed_cpu_usage_usec(self) -> int | None:
        return None

    def _read_health_session_init_ms(self, port: int) -> int | None:
        try:
            result = self.execute(f"curl -s --max-time 5 http://localhost:{port}/health", timeout_seconds=10)
            payload = json.loads(result.stdout or "{}")
            session_init_ms = payload.get("sessionInitMs")
            return int(session_init_ms) if isinstance(session_init_ms, int | float) else None
        except Exception:
            return None

    def _read_health_boot_metrics(self, port: int) -> tuple[int | None, dict[str, int]]:
        try:
            result = self.execute(f"curl -s --max-time 5 http://localhost:{port}/health", timeout_seconds=10)
            payload = json.loads(result.stdout or "{}")
            session_init_ms = payload.get("sessionInitMs")
            raw_phases = payload.get("boot", {}).get("phasesMs", {})
            allowed_phases = {
                "context_fetch",
                "acp_initialize",
                "repository_ready",
                "session_dependencies",
                "session_create",
            }
            phases = (
                {
                    phase: max(0, int(duration))
                    for phase, duration in raw_phases.items()
                    if phase in allowed_phases and isinstance(duration, int | float)
                }
                if isinstance(raw_phases, dict)
                else {}
            )
            return int(session_init_ms) if isinstance(session_init_ms, int | float) else None, phases
        except Exception:
            return None, {}

    def _read_health_boot_phases_ms(self, port: int) -> dict[str, int]:
        try:
            result = self.execute(f"curl -s --max-time 5 http://localhost:{port}/health", timeout_seconds=10)
            payload = json.loads(result.stdout or "{}")
            raw_phases = payload.get("boot", {}).get("phasesMs", {})
            allowed_phases = {
                "context_fetch",
                "acp_initialize",
                "repository_ready",
                "session_dependencies",
                "session_create",
            }
            if not isinstance(raw_phases, dict):
                return {}
            return {
                phase: max(0, int(duration))
                for phase, duration in raw_phases.items()
                if phase in allowed_phases and isinstance(duration, int | float)
            }
        except Exception:
            return {}

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
        STREAMLIT_APP_NAME = "posthog-sandbox-modal-docker-streamlit"
        SELF_DRIVING_APP_NAME = "posthog-sandbox-modal-docker-self-driving"

    return ModalDockerSandbox


def _get_modal_evals_sandbox_class() -> SandboxClass:
    """Modal sandbox isolated from both production and local development apps."""
    if not (settings.DEBUG or settings.TEST):
        raise RuntimeError("MODAL_EVALS sandbox is for evals only and requires DEBUG=1 or TEST=1.")
    from .modal_sandbox import ModalSandbox

    class ModalEvalsSandbox(ModalSandbox):
        DEFAULT_APP_NAME = "posthog-sandbox-evals"
        NOTEBOOK_APP_NAME = "posthog-sandbox-evals"
        STREAMLIT_APP_NAME = "posthog-sandbox-evals"
        # Evals are their own cost centre already — a self-driving eval stays in the evals app.
        SELF_DRIVING_APP_NAME = "posthog-sandbox-evals"

    return ModalEvalsSandbox


def _get_hogland_sandbox_class() -> SandboxClass:
    from .hogland_sandbox import HoglandSandbox

    return HoglandSandbox


def get_sandbox_class() -> SandboxClass:
    provider = getattr(settings, "SANDBOX_PROVIDER", None)

    if provider == "docker":
        return _get_docker_sandbox_class()

    if provider and provider.upper() == "MODAL_DOCKER":
        return _get_modal_docker_sandbox_class()

    if provider and provider.upper() == "MODAL_EVALS":
        return _get_modal_evals_sandbox_class()

    if provider and provider.lower() == "hogland":
        # Global default only for local development — production routes per run via
        # get_sandbox_class_for_backend, driven by the tasks-hogland-sandbox flag.
        if not (settings.DEBUG or settings.TEST):
            raise RuntimeError(
                "SANDBOX_PROVIDER=hogland is for local development only. In production the "
                "hogland backend is selected per run by the tasks-hogland-sandbox feature flag."
            )
        return _get_hogland_sandbox_class()

    # Default to Modal everywhere
    from .modal_sandbox import ModalSandbox

    return ModalSandbox


def get_sandbox_class_for_backend(backend: str) -> SandboxClass:
    if backend == "modal":
        from .modal_sandbox import ModalSandbox

        return ModalSandbox
    if backend in ("modal_docker", "MODAL_DOCKER"):
        return _get_modal_docker_sandbox_class()
    if backend in ("modal_evals", "MODAL_EVALS"):
        return _get_modal_evals_sandbox_class()
    if backend == "docker":
        return _get_docker_sandbox_class()
    if backend == "hogland":
        return _get_hogland_sandbox_class()
    raise RuntimeError(f"Unsupported sandbox backend: {backend}")


def get_sandbox_class_for_run_backend(backend: str) -> SandboxClass:
    """Resolve the provider class for a run whose backend was chosen at context time.

    Only ``"hogland"`` diverts from the process default. Every other value — including
    the ``"modal"`` default — falls through to ``get_sandbox_class()`` so
    ``SANDBOX_PROVIDER`` still selects docker / modal-docker / modal-evals in dev, test,
    and evals. Routing straight to ``get_sandbox_class_for_backend("modal")`` here would
    force ModalSandbox even under ``SANDBOX_PROVIDER=docker``, breaking local runs.
    """
    if backend == "hogland":
        return _get_hogland_sandbox_class()
    return get_sandbox_class()


# hogland mints `box-<12 hex>` (hogd enforces `^box-[0-9a-f]{12}$`); Modal object ids
# are `sb-...`. A box restored from a pen keeps a `box-` id, so this covers pens too.
HOGLAND_SANDBOX_ID_PREFIX = "box-"


def get_sandbox_class_for_sandbox_id(sandbox_id: str) -> SandboxClass:
    """Resolve the provider class for an existing sandbox from its id alone.

    Hogland box ids are `box-...` and Modal object ids `sb-...`, so the prefix is enough
    to route the ~20 `get_by_id` call sites that hold only a persisted sandbox id (the
    reaper, cleanup, and snapshot activities have no other backend context). Anything
    that is not a hogland id falls through to the process-wide provider, preserving the
    docker/local-dev behavior.

    Getting this prefix wrong fails closed to the wrong provider: a hogland id would
    resolve to Modal, whose `get_by_id` raises `SandboxNotFoundError`, so cleanup and the
    reaper would silently skip a real hogbox and leak it. The persisted `sandbox_backend`
    (see get_task_processing_context) is the authoritative signal for behavioral branches;
    this prefix is a routing convenience checked against hogland's enforced id shape.
    """
    if sandbox_id.startswith(HOGLAND_SANDBOX_ID_PREFIX):
        return _get_hogland_sandbox_class()
    return get_sandbox_class()


if TYPE_CHECKING:
    # Declared for type-checkers only; resolved at runtime by __getattr__ -> get_sandbox_class().
    Sandbox: SandboxClass
else:

    def __getattr__(name: str) -> object:
        # Resolve `Sandbox` lazily. Computing it at import time calls get_sandbox_class(),
        # which for the docker / local Modal providers imports a sibling module
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
