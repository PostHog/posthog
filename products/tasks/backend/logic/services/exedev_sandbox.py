"""
exe.dev-backed sandbox provider.

Implements the SandboxBase contract against exe.dev VMs, driving the full
lifecycle through the exe.dev HTTPS gateway (`POST /exec`) instead of a
provider SDK. Selected with SANDBOX_PROVIDER=exedev and configured via:

  SANDBOX_EXEDEV_IMAGE             Docker reference pre-loaded with the PostHog
                                   agent-server installed at /scripts (required).
  SANDBOX_EXEDEV_API_TOKEN         Scoped exe.dev API token for the /exec gateway.
  SANDBOX_EXEDEV_EGRESS_ALLOWLIST  Comma-separated domains the VM may reach;
                                   enforced via the provider's egress proxy.
  SANDBOX_EXEDEV_REGION            Optional exe.dev region to create VMs in.

Egress is allowlisted at the exe.dev proxy edge, not via the in-sandbox agentsh
shim the Modal/Docker providers install — pass the effective domains through
SANDBOX_EXEDEV_EGRESS_ALLOWLIST rather than the per-run allowed_domains path.

Snapshots are not available on exe.dev: resume/directory snapshots raise, and
boot uses the configured image only (no warm snapshot restore).
"""

from __future__ import annotations

import json
import shlex
import uuid
import base64
from collections.abc import Iterable
from typing import TYPE_CHECKING, Optional

from django.conf import settings

import requests
import structlog

from products.tasks.backend.constants import POSTHOG_EXEC_PERMISSION_REGEX, SANDBOX_AGENT_LAUNCH_UNSET_ENV_VARS
from products.tasks.backend.exceptions import (
    SandboxCleanupError,
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxProvisionError,
    SandboxTimeoutError,
    SnapshotCreationError,
)

from .agentsh import BASH_ENV_SCRIPT, GH_GUARD_INSTALL_PATH, generate_bash_env_script, read_gh_guard_script
from .sandbox import (
    WORKING_DIR,
    AgentServerResult,
    ExecutionResult,
    ExecutionStream,
    SandboxBase,
    SandboxConfig,
    SandboxStatus,
    build_agent_runtime_env_prefix,
    redact_sandbox_command,
    wait_for_health_check,
)

if TYPE_CHECKING:
    from products.tasks.backend.temporal.process_task.utils import McpServerConfig

logger = structlog.get_logger(__name__)

# Reachable over HTTPS at https://<vm>.exe.xyz:<port>; exe.dev forwards ports
# 3000-9999 through its proxy, so pick one inside that band.
AGENT_SERVER_PORT = 8080

EXEC_API_URL = "https://exe.dev/exec"
EXEC_TIMEOUT_SECONDS = 660  # Slightly above the 10-minute default execution timeout
EXEC_MAX_BODY_CHARS = 60_000  # Stay under the /exec 64KB request limit with room to spare


# exe.dev's `ls --json` wraps results in a {"vms": [...]} envelope; each entry has a
# "status" field ("running", plus non-running/terminal states). A pattern arg filters
# by name, so an unknown VM yields HTTP 200 with an empty list, not a 404.
def _find_vm(stdout: str, vm_name: str) -> str | None:
    """Return the VM's status if `vm_name` appears in `ls --json` output, else None."""
    try:
        payload = json.loads(stdout) if stdout.strip() else {}
    except (ValueError, TypeError):
        payload = {}
    entries: list = []
    if isinstance(payload, dict):
        vms = payload.get("vms")
        entries = vms if isinstance(vms, list) else [payload]
    elif isinstance(payload, list):
        entries = payload
    for entry in entries:
        if isinstance(entry, dict) and entry.get("vm_name") == vm_name:
            status = entry.get("status")
            return status if isinstance(status, str) else "running"
    return None


_VM_TOKEN_KEYS = ("token", "api_key", "key", "apiKey")


