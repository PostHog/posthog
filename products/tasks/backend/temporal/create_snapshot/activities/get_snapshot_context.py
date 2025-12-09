from dataclasses import dataclass

from temporalio import activity

from posthog.models.integration import Integration
from posthog.temporal.common.utils import asyncify

from products.tasks.backend.temporal.exceptions import TaskInvalidStateError
from products.tasks.backend.temporal.observability import log_with_activity_context


@dataclass
class SnapshotContext:
    github_integration_id: int
    repository: str
    team_id: int

    def to_log_context(self) -> dict:
        return {
            "github_integration_id": self.github_integration_id,
            "repository": self.repository,
            "team_id": self.team_id,
        }


@dataclass
class GetSnapshotContextInput:
    github_integration_id: int
    repository: str
    team_id: int


@activity.defn
@asyncify
def get_snapshot_context(input: GetSnapshotContextInput) -> SnapshotContext:
    log_with_activity_context(
        "Fetching snapshot context",
        github_integration_id=input.github_integration_id,
        repository=input.repository,
    )

    try:
        Integration.objects.get(id=input.github_integration_id)
    except Integration.DoesNotExist as e:
        raise TaskInvalidStateError(
            f"Integration {input.github_integration_id} not found",
            {"github_integration_id": input.github_integration_id},
            cause=e,
        )

    return SnapshotContext(
        github_integration_id=input.github_integration_id,
        repository=input.repository,
        team_id=input.team_id,
    )
