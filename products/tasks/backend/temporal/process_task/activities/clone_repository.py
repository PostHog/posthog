from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import GitHubAuthenticationError, RepositoryCloneError
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution

from ..utils import get_github_token
from .get_task_processing_context import TaskProcessingContext


@dataclass
class CloneRepositoryInput:
    context: TaskProcessingContext
    sandbox_id: str


@activity.defn
@asyncify
def clone_repository(input: CloneRepositoryInput) -> str:
    """Clone repository into sandbox. Idempotent: wipes existing directory. Returns clone logs."""
    ctx = input.context

    with log_activity_execution(
        "clone_repository",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "info", f"Cloning repository {ctx.repository}")

        try:
            github_token = get_github_token(ctx.github_integration_id)
        except Exception as e:
            raise GitHubAuthenticationError(
                f"Failed to get GitHub token for integration {ctx.github_integration_id}",
                {"github_integration_id": ctx.github_integration_id, "task_id": ctx.task_id, "error": str(e)},
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
                    "task_id": ctx.task_id,
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
                    "task_id": ctx.task_id,
                },
                cause=RuntimeError(f"Git clone exited with code {result.exit_code}: {result.stderr[:200]}"),
            )

        # NOTE: git clone returns it's output in stderr
        return result.stderr
