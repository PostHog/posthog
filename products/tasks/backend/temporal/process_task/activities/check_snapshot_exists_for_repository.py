from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.observability import emit_agent_log, log_with_activity_context

from .get_task_processing_context import TaskProcessingContext


@dataclass
class CheckSnapshotExistsForRepositoryInput:
    context: TaskProcessingContext


@dataclass
class CheckSnapshotExistsForRepositoryOutput:
    exists: bool
    snapshot_id: str | None


@activity.defn
@asyncify
def check_snapshot_exists_for_repository(
    input: CheckSnapshotExistsForRepositoryInput,
) -> CheckSnapshotExistsForRepositoryOutput:
    """Check if a repository exists in the latest complete snapshot."""
    ctx = input.context

    log_with_activity_context(
        "Checking if snapshot exists for repository",
        **ctx.to_log_context(),
    )

    snapshot = SandboxSnapshot.get_latest_snapshot_with_repos(ctx.github_integration_id, [ctx.repository])

    if snapshot:
        emit_agent_log(ctx.run_id, "info", f"Found existing development environment for repository {ctx.repository}")
        return CheckSnapshotExistsForRepositoryOutput(exists=True, snapshot_id=str(snapshot.id))

    emit_agent_log(
        ctx.run_id,
        "info",
        f"Did not find an existing development environment for repository {ctx.repository}, creating one (this may take a few minutes to complete)",
    )
    return CheckSnapshotExistsForRepositoryOutput(exists=False, snapshot_id=None)
