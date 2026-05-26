from __future__ import annotations

import os
import json
import uuid
import shlex
import logging
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

from django.conf import settings

from hogland import (
    APIError,
    ExecEvent,
    Hogbox,
    Hogland,
    NotFoundError,
    ServerError as HoglandServerError,
    ValidationError,
)

from posthog.exceptions_capture import capture_exception

from products.tasks.backend.services.sandbox import (
    AgentServerResult,
    ExecutionResult,
    ExecutionStream,
    SandboxBase,
    SandboxConfig,
    SandboxStatus,
    SandboxTemplate,
    build_agent_runtime_env_prefix,
    redact_sandbox_command,
    wait_for_health_check,
)
from products.tasks.backend.temporal.exceptions import (
    SandboxCleanupError,
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxProvisionError,
    SandboxTimeoutError,
    SnapshotCreationError,
)

if TYPE_CHECKING:
    from products.tasks.backend.temporal.process_task.utils import McpServerConfig

logger = logging.getLogger(__name__)

# Where we drop KEY=value lines for the agent server to source on startup
# (and on snapshot-resume token refreshes).
ENV_FILE_PATH = "/etc/hogbox-env"

# Agent-server HTTP port — matches Modal's expectation; the proxy URL we
# hand the consumer back tunnels into this port.
AGENT_SERVER_PORT = 8080

# Snapshot-alias map: server-side aliases need to exist (creatable via
# `hogland snapshot alias create posthog-tasks-<x> <snap-id>` after baking
# the base image). Falling back to `None` lets the hogland server pick the
# kind's default snapshot.
TEMPLATE_TO_SNAPSHOT_ALIAS: dict[SandboxTemplate, str] = {
    SandboxTemplate.DEFAULT_BASE: "alias:posthog-tasks-default",
    SandboxTemplate.NOTEBOOK_BASE: "alias:posthog-tasks-notebook",
    SandboxTemplate.PI_BASE: "alias:posthog-tasks-pi",
}

HOGLAND_KIND = "posthog-tasks"


def _render_env_file(env: dict[str, str]) -> str:
    """Render an env dict to `export KEY="value"` lines for `source`-ing."""
    lines = [f"export {k}={shlex.quote(v)}" for k, v in sorted(env.items())]
    return "\n".join(lines) + "\n"


def _resolve_snapshot(config: SandboxConfig) -> str | None:
    """Pick the right snapshot id for `Hogland.create`.

    Precedence: explicit `snapshot_id` (resolved upstream from the Django
    record) → `snapshot_external_id` (already a hogland id) → template
    alias → None (server picks the default).
    """
    if config.snapshot_id:
        return config.snapshot_id
    if config.snapshot_external_id:
        return config.snapshot_external_id
    return TEMPLATE_TO_SNAPSHOT_ALIAS.get(config.template)


def _translate_error(err: APIError, action: str, sandbox_id: str | None = None) -> Exception:
    """Map a hogland APIError to the PostHog exception tree."""
    context: dict[str, str] = {"action": action, "error": str(err)}
    if sandbox_id is not None:
        context["sandbox_id"] = sandbox_id
    if isinstance(err, NotFoundError):
        return SandboxNotFoundError(f"hogbox not found during {action}", context, cause=err)
    if isinstance(err, ValidationError):
        return SandboxExecutionError(f"hogbox rejected {action}", context, cause=err)
    if isinstance(err, HoglandServerError):
        return SandboxExecutionError(f"hogbox server error during {action}", context, cause=err)
    return SandboxExecutionError(f"hogbox call failed during {action}", context, cause=err)


# Where AWS EKS / GKE / standard k8s projects the service-account JWT.
# Used by the OIDC-on-EKS auth path once hogland trust-mapping lands.
_K8S_SA_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"


