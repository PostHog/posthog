import shlex
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import asyncify
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.models import Task
from products.tasks.backend.services.agentsh import ENV_FILE, ENV_WRAPPER_SCRIPT, build_exec_prefix
from products.tasks.backend.services.sandbox import Sandbox, SandboxBase
from products.tasks.backend.temporal.exceptions import OAuthTokenError, SandboxExecutionError
from products.tasks.backend.temporal.oauth import create_oauth_access_token
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution
from products.tasks.backend.temporal.process_task.utils import (
    format_allowed_domains_for_log,
    get_sandbox_ph_mcp_configs,
    get_user_mcp_server_configs,
)

from .get_task_processing_context import TaskProcessingContext

logger = get_logger(__name__)


def _emit_agentsh_log_tail(ctx: TaskProcessingContext, sandbox: SandboxBase) -> None:
    try:
        result = sandbox.execute("tail -n 20 /var/log/agentsh/agentsh.log 2>/dev/null || true", timeout_seconds=5)
    except Exception:
        logger.exception("Failed to fetch agentsh log tail", task_id=ctx.task_id, run_id=ctx.run_id)
        return

    log_tail = result.stdout.strip()
    if log_tail:
        emit_agent_log(ctx.run_id, "debug", f"agentsh log tail:\n{log_tail}")


def _emit_agent_server_log_tail(ctx: TaskProcessingContext, sandbox: SandboxBase) -> None:
    try:
        result = sandbox.execute("tail -n 40 /tmp/agent-server.log 2>/dev/null || true", timeout_seconds=5)
    except Exception:
        logger.exception("Failed to fetch agent-server log tail", task_id=ctx.task_id, run_id=ctx.run_id)
        return

    log_tail = result.stdout.strip()
    if log_tail:
        emit_agent_log(ctx.run_id, "debug", f"agent-server log tail:\n{log_tail}")


def _run_connectivity_diagnostics(ctx: TaskProcessingContext, sandbox: SandboxBase) -> None:
    """Emit diagnostic info about env vars and network connectivity.

    When allowed_domains is set, runs the checks inside the agentsh exec
    context to verify the env wrapper restores variables and the DNS proxy
    resolves correctly.  Without domains, runs directly.
    """
    try:
        checks = (
            "echo ENV_CHECK:"
            " LLM_GATEWAY_URL=${LLM_GATEWAY_URL:-UNSET}"
            " POSTHOG_API_URL=${POSTHOG_API_URL:-UNSET}"
            " ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL:-UNSET};"
            ' node -e "'
            "const dns=require('dns');"
            "dns.resolve('gateway.us.posthog.com',(e,a)=>console.log('DNS_RESOLVE:',e?e.code:JSON.stringify(a)));"
            "dns.lookup('gateway.us.posthog.com',(e,a)=>console.log('DNS_LOOKUP:',e?e.code:a))"
            '" 2>&1;'
            " curl -sS --max-time 5 -o /dev/null"
            " -w 'CURL_GATEWAY: http_code=%{http_code}'"
            " https://gateway.us.posthog.com/health 2>&1 || echo 'CURL_GATEWAY: failed'"
        )

        if ctx.allowed_domains:
            cmd = (
                f"cd /scripts && env -0 > {ENV_FILE} && "
                f"{build_exec_prefix()} {ENV_WRAPPER_SCRIPT} bash -c {shlex.quote(checks)}"
            )
        else:
            cmd = f"bash -c {shlex.quote(checks)}"

        result = sandbox.execute(cmd, timeout_seconds=15)
        output = (result.stdout + "\n" + result.stderr).strip()
        if output:
            emit_agent_log(ctx.run_id, "debug", f"Connectivity diagnostics:\n{output}")
    except Exception as e:
        logger.warning("Connectivity diagnostics failed (non-fatal)", error=str(e), run_id=ctx.run_id)


@dataclass
class StartAgentServerInput:
    context: TaskProcessingContext
    sandbox_id: str
    sandbox_url: str
    sandbox_connect_token: str | None = None
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"


@dataclass
class StartAgentServerOutput:
    sandbox_url: str
    connect_token: str | None = None


