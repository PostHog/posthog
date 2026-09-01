"""Hogland-backed sandbox provider.

Hogland is PostHog's Firecracker microVM service. A hogbox boots from a golden
snapshot (alias ``posthog-tasks-default``) baked from the same layout as the Modal
base image, so the shared ``AgentServerLaunchMixin`` drives it unchanged: repo
clone, agent-server launch, and health checks are all bash over ``execute``.

Transport differences from Modal, handled by the callers that read
``TaskRun.state``:
- the agent-server is reached through hogplane's authenticated proxy
  (``/v1/hogboxes/<id>/proxy/8080``), authenticated with the backend's hogland
  bearer as a ``?token=`` query param — never a per-sandbox token, so
  ``get_connect_credentials`` deliberately returns ``token=None`` and nothing
  secret lands in ``TaskRun.state``;
- resume snapshots are not supported yet — every run cold-boots from the golden
  snapshot.
"""

from __future__ import annotations

import time
import uuid
import shlex
import logging
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

from django.conf import settings

import httpx
from hogland import APIError, ExecEvent, Hogbox, Hogland, NotFoundError

from products.tasks.backend.exceptions import (
    SandboxCleanupError,
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxNotRunningError,
    SandboxProvisionError,
    SandboxTimeoutError,
    SnapshotCreationError,
)
from products.tasks.backend.logic.services.agent_server_launcher import AGENT_SERVER_PORT, AgentServerLaunchMixin
from products.tasks.backend.logic.services.agentsh import AGENTSH_DAEMON_PORT
from products.tasks.backend.logic.services.cpu_billing import (
    CPU_BILLING_STATE_PATH,
    build_sampler_start_command,
    compute_billed_cpu_usage_usec,
    parse_cpu_stat_usage_usec,
)
from products.tasks.backend.logic.services.sandbox import redact_sandbox_command
from products.tasks.backend.logic.services.sandbox_config import BURSTABLE_REQUEST_CPU_CORES

from .sandbox import AgentServerResult, ExecutionResult, ExecutionStream, SandboxConfig, SandboxStatus, SandboxTemplate

logger = logging.getLogger(__name__)

# "agent" is a registered hogland kind (1h idle-TTL default) for API-driven
# LLM sandbox runs — exactly this workload. Using it rather than an unregistered
# kind means a call site that ever omits ttl_seconds inherits a safe default
# instead of minting an immortal box.
HOGLAND_TASKS_BOX_KIND = "agent"

# Every template hogland supports maps to a global snapshot alias baked in CI
# (the tasks golden-snapshot workflow). Only the plain default-template run is routed
# to hogland; anything else stays on Modal (see get_task_processing_context).
TEMPLATE_TO_SNAPSHOT_ALIAS: dict[SandboxTemplate, str] = {
    SandboxTemplate.DEFAULT_BASE: "alias:posthog-tasks-default",
}

# The golden snapshot (baked in CI) pins this machine shape. A hogland
# restore must inherit-or-match it, so per-task overrides are ignored and the provisioned
# box is always this size. Keep in sync with the shape the CI golden bake boots at.
HOGLAND_GOLDEN_CPU_CORES = 4.0
HOGLAND_GOLDEN_MEMORY_GB = 16.0
HOGLAND_GOLDEN_DISK_GB = 64.0

# `create()` blocks until the box is running; a cold boot on a fresh Karpenter node
# can take minutes, and `exec` calls legitimately run up to the caller's
# timeout_seconds (default 10 minutes). One generous read timeout covers both —
# the server enforces the real per-call budgets.
_HTTP_TIMEOUT = httpx.Timeout(30 * 60, connect=15)

