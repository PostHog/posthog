from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.exceptions import RetryableRepositorySetupError
from products.tasks.backend.temporal.observability import log_activity_execution


@dataclass
class SetupRepositoryInput:
    sandbox_id: str
    repository: str
    task_id: str
    distinct_id: str


@activity.defn
@asyncify
def setup_repository(input: SetupRepositoryInput) -> str:
    """Run code agent setup on repository. Returns setup logs."""
    with log_activity_execution(
        "setup_repository",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        sandbox_id=input.sandbox_id,
        repository=input.repository,
    ):
        sandbox = Sandbox.get_by_id(input.sandbox_id)

        try:
            result = sandbox.setup_repository(input.repository)
        except Exception as e:
            raise RetryableRepositorySetupError(
                f"Failed to setup repository {input.repository}",
                {"repository": input.repository, "sandbox_id": input.sandbox_id, "error": str(e)},
            )

        if result.exit_code != 0:
            raise RetryableRepositorySetupError(
                f"Repository setup failed with exit code {result.exit_code}",
                {"repository": input.repository, "exit_code": result.exit_code, "stderr": result.stderr[:500]},
            )

        is_clean, status_output = sandbox.is_git_clean(input.repository)

        if not is_clean:
            raise RetryableRepositorySetupError(
                "Repository setup left uncommitted changes. Cannot snapshot with modified git state.",
                {
                    "repository": input.repository,
                    "uncommitted_changes": status_output[:500],
                },
            )

        return result.stdout
