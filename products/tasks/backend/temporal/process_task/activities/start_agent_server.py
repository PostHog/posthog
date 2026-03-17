from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import asyncify
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.models import Task
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import OAuthTokenError, SandboxExecutionError
from products.tasks.backend.temporal.oauth import create_oauth_access_token
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution
from products.tasks.backend.temporal.process_task.utils import get_sandbox_mcp_configs

from .get_task_processing_context import TaskProcessingContext

logger = get_logger(__name__)


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

        emit_agent_log(ctx.run_id, "info", "Starting agent server in development environment")

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

        mcp_configs = get_sandbox_mcp_configs(
            token=access_token,
            project_id=ctx.team_id,
            scopes=scopes,
        )

        try:
            sandbox.start_agent_server(
                repository=ctx.repository,
                task_id=ctx.task_id,
                run_id=ctx.run_id,
                mode=ctx.mode,
                interaction_origin=ctx.interaction_origin,
                branch=ctx.branch,
                mcp_configs=mcp_configs or None,
                allowed_domains=ctx.allowed_domains,
            )
        except Exception as e:
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

        emit_agent_log(ctx.run_id, "info", f"Agent server started at {sandbox_url}")
        activity.logger.info(f"Agent server started at {sandbox_url} for task {ctx.task_id}")

        return StartAgentServerOutput(sandbox_url=sandbox_url, connect_token=connect_token)
