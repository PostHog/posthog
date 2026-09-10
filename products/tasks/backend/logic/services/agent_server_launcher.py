"""Provider-agnostic agent-server launch, health, and agentsh setup.

Everything here drives the sandbox exclusively through ``SandboxBase.execute`` /
``write_file``, so any provider whose image carries the standard layout
(``/scripts/node_modules/.bin/agent-server``, guards in ``/opt/posthog/bin``) can
inherit it unchanged.
"""

from __future__ import annotations

import re
import json
import time
import shlex
import logging
from typing import TYPE_CHECKING

from django.conf import settings

from products.tasks.backend.constants import POSTHOG_EXEC_PERMISSION_REGEX, SANDBOX_AGENT_LAUNCH_UNSET_ENV_VARS
from products.tasks.backend.exceptions import ProcessTaskFatalError, SandboxExecutionError, SandboxTimeoutError
from products.tasks.backend.logic.services.agentsh import (
    AGENTSH_DAEMON_PORT,
    BASH_ENV_SCRIPT,
    ENV_WRAPPER_SCRIPT,
    GH_GUARD_INSTALL_PATH,
    SESSION_ID_FILE,
    _hostname_from_url,
    build_exec_prefix,
    build_setup_script,
    generate_bash_env_script,
    generate_config_yaml,
    generate_env_wrapper,
    generate_policy_yaml,
    read_gh_guard_script,
)
from products.tasks.backend.logic.services.mcp_url import resolve_mcp_url
from products.tasks.backend.logic.services.sandbox import (
    WORKING_DIR,
    SandboxBase,
    build_agent_runtime_env_prefix,
    build_health_check_command,
    health_check_timeout_seconds,
    wait_for_health_check,
)

if TYPE_CHECKING:
    from products.tasks.backend.temporal.process_task.utils import McpServerConfig

logger = logging.getLogger(__name__)

AGENT_SERVER_PORT = 8080  # Modal connect tokens require port 8080
AGENT_SERVER_HEALTH_MAX_ATTEMPTS = 240
# The whole diagnostics dict rides in the Temporal failure payload, which is capped at about 2 MiB.
STARTUP_LOG_MAX_BYTES = 64 * 1024
AGENT_SERVER_HEALTH_DURATION_PREFIX = "__posthog_agent_health_ms="

# The read probe wants a large file the agent-server boot never opens, so its first read is cold:
# nothing at boot loads the global TypeScript compiler. Its prefix follows the Node install and its
# largest asset moves between releases, so take the biggest file under either prefix. Nothing above
# the floor means no usable read, because the interpreter boot paged in would time fast, not cold.
HOST_PRESSURE_COLD_READ_ROOTS = "/usr/lib/node_modules/typescript /usr/local/lib/node_modules/typescript"
HOST_PRESSURE_COLD_READ_MIN_BYTES = 1024 * 1024
HOST_PRESSURE_PROBE_SCRIPT = (
    'echo "loadavg=$(cat /proc/loadavg 2>/dev/null)"; '
    'echo "nproc=$(nproc 2>/dev/null)"; '
    "for f in /proc/pressure/cpu /proc/pressure/io /proc/pressure/memory /sys/fs/cgroup/cpu.stat; do "
    '  [ -r "$f" ] && echo "$f: $(tr \'\\n\' \' \' < "$f")"; '
    "done; "
    'cpu_start=$(date +%s%3N); i=0; while [ "$i" -lt 200000 ]; do i=$((i+1)); done; '
    'echo "cpu_loop_ms=$(( $(date +%s%3N) - cpu_start ))"; '
    "spawn_start=$(date +%s%3N); python3 -c pass; "
    'echo "python_spawn_ms=$(( $(date +%s%3N) - spawn_start ))"; '
    f'probe_file="$(timeout 10 find {HOST_PRESSURE_COLD_READ_ROOTS} -type f '
    '-printf "%s\\t%p\\n" 2>/dev/null | sort -rn | head -1 | cut -f2)"; '
    'probe_size="$(stat -c %s "$probe_file" 2>/dev/null || echo 0)"; '
    f'if [ "$probe_size" -ge {HOST_PRESSURE_COLD_READ_MIN_BYTES} ]; then '
    '  read_start=$(date +%s%3N); timeout 20 cat "$probe_file" > /dev/null; '
    '  echo "cold_read_ms=$(( $(date +%s%3N) - read_start )) file=$probe_file size=$probe_size"; '
    'else echo "cold_read_ms=unavailable file=${probe_file:-none} size=$probe_size"; fi'
)

