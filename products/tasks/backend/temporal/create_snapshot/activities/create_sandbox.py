from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.observability import log_activity_execution

from ..utils import get_sandbox_name_for_snapshot
from .get_snapshot_context import SnapshotContext


@dataclass
class CreateSandboxInput:
    context: SnapshotContext


@dataclass
class CreateSandboxOutput:
    sandbox_id: str


@activity.defn
@asyncify
def create_sandbox(input: CreateSandboxInput) -> CreateSandboxOutput:
    ctx = input.context

    with log_activity_execution(
        "create_sandbox",
        **ctx.to_log_context(),
    ):
        config = SandboxConfig(
            name=get_sandbox_name_for_snapshot(ctx.github_integration_id, ctx.repository),
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables={},
            snapshot_id=None,
            metadata={"purpose": "snapshot_creation"},
        )

        sandbox = Sandbox.create(config)

        activity.logger.info(f"Created sandbox {sandbox.id} for snapshot creation")

        return CreateSandboxOutput(sandbox_id=sandbox.id)