def _get_hog_token() -> str | None:
    """Fetch the hogland bearer token at call time, not at import.

    Today: read `HOG_TOKEN` from env (Path 1 — single bearer per caller).
    Tomorrow: when EKS OIDC + TrustMapping lands, swap the body to read
    the projected K8s SA token from `_K8S_SA_TOKEN_PATH` and hand that to
    hogplane. This is intentionally the single seam — callers downstream
    never see the credential shape.
    """
    token = os.environ.get("HOG_TOKEN")
    if token:
        return token
    # Forward-compat: if no env token but the pod has a projected SA
    # token mounted, use it. Once hogland's TrustMapping exists for the
    # `posthog-sandboxes` SA, this path becomes the default and the env
    # branch above goes away.
    sa_token_path = Path(_K8S_SA_TOKEN_PATH)
    if sa_token_path.exists():
        return sa_token_path.read_text(encoding="utf-8").strip() or None
    return None


def _get_hog_host() -> str | None:
    """Resolve the hogland endpoint at call time.

    Single source of truth: `settings.HOGLAND_API_URL` (env var
    `HOGLAND_API_URL`). The SDK also reads `HOG_HOST` from env directly,
    so passing `None` here lets the SDK fall back to its built-in default.
    Region routing (eu-west / us-east) would layer on top of this.
    """
    return getattr(settings, "HOGLAND_API_URL", None) or os.environ.get("HOG_HOST") or None


def _build_client() -> Hogland:
    """Build a Hogland client with credentials fetched at call time.

    Both token and host are fetched per-call so swapping to OIDC, or
    flipping the API host mid-deploy, is a one-line change in
    `_get_hog_token` / `_get_hog_host` with no integration-site refactor.
    """
    return Hogland(token=_get_hog_token(), base_url=_get_hog_host())


class _HoglandExecutionStream:
    """Wraps hogland's SSE exec_stream to satisfy ExecutionStream.

    PostHog's ExecutionStream exposes `iter_stdout()` (stdout-only
    iterator) + `wait() -> ExecutionResult` (final result with stderr
    accumulated and exit code). Hogland yields stdout, stderr, and exit
    events interleaved on a single SSE stream, so we buffer stderr as we
    go and surface it in `wait()`.
    """

    _STDERR_CAP = 1 << 20  # 1 MiB — mirrors hogland's server-side stderr cap

    def __init__(self, source: Iterable[ExecEvent]) -> None:
        self._source: Iterator[ExecEvent] = iter(source)
        self._stderr_buf: list[str] = []
        self._stderr_bytes = 0
        self._exit_code: int | None = None
        self._drained = False

    def _record_stderr(self, chunk: str) -> None:
        remaining = self._STDERR_CAP - self._stderr_bytes
        if remaining <= 0:
            return
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
        self._stderr_buf.append(chunk)
        self._stderr_bytes += len(chunk)

    def iter_stdout(self) -> Iterator[str]:
        for event in self._source:
            if event.kind == "stdout":
                yield event.data
            elif event.kind == "stderr":
                self._record_stderr(event.data)
            elif event.kind == "exit":
                self._exit_code = event.exit_code
                break
        self._drained = True

    def wait(self) -> ExecutionResult:
        if not self._drained:
            for event in self._source:
                if event.kind == "stderr":
                    self._record_stderr(event.data)
                elif event.kind == "exit":
                    self._exit_code = event.exit_code
                    break
            self._drained = True
        return ExecutionResult(
            stdout="",
            stderr="".join(self._stderr_buf),
            exit_code=self._exit_code if self._exit_code is not None else -1,
            error=None,
        )


