import json
import asyncio
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from temporalio import activity

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox_environment import SandboxEnvironment
from products.tasks.backend.temporal.exceptions import SandboxTimeoutError, SnapshotCreationError
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
async def create_snapshot(input: CreateSnapshotInput) -> str:
    """
    Create and finalize snapshot. Initiates snapshot, polls until complete,
    and saves the snapshot record. Returns snapshot_id.
    """
    async with log_activity_execution(
        "create_snapshot",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        sandbox_id=input.sandbox_id,
        repository=input.repository,
    ):
        base_snapshot = await sync_to_async(SandboxSnapshot.get_latest_snapshot_for_integration)(
            input.github_integration_id
        )

        base_repos = base_snapshot.repos if base_snapshot else []
        new_repos: list[str] = list({*base_repos, input.repository})

        sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)

        snapshot_external_id = await sandbox.initiate_snapshot(
            {
                "integration_id": str(input.github_integration_id),
                "team_id": str(input.team_id),
                "repositories": json.dumps(new_repos),
                "base_snapshot_id": str(base_snapshot.id) if base_snapshot else "",
            }
        )

        max_polls = 80
        for _ in range(max_polls):
            status = await SandboxEnvironment.get_snapshot_status(snapshot_external_id)

            if status.value == "complete":
                break
            elif status.value == "error":
                raise SnapshotCreationError(
                    "Snapshot creation failed",
                    {"snapshot_external_id": snapshot_external_id, "repository": input.repository},
                )

            await asyncio.sleep(15)
        else:
            raise SandboxTimeoutError(
                "Snapshot creation timed out after 20 minutes",
                {"snapshot_external_id": snapshot_external_id, "repository": input.repository},
            )

        snapshot = await sync_to_async(SandboxSnapshot.objects.create)(
            integration_id=input.github_integration_id,
            repos=new_repos,
            external_id=snapshot_external_id,
            status=SandboxSnapshot.Status.COMPLETE,
        )

        return str(snapshot.id)
