from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxSnapshot


@dataclass
class CheckSnapshotExistsForRepositoryInput:
    github_integration_id: int
    repository: str


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
    snapshot = SandboxSnapshot.get_latest_snapshot_with_repos(
        input.github_integration_id, [input.repository], status=SandboxSnapshot.Status.COMPLETE
    )

    if snapshot:
        return CheckSnapshotExistsForRepositoryOutput(exists=True, snapshot_id=str(snapshot.id))

    return CheckSnapshotExistsForRepositoryOutput(exists=False, snapshot_id=None)
