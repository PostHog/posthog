from dataclasses import dataclass

from temporalio import activity

from products.tasks.backend.services.sandbox_agent import SandboxAgent
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment
from products.tasks.backend.temporal.exceptions import RepositorySetupError
from products.tasks.backend.temporal.observability import log_activity_execution


@dataclass
class SetupRepositoryInput:
    sandbox_id: str
    repository: str
    task_id: str
    distinct_id: str


@activity.defn
async def setup_repository(input: SetupRepositoryInput) -> str:
    """Run code agent setup on repository. Returns setup logs."""
    async with log_activity_execution(
        "setup_repository",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        sandbox_id=input.sandbox_id,
        repository=input.repository,
    ):
        sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)

        agent = SandboxAgent(sandbox)

        try:
            result = await agent.setup_repository(input.repository)
        except Exception as e:
            raise RepositorySetupError(
                f"Failed to setup repository {input.repository}",
                {"repository": input.repository, "sandbox_id": input.sandbox_id, "error": str(e)},
            )

        if result.exit_code != 0:
            raise RepositorySetupError(
                f"Repository setup failed with exit code {result.exit_code}",
                {"repository": input.repository, "exit_code": result.exit_code, "stderr": result.stderr[:500]},
            )

        return result.stdout