# Static container env the Modal image carries as Dockerfile ENVs. The golden image
# bakes them into /etc/environment too; passing them per-box keeps a restore that
# predates a bake change consistent with this backend.
_STATIC_BOX_ENV = {
    "IS_SANDBOX": "1",
    "GH_TELEMETRY": "false",
    "PYTHONPATH": "/tmp/workspace",
    "AGENTSH_SERVER": f"http://127.0.0.1:{AGENTSH_DAEMON_PORT}",
    # Guards in /opt/posthog/bin must shadow the real git/gh.
    "PATH": "/opt/posthog/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
}


@lru_cache(maxsize=4)
def _cached_client(base_url: str, token: str) -> Hogland:
    return Hogland(token=token, base_url=base_url, timeout=_HTTP_TIMEOUT)


def _read_token_file() -> str | None:
    path = settings.HOGLAND_API_TOKEN_FILE
    if not path:
        return None
    try:
        token = Path(path).read_text().strip()
    except OSError:
        logger.warning(
            "Hogland token file is set but unreadable; falling back to the static token", extra={"path": path}
        )
        return None
    return token or None


def get_hogland_api_token() -> str | None:
    """Current control-plane bearer, preferring the projected ServiceAccount token file.

    The file carries a rotating JWT, so it is re-read on every call; the static
    HOGLAND_API_TOKEN is the local-dev/bake fallback.
    """
    return _read_token_file() or settings.HOGLAND_API_TOKEN


def get_hogland_client() -> Hogland:
    base_url = settings.HOGLAND_API_URL
    file_token = _read_token_file()
    if base_url and file_token:
        # SDK 0.3.x binds the token at construction, so a cached client would keep a
        # rotated-out JWT and 401. Build a fresh client per call until the SDK ships
        # Hogland.from_token_file with per-request re-reads; then this collapses to a
        # cached Hogland.from_token_file(...) client.
        return Hogland(token=file_token, base_url=base_url, timeout=_HTTP_TIMEOUT)
    token = settings.HOGLAND_API_TOKEN
    if not base_url or not token:
        raise SandboxProvisionError(
            "Hogland sandbox backend is not configured",
            {"missing": "HOGLAND_API_URL/HOGLAND_API_TOKEN_FILE/HOGLAND_API_TOKEN"},
            cause=RuntimeError("HOGLAND_API_URL and a hogland token (file or static) must both be set"),
        )
    return _cached_client(base_url, token)


class _HogboxExecutionStream:
    """Adapts the SDK's SSE exec stream to the ExecutionStream protocol."""

    def __init__(self, events: Iterable[ExecEvent]):
        self._events = iter(events)
        self._stdout_chunks: list[str] = []
        self._stderr_chunks: list[str] = []
        self._exit_code: int | None = None

    def _consume(self, event: ExecEvent) -> str | None:
        if event.kind == "stdout":
            self._stdout_chunks.append(event.data)
            return event.data
        if event.kind == "stderr":
            self._stderr_chunks.append(event.data)
        elif event.kind == "exit":
            self._exit_code = event.exit_code
        return None

    def iter_stdout(self) -> Iterable[str]:
        for event in self._events:
            chunk = self._consume(event)
            if chunk is not None:
                yield chunk

    def wait(self) -> ExecutionResult:
        for event in self._events:
            self._consume(event)
        return ExecutionResult(
            stdout="".join(self._stdout_chunks),
            stderr="".join(self._stderr_chunks),
            # -1 mirrors the server's "killed before reporting" sentinel for a
            # stream that ended without an exit frame.
            exit_code=self._exit_code if self._exit_code is not None else -1,
            error=None,
        )