EGRESS_PROBE_MAX_TIME_SECONDS = 3
# curl(1): "Operation timeout. The specified time-out period was reached according to the conditions."
CURL_EXIT_OPERATION_TIMEOUT = 28
CURL_EXIT_PATTERN = re.compile(r"curl_exit=(\d+)$")

SESSION_INIT_PROBE_HOSTS = (
    "gateway.us.posthog.com",
    "gateway.eu.posthog.com",
    "api.anthropic.com",
)


def _session_init_probe_hosts() -> list[str]:
    """Hosts the startup-failure egress probe checks. Both gateway settings
    are included: routed products call SANDBOX_AI_GATEWAY_URL, everything
    else SANDBOX_LLM_GATEWAY_URL, and a block on either is this probe's
    reason to exist.
    """
    hosts = list(SESSION_INIT_PROBE_HOSTS)
    mcp_host = _hostname_from_url(resolve_mcp_url(sandbox_mcp_url=settings.SANDBOX_MCP_URL, site_url=settings.SITE_URL))
    if mcp_host and mcp_host not in hosts:
        hosts.insert(0, mcp_host)
    for setting_name in ("SANDBOX_LLM_GATEWAY_URL", "SANDBOX_AI_GATEWAY_URL"):
        gateway_host = _hostname_from_url(getattr(settings, setting_name, None))
        if gateway_host and gateway_host not in hosts:
            hosts.insert(0, gateway_host)
    return hosts


def _curl_exit_code(line: str) -> int | None:
    """Read the exit code the probe appends, or None for output from an image that predates it."""
    match = CURL_EXIT_PATTERN.search(line)
    return int(match.group(1)) if match else None


def _egress_failure_reason(egress: str) -> str | None:
    """Name the failure the egress probe saw, or None when every host answered.

    A refused connection (curl exit 7) or a failed lookup (exit 6) proves a network policy block.
    A timeout (exit 28) proves nothing on its own: a slow sandbox and a policy that drops packets
    silently both look like one. So a timeout is reported as a timeout, and the reader is sent to
    the host-pressure probe in the same diagnostics rather than to the allowlist. A nonzero exit
    with no HTTP code means curl never ran or was killed, so that host was never probed at all.
    """
    failed: list[str] = []
    blocked: list[str] = []
    unprobed: list[str] = []
    for line in egress.splitlines():
        exit_code = _curl_exit_code(line)
        if exit_code == 0:
            continue
        curl_reported_no_response = "http_code=000" in line or line.endswith("FAILED")
        if not curl_reported_no_response and (exit_code is None or "http_code=" in line):
            continue
        failed.append(line)
        if exit_code == CURL_EXIT_OPERATION_TIMEOUT:
            continue
        if curl_reported_no_response:
            blocked.append(line)
        else:
            unprobed.append(line)
    if not failed:
        return None
    if blocked:
        return "egress blocked to required session-init host(s): " + "; ".join(failed)
    if unprobed:
        return (
            "egress probe did not run for required session-init host(s); curl exited without an HTTP code, "
            "so nothing here rules an allowlist block in or out: " + "; ".join(failed)
        )
    return (
        f"egress probe timed out after {EGRESS_PROBE_MAX_TIME_SECONDS}s to every session-init host it could "
        "not reach, and none refused the connection; read the host-pressure probe before the allowlist, "
        "because a starved sandbox and a policy that drops packets silently both time out: " + "; ".join(failed)
    )


def _start_and_wait_command(command: str, max_attempts: int = AGENT_SERVER_HEALTH_MAX_ATTEMPTS) -> str:
    health_command = build_health_check_command(AGENT_SERVER_PORT, max_attempts, pid_file="/tmp/agent-server.pid")
    return (
        f"{command}; launch_status=$?; "
        'if [ "$launch_status" -ne 0 ]; then exit "$launch_status"; fi; '
        "health_started=$(date +%s%3N); "
        f"({health_command}); health_status=$?; "
        "health_finished=$(date +%s%3N); "
        f'echo "{AGENT_SERVER_HEALTH_DURATION_PREFIX}$((health_finished - health_started))"; '
        'exit "$health_status"'
    )


