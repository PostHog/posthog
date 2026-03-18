from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import log_activity_execution

from .get_snapshot_context import SnapshotContext


@dataclass
class CreateSnapshotInput:
    context: SnapshotContext
    sandbox_id: str


@activity.defn
@asyncify
def create_snapshot(input: CreateSnapshotInput) -> str:
    ctx = input.context

    with log_activity_execution(
        "create_snapshot",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        sandbox = Sandbox.get_by_id(input.sandbox_id)

        snapshot_external_id = sandbox.create_snapshot()

        snapshot = SandboxSnapshot.objects.create(
            integration_id=ctx.github_integration_id,
            repos=[ctx.repository],
            external_id=snapshot_external_id,
            status=SandboxSnapshot.Status.COMPLETE,
        )

        return str(snapshot.id)
