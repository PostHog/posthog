from dataclasses import dataclass

from asgiref.sync import sync_to_async
from temporalio import activity

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox_environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfig,
    SandboxEnvironmentTemplate,
)
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.utils import get_sandbox_name_for_task


@dataclass
class GetSandboxForSetupInput:
    github_integration_id: int
    team_id: int
    task_id: str
    distinct_id: str


@activity.defn
async def get_sandbox_for_setup(input: GetSandboxForSetupInput) -> str:
    """
    Get sandbox for setup. Searches for existing snapshot to use as base,
    otherwise uses default template. Returns sandbox_id when sandbox is running.
    """
    async with log_activity_execution(
        "get_sandbox_for_setup",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        github_integration_id=input.github_integration_id,
    ):
        snapshot = await sync_to_async(SandboxSnapshot.get_latest_snapshot_for_integration)(input.github_integration_id)

        config = SandboxEnvironmentConfig(
            name=get_sandbox_name_for_task(input.task_id),
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
            environment_variables={},
            snapshot_id=str(snapshot.id) if snapshot else None,
            metadata={"task_id": input.task_id},
        )

        sandbox = await SandboxEnvironment.create(config)

        return sandbox.id
