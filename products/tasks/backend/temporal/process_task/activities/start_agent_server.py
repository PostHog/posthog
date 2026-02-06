from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import SandboxExecutionError
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution

from .get_task_processing_context import TaskProcessingContext

logger = get_logger(__name__)


@dataclass
class StartAgentServerInput:
    context: TaskProcessingContext
    sandbox_id: str


@dataclass
class StartAgentServerOutput:
    sandbox_url: str
    connect_token: str | None = None


@activity.defn
@asyncify
def start_agent_server(input: StartAgentServerInput) -> StartAgentServerOutput:
    """Start the agent-server HTTP server in the sandbox.

    Credentials (sandbox_url, connect_token) must already be stored in TaskRun state
    by get_sandbox_for_repository before calling this activity.
    """
    ctx = input.context

    with log_activity_execution(
        "start_agent_server",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        task_run = TaskRun.objects.get(id=ctx.run_id)
        state = task_run.state or {}

        sandbox_url = state.get("sandbox_url")
        connect_token = state.get("sandbox_connect_token")

        if not sandbox_url:
            raise SandboxExecutionError(
                "Sandbox URL not found in TaskRun state - get_sandbox_for_repository must be called first",
                {
                    "task_id": ctx.task_id,
                    "sandbox_id": input.sandbox_id,
                    "run_id": ctx.run_id,
                },
            )

        emit_agent_log(ctx.run_id, "info", "Starting agent server in development environment")

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        try:
            sandbox.start_agent_server(
                repository=ctx.repository,
                task_id=ctx.task_id,
                run_id=ctx.run_id,
                mode=ctx.mode,
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
