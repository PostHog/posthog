from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import RetryableRepositorySetupError
from products.tasks.backend.temporal.observability import log_activity_execution

from .get_snapshot_context import SnapshotContext


@dataclass
class SetupRepositoryInput:
    context: SnapshotContext
    sandbox_id: str


@activity.defn
@asyncify
def setup_repository(input: SetupRepositoryInput) -> str:
    ctx = input.context

    with log_activity_execution(
        "setup_repository",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        sandbox = Sandbox.get_by_id(input.sandbox_id)

        try:
            result = sandbox.setup_repository(ctx.repository)
        except Exception as e:
            raise RetryableRepositorySetupError(
                f"Failed to setup repository {ctx.repository}",
                {
                    "repository": ctx.repository,
                    "sandbox_id": input.sandbox_id,
                    "error": str(e),
                },
                cause=e,
            )

        if result.exit_code != 0:
            raise RetryableRepositorySetupError(
                f"Repository setup failed with exit code {result.exit_code}",
                {
                    "repository": ctx.repository,
                    "exit_code": result.exit_code,
                    "stderr": result.stderr[:500],
                },
                cause=RuntimeError(f"Setup exited with code {result.exit_code}: {result.stderr[:200]}"),
            )

        is_clean, status_output = sandbox.is_git_clean(ctx.repository)

        if not is_clean:
            raise RetryableRepositorySetupError(
                "Repository setup left uncommitted changes. Cannot snapshot with modified git state.",
                {
                    "repository": ctx.repository,
                    "uncommitted_changes": status_output[:500],
                },
                cause=RuntimeError(f"Uncommitted changes: {status_output[:200]}"),
            )

        return result.stdout
