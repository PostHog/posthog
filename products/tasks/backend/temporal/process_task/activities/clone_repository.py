from dataclasses import dataclass

from temporalio import activity

from products.tasks.backend.services.sandbox_agent import SandboxAgent
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment
from products.tasks.backend.temporal.exceptions import GitHubAuthenticationError, RepositoryCloneError
from products.tasks.backend.temporal.observability import log_activity_execution

from ..utils import get_github_token


@dataclass
class CloneRepositoryInput:
    sandbox_id: str
    repository: str
    github_integration_id: int
    task_id: str
    distinct_id: str


@activity.defn
async def clone_repository(input: CloneRepositoryInput) -> str:
    """Clone repository into sandbox. Idempotent: wipes existing directory. Returns clone logs."""
    async with log_activity_execution(
        "clone_repository",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        sandbox_id=input.sandbox_id,
        repository=input.repository,
    ):
        try:
            github_token = await get_github_token(input.github_integration_id)
        except Exception as e:
            raise GitHubAuthenticationError(
                f"Failed to get GitHub token for integration {input.github_integration_id}",
                {"github_integration_id": input.github_integration_id, "error": str(e)},
            )

        sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)

        agent = SandboxAgent(sandbox)

        try:
            result = await agent.clone_repository(input.repository, github_token)
        except Exception as e:
            raise RepositoryCloneError(
                f"Failed to clone repository {input.repository}",
                {"repository": input.repository, "sandbox_id": input.sandbox_id, "error": str(e)},
            )

        if result.exit_code != 0:
            raise RepositoryCloneError(
                f"Git clone failed with exit code {result.exit_code}",
                {
                    "repository": input.repository,
                    "exit_code": result.exit_code,
                    "stderr": result.stderr[:500],
                },
            )

        # NOTE: git clone returns it's output in stderr
        return result.stderr