@activity.defn
@asyncify
def start_agent_server(input: StartAgentServerInput) -> StartAgentServerOutput:
    """Start the agent-server HTTP server in the sandbox.

    Sandbox credentials (sandbox_url, connect_token) are passed directly via input
    from get_sandbox_for_repository output.
    """
    ctx = input.context

    with log_activity_execution(
        "start_agent_server",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        sandbox_url = input.sandbox_url
        connect_token = input.sandbox_connect_token

        emit_agent_log(ctx.run_id, "info", "Starting agent server")

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        scopes: PosthogMcpScopes = input.posthog_mcp_scopes

        try:
            task = Task.objects.select_related("created_by").get(id=ctx.task_id)
            access_token = create_oauth_access_token(task, scopes=scopes)
        except OAuthTokenError:
            raise
        except Exception as e:
            raise OAuthTokenError(
                f"Failed to create OAuth access token for MCP auth in task {ctx.task_id}",
                {"task_id": ctx.task_id, "error": str(e)},
                cause=e,
            )

        mcp_configs = get_sandbox_ph_mcp_configs(
            token=access_token,
            project_id=ctx.team_id,
            scopes=scopes,
        )
        if task.created_by_id:
            user_mcp_configs = get_user_mcp_server_configs(
                token=access_token,
                team_id=ctx.team_id,
                user_id=task.created_by_id,
            )
            if user_mcp_configs:
                mcp_configs = mcp_configs + user_mcp_configs

        if mcp_configs:
            emit_agent_log(
                ctx.run_id,
                "debug",
                f"Resolved {len(mcp_configs)} MCP config(s) for agent server: {', '.join(config.name for config in mcp_configs)}",
            )
        else:
            emit_agent_log(
                ctx.run_id,
                "warn",
                "No MCP configs were resolved for this run. PostHog MCP tools will be unavailable in the agent session.",
            )

        if ctx.allowed_domains:
            environment_name = ctx.sandbox_environment_name or ctx.sandbox_environment_id or "selected environment"
            emit_agent_log(
                ctx.run_id,
                "debug",
                f"Applying agentsh network policy for '{environment_name}' with allowlist: {format_allowed_domains_for_log(ctx.allowed_domains)}",
            )
        elif ctx.sandbox_environment_id:
            environment_name = ctx.sandbox_environment_name or ctx.sandbox_environment_id
            emit_agent_log(
                ctx.run_id,
                "debug",
                f"Sandbox environment '{environment_name}' grants full network access; starting without agentsh restrictions",
            )

        try:
            sandbox.start_agent_server(
                repository=ctx.repository,
                task_id=ctx.task_id,
                run_id=ctx.run_id,
                mode=ctx.mode,
                create_pr=ctx.create_pr,
                interaction_origin=ctx.interaction_origin,
                branch=ctx.branch,
                runtime_adapter=ctx.runtime_adapter,
                provider=ctx.provider,
                model=ctx.model,
                reasoning_effort=ctx.reasoning_effort,
                mcp_configs=mcp_configs or None,
                allowed_domains=ctx.allowed_domains,
            )

            # emit agentsh logs
            if ctx.allowed_domains:
                _emit_agentsh_log_tail(ctx, sandbox)
        except Exception as e:
            if ctx.allowed_domains:
                _emit_agentsh_log_tail(ctx, sandbox)
            _emit_agent_server_log_tail(ctx, sandbox)
            raise SandboxExecutionError(
                "Failed to start agent server in sandbox",
                {
                    "task_id": ctx.task_id,
                    "sandbox_id": input.sandbox_id,
                    "repository": ctx.repository,
                    "error": str(e),
                },
                cause=e,
            )

        if ctx.allowed_domains:
            emit_agent_log(ctx.run_id, "debug", "agentsh policy initialized successfully")
            _emit_agentsh_log_tail(ctx, sandbox)
        _emit_agent_server_log_tail(ctx, sandbox)

        # Connectivity diagnostics — run inside the agentsh exec context when
        # domains are restricted so we can verify the env wrapper + DNS proxy work.
        _run_connectivity_diagnostics(ctx, sandbox)

        emit_agent_log(ctx.run_id, "info", f"Agent server started at {sandbox_url}")
        activity.logger.info(f"Agent server started at {sandbox_url} for task {ctx.task_id}")

        return StartAgentServerOutput(sandbox_url=sandbox_url, connect_token=connect_token)
