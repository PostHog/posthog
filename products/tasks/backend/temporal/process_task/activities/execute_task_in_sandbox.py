from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import TaskRun
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import SandboxExecutionError, TaskExecutionFailedError
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution

from .get_task_processing_context import TaskProcessingContext

logger = get_logger(__name__)


@dataclass
class ExecuteTaskInput:
    context: TaskProcessingContext
    sandbox_id: str


@dataclass
class ExecuteTaskOutput:
    stdout: str
    stderr: str
    exit_code: int
    error: str | None = None


def _emit_sandbox_output(run_id: str, stdout: str, stderr: str, exit_code: int) -> None:
    """Emit sandbox stdout/stderr to S3 logs as structured ACP notification."""
    try:
        task_run = TaskRun.objects.get(id=run_id)
        task_run.emit_sandbox_output(stdout, stderr, exit_code)
    except TaskRun.DoesNotExist:
        logger.warning("TaskRun not found for sandbox output", run_id=run_id)
    except Exception:
        logger.exception("Failed to emit sandbox output", run_id=run_id)


@activity.defn
@asyncify
def execute_task_in_sandbox(input: ExecuteTaskInput) -> ExecuteTaskOutput:
    """Execute the code agent task in the sandbox."""
    ctx = input.context

    with log_activity_execution(
        "execute_task_in_sandbox",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "info", "Initiating task execution in development environment")

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        try:
            result = sandbox.execute_task(
                task_id=ctx.task_id, run_id=ctx.run_id, repository=ctx.repository, create_pr=ctx.create_pr
            )
        except Exception as e:
            raise SandboxExecutionError(
                "Failed to execute task in sandbox",
                {
                    "task_id": ctx.task_id,
                    "sandbox_id": input.sandbox_id,
                    "repository": ctx.repository,
                    "error": str(e),
                },
                cause=e,
            )

        _emit_sandbox_output(ctx.run_id, result.stdout, result.stderr, result.exit_code)

        if result.exit_code != 0:
            logger.error(f"Task execution failed for task {ctx.task_id}")
            logger.error(f"stdout:\n{result.stdout}")
            logger.error(f"stderr:\n{result.stderr}")
            raise TaskExecutionFailedError(
                f"Task execution failed with exit code {result.exit_code}",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                context={"task_id": ctx.task_id, "sandbox_id": input.sandbox_id},
            )
        else:
            activity.logger.info(f"Task execution succeeded with exit code {result.exit_code} for task {ctx.task_id}")

        return ExecuteTaskOutput(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            error=result.error,
        )
