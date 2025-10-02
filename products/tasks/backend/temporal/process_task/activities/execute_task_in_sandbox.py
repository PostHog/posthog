from dataclasses import dataclass
from typing import Optional

from temporalio import activity

from products.tasks.backend.services.sandbox_agent import SandboxAgent
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment


@dataclass
class ExecuteTaskInput:
    sandbox_id: str
    task_id: str
    repository: str


@dataclass
class ExecuteTaskOutput:
    stdout: str
    stderr: str
    exit_code: int
    error: Optional[str] = None


@activity.defn
async def execute_task_in_sandbox(input: ExecuteTaskInput) -> ExecuteTaskOutput:
    """Execute the code agent task in the sandbox."""
    sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)
    agent = SandboxAgent(sandbox)

    result = await agent.execute_task(input.task_id, input.repository)

    if result.exit_code != 0:
        raise RuntimeError(f"Task execution failed: {result.stderr}")

    return ExecuteTaskOutput(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        error=result.error,
    )
