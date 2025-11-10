import json
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import log_activity_execution


@dataclass
class CreateSnapshotInput:
    sandbox_id: str
    github_integration_id: int
    team_id: int
    repository: str
    task_id: str
    distinct_id: str


@activity.defn
@asyncify
def create_snapshot(input: CreateSnapshotInput) -> str:
    """
    Create and finalize snapshot. Creates and saves the snapshot record. Returns snapshot_id.
    """
    with log_activity_execution(
        "create_snapshot",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        sandbox_id=input.sandbox_id,
        repository=input.repository,
    ):
        base_snapshot = SandboxSnapshot.get_latest_snapshot_for_integration(input.github_integration_id)

        base_repos = base_snapshot.repos if base_snapshot else []
        new_repos: list[str] = list({*base_repos, input.repository})

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        snapshot_external_id = sandbox.create_snapshot(
            {
                "integration_id": str(input.github_integration_id),
                "team_id": str(input.team_id),
                "repositories": json.dumps(new_repos),
                "base_snapshot_id": str(base_snapshot.id) if base_snapshot else "",
            }
        )

        snapshot = SandboxSnapshot.objects.create(
            integration_id=input.github_integration_id,
            repos=new_repos,
            external_id=snapshot_external_id,
            status=SandboxSnapshot.Status.COMPLETE,
        )

        return str(snapshot.id)
