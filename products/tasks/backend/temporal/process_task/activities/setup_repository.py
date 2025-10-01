from dataclasses import dataclass

from temporalio import activity

from products.tasks.backend.services.sandbox_agent import SandboxAgent
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment


@dataclass
class SetupRepositoryInput:
    sandbox_id: str
    repository: str


@activity.defn
async def setup_repository(input: SetupRepositoryInput) -> str:
    """Run code agent setup on repository. Returns setup logs."""
    sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)
    agent = SandboxAgent(sandbox)
    result = await agent.setup_repository(input.repository)

    if result.exit_code != 0:
        raise RuntimeError(f"Failed to setup repository: {result.stderr}")

    return result.stdout