class HoglandSandbox(AgentServerLaunchMixin):
    """Firecracker sandbox on hogland. A box on our own metal."""

    id: str
    config: SandboxConfig
    _box: Hogbox
    _sandbox_url: str | None

    def __init__(self, box: Hogbox, config: SandboxConfig, sandbox_url: str | None = None):
        self.id = box.id
        self.config = config
        self._box = box
        self._sandbox_url = sandbox_url

    @property
    def sandbox_url(self) -> str | None:
        return self._sandbox_url

    @classmethod
    def create(cls, config: SandboxConfig) -> HoglandSandbox:
        snapshot_alias = TEMPLATE_TO_SNAPSHOT_ALIAS.get(config.template)
        if snapshot_alias is None:
            raise SandboxProvisionError(
                "Template is not supported on the hogland backend",
                {"config_name": config.name, "template": config.template.value},
                cause=RuntimeError(f"no hogland golden snapshot for template {config.template.value}"),
            )
        if config.snapshot_id or config.snapshot_external_id:
            # Backend resolution forces resume snapshots off for hogland runs; if an id
            # slips through anyway, cold-boot loudly rather than restoring the wrong thing.
            logger.warning(
                "Hogland backend ignores resume snapshot; cold-booting from the golden image",
                extra={"snapshot_id": config.snapshot_id, "snapshot_external_id": config.snapshot_external_id},
            )
        config.snapshot_restored = False
        config.image_fallback = None

        env = {**_STATIC_BOX_ENV, **(config.environment_variables or {})}
        tags = [f"{key}={value}" for key, value in (config.metadata or {}).items()]

        try:
            client = get_hogland_client()
            box = client.create(
                # cpus/memory_mib/disk_gib deliberately omitted: a snapshot restore must
                # inherit the golden snapshot's machine config (a mismatch is a 400).
                # Per-task resource overrides are therefore unsupported on hogland.
                snapshot_id=snapshot_alias,
                # Explicit and defensive: a restore inherits the snapshot's access_type,
                # and the key-less golden bake is stamped "none", so task boxes already
                # restore as "none". Passing it here just pins that intent. Note "none"
                # still allocates a port + DNAT, so it does not remove ingress; the box is
                # driven via exec / files / proxy regardless.
                access_type="none",
                # Non-empty names must be unique per owner; suffix like the Modal backend.
                name=f"{config.name}-{uuid.uuid4().hex[:6]}"[:64],
                kind=HOGLAND_TASKS_BOX_KIND,
                # Always explicit: an unregistered kind carries no server-side TTL
                # default, and an omitted value would make the box immortal.
                ttl_seconds=config.ttl_seconds,
                env=env,
                tags=tags or None,
            )
        except APIError as e:
            raise SandboxProvisionError(
                "Failed to create hogland sandbox",
                {"config_name": config.name, "status_code": str(e.status_code), "error": str(e)},
                cause=e,
            )
        except SandboxProvisionError:
            raise
        except Exception as e:
            raise SandboxProvisionError(
                "Failed to create hogland sandbox", {"config_name": config.name, "error": str(e)}, cause=e
            )

        if (config.cpu_cores, config.memory_gb, config.disk_size_gb) != (
            HOGLAND_GOLDEN_CPU_CORES,
            HOGLAND_GOLDEN_MEMORY_GB,
            HOGLAND_GOLDEN_DISK_GB,
        ):
            logger.info(
                "Hogland sandbox ignores per-task resource overrides; using the golden snapshot's machine config",
                extra={"sandbox_id": box.id, "cpu_cores": config.cpu_cores, "memory_gb": config.memory_gb},
            )
        # Price the usage ledger on the shape the box actually delivered, read back from
        # the box spec, not the requested golden constants. A restored box always reports a
        # concrete machine shape (snapshot defaults + inheritance), so a golden snapshot
        # rebaked at a different shape flows through here instead of desyncing every ledger
        # row against a pinned constant.
        spec = box.view.spec
        if spec.cpus is None or spec.memory_mib is None or spec.disk_gib is None:
            raise SandboxProvisionError(
                "Hogland box spec is missing a machine dimension",
                {"config_name": config.name, "sandbox_id": box.id},
                cause=RuntimeError(f"incomplete box spec for {box.id}"),
            )
        config.cpu_cores = spec.cpus
        config.memory_gb = spec.memory_mib / 1024
        config.disk_size_gb = float(spec.disk_gib)

        logger.info(f"Created hogland sandbox {box.id} for {config.name}")
        return cls(box=box, config=config)

    @staticmethod
    def get_by_id(sandbox_id: str) -> HoglandSandbox:
        try:
            box = get_hogland_client().get(sandbox_id)
        except NotFoundError as e:
            raise SandboxNotFoundError(
                f"Sandbox {sandbox_id} not found", {"sandbox_id": sandbox_id, "error": str(e)}, cause=e
            )
        except Exception as e:
            logger.exception(f"Failed to retrieve hogland sandbox {sandbox_id}: {e}")
            raise SandboxNotFoundError(
                f"Sandbox {sandbox_id} not found", {"sandbox_id": sandbox_id, "error": str(e)}, cause=e
            )
        config = SandboxConfig(name=box.view.spec.name or f"sandbox-{sandbox_id}")
        return HoglandSandbox(box=box, config=config)

    def get_status(self) -> SandboxStatus:
        try:
            self._box.refresh()
        except NotFoundError:
            return SandboxStatus.SHUTDOWN
        return SandboxStatus.RUNNING if self._box.status == "running" else SandboxStatus.SHUTDOWN

    def is_running(self) -> bool:
        return self.get_status() == SandboxStatus.RUNNING

    def execute(
        self, command: str, timeout_seconds: int | None = None, env: dict[str, str] | None = None
    ) -> ExecutionResult:
        if not self.is_running():
            raise SandboxNotRunningError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        if timeout_seconds is None:
            timeout_seconds = self.config.default_execution_timeout_seconds

        redacted_command = redact_sandbox_command(command)
        try:
            result = self._box.exec(["bash", "-c", command], timeout_seconds=timeout_seconds, env=env)
        except Exception as e:
            redacted_error = redact_sandbox_command(str(e))
            # Provider exceptions can echo the shell command, so avoid exc_info here.
            logger.error(  # noqa: TRY400
                "Failed to execute command", extra={"sandbox_id": self.id, "redacted_error": redacted_error}
            )
            raise SandboxExecutionError(
                "Failed to execute command",
                {"sandbox_id": self.id, "command": redacted_command, "error": redacted_error},
                cause=RuntimeError(redacted_error),
            )

        if result.timed_out:
            raise SandboxTimeoutError(
                f"Execution timed out after {timeout_seconds} seconds",
                {"sandbox_id": self.id, "timeout_seconds": timeout_seconds},
                cause=RuntimeError(f"exec timed out after {timeout_seconds}s"),
            )

        return ExecutionResult(stdout=result.stdout, stderr=result.stderr, exit_code=result.exit_code, error=None)

    def execute_stream(self, command: str, timeout_seconds: int | None = None) -> ExecutionStream:
        if not self.is_running():
            raise SandboxNotRunningError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        if timeout_seconds is None:
            timeout_seconds = self.config.default_execution_timeout_seconds

        events = self._box.exec_stream(["bash", "-c", command], timeout_seconds=timeout_seconds)
        return _HogboxExecutionStream(events)

    def write_file(self, path: str, payload: bytes, timeout_seconds: int | None = None) -> ExecutionResult:
        if not self.is_running():
            raise SandboxNotRunningError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )
        try:
            # The server writes via tmp + rename, so this matches the Modal
            # backend's temp-file + mv atomicity.
            self._box.write_file(path, payload, mkdir=True)
        except Exception as e:
            logger.exception(f"Failed to write file to sandbox: {e}")
            raise SandboxExecutionError(
                "Failed to write file",
                {"sandbox_id": self.id, "path": path, "error": str(e)},
                cause=e,
            )
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def get_connect_credentials(self) -> AgentServerResult:
        """URL of the agent-server behind hogplane's box proxy.

        There is no per-sandbox token: the proxy authenticates with the backend's
        hogland bearer, which callers attach at request time (never persisted in
        ``TaskRun.state``) — see ``agent_command.sandbox_transport_token``.
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        self._sandbox_url = self._box.proxy_url(AGENT_SERVER_PORT).rstrip("/")
        logger.info(f"Got connect credentials for sandbox {self.id}: {self._sandbox_url}")
        return AgentServerResult(url=self._sandbox_url, token=None)

    def create_preview_connect_credentials(self, port: int, user_metadata: dict[str, Any]) -> AgentServerResult:
        raise NotImplementedError("Hogland sandboxes do not support preview connect tokens")

    def setup_repository(self, repository: str) -> ExecutionResult:
        """No-op: repository setup is handled by agent-server."""
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def is_git_clean(self, repository: str) -> tuple[bool, str]:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        result = self.execute(f"cd {shlex.quote(repo_path)} && git status --porcelain")
        return not result.stdout.strip(), result.stdout

    def execute_task(
        self, task_id: str, run_id: str, repository: str | None = None, create_pr: bool = True
    ) -> ExecutionResult:
        """No-op: task execution is handled by agent-server."""
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def create_snapshot(self, *, timeout_seconds: int | None = None) -> str:
        raise SnapshotCreationError(
            "Resume snapshots are not supported on the hogland backend yet",
            {"sandbox_id": self.id},
            cause=NotImplementedError("hogland resume snapshots"),
        )

    def create_directory_snapshot(self, path: str) -> str:
        raise SnapshotCreationError(
            "Resume snapshots are not supported on the hogland backend yet",
            {"sandbox_id": self.id, "path": path},
            cause=NotImplementedError("hogland resume snapshots"),
        )

    def prune_snapshot_heavy_dirs(self, path: str) -> None:
        """No-op: hogland snapshots are block-level and have no file-count cap."""

    def read_cpu_usage_usec(self) -> int | None:
        # Must go through exec: hogpanion's file endpoint sets Content-Length from
        # stat(), and sysfs files stat as size 0, so read_file returns an empty body.
        result = self.execute("cat /sys/fs/cgroup/cpu.stat", timeout_seconds=10)
        if result.exit_code != 0:
            return None
        return parse_cpu_stat_usage_usec(result.stdout)

    def _cpu_billing_request_cores(self) -> float:
        # Hogland reserves request == limit, so its own billing floor would be the full
        # box. Running the sampler with Modal's default burstable floor instead makes
        # provider_billed_* mean "what Modal would have billed this same workload" —
        # the like-for-like number the platform cost comparison needs. Fixed constant
        # rather than config so a get_by_id-synthesized config reads the same floor.
        return BURSTABLE_REQUEST_CPU_CORES

    def start_cpu_billing_sampler(self) -> bool:
        result = self.execute(build_sampler_start_command(self._cpu_billing_request_cores()), timeout_seconds=10)
        return result.exit_code == 0

    def read_billed_cpu_usage_usec(self) -> int | None:
        try:
            # The state file is a regular file, so read_file works here.
            state_text = self._box.read_file(CPU_BILLING_STATE_PATH).decode()
        except Exception:
            return None
        current_cpu = self.read_cpu_usage_usec()
        if current_cpu is None:
            return None
        return compute_billed_cpu_usage_usec(state_text, current_cpu, self._cpu_billing_request_cores(), time.time_ns())

    @staticmethod
    def delete_snapshot(external_id: str) -> None:
        logger.info(f"Ignoring delete for hogland snapshot {external_id}; hogland snapshots are unreachable in MVP")

    def destroy(self) -> None:
        try:
            self._box.delete()
            logger.info(f"Destroyed hogland sandbox {self.id}")
        except Exception as e:
            logger.exception(f"Failed to destroy sandbox: {e}")
            raise SandboxCleanupError(
                f"Failed to destroy sandbox: {e}", {"sandbox_id": self.id, "error": str(e)}, cause=e
            )

    @property
    def name(self) -> str:
        return self.config.name
