from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.services.sandbox import AgentServerResult, Sandbox
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


def _update_task_run_state(run_id: str, sandbox_id: str, result: AgentServerResult) -> None:
    """Update TaskRun state with sandbox information."""
    logger.info(
        "Updating TaskRun state",
        run_id=run_id,
        sandbox_id=sandbox_id,
        sandbox_url=result.url,
        has_token=result.token is not None,
    )

    task_run = TaskRun.objects.get(id=run_id)
    state = task_run.state or {}
    state["sandbox_id"] = sandbox_id
    state["sandbox_url"] = result.url
    if result.token:
        state["sandbox_connect_token"] = result.token
    task_run.state = state
    task_run.save(update_fields=["state", "updated_at"])

    task_run.refresh_from_db()
    saved_url = (task_run.state or {}).get("sandbox_url")
    if saved_url != result.url:
        raise RuntimeError(f"Failed to persist sandbox_url: expected {result.url}, got {saved_url}")

    logger.info("TaskRun state updated successfully", run_id=run_id, sandbox_url=saved_url)


@activity.defn
@asyncify
def start_agent_server(input: StartAgentServerInput) -> StartAgentServerOutput:
    """Start the agent-server HTTP server in the sandbox."""
    ctx = input.context

    with log_activity_execution(
        "start_agent_server",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "info", "Starting agent server in development environment")

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        try:
            result = sandbox.start_agent_server(
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

        _update_task_run_state(ctx.run_id, input.sandbox_id, result)

        emit_agent_log(ctx.run_id, "info", f"Agent server started at {result.url}")
        activity.logger.info(f"Agent server started at {result.url} for task {ctx.task_id}")

        return StartAgentServerOutput(sandbox_url=result.url, connect_token=result.token)
