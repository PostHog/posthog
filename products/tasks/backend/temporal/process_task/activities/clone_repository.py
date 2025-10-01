from dataclasses import dataclass

from temporalio import activity

from products.tasks.backend.services.sandbox_agent import SandboxAgent
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment

from ..utils import get_github_token


@dataclass
class CloneRepositoryInput:
    sandbox_id: str
    repository: str
    github_integration_id: int


@activity.defn
async def clone_repository(input: CloneRepositoryInput) -> str:
    """Clone repository into sandbox. Idempotent: wipes existing directory. Returns clone logs."""
    github_token = await get_github_token(input.github_integration_id)

    sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)
    agent = SandboxAgent(sandbox)
    result = await agent.clone_repository(input.repository, github_token)

    if result.exit_code != 0:
        raise RuntimeError(f"Failed to clone repository: {result.stderr}")

    return result.stdout
