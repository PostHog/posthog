from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import GitHubAuthenticationError, RepositoryCloneError
from products.tasks.backend.temporal.observability import log_activity_execution

from ..utils import get_github_token
from .get_snapshot_context import SnapshotContext


@dataclass
class CloneRepositoryInput:
    context: SnapshotContext
    sandbox_id: str


@activity.defn
@asyncify
def clone_repository(input: CloneRepositoryInput) -> str:
    ctx = input.context

    with log_activity_execution(
        "clone_repository",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        try:
            github_token = get_github_token(ctx.github_integration_id)
        except Exception as e:
            raise GitHubAuthenticationError(
                f"Failed to get GitHub token for integration {ctx.github_integration_id}",
                {"github_integration_id": ctx.github_integration_id, "error": str(e)},
                cause=e,
            )

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        try:
            result = sandbox.clone_repository(ctx.repository, github_token)
        except Exception as e:
            raise RepositoryCloneError(
                f"Failed to clone repository {ctx.repository}",
                {
                    "repository": ctx.repository,
                    "sandbox_id": input.sandbox_id,
                    "error": str(e),
                },
                cause=e,
            )

        if result.exit_code != 0:
            raise RepositoryCloneError(
                f"Git clone failed with exit code {result.exit_code}",
                {
                    "repository": ctx.repository,
                    "exit_code": result.exit_code,
                    "stderr": result.stderr[:500],
                },
                cause=RuntimeError(f"Git clone exited with code {result.exit_code}: {result.stderr[:200]}"),
            )

        return result.stderr