def _health_duration_ms(stdout: str) -> int | None:
    for line in stdout.splitlines():
        if line.startswith(AGENT_SERVER_HEALTH_DURATION_PREFIX):
            try:
                return max(0, int(line.removeprefix(AGENT_SERVER_HEALTH_DURATION_PREFIX)))
            except ValueError:
                return None
    return None


class AgentServerLaunchMixin(SandboxBase):
    """Launches and supervises the in-sandbox agent-server over ``execute``."""

    def supports_combined_agent_server_start_and_health(self) -> bool:
        return True

    def _write_required_file(self, path: str, payload: bytes) -> None:
        result = self.write_file(path, payload)
        if result.exit_code != 0:
            write_stage = (result.error or "unknown")[:100]
            raise SandboxExecutionError(
                "Failed to write required sandbox file",
                {
                    "sandbox_id": self.id,
                    "path": path,
                    "exit_code": str(result.exit_code),
                    "write_stage": write_stage,
                },
                cause=RuntimeError(f"write_file returned {result.exit_code} during {write_stage}"),
            )

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
        service_tier: str | None = None,
        context_window: str | None = None,
        fast_mode: bool | None = None,
        initial_permission_mode: str | None = None,
        mcp_servers_arg: str = "",
        relay_mcp_servers_arg: str = "",
        allowed_domains: list[str] | None = None,
        event_ingest_token: str | None = None,
        task_run_session_token: str | None = None,
        event_ingest_url: str | None = None,
        event_ingest_keep_stream_open: bool = False,
        repo_ready_file: str | None = None,
        rtk_enabled: bool = True,
        benjamin_enabled: bool = False,
        peer_messaging: bool = False,
        posthog_exec_permission_regex: str | None = None,
        claude_model_access: str | None = None,
    ) -> str:
        env_prefix = build_agent_runtime_env_prefix(
            interaction_origin=interaction_origin,
            agent_runtime=agent_runtime,
            sandbox_id=self.id,
            runtime_adapter=runtime_adapter,
            provider=provider,
            model=model,
            reasoning_effort=reasoning_effort,
            service_tier=service_tier,
            context_window=context_window,
            fast_mode=fast_mode,
            initial_permission_mode=initial_permission_mode,
            event_ingest_token=event_ingest_token,
            task_run_session_token=task_run_session_token,
            event_ingest_url=event_ingest_url,
            event_ingest_keep_stream_open=event_ingest_keep_stream_open,
            rtk_enabled=rtk_enabled,
            benjamin_enabled=benjamin_enabled,
            peer_messaging=peer_messaging,
            unset_bedrock=self.disable_direct_bedrock,
        )
        subscription_flag = " --claudeSubscription" if claude_model_access == "own-subscription" else ""
        create_pr_flag = f" --createPr {shlex.quote('true' if create_pr else 'false')}"
        # Only append when opted in: agent-server builds without the option reject unknown
        # flags, so default runs (and resumes of old snapshots) must not see it.
        auto_publish_flag = " --autoPublish true" if auto_publish else ""
        repo_flag = f" --repositoryPath {shlex.quote(repo_path)}" if repo_path else ""
        branch_flag = f" --baseBranch {shlex.quote(branch)}" if branch else ""
        domains_flag = f" --allowedDomains {shlex.quote(','.join(allowed_domains))}" if allowed_domains else ""
        repo_ready_flag = f" --repoReadyFile {shlex.quote(repo_ready_file)}" if repo_ready_file else ""
        exec_permission_flag = (
            f" --posthogExecPermissionRegex {shlex.quote(posthog_exec_permission_regex)}"
            if posthog_exec_permission_regex
            else ""
        )
        # Scope BASH_ENV to the agent-server process (not the container env) so only the
        # agent's per-command tool shells re-source the refreshed token. Backend maintenance
        # execs (clone/checkout/token injection) must not source it — the script could be
        # persisted in a resume snapshot, so sourcing it from a backend exec is a trust hole.
        unset_flags = "".join(f"-u {name} " for name in SANDBOX_AGENT_LAUNCH_UNSET_ENV_VARS)
        server_cmd = (
            f"env {unset_flags}BASH_ENV={shlex.quote(BASH_ENV_SCRIPT)} "
            f"{env_prefix}./node_modules/.bin/agent-server --port {AGENT_SERVER_PORT}{repo_flag} "
            f"--taskId {shlex.quote(task_id)} --runId {shlex.quote(run_id)} --mode {shlex.quote(mode)}"
            f"{create_pr_flag}{auto_publish_flag}{branch_flag}{mcp_servers_arg}{relay_mcp_servers_arg}"
            f"{domains_flag}{repo_ready_flag}{exec_permission_flag}{subscription_flag}"
        )
        launch_started_at = "export POSTHOG_AGENT_LAUNCH_STARTED_AT_MS=$(date +%s%3N)"

        if repo_ready_file:
            # Keep the adapter process from inheriting a repository cwd that does not
            # exist yet, even if an overlaid agent-server mishandles its readiness flag.
            wait_for_repo = (
                f"while [ ! -f {shlex.quote(repo_ready_file)} ]; do sleep 0.1; done; "
                f"{launch_started_at}; exec {server_cmd}"
            )
            server_cmd = f"bash -c {shlex.quote(wait_for_repo)}"

        inner = f"cd /scripts && {server_cmd} > /tmp/agent-server.log 2>&1"
        initialize_env_file = f"bash {shlex.quote(BASH_ENV_SCRIPT)}"
        launch_started_prefix = "" if repo_ready_file else f"{launch_started_at} && "

        if allowed_domains is not None:
            return (
                f"cd /scripts && {launch_started_prefix}{initialize_env_file} && "
                f"({build_exec_prefix()} {ENV_WRAPPER_SCRIPT} bash -c {shlex.quote(inner)} & echo $! > /tmp/agent-server.pid)"
            )
        else:
            return (
                f"cd /scripts && {launch_started_prefix}{initialize_env_file} && "
                f"(nohup {server_cmd} > /tmp/agent-server.log 2>&1 & echo $! > /tmp/agent-server.pid)"
            )

    def _termination_failure_reason(self) -> str:
        """Provider-specific detail for a sandbox that died before becoming healthy."""
        return (
            "sandbox terminated before becoming healthy; "
            "the VM/container exited (OOM, init exit, or reaping) rather than egress being blocked"
        )

    def _diagnose_startup_failure(self, allowed_domains: list[str] | None) -> dict[str, str]:
        diagnostics: dict[str, str] = {}
        try:
            if not self.is_running():
                diagnostics["sandbox_terminated"] = "true"
                diagnostics["failure_reason"] = self._termination_failure_reason()
                return diagnostics

            diagnostics["sandbox_terminated"] = "false"
            log_result = self.execute(
                f"tail -c {STARTUP_LOG_MAX_BYTES} /tmp/agent-server.log 2>/dev/null || echo 'No log file'",
                timeout_seconds=5,
            )
            diagnostics["log"] = log_result.stdout
            if len(log_result.stdout.encode()) >= STARTUP_LOG_MAX_BYTES:
                diagnostics["log_truncated"] = "true"
            health_result = self.execute(
                f"curl -s --max-time 3 http://localhost:{AGENT_SERVER_PORT}/health || echo 'no-health-response'",
                timeout_seconds=5,
            )
            diagnostics["health_response"] = health_result.stdout.strip()[:500]

            egress = self._probe_session_init_egress()
            diagnostics["egress_probe"] = egress
            egress_reason = _egress_failure_reason(egress)
            if egress_reason:
                diagnostics["failure_reason"] = egress_reason
            else:
                diagnostics["failure_reason"] = (
                    "agent server alive but never reported hasSession=true; no egress block detected, "
                    "inspect agent-server log"
                )
        except Exception as e:
            diagnostics.setdefault("failure_reason", f"health check failed; diagnostics unavailable: {e}")
        # Last, and guarded on its own: a starved box can stall this probe too, and that must
        # not replace the failure reason the checks above already produced.
        try:
            diagnostics["host_pressure"] = self._probe_host_pressure()
        except Exception as e:
            diagnostics["host_pressure"] = f"unavailable: {e}"
        return diagnostics

    def _probe_host_pressure(self) -> str:
        """Measure the box, not the agent, so a startup failure can be told apart by cause.

        A slow CPU loop or spawn means CPU starvation. A slow read of a file that boot never
        touches means the image filesystem is slow to load it, which is what a lazily loaded
        image looks like on a cold host. Both fast means the agent itself stalled.
        """
        return self.execute(HOST_PRESSURE_PROBE_SCRIPT, timeout_seconds=45).stdout.strip()

    def _probe_session_init_egress(self) -> str:
        hosts = _session_init_probe_hosts()
        checks = "; ".join(
            f"printf '%s ' {shlex.quote(host)}; "
            f"curl -sS --max-time {EGRESS_PROBE_MAX_TIME_SECONDS} -o /dev/null -w 'http_code=%{{http_code}}' "
            f"https://{host}/ 2>/dev/null; "
            'echo " curl_exit=$?"'
            for host in hosts
        )
        return self.execute(checks, timeout_seconds=30).stdout.strip()

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
        service_tier: str | None = None,
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
        benjamin_enabled: bool = False,
        peer_messaging: bool = False,
        claude_model_access: str | None = None,
    ) -> int | None:
        """Start the agent-server HTTP server in the sandbox.

        The sandbox URL and token should be obtained via get_connect_credentials()
        before calling this method. The agent-server runs on port 8080 which is
        exposed via the provider's tunnel/proxy mechanism.
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        # Before the already-healthy shortcut: images that boot the agent server never relaunch it,
        # and the agent reads its skill directories when a session starts, not when the server does.
        self.clear_bundled_skills_if_disabled()
        if self._agent_server_is_healthy() and (allowed_domains is None or self._agentsh_daemon_is_healthy()):
            logger.info(f"Agent-server already healthy in sandbox {self.id}; skipping relaunch")
            return 0 if wait_for_health else None
        self._free_agent_server_port()

        repo_path: str | None = None
        if repository:
            org, repo = repository.lower().split("/")
            repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        self._write_required_file(BASH_ENV_SCRIPT, generate_bash_env_script().encode())
        # Install the gh shim at runtime too (see agentsh.GH_GUARD_INSTALL_PATH): a resume from a
        # pre-shim filesystem snapshot — or any window where the base image lags this backend —
        # would otherwise leave gh with no token once the frozen launch-env token is unset.
        self._write_required_file(GH_GUARD_INSTALL_PATH, read_gh_guard_script())
        self.execute(f"chmod +x {shlex.quote(GH_GUARD_INSTALL_PATH)}", timeout_seconds=30)

        if allowed_domains is not None:
            self._setup_agentsh(WORKING_DIR, allowed_domains)

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
            logger.warning(f"Installed agent-server in sandbox {self.id} predates --autoPublish; starting review-first")
            auto_publish = False

        exec_permission_regex: str | None = POSTHOG_EXEC_PERMISSION_REGEX
        if not self.agent_server_supports_exec_permission_regex():
            logger.warning(
                f"Installed agent-server in sandbox {self.id} predates --posthogExecPermissionRegex; "
                "connected-project operations will not prompt"
            )
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
            service_tier=service_tier,
            context_window=context_window,
            fast_mode=fast_mode,
            initial_permission_mode=initial_permission_mode,
            mcp_servers_arg=mcp_servers_arg,
            relay_mcp_servers_arg=relay_mcp_servers_arg,
            allowed_domains=allowed_domains,
            event_ingest_token=event_ingest_token,
            task_run_session_token=task_run_session_token,
            event_ingest_url=event_ingest_url,
            event_ingest_keep_stream_open=event_ingest_keep_stream_open,
            repo_ready_file=repo_ready_file,
            rtk_enabled=rtk_enabled,
            benjamin_enabled=benjamin_enabled,
            peer_messaging=peer_messaging,
            posthog_exec_permission_regex=exec_permission_regex,
            claude_model_access=claude_model_access,
        )

        logger.info(f"Starting agent-server in sandbox {self.id} for {repository or 'no-repo'}")
        max_attempts = 300 if claude_model_access == "own-subscription" else AGENT_SERVER_HEALTH_MAX_ATTEMPTS
        execute_command = _start_and_wait_command(command, max_attempts) if wait_for_health else command
        timeout_seconds = 30 + health_check_timeout_seconds(max_attempts) if wait_for_health else 30
        start_time = time.perf_counter()
        try:
            launch_result = self.execute(execute_command, timeout_seconds=timeout_seconds)
        except SandboxTimeoutError as error:
            if not wait_for_health:
                raise
            raise self._startup_timeout_with_diagnostics(allowed_domains, timeout_seconds) from error
        start_and_health_ms = int((time.perf_counter() - start_time) * 1000)
        if launch_result.exit_code != 0:
            health_duration_ms = _health_duration_ms(launch_result.stdout)
            if wait_for_health and health_duration_ms is not None:
                diagnostics = self._diagnose_startup_failure(allowed_domains)
                if (
                    "claude_credential_unavailable" in launch_result.stdout
                    or "claude_credential_unavailable" in diagnostics.get("log", "")
                ):
                    raise ProcessTaskFatalError(
                        "The Claude token did not arrive. Open Desktop and check your token in Settings > Harness. Then start the task again.",
                        {"task_id": task_id, "run_id": run_id},
                        RuntimeError("Claude token unavailable"),
                        capture=False,
                    )
                raise SandboxExecutionError(
                    "Agent-server failed to start",
                    {
                        "sandbox_id": self.id,
                        **diagnostics,
                        "health_poll_ms": health_duration_ms,
                        "start_and_health_ms": start_and_health_ms,
                    },
                    cause=RuntimeError(diagnostics.get("failure_reason", "Health check failed after retries")),
                )
            logger.warning(f"Agent-server process failed to launch in sandbox {self.id}: {launch_result.stderr}")
            raise SandboxExecutionError(
                "Agent-server failed to start",
                {"sandbox_id": self.id, "stderr": launch_result.stderr, "exit_code": str(launch_result.exit_code)},
                cause=RuntimeError(launch_result.stderr or "launch command returned non-zero exit"),
            )

        if wait_for_health:
            if allowed_domains is not None and not self._agentsh_daemon_is_healthy():
                raise SandboxExecutionError(
                    "Failed to verify agentsh network enforcement",
                    {"sandbox_id": self.id},
                    cause=RuntimeError("agentsh daemon health check failed"),
                )
            logger.info(f"Agent-server ready in sandbox {self.id}")
            return _health_duration_ms(launch_result.stdout)
        return None

    def wait_for_agent_server_ready(
        self, allowed_domains: list[str] | None = None, *, claude_model_access: str | None = None
    ) -> None:
        max_attempts = 300 if claude_model_access == "own-subscription" else AGENT_SERVER_HEALTH_MAX_ATTEMPTS
        try:
            healthy = self._wait_for_health_check(max_attempts=max_attempts)
        except SandboxTimeoutError as error:
            raise self._startup_timeout_with_diagnostics(
                allowed_domains, health_check_timeout_seconds(max_attempts)
            ) from error
        if healthy:
            if allowed_domains is not None and not self._agentsh_daemon_is_healthy():
                raise SandboxExecutionError(
                    "Failed to verify agentsh network enforcement",
                    {"sandbox_id": self.id},
                    cause=RuntimeError("agentsh daemon health check failed"),
                )
            logger.info(f"Agent-server ready in sandbox {self.id}")
            return
        diagnostics = self._diagnose_startup_failure(allowed_domains)
        raise SandboxExecutionError(
            "Agent-server failed to start",
            {"sandbox_id": self.id, **diagnostics},
            cause=RuntimeError(diagnostics.get("failure_reason", "Health check failed after retries")),
        )

    def _startup_timeout_with_diagnostics(
        self, allowed_domains: list[str] | None, timeout_seconds: int
    ) -> SandboxTimeoutError:
        diagnostics = self._diagnose_startup_failure(allowed_domains)
        logger.warning(
            "Agent-server health poll timed out in sandbox %s after %ss: %s",
            self.id,
            timeout_seconds,
            diagnostics.get("failure_reason"),
        )
        return SandboxTimeoutError(
            "Agent-server failed to start",
            {"sandbox_id": self.id, "timeout_seconds": timeout_seconds, **diagnostics},
            cause=RuntimeError(diagnostics.get("failure_reason", f"health poll exceeded {timeout_seconds}s")),
        )

    def mark_repo_ready(self, repo_ready_file: str) -> None:
        self.execute(f"touch {shlex.quote(repo_ready_file)}", timeout_seconds=10)

    def _setup_agentsh(self, workspace_path: str, allowed_domains: list[str] | None = None) -> None:
        if allowed_domains is not None:
            logger.info("Configuring agentsh in sandbox %s for %d allowed domain(s)", self.id, len(allowed_domains))
        else:
            logger.info("Configuring agentsh in sandbox %s (allow-all mode)", self.id)

        config_yaml = generate_config_yaml(enable_ptrace=True, full_trace=True)
        policy_yaml = generate_policy_yaml(allowed_domains)

        self.execute("pkill -f 'agentsh server' || true", timeout_seconds=5)
        self.execute("mkdir -p /etc/agentsh/policies /var/log/agentsh /var/lib/agentsh/sessions", timeout_seconds=5)
        self._write_required_file("/etc/agentsh/config.yaml", config_yaml.encode())
        self._write_required_file("/etc/agentsh/policies/default.yaml", policy_yaml.encode())
        self._write_required_file(ENV_WRAPPER_SCRIPT, generate_env_wrapper().encode())
        self.execute(f"chmod +x {ENV_WRAPPER_SCRIPT}", timeout_seconds=5)

        setup_script = build_setup_script(workspace_path)
        result = self.execute(setup_script, timeout_seconds=30)
        if not self._agentsh_daemon_is_healthy():
            agentsh_log = self.execute("cat /var/log/agentsh/agentsh.log 2>/dev/null || true", timeout_seconds=5)
            logger.error(
                "agentsh daemon failed to start in sandbox %s (setup exit_code=%s); stderr=%r agentsh_log=%r",
                self.id,
                result.exit_code,
                result.stderr.strip()[:1000],
                agentsh_log.stdout.strip()[:2000],
            )
            raise SandboxExecutionError(
                "Failed to start agentsh daemon",
                {
                    "sandbox_id": self.id,
                    "stderr": result.stderr,
                    "stdout": result.stdout,
                    "exit_code": result.exit_code,
                    "agentsh_log": agentsh_log.stdout,
                },
                cause=RuntimeError(result.stderr or "agentsh daemon health check failed"),
            )

        session_check = self.execute(f"cat {SESSION_ID_FILE}", timeout_seconds=5)
        if session_check.exit_code != 0 or not session_check.stdout.strip():
            agentsh_log = self.execute("cat /var/log/agentsh/agentsh.log 2>/dev/null || true", timeout_seconds=5)
            logger.error(
                "agentsh session creation failed in sandbox %s; stderr=%r agentsh_log=%r",
                self.id,
                session_check.stderr.strip()[:1000],
                agentsh_log.stdout.strip()[:2000],
            )
            raise SandboxExecutionError(
                "Failed to create agentsh session",
                {
                    "sandbox_id": self.id,
                    "stderr": session_check.stderr,
                    "agentsh_log": agentsh_log.stdout,
                },
                cause=RuntimeError("agentsh session create failed"),
            )

        logger.info("agentsh daemon started and session created in sandbox %s", self.id)

    def _agentsh_daemon_is_healthy(self, max_attempts: int = 30, poll_interval: float = 0.5) -> bool:
        health_script = (
            f"for i in $(seq 1 {max_attempts}); do "
            f"  status=$(curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:{AGENTSH_DAEMON_PORT}/health); "
            f'  [ "$status" = "200" ] && exit 0; '
            f'  [ "$i" -lt {max_attempts} ] && sleep {poll_interval}; '
            f"done; "
            f"exit 1"
        )
        result = self.execute(health_script, timeout_seconds=max(30, int(max_attempts * poll_interval) + 5))
        return result.exit_code == 0

    def _wait_for_health_check(
        self, max_attempts: int = AGENT_SERVER_HEALTH_MAX_ATTEMPTS, poll_interval: float = 0.5
    ) -> bool:
        """Poll health endpoint until server is ready (single remote call)."""
        return wait_for_health_check(
            self.execute, self.id, AGENT_SERVER_PORT, max_attempts, poll_interval, pid_file="/tmp/agent-server.pid"
        )

    def _agent_server_is_healthy(self) -> bool:
        return wait_for_health_check(self.execute, self.id, AGENT_SERVER_PORT, max_attempts=1, poll_interval=0.0)

    def read_agent_server_session_init_ms(self) -> int | None:
        return self._read_health_session_init_ms(AGENT_SERVER_PORT)

    def read_agent_server_boot_phases_ms(self) -> dict[str, int]:
        return self._read_health_boot_phases_ms(AGENT_SERVER_PORT)

    def read_agent_server_boot_metrics(self) -> tuple[int | None, dict[str, int]]:
        return self._read_health_boot_metrics(AGENT_SERVER_PORT)

    def _free_agent_server_port(self) -> None:
        self.execute(
            "pkill -TERM -f '[a]gent-server' 2>/dev/null || true; "
            "for _ in $(seq 1 10); do pgrep -f '[a]gent-server' >/dev/null || break; sleep 0.5; done; "
            "pkill -KILL -f '[a]gent-server' 2>/dev/null || true",
            timeout_seconds=15,
        )