def _extract_vm_token(stdout: str) -> str | None:
    """Pull the VM-scoped API token out of `ssh-key generate-api-key --json` output."""
    data = stdout.strip()
    if not data:
        return None
    try:
        payload = json.loads(data)
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict):
        for key in _VM_TOKEN_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    elif isinstance(payload, str) and payload.strip():
        return payload.strip()
    # Fallback: the gateway sometimes returns the bare token as text.
    return data if data and "\n" not in data and len(data) < 4096 else None


def _api_token() -> str:
    token = getattr(settings, "SANDBOX_EXEDEV_API_TOKEN", None)
    if not token:
        raise SandboxProvisionError(
            "SANDBOX_EXEDEV_API_TOKEN is not configured",
            {"provider": "exedev"},
            cause=RuntimeError("SANDBOX_EXEDEV_API_TOKEN is required for the exe.dev provider"),
        )
    return token


def _required_image() -> str:
    image = getattr(settings, "SANDBOX_EXEDEV_IMAGE", None)
    if not image:
        raise SandboxProvisionError(
            "SANDBOX_EXEDEV_IMAGE is not configured",
            {"provider": "exedev"},
            cause=RuntimeError(
                "SANDBOX_EXEDEV_IMAGE is required for the exe.dev provider: supply a Docker "
                "reference pre-loaded with the PostHog agent-server at /scripts"
            ),
        )
    return image


def _exec_cli(command: str, timeout_seconds: int | None = None) -> ExecutionResult:
    """Run one exe.dev CLI command through the HTTPS /exec gateway.

    The gateway returns JSON output for the command with stdout/stderr fields; a
    non-zero command exit surfaces as HTTP 422, and auth/not-found as 401/404.
    """
    logger.debug(f"exe.dev exec: {redact_sandbox_command(command)[:200]}")
    try:
        response = requests.post(
            EXEC_API_URL,
            data=command.encode("utf-8"),
            headers={
                "Authorization": f"Bearer {_api_token()}",
                "Content-Type": "text/plain",
            },
            timeout=timeout_seconds or EXEC_TIMEOUT_SECONDS,
        )
    except requests.Timeout as e:
        raise SandboxTimeoutError(
            f"exe.dev exec timed out after {timeout_seconds or EXEC_TIMEOUT_SECONDS} seconds",
            {"provider": "exedev"},
            cause=e,
        )
    except requests.RequestException as e:
        raise SandboxExecutionError(
            "exe.dev exec request failed",
            {"provider": "exedev", "error": str(e)},
            cause=e,
        )

    body = response.text or ""
    if len(body) > EXEC_MAX_BODY_CHARS:
        body = body[:EXEC_MAX_BODY_CHARS] + "\n...[truncated]..."

    stdout, stderr = "", ""
    try:
        payload = json.loads(body) if body else {}
        if isinstance(payload, dict):
            stdout = str(payload.get("stdout") or payload.get("output") or "")
            stderr = str(payload.get("stderr") or "")
        elif isinstance(payload, str):
            stdout = payload
    except (ValueError, TypeError):
        stdout = body

    if response.status_code == 404:
        raise SandboxNotFoundError(
            "exe.dev VM or command not found",
            {"provider": "exedev", "error": body[:500]},
            cause=RuntimeError(body[:500]),
        )
    if response.status_code == 422:
        # The command ran but exited non-zero; surface as a result so callers
        # that probe (health checks, version greps) can branch on exit_code.
        return ExecutionResult(stdout=stdout, stderr=stderr or body, exit_code=1, error=body[:500] or None)
    if response.status_code >= 400:
        raise SandboxExecutionError(
            f"exe.dev exec failed with HTTP {response.status_code}",
            {"provider": "exedev", "error": body[:500]},
            cause=RuntimeError(body[:500]),
        )

    return ExecutionResult(stdout=stdout, stderr=stderr, exit_code=0, error=None)


