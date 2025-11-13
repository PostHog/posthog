from dataclasses import dataclass
from typing import Optional

from temporalio import activity

from posthog.temporal.common.logger import get_logger

from products.tasks.backend.services.sandbox_agent import SandboxAgent
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment
from products.tasks.backend.temporal.exceptions import SandboxExecutionError, TaskExecutionFailedError
from products.tasks.backend.temporal.observability import log_activity_execution

logger = get_logger(__name__)


@dataclass
class ExecuteTaskInput:
    sandbox_id: str
    task_id: str
    repository: str
    distinct_id: str


@dataclass
class ExecuteTaskOutput:
    stdout: str
    stderr: str
    exit_code: int
    error: Optional[str] = None


@activity.defn
async def execute_task_in_sandbox(input: ExecuteTaskInput) -> ExecuteTaskOutput:
    """Execute the code agent task in the sandbox."""
    async with log_activity_execution(
        "execute_task_in_sandbox",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        sandbox_id=input.sandbox_id,
        repository=input.repository,
    ):
        sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)

        agent = SandboxAgent(sandbox)

        try:
            result = await agent.execute_task(input.task_id, input.repository)
        except Exception as e:
            raise SandboxExecutionError(
                f"Failed to execute task in sandbox",
                {"task_id": input.task_id, "sandbox_id": input.sandbox_id, "error": str(e)},
            )

        if result.exit_code != 0:
            logger.exception(f"Task execution failed with exit code {result.exit_code} for task {input.task_id}")
            logger.exception(f"stdout: {result.stdout}")
            logger.exception(f"stderr: {result.stderr}")
            logger.exception(f"error: {result.error}")
            raise TaskExecutionFailedError(
                f"Task execution failed with exit code {result.exit_code}",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                context={"task_id": input.task_id, "sandbox_id": input.sandbox_id},
            )
        else:
            logger.info(f"Task execution succeeded with exit code {result.exit_code} for task {input.task_id}")
            logger.info(f"stdout: {result.stdout}")
            logger.info(f"stderr: {result.stderr}")
            logger.info(f"error: {result.error}")

        return ExecuteTaskOutput(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            error=result.error,
        )
