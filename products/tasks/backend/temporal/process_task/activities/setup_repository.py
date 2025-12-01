from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import RetryableRepositorySetupError
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution

from .get_task_processing_context import TaskProcessingContext


@dataclass
class SetupRepositoryInput:
    context: TaskProcessingContext
    sandbox_id: str


@activity.defn
@asyncify
def setup_repository(input: SetupRepositoryInput) -> str:
    """Run code agent setup on repository. Returns setup logs."""
    ctx = input.context

    with log_activity_execution(
        "setup_repository",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "info", "Installing dependencies and setting up repository")

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        try:
            result = sandbox.setup_repository(ctx.repository)
        except Exception as e:
            raise RetryableRepositorySetupError(
                f"Failed to setup repository {ctx.repository}",
                {
                    "repository": ctx.repository,
                    "sandbox_id": input.sandbox_id,
                    "task_id": ctx.task_id,
                    "error": str(e),
                },
                cause=e,
            )

        if result.exit_code != 0:
            raise RetryableRepositorySetupError(
                f"Repository setup failed with exit code {result.exit_code}",
                {
                    "repository": ctx.repository,
                    "exit_code": result.exit_code,
                    "stderr": result.stderr[:500],
                    "task_id": ctx.task_id,
                },
                cause=RuntimeError(f"Setup exited with code {result.exit_code}: {result.stderr[:200]}"),
            )

        is_clean, status_output = sandbox.is_git_clean(ctx.repository)

        if not is_clean:
            raise RetryableRepositorySetupError(
                "Repository setup left uncommitted changes. Cannot snapshot with modified git state.",
                {
                    "repository": ctx.repository,
                    "task_id": ctx.task_id,
                    "uncommitted_changes": status_output[:500],
                },
                cause=RuntimeError(f"Uncommitted changes: {status_output[:200]}"),
            )

        return result.stdout
