from dataclasses import dataclass

from temporalio import activity

from products.tasks.backend.services.sandbox_environment import SandboxEnvironment

from ..utils import get_github_token


@dataclass
class InjectGitHubTokenInput:
    sandbox_id: str
    github_integration_id: int


@activity.defn
async def inject_github_token(input: InjectGitHubTokenInput) -> None:
    github_token = await get_github_token(input.github_integration_id)

    if not github_token:
        raise RuntimeError("Unable to get a valid github token from the integration.")

    sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)

    result = await sandbox.execute(
        f"echo 'export GITHUB_TOKEN=\"{github_token}\"' >> ~/.bash_profile && echo 'export GITHUB_TOKEN=\"{github_token}\"' >> ~/.bashrc"
    )

    if result.exit_code != 0:
        raise RuntimeError(f"Failed to inject GitHub token: {result.stderr}")
