from dataclasses import dataclass

from temporalio import activity

from products.tasks.backend.services.sandbox_environment import SandboxEnvironment
from products.tasks.backend.temporal.exceptions import GitHubAuthenticationError, SandboxExecutionError
from products.tasks.backend.temporal.observability import log_activity_execution

from ..utils import get_github_token


@dataclass
class InjectGitHubTokenInput:
    sandbox_id: str
    github_integration_id: int
    task_id: str
    distinct_id: str


@activity.defn
async def inject_github_token(input: InjectGitHubTokenInput) -> None:
    async with log_activity_execution(
        "inject_github_token",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        sandbox_id=input.sandbox_id,
        github_integration_id=input.github_integration_id,
    ):
        try:
            github_token = await get_github_token(input.github_integration_id)
        except Exception as e:
            raise GitHubAuthenticationError(
                f"Failed to get GitHub token for integration {input.github_integration_id}",
                {"github_integration_id": input.github_integration_id, "error": str(e)},
            )

        if not github_token:
            raise GitHubAuthenticationError(
                "Unable to get a valid GitHub token from the integration",
                {"github_integration_id": input.github_integration_id},
            )

        try:
            sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)
        except Exception as e:
            raise SandboxExecutionError(
                f"Failed to get sandbox {input.sandbox_id}",
                {"sandbox_id": input.sandbox_id, "error": str(e)},
            )

        result = await sandbox.execute(
            f"echo 'export GITHUB_TOKEN=\"{github_token}\"' >> ~/.bash_profile && echo 'export GITHUB_TOKEN=\"{github_token}\"' >> ~/.bashrc"
        )

        if result.exit_code != 0:
            raise SandboxExecutionError(
                f"Failed to inject GitHub token into sandbox",
                {"sandbox_id": input.sandbox_id, "exit_code": result.exit_code, "stderr": result.stderr[:500]},
            )