class HoglandSandbox(SandboxBase):
    """SandboxBase implementation backed by hogland's HTTP API.

    Mirrors `ModalSandbox` — same lifecycle, same exception surface,
    same agent-server port. Differences vs Modal documented inline.
    """

    id: str
    config: SandboxConfig

    def __init__(self, client: Hogland, box: Hogbox, config: SandboxConfig) -> None:
        self._client = client
        self._box = box
        self._sandbox_url: str | None = None
        self.id = box.id
        self.config = config

    # ---- factory methods -------------------------------------------------

    @classmethod
    def create(cls, config: SandboxConfig) -> HoglandSandbox:
        client = _build_client()
        snapshot_id = _resolve_snapshot(config)
        sandbox_name = f"{config.name}-{uuid.uuid4().hex[:6]}" if config.name else None

        # TTL is not yet on hogland's BoxSpec — we rely on the cleanup
        # activity calling destroy(). The audit doc acknowledges this gap.
        bootstrap = _render_env_file(config.environment_variables) if config.environment_variables else None

        try:
            box = client.create(
                cpus=float(config.cpu_cores),
                memory_mib=int(config.memory_gb * 1024),
                disk_gib=int(config.disk_size_gb),
                snapshot_id=snapshot_id,
                bootstrap=bootstrap,
                name=sandbox_name,
                tags=[f"{k}={v}" for k, v in (config.metadata or {}).items()] or None,
                kind=HOGLAND_KIND,
            )
        except APIError as err:
            capture_exception(err)
            logger.exception("Failed to create hogbox sandbox")
            raise SandboxProvisionError(
                "Failed to create sandbox",
                {"config_name": config.name, "error": str(err)},
                cause=err,
            ) from err

        logger.info(f"Created hogbox sandbox {box.id} for {config.name}")
        return cls(client=client, box=box, config=config)

    @staticmethod
    def get_by_id(sandbox_id: str) -> HoglandSandbox:
        client = _build_client()
        try:
            box = client.get(sandbox_id)
        except NotFoundError as err:
            raise SandboxNotFoundError(
                f"Hogbox sandbox {sandbox_id} not found",
                {"sandbox_id": sandbox_id, "error": str(err)},
                cause=err,
            ) from err
        except APIError as err:
            raise _translate_error(err, "get_by_id", sandbox_id) from err

        # Reconstruct a minimal SandboxConfig from the cached view so
        # `self.config` is meaningful after re-attach. Fields we can't
        # recover (template, ttl) stay as their defaults.
        spec = box.view.spec
        config = SandboxConfig(
            name=spec.name or f"sandbox-{sandbox_id}",
            cpu_cores=float(spec.cpus) if spec.cpus else 4,
            memory_gb=float(spec.memory_mib) / 1024 if spec.memory_mib else 16,
            disk_size_gb=float(spec.disk_gib) if spec.disk_gib else 64,
        )
        return HoglandSandbox(client=client, box=box, config=config)

    @staticmethod
    def delete_snapshot(external_id: str) -> None:
        # No-op — matches ModalSandbox. Hogland snapshots are owned by
        # the OwnerID Principal and reaped by their lifecycle.
        logger.info(f"Snapshot {external_id} marked for cleanup (hogland reaps on lifecycle)")

    # ---- lifecycle -------------------------------------------------------

    @property
    def sandbox_url(self) -> str | None:
        """The agent-server URL, cached after `get_connect_credentials`."""
        return self._sandbox_url

    def get_status(self) -> SandboxStatus:
        try:
            self._box.refresh()
        except NotFoundError:
            return SandboxStatus.SHUTDOWN
        except APIError as err:
            raise _translate_error(err, "get_status", self.id) from err
        return SandboxStatus.RUNNING if self._box.is_running() else SandboxStatus.SHUTDOWN

    def is_running(self) -> bool:
        return self.get_status() == SandboxStatus.RUNNING

    def destroy(self) -> None:
        try:
            self._box.destroy()
            logger.info(f"Destroyed hogbox sandbox {self.id}")
        except APIError as err:
            logger.exception("Failed to destroy hogbox sandbox")
            raise SandboxCleanupError(
                f"Failed to destroy sandbox: {err}",
                {"sandbox_id": self.id, "error": str(err)},
                cause=err,
            ) from err
        finally:
            self._client.close()

    # ---- exec ------------------------------------------------------------

    def execute(self, command: str, timeout_seconds: int | None = None) -> ExecutionResult:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        timeout = timeout_seconds if timeout_seconds is not None else self.config.default_execution_timeout_seconds
        redacted_command = redact_sandbox_command(command)

        try:
            result = self._box.exec(["bash", "-c", command], timeout_seconds=timeout)
        except APIError as err:
            redacted_error = redact_sandbox_command(str(err))
            logger.error(  # noqa: TRY400
                "Failed to execute command",
                extra={"sandbox_id": self.id, "redacted_error": redacted_error},
            )
            raise SandboxExecutionError(
                "Failed to execute command",
                {"sandbox_id": self.id, "command": redacted_command, "error": redacted_error},
                cause=err,
            ) from err

        if result.timed_out:
            raise SandboxTimeoutError(
                f"Execution timed out after {timeout} seconds",
                {"sandbox_id": self.id, "timeout_seconds": timeout, "command": redacted_command},
                cause=TimeoutError(f"hogbox exec timed out: {redacted_command}"),
            )

        return ExecutionResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            error=None,
        )

    def execute_stream(self, command: str, timeout_seconds: int | None = None) -> ExecutionStream:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        timeout = timeout_seconds if timeout_seconds is not None else self.config.default_execution_timeout_seconds
        redacted_command = redact_sandbox_command(command)

        try:
            source = self._box.exec_stream(["bash", "-c", command], timeout_seconds=timeout)
        except APIError as err:
            redacted_error = redact_sandbox_command(str(err))
            logger.error(  # noqa: TRY400
                "Failed to start streaming exec",
                extra={"sandbox_id": self.id, "redacted_error": redacted_error},
            )
            raise SandboxExecutionError(
                "Failed to execute command",
                {"sandbox_id": self.id, "command": redacted_command, "error": redacted_error},
                cause=err,
            ) from err

        return _HoglandExecutionStream(source)

    # ---- files -----------------------------------------------------------

    def write_file(self, path: str, payload: bytes) -> ExecutionResult:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        try:
            self._box.write_file(path, payload, mkdir=True)
        except APIError as err:
            capture_exception(err)
            logger.exception(f"Failed to write file to hogbox sandbox: {err}")
            raise SandboxExecutionError(
                "Failed to write file",
                {"sandbox_id": self.id, "path": path, "error": str(err)},
                cause=err,
            ) from err

        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    # ---- repo / task helpers --------------------------------------------

    def setup_repository(self, repository: str) -> ExecutionResult:
        """No-op: Repository setup is now handled by agent-server."""
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def is_git_clean(self, repository: str) -> tuple[bool, str]:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        result = self.execute(f"cd {shlex.quote(repo_path)} && git status --porcelain")
        is_clean = not result.stdout.strip()
        return is_clean, result.stdout

    def execute_task(
        self,
        task_id: str,
        run_id: str,
        repository: str | None = None,
        create_pr: bool = True,
    ) -> ExecutionResult:
        """No-op: Task execution is now handled by agent-server."""
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    # ---- agent-server credentials & boot --------------------------------

    def get_connect_credentials(self) -> AgentServerResult:
        """Return the URL + bearer the consumer hits the agent-server with.

        Hogland's auth model is single-credential: there is no per-tunnel
        token (see hogland's docs/AUTH_PLAN.md). The proxy URL tunnels
        into the agent-server port, authenticated with the same bearer
        the SDK is already using.
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        url = self._box.proxy_url(AGENT_SERVER_PORT)
        self._sandbox_url = url
        logger.info(f"Got connect credentials for hogbox sandbox {self.id}: {url}")
        return AgentServerResult(url=url, token=self._client.token)

    def _build_agent_server_command(
        self,
        repo_path: str | None,
        task_id: str,
        run_id: str,
        mode: str,
        create_pr: bool,
        interaction_origin: str | None = None,
        branch: str | None = None,
        runtime_adapter: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        mcp_servers_arg: str = "",
        allowed_domains: list[str] | None = None,
        event_ingest_token: str | None = None,
    ) -> str:
        env_prefix = build_agent_runtime_env_prefix(
            interaction_origin=interaction_origin,
            runtime_adapter=runtime_adapter,
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            event_ingest_token=event_ingest_token,
        )
        create_pr_flag = f" --createPr {shlex.quote('true' if create_pr else 'false')}"
        repo_flag = f" --repositoryPath {shlex.quote(repo_path)}" if repo_path else ""
        branch_flag = f" --baseBranch {shlex.quote(branch)}" if branch else ""
        domains_flag = f" --allowedDomains {shlex.quote(','.join(allowed_domains))}" if allowed_domains else ""
        server_cmd = (
            f"{env_prefix}./node_modules/.bin/agent-server --port {AGENT_SERVER_PORT}{repo_flag} "
            f"--taskId {shlex.quote(task_id)} --runId {shlex.quote(run_id)} --mode {shlex.quote(mode)}"
            f"{create_pr_flag}{branch_flag}{mcp_servers_arg}{domains_flag}"
        )
        return f"cd /scripts && nohup {server_cmd} > /tmp/agent-server.log 2>&1 &"

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
    ) -> None:
        """Boot the agent-server inside the hogbox and wait for it to be healthy."""
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        repo_path: str | None = None
        if repository:
            org, repo = repository.lower().split("/")
            repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        # agentsh policy plumbing for hogland is not yet defined — when
        # `allowed_domains` is set, the agent-server still gets the flag
        # for self-policing but we skip the host-side agentsh daemon.
        # TODO(hogland): wire hogland-side egress policy once available.

        mcp_servers_arg = ""
        if mcp_configs:
            mcp_json = json.dumps([c.to_dict() for c in mcp_configs])
            mcp_servers_arg = f" --mcpServers {shlex.quote(mcp_json)}"

        command = self._build_agent_server_command(
            repo_path,
            task_id,
            run_id,
            mode,
            create_pr,
            interaction_origin,
            branch,
            runtime_adapter,
            provider,
            model,
            reasoning_effort,
            mcp_servers_arg,
            allowed_domains=allowed_domains,
            event_ingest_token=event_ingest_token,
        )

        logger.info(f"Starting agent-server in hogbox sandbox {self.id} for {repository or 'no-repo'}")
        launch = self.execute(command, timeout_seconds=30)
        if launch.exit_code != 0:
            raise SandboxExecutionError(
                "Agent-server failed to launch",
                {"sandbox_id": self.id, "stderr": launch.stderr, "stdout": launch.stdout},
                cause=RuntimeError(launch.stderr or "non-zero exit launching agent-server"),
            )

        if not wait_for_health_check(self.execute, self.id, AGENT_SERVER_PORT):
            log_result = self.execute(
                "cat /tmp/agent-server.log 2>/dev/null || echo 'No log file'",
                timeout_seconds=5,
            )
            raise SandboxExecutionError(
                "Agent-server failed to start",
                {"sandbox_id": self.id, "log": log_result.stdout},
                cause=RuntimeError("Health check failed after retries"),
            )

        logger.info(f"Agent-server started in hogbox sandbox {self.id}")

    # ---- snapshots -------------------------------------------------------

    def create_snapshot(self) -> str:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        # Mirror Modal's pre-snapshot sync exec — surfaces "dead process
        # tree" before we burn a snapshot on it. Hogland's pause-then-
        # snapshot makes the FS-readiness aspect unnecessary, but the
        # liveness check is cheap and worth keeping.
        try:
            self._box.exec(["true"], timeout_seconds=30)
            record = self._box.snapshot()
        except APIError as err:
            logger.exception("Failed to create hogbox snapshot")
            raise SnapshotCreationError(
                f"Failed to create snapshot: {err}",
                {"sandbox_id": self.id, "error": str(err)},
                cause=err,
            ) from err

        logger.info(f"Created snapshot for hogbox sandbox {self.id}, snapshot ID: {record.id}")
        return record.id

    # ---- env-var refresh (snapshot resume) ------------------------------

    def update_environment_variables(self, env: dict[str, str]) -> None:
        """Overwrite the in-box env file used by the agent-server.

        Called after a snapshot restore so fresh GITHUB_TOKEN / POSTHOG_*
        values replace the stale ones baked into the snapshot. The
        agent-server is expected to re-source the file on (re)start.
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")
        try:
            self._box.write_file(ENV_FILE_PATH, _render_env_file(env).encode(), mode="0600", mkdir=False)
        except APIError as err:
            raise _translate_error(err, "update_environment_variables", self.id) from err

    @property
    def name(self) -> str:
        return self.config.name


__all__ = ["HoglandSandbox"]
