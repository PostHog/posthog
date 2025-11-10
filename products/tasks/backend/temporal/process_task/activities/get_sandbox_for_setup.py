from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.observability import log_activity_execution
from products.tasks.backend.temporal.process_task.utils import get_sandbox_name_for_task


@dataclass
class GetSandboxForSetupInput:
    github_integration_id: int
    team_id: int
    task_id: str
    distinct_id: str


@activity.defn
@asyncify
def get_sandbox_for_setup(input: GetSandboxForSetupInput) -> str:
    """
    Get sandbox for setup. Searches for existing snapshot to use as base,
    otherwise uses default template. Returns sandbox_id when sandbox is running.
    """
    with log_activity_execution(
        "get_sandbox_for_setup",
        distinct_id=input.distinct_id,
        task_id=input.task_id,
        github_integration_id=input.github_integration_id,
    ):
        snapshot = SandboxSnapshot.get_latest_snapshot_for_integration(input.github_integration_id)

        config = SandboxConfig(
            name=get_sandbox_name_for_task(input.task_id),
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables={},
            snapshot_id=str(snapshot.id) if snapshot else None,
            metadata={"task_id": input.task_id},
        )

        sandbox = Sandbox.create(config)

        return sandbox.id
