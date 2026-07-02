import shlex
import threading
from dataclasses import dataclass

from django.conf import settings
from django.db import connection

from temporalio import activity

from posthog.models import Integration
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import asyncify
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.exceptions import OAuthTokenError, SandboxExecutionError, SandboxMissingRepositoryError
from products.tasks.backend.logic.services.connection_token import create_sandbox_event_ingest_token
from products.tasks.backend.logic.services.sandbox import REPO_READY_FILE, Sandbox, SandboxBase, sandbox_repo_path
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.metrics import StepTimer, record_agent_server_session_init_ms
from products.tasks.backend.temporal.oauth import create_oauth_access_token
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution
from products.tasks.backend.temporal.process_task.utils import (
    McpServerConfig,
    format_allowed_domains_for_log,
    get_sandbox_ph_mcp_configs,
    get_user_mcp_server_configs,
    mark_mcp_token_issued,
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


def _resolve_protected_base_branch(ctx: TaskProcessingContext) -> str | None:
    """The branch the agent must not commit directly onto (passed to the agent-server as --baseBranch).

    The task's working branch is normally the PR base it was started from, so protecting it is correct.
    But when the working branch itself heads an open PR — e.g. a quick action started on an existing
    posthog-code/* branch the agent is meant to update — the agent must commit *to* that branch, so the
    protected base is the PR's own base instead. Without this the signed-commit guard refuses the very
    branch the run needs to update. Best-effort: any failure falls back to the working branch.
    """
    branch = ctx.branch
    if not branch or not ctx.repository or not ctx.has_github_credentials:
        return branch

    try:
        integration: GitHubIntegration | UserGitHubIntegration
        if ctx.github_integration_id:
            integration = GitHubIntegration(Integration.objects.get(id=ctx.github_integration_id))
            if integration.access_token_expired():
                integration.refresh_access_token()
        else:
            integration = UserGitHubIntegration(UserIntegration.objects.get(id=str(ctx.github_user_integration_id)))
        pr_base = integration.get_open_pr_base_for_head(ctx.repository, branch)
    except Exception:
        logger.warning("resolve_protected_base_branch_failed", task_id=ctx.task_id, run_id=ctx.run_id, exc_info=True)
        return branch

    if pr_base and pr_base != branch:
        emit_agent_log(
            ctx.run_id,
            "debug",
            f"Working branch '{branch}' heads an open PR; protecting its base '{pr_base}' so commits to "
            f"'{branch}' are allowed",
        )
        return pr_base
    return branch


def _ensure_repository_on_disk(ctx: TaskProcessingContext, sandbox: SandboxBase) -> None:
    """Fail fast when the repository the agent-server will use as its cwd was never materialized.

    A run can reach this point without a clone: no snapshot restored and no usable GitHub
    credentials (``will_clone`` is false in the workflow). The agent-server then boots against a
    missing working directory, every ACP ``session/new`` fails, and the health wait times out —
    repeated 5-minute attempts surfacing as a misleading "Failed to start agent server". Check
    the directory upfront and fail non-retryably with the actual reason instead.
    """
    if not ctx.repository:
        return
    repo_path = sandbox_repo_path(ctx.repository)
    result = sandbox.execute(f"test -d {shlex.quote(repo_path)}", timeout_seconds=10)
    if result.exit_code == 0:
        return
    raise SandboxMissingRepositoryError(
        f"Repository {ctx.repository} is not present in the sandbox at {repo_path} — it was never "
        "cloned (no snapshot restored and no usable GitHub credentials for this task)",
        {
            "task_id": ctx.task_id,
            "run_id": ctx.run_id,
            "sandbox_id": sandbox.id,
            "repository": ctx.repository,
            "repo_path": repo_path,
            "github_integration_id": ctx.github_integration_id,
            "github_user_integration_id": ctx.github_user_integration_id,
        },
        cause=RuntimeError(f"missing repository directory {repo_path}"),
    )


@dataclass
class StartAgentServerInput:
    context: TaskProcessingContext
    sandbox_id: str
    sandbox_url: str
    sandbox_connect_token: str | None = None
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"
    defer_for_clone: bool = False


@dataclass
class MarkRepoReadyInput:
    sandbox_id: str
    run_id: str


@dataclass
class StartAgentServerOutput:
    sandbox_url: str
    connect_token: str | None = None


@dataclass
class _LaunchParams:
    mcp_configs: list[McpServerConfig]
    agentsh_domains: list[str] | None
    protected_base_branch: str | None
    event_ingest_token: str | None
    event_ingest_url: str | None
    event_ingest_keep_stream_open: bool


def _agentsh_domains_for(ctx: TaskProcessingContext) -> list[str] | None:
    # Modal enforces egress at the edge (gVisor only), so agentsh is skipped only when it does.
    return None if (ctx.use_modal_network_allowlist and not ctx.use_modal_vm_sandbox) else ctx.allowed_domains


def _prepare_launch(ctx: TaskProcessingContext, scopes: PosthogMcpScopes) -> _LaunchParams:
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

    event_stream_ingest_enabled = ctx.sandbox_event_ingest_enabled
    event_ingest_token: str | None = None
    # When the agent-proxy is configured, route the sandbox ingest POST to it instead of the
    # Django ASGI short-circuit. Only meaningful once sequenced ingest is enabled. Unset means
    # the agent falls back to POSTHOG_API_URL (Django).
    event_ingest_url: str | None = settings.TASKS_AGENT_PROXY_INGEST_URL if event_stream_ingest_enabled else None
    if event_stream_ingest_enabled:
        try:
            task_run = TaskRun.objects.get(id=ctx.run_id, task_id=ctx.task_id, team_id=ctx.team_id)
            event_ingest_token = create_sandbox_event_ingest_token(task_run)
        except Exception as e:
            raise SandboxExecutionError(
                "Failed to create sandbox event ingest token",
                {"task_id": ctx.task_id, "run_id": ctx.run_id, "error": str(e)},
                cause=e,
            )

    mcp_configs = get_sandbox_ph_mcp_configs(
        token=access_token,
        project_id=ctx.team_id,
        scopes=scopes,
        interaction_origin=ctx.interaction_origin,
        task_id=str(ctx.task_id),
    )
    if task.created_by_id:
        user_mcp_configs = get_user_mcp_server_configs(
            token=access_token,
            team_id=ctx.team_id,
            user_id=task.created_by_id,
            interaction_origin=ctx.interaction_origin,
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

    agentsh_domains = _agentsh_domains_for(ctx)
    if ctx.use_modal_network_allowlist and not ctx.use_modal_vm_sandbox and ctx.allowed_domains is not None:
        environment_name = ctx.sandbox_environment_name or ctx.sandbox_environment_id or "selected environment"
        emit_agent_log(
            ctx.run_id,
            "debug",
            f"Enforcing network allowlist for '{environment_name}' via Modal (agentsh disabled)",
        )
    elif agentsh_domains is not None:
        environment_name = ctx.sandbox_environment_name or ctx.sandbox_environment_id or "selected environment"
        emit_agent_log(
            ctx.run_id,
            "debug",
            f"Applying agentsh network policy for '{environment_name}' with allowlist: {format_allowed_domains_for_log(agentsh_domains)}",
        )
    elif ctx.sandbox_environment_id:
        environment_name = ctx.sandbox_environment_name or ctx.sandbox_environment_id
        emit_agent_log(
            ctx.run_id,
            "debug",
            f"Sandbox environment '{environment_name}' grants full network access; starting without agentsh restrictions",
        )

    protected_base_branch = _resolve_protected_base_branch(ctx)

    return _LaunchParams(
        mcp_configs=mcp_configs,
        agentsh_domains=agentsh_domains,
        protected_base_branch=protected_base_branch,
        event_ingest_token=event_ingest_token,
        event_ingest_url=event_ingest_url,
        event_ingest_keep_stream_open=ctx.agent_proxy_keep_stream_open,
    )


def _invoke_start_agent_server(
    sandbox: SandboxBase,
    ctx: TaskProcessingContext,
    params: _LaunchParams,
    *,
    repo_ready_file: str | None,
    wait_for_health: bool,
) -> None:
    try:
        sandbox.start_agent_server(
            repository=ctx.repository,
            task_id=ctx.task_id,
            run_id=ctx.run_id,
            mode=ctx.mode,
            create_pr=ctx.create_pr,
            interaction_origin=ctx.interaction_origin,
            branch=params.protected_base_branch,
            runtime_adapter=ctx.runtime_adapter,
            provider=ctx.provider,
            model=ctx.model,
            reasoning_effort=ctx.reasoning_effort,
            mcp_configs=params.mcp_configs or None,
            allowed_domains=params.agentsh_domains,
            event_ingest_token=params.event_ingest_token,
            event_ingest_url=params.event_ingest_url,
            event_ingest_keep_stream_open=params.event_ingest_keep_stream_open,
            repo_ready_file=repo_ready_file,
            wait_for_health=wait_for_health,
        )

        # Mark startup-time token issuance so follow-ups within the next
        # 30m window skip the redundant refresh.
        if params.mcp_configs:
            mark_mcp_token_issued(ctx.run_id)
    except Exception as e:
        if params.agentsh_domains is not None:
            _emit_agentsh_log_tail(ctx, sandbox)
        _emit_agent_server_log_tail(ctx, sandbox)
        raise SandboxExecutionError(
            "Failed to start agent server in sandbox",
            {
                "task_id": ctx.task_id,
                "sandbox_id": sandbox.id,
                "repository": ctx.repository,
                "error": str(e),
            },
            cause=e,
        )


def _spawn_post_ready_diagnostics(
    ctx: TaskProcessingContext, sandbox: SandboxBase, agentsh_domains: list[str] | None
) -> None:
    def _run() -> None:
        try:
            if agentsh_domains is not None:
                emit_agent_log(ctx.run_id, "debug", "agentsh policy initialized successfully")
                _emit_agentsh_log_tail(ctx, sandbox)
            _emit_agent_server_log_tail(ctx, sandbox)
        except Exception:
            logger.warning("post_ready_diagnostics_failed", run_id=ctx.run_id, exc_info=True)
        finally:
            try:
                connection.close()
            except Exception:
                pass

    threading.Thread(target=_run, name=f"post-ready-diag-{ctx.run_id}", daemon=True).start()


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
        emit_agent_log(ctx.run_id, "debug", "Starting agent server")

        sandbox = Sandbox.get_by_id(input.sandbox_id)
        # Classic (non-deferred) path only: any clone has already happened by now, so a missing
        # repo directory can never appear later. The deferred/overlap path clones in parallel
        # and gates the session on the repo-ready barrier instead.
        _ensure_repository_on_disk(ctx, sandbox)
        params = _prepare_launch(ctx, input.posthog_mcp_scopes)

        with StepTimer("agent_server_ready"):
            _invoke_start_agent_server(sandbox, ctx, params, repo_ready_file=None, wait_for_health=True)

        emit_agent_log(ctx.run_id, "debug", f"Agent server started at {input.sandbox_url}")
        activity.logger.info(f"Agent server started at {input.sandbox_url} for task {ctx.task_id}")

        session_init_ms = sandbox.read_agent_server_session_init_ms()
        if session_init_ms is not None:
            record_agent_server_session_init_ms(session_init_ms)

        _spawn_post_ready_diagnostics(ctx, sandbox, params.agentsh_domains)

        return StartAgentServerOutput(sandbox_url=input.sandbox_url, connect_token=input.sandbox_connect_token)


@activity.defn
@asyncify
def launch_agent_server(input: StartAgentServerInput) -> StartAgentServerOutput:
    ctx = input.context

    with log_activity_execution(
        "launch_agent_server",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "debug", "Launching agent server (deferred readiness)")

        sandbox = Sandbox.get_by_id(input.sandbox_id)
        params = _prepare_launch(ctx, input.posthog_mcp_scopes)

        repo_ready_file = REPO_READY_FILE if input.defer_for_clone else None
        _invoke_start_agent_server(sandbox, ctx, params, repo_ready_file=repo_ready_file, wait_for_health=False)

        activity.logger.info(f"Agent server process launched for task {ctx.task_id}")
        return StartAgentServerOutput(sandbox_url=input.sandbox_url, connect_token=input.sandbox_connect_token)


@activity.defn
@asyncify
def mark_repo_ready(input: MarkRepoReadyInput) -> None:
    sandbox = Sandbox.get_by_id(input.sandbox_id)
    sandbox.mark_repo_ready(REPO_READY_FILE)
    emit_agent_log(input.run_id, "debug", "Repo ready; released agent-server session barrier")


@activity.defn
@asyncify
def await_agent_server_ready(input: StartAgentServerInput) -> StartAgentServerOutput:
    ctx = input.context

    with log_activity_execution(
        "await_agent_server_ready",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        sandbox = Sandbox.get_by_id(input.sandbox_id)
        agentsh_domains = _agentsh_domains_for(ctx)

        try:
            with StepTimer("agent_server_ready"):
                sandbox.wait_for_agent_server_ready(agentsh_domains)
        except Exception:
            if agentsh_domains is not None:
                _emit_agentsh_log_tail(ctx, sandbox)
            _emit_agent_server_log_tail(ctx, sandbox)
            raise

        emit_agent_log(ctx.run_id, "debug", f"Agent server ready at {input.sandbox_url}")
        activity.logger.info(f"Agent server ready at {input.sandbox_url} for task {ctx.task_id}")

        session_init_ms = sandbox.read_agent_server_session_init_ms()
        if session_init_ms is not None:
            record_agent_server_session_init_ms(session_init_ms)

        _spawn_post_ready_diagnostics(ctx, sandbox, agentsh_domains)

        return StartAgentServerOutput(sandbox_url=input.sandbox_url, connect_token=input.sandbox_connect_token)