class ExeDevSandbox(SandboxBase):
    """SandboxBase implementation driving an exe.dev VM.

    ``id`` is the exe.dev VM name (the handle used for ssh/exec/rm). Each exec is
    one HTTP request to the gateway — there is no persistent SDK connection — so
    ``get_by_id`` reconstructs the handle directly from the VM name.
    """

    id: str
    config: SandboxConfig

    def __init__(self, vm_name: str, config: SandboxConfig):
        self.id = vm_name
        self.config = config

    @property
    def sandbox_url(self) -> str | None:
        if not self.id:
            return None
        # exe.dev forwards ports 3000-9999 through its HTTPS proxy.
        return f"https://{self.id}.exe.xyz:{AGENT_SERVER_PORT}"

    @staticmethod
    def create(config: SandboxConfig) -> ExeDevSandbox:
        if config.snapshot_id or config.snapshot_external_id:
            raise SandboxProvisionError(
                "exe.dev provider does not support resume snapshots",
                {"config_name": config.name},
                cause=RuntimeError("snapshot resume is unsupported on exe.dev"),
            )

        image = _required_image()
        vm_name = f"{config.name}-{uuid.uuid4().hex[:6]}".lower().replace("_", "-")

        create_cmd = ["new", f"--name={shlex.quote(vm_name)}", f"--image={shlex.quote(image)}", "--json"]
        create_cmd.append(f"--cpu={config.cpu_cores:g}")
        create_cmd.append(f"--memory={config.memory_gb:g}GB")
        create_cmd.append(f"--disk={config.disk_size_gb:g}GB")
        if config.environment_variables:
            for key, value in config.environment_variables.items():
                if value is not None:
                    create_cmd.append(f"--env {shlex.quote(f'{key}={value}')}")

        region = getattr(settings, "SANDBOX_EXEDEV_REGION", None)
        if region:
            create_cmd.append(f"--tag={shlex.quote(f'region-{region}')}")

        egress = getattr(settings, "SANDBOX_EXEDEV_EGRESS_ALLOWLIST", None)
        if egress:
            create_cmd.append(f"--tag={shlex.quote('egress-' + egress.replace(',', '_')[:64])}")

        try:
            _exec_cli(" ".join(create_cmd), timeout_seconds=180)
        except SandboxNotFoundError:
            raise
        except Exception as e:
            logger.exception(f"Failed to create exe.dev VM: {e}")
            raise SandboxProvisionError(
                "Failed to create exe.dev VM",
                {"config_name": config.name, "error": str(e)},
                cause=e,
            )

        sandbox = ExeDevSandbox(vm_name=vm_name, config=config)
        logger.info(f"Created exe.dev sandbox {sandbox.id} for {config.name}")
        return sandbox

    @staticmethod
    def get_by_id(sandbox_id: str) -> ExeDevSandbox:
        result = _exec_cli(f"ls --json {shlex.quote(sandbox_id)}", timeout_seconds=30)
        if result.exit_code != 0 or _find_vm(result.stdout, sandbox_id) is None:
            raise SandboxNotFoundError(
                f"exe.dev VM {sandbox_id} not found",
                {"sandbox_id": sandbox_id, "error": result.stderr[:500]},
                cause=RuntimeError(result.stderr or "vm not found"),
            )
        return ExeDevSandbox(vm_name=sandbox_id, config=SandboxConfig(name=f"sandbox-{sandbox_id}"))

    @staticmethod
    def delete_snapshot(external_id: str) -> None:
        raise SnapshotCreationError(
            "exe.dev provider does not support snapshots",
            {"external_id": external_id},
            cause=RuntimeError("snapshots are unsupported on exe.dev"),
        )

    def get_status(self) -> SandboxStatus:
        try:
            result = _exec_cli(f"ls --json {shlex.quote(self.id)}", timeout_seconds=30)
            status = _find_vm(result.stdout, self.id)
            # Only an explicit "running" state counts; a missing VM (empty list),
            # a stopped/errored VM, or any gateway failure all report SHUTDOWN.
            return SandboxStatus.RUNNING if status == "running" else SandboxStatus.SHUTDOWN
        except Exception:
            return SandboxStatus.SHUTDOWN

    def execute(self, command: str, timeout_seconds: Optional[int] = None) -> ExecutionResult:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )
        if timeout_seconds is None:
            timeout_seconds = self.config.default_execution_timeout_seconds
        redacted_command = redact_sandbox_command(command)
        logger.debug(f"Executing in exe.dev sandbox {self.id}: {redacted_command[:100]}...")
        # `ssh <vm> <cmd>` runs the command inside the VM; wrap in bash -c so
        # shell features (pipes, redirects, globs) behave like the other providers.
        return _exec_cli(
            f"ssh {shlex.quote(self.id)} bash -c {shlex.quote(command)}",
            timeout_seconds=min(timeout_seconds + 30, 650),
        )

    def execute_stream(self, command: str, timeout_seconds: Optional[int] = None) -> ExecutionStream:
        # No streaming transport through /exec: run to completion, then replay
        # the captured stdout as an in-memory stream.
        result = self.execute(command, timeout_seconds)

        class _BufferedExecutionStream:
            def __init__(self, res: ExecutionResult):
                self._res = res

            def iter_stdout(self) -> Iterable[str]:
                yield from self._res.stdout.splitlines(keepends=True)

            def wait(self) -> ExecutionResult:
                return self._res

        return _BufferedExecutionStream(result)

    def write_file(self, path: str, payload: bytes) -> ExecutionResult:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )
        chunk_size = 40_000
        encoded = base64.b64encode(payload).decode("utf-8")
        temp_path = f"{path}.tmp-{uuid.uuid4().hex}"
        result = ExecutionResult(stdout="", stderr="", exit_code=0, error=None)
        for index in range(0, len(encoded), chunk_size):
            chunk = encoded[index : index + chunk_size]
            write_mode = "wb" if index == 0 else "ab"
            command = (
                "python3 - <<'EOF_EXEDEV_WRITE'\n"
                "import base64\n"
                "from pathlib import Path\n"
                f"path = Path({json.dumps(temp_path)})\n"
                "path.parent.mkdir(parents=True, exist_ok=True)\n"
                f"payload = base64.b64decode('{chunk}')\n"
                f"with path.open({json.dumps(write_mode)}) as f:\n"
                "    f.write(payload)\n"
                "EOF_EXEDEV_WRITE"
            )
            result = self.execute(command, timeout_seconds=self.config.default_execution_timeout_seconds)
            if result.exit_code != 0:
                logger.warning("exe.dev write failed", extra={"stderr": result.stderr, "sandbox_id": self.id})
                break

        if result.exit_code == 0:
            result = self.execute(
                f"mv {shlex.quote(temp_path)} {shlex.quote(path)}",
                timeout_seconds=self.config.default_execution_timeout_seconds,
            )
        return result

    def setup_repository(self, repository: str) -> ExecutionResult:
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def is_git_clean(self, repository: str) -> tuple[bool, str]:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")
        org, repo = repository.lower().split("/")
        repo_path = f"{WORKING_DIR}/repos/{org}/{repo}"
        result = self.execute(f"cd {shlex.quote(repo_path)} && git status --porcelain")
        return (not result.stdout.strip()), result.stdout

    def execute_task(
        self, task_id: str, run_id: str, repository: str | None = None, create_pr: bool = True
    ) -> ExecutionResult:
        return ExecutionResult(stdout="", stderr="", exit_code=0, error=None)

    def get_connect_credentials(self) -> AgentServerResult:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")
        url = self.sandbox_url
        if url is None:
            raise RuntimeError("Sandbox URL is not available.")
        # exe.dev's HTTPS auth proxy is default-private: it only forwards requests
        # carrying a VM-scoped token (sent as X-Exedev-Authorization). Mint one for
        # this VM; it rides TaskRun.state as sandbox_connect_token (like Modal's
        # connect token) and the proxy layer sends it on the dedicated header,
        # leaving Authorization: Bearer free for the agent server's own JWT.
        token = self._mint_vm_token()
        logger.info(f"Got connect credentials for exe.dev sandbox {self.id}: {url}")
        return AgentServerResult(url=url, token=token)

    def _mint_vm_token(self) -> str:
        result = _exec_cli(
            f"ssh-key generate-api-key --vm={shlex.quote(self.id)} --label=posthog-sandbox --json",
            timeout_seconds=60,
        )
        token = _extract_vm_token(result.stdout)
        if token is None:
            # Don't destroy the VM here: the caller may hold it across retries, and
            # sandbox_state cleanup belongs to the workflow, not a credential helper.
            raise SandboxProvisionError(
                "Failed to mint an exe.dev VM access token; the sandbox is unreachable over HTTPS",
                {"sandbox_id": self.id, "stdout": result.stdout[:500], "stderr": result.stderr[:500]},
                cause=RuntimeError(result.stderr or result.stdout or "no api key in response"),
            )
        return token

    def _build_agent_server_command(
        self,
        repo_path: str | None,
        task_id: str,
        run_id: str,
        mode: str,
        create_pr: bool,
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
        mcp_servers_arg: str = "",
        relay_mcp_servers_arg: str = "",
        event_ingest_token: str | None = None,
        task_run_session_token: str | None = None,
        event_ingest_url: str | None = None,
        event_ingest_keep_stream_open: bool = False,
        repo_ready_file: str | None = None,
        rtk_enabled: bool = True,
        posthog_exec_permission_regex: str | None = None,
    ) -> str:
        env_prefix = build_agent_runtime_env_prefix(
            interaction_origin=interaction_origin,
            agent_runtime=agent_runtime,
            sandbox_id=self.id,
            runtime_adapter=runtime_adapter,
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            context_window=context_window,
            fast_mode=fast_mode,
            initial_permission_mode=initial_permission_mode,
            event_ingest_token=event_ingest_token,
            task_run_session_token=task_run_session_token,
            event_ingest_url=event_ingest_url,
            event_ingest_keep_stream_open=event_ingest_keep_stream_open,
            rtk_enabled=rtk_enabled,
        )
        create_pr_flag = f" --createPr {shlex.quote('true' if create_pr else 'false')}"
        auto_publish_flag = " --autoPublish true" if auto_publish else ""
        repo_flag = f" --repositoryPath {shlex.quote(repo_path)}" if repo_path else ""
        branch_flag = f" --baseBranch {shlex.quote(branch)}" if branch else ""
        repo_ready_flag = f" --repoReadyFile {shlex.quote(repo_ready_file)}" if repo_ready_file else ""
        exec_permission_flag = (
            f" --posthogExecPermissionRegex {shlex.quote(posthog_exec_permission_regex)}"
            if posthog_exec_permission_regex
            else ""
        )
        unset_flags = "".join(f"-u {name} " for name in SANDBOX_AGENT_LAUNCH_UNSET_ENV_VARS)
        server_cmd = (
            f"env {unset_flags}BASH_ENV={shlex.quote(BASH_ENV_SCRIPT)} "
            f"{env_prefix}./node_modules/.bin/agent-server --port {AGENT_SERVER_PORT}{repo_flag} "
            f"--taskId {shlex.quote(task_id)} --runId {shlex.quote(run_id)} --mode {shlex.quote(mode)}"
            f"{create_pr_flag}{auto_publish_flag}{branch_flag}{mcp_servers_arg}{relay_mcp_servers_arg}"
            f"{repo_ready_flag}{exec_permission_flag}"
        )

        if repo_ready_file:
            wait_for_repo = f"while [ ! -f {shlex.quote(repo_ready_file)} ]; do sleep 0.1; done; exec {server_cmd}"
            server_cmd = f"bash -c {shlex.quote(wait_for_repo)}"

        inner = f"cd /scripts && {server_cmd} > /tmp/agent-server.log 2>&1"
        initialize_env_file = f"bash {shlex.quote(BASH_ENV_SCRIPT)}"
        # No agentsh egress shim here — egress is controlled at the exe.dev proxy
        # edge (SANDBOX_EXEDEV_EGRESS_ALLOWLIST), so launch the server directly.
        return f"cd /scripts && {initialize_env_file} && (nohup {inner} >/dev/null 2>&1 &)"

    def _install_gh_guard(self) -> None:
        self.write_file(GH_GUARD_INSTALL_PATH, read_gh_guard_script())
        self.execute(f"chmod +x {shlex.quote(GH_GUARD_INSTALL_PATH)}", timeout_seconds=30)

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
    ) -> None:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        repo_path: str | None = None
        if repository:
            org, repo = repository.lower().split("/")
            repo_path = f"{WORKING_DIR}/repos/{org}/{repo}"

        self.write_file(BASH_ENV_SCRIPT, generate_bash_env_script().encode())
        self._install_gh_guard()

        if allowed_domains is not None:
            logger.warning(
                f"exe.dev sandbox {self.id}: per-run allowed_domains is not enforced in-sandbox; "
                "configure egress via SANDBOX_EXEDEV_EGRESS_ALLOWLIST"
            )

        mcp_servers_arg = ""
        if mcp_configs:
            mcp_json = json.dumps([c.to_dict() for c in mcp_configs])
            mcp_servers_arg = f" --mcpServers {shlex.quote(mcp_json)}"

        relay_mcp_servers_arg = ""
        if relayed_mcp_servers:
            relay_mcp_servers_arg = f" --relayMcpServers {shlex.quote(json.dumps(relayed_mcp_servers))}"

        if agent_runtime == "pi" and not self.agent_server_supports_pi_runtime():
            raise RuntimeError("Installed sandbox agent-server does not support the Pi runtime")

        if auto_publish and not self.agent_server_supports_auto_publish():
            logger.warning(f"Installed agent-server in {self.id} predates --autoPublish; starting review-first")
            auto_publish = False

        exec_permission_regex: str | None = POSTHOG_EXEC_PERMISSION_REGEX
        if not self.agent_server_supports_exec_permission_regex():
            exec_permission_regex = None

        command = self._build_agent_server_command(
            repo_path,
            task_id,
            run_id,
            mode,
            create_pr,
            auto_publish,
            interaction_origin,
            branch,
            agent_runtime,
            runtime_adapter,
            provider,
            model,
            reasoning_effort,
            context_window=context_window,
            fast_mode=fast_mode,
            initial_permission_mode=initial_permission_mode,
            mcp_servers_arg=mcp_servers_arg,
            relay_mcp_servers_arg=relay_mcp_servers_arg,
            event_ingest_token=event_ingest_token,
            task_run_session_token=task_run_session_token,
            event_ingest_url=event_ingest_url,
            event_ingest_keep_stream_open=event_ingest_keep_stream_open,
            repo_ready_file=repo_ready_file,
            rtk_enabled=rtk_enabled,
            posthog_exec_permission_regex=exec_permission_regex,
        )

        logger.info(f"Starting agent-server in exe.dev sandbox {self.id} for {repository or 'no-repo'}")

        if not wait_for_health:
            result = self.execute(command, timeout_seconds=30)
            if result.exit_code != 0:
                raise SandboxExecutionError(
                    "Agent-server process failed to launch",
                    {"sandbox_id": self.id, "stderr": result.stderr, "exit_code": str(result.exit_code)},
                    cause=RuntimeError(result.stderr or "launch command returned non-zero exit"),
                )
            return

        if self._launch_and_check(command):
            logger.info(f"Agent-server started on exe.dev sandbox {self.id}")
            return

        if branch:
            self.execute("pkill -f agent-server || true", timeout_seconds=5)
            command = self._build_agent_server_command(
                repo_path,
                task_id,
                run_id,
                mode,
                create_pr,
                auto_publish,
                interaction_origin,
                branch=None,
                agent_runtime=agent_runtime,
                runtime_adapter=runtime_adapter,
                provider=provider,
                model=model,
                reasoning_effort=reasoning_effort,
                context_window=context_window,
                fast_mode=fast_mode,
                initial_permission_mode=initial_permission_mode,
                mcp_servers_arg=mcp_servers_arg,
                relay_mcp_servers_arg=relay_mcp_servers_arg,
                event_ingest_token=event_ingest_token,
                task_run_session_token=task_run_session_token,
                event_ingest_url=event_ingest_url,
                event_ingest_keep_stream_open=event_ingest_keep_stream_open,
                repo_ready_file=repo_ready_file,
                rtk_enabled=rtk_enabled,
                posthog_exec_permission_regex=exec_permission_regex,
            )
            if self._launch_and_check(command):
                logger.info(f"Agent-server started on exe.dev sandbox {self.id} (without --baseBranch)")
                return

        log_result = self.execute("cat /tmp/agent-server.log 2>/dev/null || echo 'No log file'", timeout_seconds=5)
        logger.warning(f"Agent-server health check failed for exe.dev sandbox {self.id}. Log:\n{log_result.stdout}")
        raise SandboxExecutionError(
            "Agent-server failed to start",
            {"sandbox_id": self.id, "log": log_result.stdout},
            cause=RuntimeError("Health check failed after retries"),
            capture=False,
        )

    def _launch_and_check(self, command: str) -> bool:
        result = self.execute(command, timeout_seconds=30)
        if result.exit_code != 0:
            logger.warning(f"Agent-server process failed to launch in exe.dev sandbox {self.id}: {result.stderr}")
            return False
        return self._wait_for_health_check(max_attempts=20)

    def wait_for_agent_server_ready(self, allowed_domains: list[str] | None = None) -> None:
        if self._wait_for_health_check(max_attempts=240):
            logger.info(f"Agent-server ready on exe.dev sandbox {self.id}")
            return
        log_result = self.execute("cat /tmp/agent-server.log 2>/dev/null || echo 'No log file'", timeout_seconds=5)
        logger.warning(f"Agent-server health check failed for exe.dev sandbox {self.id}. Log:\n{log_result.stdout}")
        raise SandboxExecutionError(
            "Agent-server failed to start",
            {"sandbox_id": self.id, "log": log_result.stdout},
            cause=RuntimeError("Health check failed after retries"),
            capture=False,
        )

    def mark_repo_ready(self, repo_ready_file: str) -> None:
        self.execute(f"touch {shlex.quote(repo_ready_file)}", timeout_seconds=10)

    def _wait_for_health_check(self, max_attempts: int = 60, poll_interval: float = 0.5) -> bool:
        return wait_for_health_check(self.execute, self.id, AGENT_SERVER_PORT, max_attempts, poll_interval)

    def read_agent_server_session_init_ms(self) -> int | None:
        return self._read_health_session_init_ms(AGENT_SERVER_PORT)

    def create_snapshot(self) -> str:
        raise SnapshotCreationError(
            "exe.dev provider does not support snapshots",
            {"sandbox_id": self.id},
            cause=RuntimeError("snapshots are unsupported on exe.dev"),
        )

    def create_directory_snapshot(self, path: str) -> str:
        raise SnapshotCreationError(
            "exe.dev provider does not support snapshots",
            {"sandbox_id": self.id, "path": path},
            cause=RuntimeError("snapshots are unsupported on exe.dev"),
        )

    def destroy(self) -> None:
        try:
            _exec_cli(f"rm --json {shlex.quote(self.id)}", timeout_seconds=120)
            logger.info(f"Destroyed exe.dev sandbox {self.id}")
        except Exception as e:
            logger.exception(f"Failed to destroy exe.dev sandbox: {e}")
            raise SandboxCleanupError(
                f"Failed to destroy exe.dev sandbox: {e}",
                {"sandbox_id": self.id, "error": str(e)},
                cause=e,
            )

    def is_running(self) -> bool:
        return self.get_status() == SandboxStatus.RUNNING

    @property
    def name(self) -> str:
        return self.config.name
