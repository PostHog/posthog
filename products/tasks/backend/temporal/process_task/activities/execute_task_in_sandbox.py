from dataclasses import dataclass

from temporalio import activity

from products.tasks.backend.services.sandbox_agent import SandboxAgent
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment


@dataclass
class ExecuteTaskInput:
    sandbox_id: str
    task_id: str
    repository: str


@activity.defn
async def execute_task_in_sandbox(input: ExecuteTaskInput) -> None:
    """Execute the code agent task in the sandbox."""
    sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)
    agent = SandboxAgent(sandbox)

    result = await agent.execute_task(input.task_id, input.repository)

    if result.exit_code != 0:
        raise RuntimeError(f"Task execution failed: {result.stderr}")
