"""Clone the organization's context wiki into a provisioned sandbox.

Best-effort by design: a missing or failing wiki must never fail provisioning,
so the activity reports whether the mount happened instead of raising.
"""

import shlex

from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.utils import asyncify

from products.context_layer.backend.facade import api as context_layer_facade
from products.tasks.backend.logic.services.sandbox import Sandbox
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext

MOUNT_TIMEOUT_SECONDS = 120


@frozen
class MaterializeContextLayerInput:
    context: TaskProcessingContext
    sandbox_id: str


@frozen
class MaterializeContextLayerOutput:
    mounted: bool


@activity.defn
@asyncify
def materialize_context_layer_in_sandbox(input: MaterializeContextLayerInput) -> MaterializeContextLayerOutput:
    ctx = input.context

    with log_activity_execution(
        "materialize_context_layer_in_sandbox",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        mount = context_layer_facade.get_sandbox_mount(ctx.organization_id)
        if mount is None:
            return MaterializeContextLayerOutput(mounted=False)

        sandbox = Sandbox.get_by_id(input.sandbox_id)
        mount_path = shlex.quote(context_layer_facade.SANDBOX_MOUNT_PATH)
        bundle_path = f"{context_layer_facade.SANDBOX_MOUNT_PATH}.bundle"
        command = (
            f"curl -fsSL {shlex.quote(mount.bundle_url)} -o {shlex.quote(bundle_path)} && "
            f"git clone --quiet {shlex.quote(bundle_path)} {mount_path} && "
            f"git -C {mount_path} checkout --quiet main && "
            f"rm -f {shlex.quote(bundle_path)}"
        )
        result = sandbox.execute(command, timeout_seconds=MOUNT_TIMEOUT_SECONDS)
        if result.exit_code != 0:
            emit_agent_log(
                ctx.run_id,
                "debug",
                f"Could not mount the context wiki; continuing without it: {result.stderr}",
            )
            return MaterializeContextLayerOutput(mounted=False)
        emit_agent_log(
            ctx.run_id,
            "debug",
            f"Mounted the context wiki at {context_layer_facade.SANDBOX_MOUNT_PATH} ({mount.head_sha[:12]})",
        )
        return MaterializeContextLayerOutput(mounted=True)
