from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution

from .get_task_processing_context import TaskProcessingContext


@dataclass
class CreateSnapshotInput:
    context: TaskProcessingContext
    sandbox_id: str


@activity.defn
@asyncify
def create_snapshot(input: CreateSnapshotInput) -> str:
    """
    Create and finalize snapshot. Creates and saves the snapshot record. Returns snapshot_id.
    """
    ctx = input.context

    with log_activity_execution(
        "create_snapshot",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        emit_agent_log(ctx.run_id, "info", "Creating development environment snapshot for future runs")

        base_snapshot = SandboxSnapshot.get_latest_snapshot_for_integration(ctx.github_integration_id)

        base_repos = base_snapshot.repos if base_snapshot else []
        new_repos: list[str] = list({*base_repos, ctx.repository})

        sandbox = Sandbox.get_by_id(input.sandbox_id)

        snapshot_external_id = sandbox.create_snapshot()

        snapshot = SandboxSnapshot.objects.create(
            integration_id=ctx.github_integration_id,
            repos=new_repos,
            external_id=snapshot_external_id,
            status=SandboxSnapshot.Status.COMPLETE,
        )

        return str(snapshot.id)
