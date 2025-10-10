from dataclasses import dataclass
from typing import Optional

from temporalio import activity

from products.tasks.backend.services.sandbox_agent import SandboxAgent
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment
from products.tasks.backend.temporal.exceptions import SandboxExecutionError, TaskExecutionFailedError
from products.tasks.backend.temporal.observability import log_activity_execution


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
            raise TaskExecutionFailedError(
                f"Task execution failed with exit code {result.exit_code}",
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                context={"task_id": input.task_id, "sandbox_id": input.sandbox_id},
            )

        return ExecuteTaskOutput(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            error=result.error,
        )
