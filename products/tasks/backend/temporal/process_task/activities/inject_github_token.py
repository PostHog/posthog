import shlex
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox
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
@asyncify
def inject_github_token(input: InjectGitHubTokenInput) -> None:
    with log_activity_execution(
        "inject_github_token",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        sandbox_id=input.sandbox_id,
        github_integration_id=input.github_integration_id,
    ):
        try:
            github_token = get_github_token(input.github_integration_id) or ""
        except Exception as e:
            raise GitHubAuthenticationError(
                f"Failed to get GitHub token for integration {input.github_integration_id}",
                {"github_integration_id": input.github_integration_id, "error": str(e)},
            )

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        escaped_github_token = shlex.quote(github_token)
        command = f"echo 'export GITHUB_TOKEN=\"{escaped_github_token}\"' >> ~/.bashrc"

        activity.logger.info(f"Executing command: {command}")
        result = sandbox.execute(command)
        activity.logger.info(
            f"Command result - exit_code: {result.exit_code}, stdout: {result.stdout}, stderr: {result.stderr}"
        )

        if result.exit_code != 0:
            raise SandboxExecutionError(
                f"Failed to inject GitHub token into sandbox",
                {"sandbox_id": input.sandbox_id, "exit_code": result.exit_code, "stderr": result.stderr[:500]},
            )

        verify_result = sandbox.execute("bash -c 'source ~/.bashrc && echo $GITHUB_TOKEN'")
        activity.logger.info(
            f"Verification result - exit_code: {verify_result.exit_code}, stdout: {verify_result.stdout}, stderr: {verify_result.stderr}"
        )
