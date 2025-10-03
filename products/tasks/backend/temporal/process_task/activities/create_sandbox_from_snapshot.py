from dataclasses import dataclass

from asgiref.sync import sync_to_async
from temporalio import activity

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox_environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfig,
    SandboxEnvironmentTemplate,
)
from products.tasks.backend.temporal.process_task.utils import get_sandbox_name_for_task


@dataclass
class CreateSandboxFromSnapshotInput:
    snapshot_id: str
    task_id: str


@activity.defn
async def create_sandbox_from_snapshot(input: CreateSandboxFromSnapshotInput) -> str:
    """Create a sandbox from a snapshot for task execution. Returns sandbox_id when running."""
    snapshot = await sync_to_async(SandboxSnapshot.objects.get)(id=input.snapshot_id)

    config = SandboxEnvironmentConfig(
        name=get_sandbox_name_for_task(input.task_id),
        template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        environment_variables={},
        snapshot_id=str(snapshot.id),
        metadata={"task_id": input.task_id},
    )

    sandbox = await SandboxEnvironment.create(config)

    return sandbox.id
