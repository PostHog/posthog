"""Provider-agnostic agent-server launch, health, and agentsh setup.

Everything here drives the sandbox exclusively through ``SandboxBase.execute`` /
``write_file``, so any provider whose image carries the standard layout
(``/scripts/node_modules/.bin/agent-server``, guards in ``/opt/posthog/bin``) can
inherit it unchanged.
"""

from __future__ import annotations

import json
import shlex
import logging
from typing import TYPE_CHECKING

from django.conf import settings

from products.tasks.backend.constants import POSTHOG_EXEC_PERMISSION_REGEX, SANDBOX_AGENT_LAUNCH_UNSET_ENV_VARS
from products.tasks.backend.exceptions import SandboxExecutionError
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
    wait_for_health_check,
)

if TYPE_CHECKING:
    from products.tasks.backend.temporal.process_task.utils import McpServerConfig

logger = logging.getLogger(__name__)

AGENT_SERVER_PORT = 8080  # Modal connect tokens require port 8080
AGENT_SERVER_HEALTH_MAX_ATTEMPTS = 240

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


class AgentServerLaunchMixin(SandboxBase):
    """Launches and supervises the in-sandbox agent-server over ``execute``."""

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
        allowed_domains: list[str] | None = None,
        event_ingest_token: str | None = None,
        task_run_session_token: str | None = None,
        event_ingest_url: str | None = None,
        event_ingest_keep_stream_open: bool = False,
        repo_ready_file: str | None = None,
        rtk_enabled: bool = True,
        peer_messaging: bool = False,
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
            peer_messaging=peer_messaging,
        )
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
            f"{domains_flag}{repo_ready_flag}{exec_permission_flag}"
        )

        if repo_ready_file:
            # Keep the adapter process from inheriting a repository cwd that does not
            # exist yet, even if an overlaid agent-server mishandles its readiness flag.
            wait_for_repo = f"while [ ! -f {shlex.quote(repo_ready_file)} ]; do sleep 0.1; done; exec {server_cmd}"
            server_cmd = f"bash -c {shlex.quote(wait_for_repo)}"

        inner = f"cd /scripts && {server_cmd} > /tmp/agent-server.log 2>&1"
        initialize_env_file = f"bash {shlex.quote(BASH_ENV_SCRIPT)}"

        if allowed_domains is not None:
            return (
                f"cd /scripts && {initialize_env_file} && "
                f"({build_exec_prefix()} {ENV_WRAPPER_SCRIPT} bash -c {shlex.quote(inner)} &)"
            )
        else:
            return f"cd /scripts && {initialize_env_file} && (nohup {server_cmd} > /tmp/agent-server.log 2>&1 &)"

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
            log_result = self.execute("cat /tmp/agent-server.log 2>/dev/null || echo 'No log file'", timeout_seconds=5)
            diagnostics["log"] = log_result.stdout
            health_result = self.execute(
                f"curl -s --max-time 3 http://localhost:{AGENT_SERVER_PORT}/health || echo 'no-health-response'",
                timeout_seconds=5,
            )
            diagnostics["health_response"] = health_result.stdout.strip()[:500]

            egress = self._probe_session_init_egress()
            diagnostics["egress_probe"] = egress
            blocked = [line for line in egress.splitlines() if "http_code=000" in line or line.endswith("FAILED")]
            if blocked:
                diagnostics["failure_reason"] = "egress blocked to required session-init host(s): " + "; ".join(blocked)
            else:
                diagnostics["failure_reason"] = (
                    "agent server alive but never reported hasSession=true; no egress block detected, "
                    "inspect agent-server log"
                )
        except Exception as e:
            diagnostics.setdefault("failure_reason", f"health check failed; diagnostics unavailable: {e}")
        return diagnostics

    def _probe_session_init_egress(self) -> str:
        hosts = _session_init_probe_hosts()
        checks = "; ".join(
            f"printf '%s ' {shlex.quote(host)}; "
            f"curl -sS --max-time 3 -o /dev/null -w 'http_code=%{{http_code}}\\n' https://{host}/ 2>/dev/null || echo FAILED"
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
        before calling this method. The agent-server runs on port 8080 which is
        exposed via the provider's tunnel/proxy mechanism.
        """
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        if self._agent_server_is_healthy() and (allowed_domains is None or self._agentsh_daemon_is_healthy()):
            if wait_for_health:
                self.wait_for_agent_server_ready(allowed_domains)
            logger.info(f"Agent-server already healthy in sandbox {self.id}; skipping relaunch")
            return
        self._free_agent_server_port()

        repo_path: str | None = None
        if repository:
            org, repo = repository.lower().split("/")
            repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        self.write_file(BASH_ENV_SCRIPT, generate_bash_env_script().encode())
        # Install the gh shim at runtime too (see agentsh.GH_GUARD_INSTALL_PATH): a resume from a
        # pre-shim filesystem snapshot — or any window where the base image lags this backend —
        # would otherwise leave gh with no token once the frozen launch-env token is unset.
        self.write_file(GH_GUARD_INSTALL_PATH, read_gh_guard_script())
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
                "exec sub-tools will not prompt"
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
            peer_messaging=peer_messaging,
            posthog_exec_permission_regex=exec_permission_regex,
        )

        logger.info(f"Starting agent-server in sandbox {self.id} for {repository or 'no-repo'}")
        launch_result = self.execute(command, timeout_seconds=30)
        if launch_result.exit_code != 0:
            logger.warning(f"Agent-server process failed to launch in sandbox {self.id}: {launch_result.stderr}")
            raise SandboxExecutionError(
                "Agent-server failed to start",
                {"sandbox_id": self.id, "stderr": launch_result.stderr, "exit_code": str(launch_result.exit_code)},
                cause=RuntimeError(launch_result.stderr or "launch command returned non-zero exit"),
            )

        if wait_for_health:
            self.wait_for_agent_server_ready(allowed_domains)

    def wait_for_agent_server_ready(self, allowed_domains: list[str] | None = None) -> None:
        if self._wait_for_health_check():
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
        self.write_file("/etc/agentsh/config.yaml", config_yaml.encode())
        self.write_file("/etc/agentsh/policies/default.yaml", policy_yaml.encode())
        self.write_file(ENV_WRAPPER_SCRIPT, generate_env_wrapper().encode())
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
        return wait_for_health_check(self.execute, self.id, AGENT_SERVER_PORT, max_attempts, poll_interval)

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
            "pkill -TERM -f agent-server 2>/dev/null || true; "
            "for _ in $(seq 1 10); do pgrep -f agent-server >/dev/null || break; sleep 0.5; done; "
            "pkill -KILL -f agent-server 2>/dev/null || true",
            timeout_seconds=15,
        )
