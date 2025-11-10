from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import SnapshotNotFoundError, SnapshotNotReadyError
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.utils import get_sandbox_name_for_task


@dataclass
class CreateSandboxFromSnapshotInput:
    snapshot_id: str
    task_id: str
    distinct_id: str


@activity.defn
@asyncify
def create_sandbox_from_snapshot(input: CreateSandboxFromSnapshotInput) -> str:
    """Create a sandbox from a snapshot for task execution. Returns sandbox_id when running."""

    with log_activity_execution(
        "create_sandbox_from_snapshot",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        snapshot_id=input.snapshot_id,
    ):
        try:
            snapshot = SandboxSnapshot.objects.get(id=input.snapshot_id)
        except SandboxSnapshot.DoesNotExist:
            raise SnapshotNotFoundError(f"Snapshot {input.snapshot_id} not found", {"snapshot_id": input.snapshot_id})

        if snapshot.status != SandboxSnapshot.Status.COMPLETE:
            raise SnapshotNotReadyError(
                f"Snapshot {input.snapshot_id} is not ready (status: {snapshot.status})",
                {"snapshot_id": input.snapshot_id, "status": snapshot.status},
            )

        config = SandboxConfig(
            name=get_sandbox_name_for_task(input.task_id),
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables={},
            snapshot_id=str(snapshot.id),
            metadata={"task_id": input.task_id},
        )

        sandbox = Sandbox.create(config)

        return sandbox.id
