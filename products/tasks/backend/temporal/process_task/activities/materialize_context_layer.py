"""Clone the organization's context wiki into a provisioned sandbox.

Best-effort by design: a missing or failing wiki must never fail provisioning,
so the activity reports whether the mount happened instead of raising.
"""

import shlex

import structlog
from temporalio import activity

from posthog.dataclasses import frozen
from posthog.temporal.common.utils import asyncify

from products.context_layer.backend.facade import api as context_layer_facade
from products.tasks.backend.logic.services.sandbox import get_sandbox_class_for_sandbox_id
from products.tasks.backend.temporal.observability import emit_agent_log, log_activity_execution
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext

MOUNT_TIMEOUT_SECONDS = 120

logger = structlog.get_logger(__name__)


@frozen
class MaterializeContextLayerInput:
    context: TaskProcessingContext
    sandbox_id: str


@frozen
class MaterializeContextLayerOutput:
    mounted: bool


def _clear_wiki_checkout(ctx: TaskProcessingContext, sandbox_id: str) -> None:
    """Remove any leftover wiki checkout. Best-effort, like the mount itself."""
    mount_path = shlex.quote(context_layer_facade.SANDBOX_MOUNT_PATH)
    bundle_path = shlex.quote(f"{context_layer_facade.SANDBOX_MOUNT_PATH}.bundle")
    try:
        sandbox = get_sandbox_class_for_sandbox_id(sandbox_id).get_by_id(sandbox_id)
        sandbox.execute(f"rm -rf {mount_path} {bundle_path}", timeout_seconds=MOUNT_TIMEOUT_SECONDS)
    except Exception as error:
        emit_agent_log(ctx.run_id, "debug", f"Could not clear a stale context wiki checkout: {error}")


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
            # A directory-resumed sandbox restores /tmp/workspace with the previous
            # run's checkout, so a wiki that has since gone dark (disabled, or the
            # organization gained a private project) would stay readable. Removing
            # the directory is what makes the agent stop seeing it, since the
            # harnesses gate on the mount path existing rather than on the env var.
            _clear_wiki_checkout(ctx, input.sandbox_id)
            return MaterializeContextLayerOutput(mounted=False)

        mount_path = shlex.quote(context_layer_facade.SANDBOX_MOUNT_PATH)
        bundle_path = shlex.quote(f"{context_layer_facade.SANDBOX_MOUNT_PATH}.bundle")
        url_path = f"{context_layer_facade.SANDBOX_MOUNT_PATH}.bundle-url"
        # Clear any leftover checkout first so the mount is idempotent: a resumed
        # snapshot re-mounts /tmp/workspace (wiki included), and git clone refuses a
        # non-empty target, which would otherwise leave the previous run's stale wiki
        # in place while reporting a fresh mount. The presigned URL travels via
        # write_file and is removed on every path, so a live credential never
        # appears in command strings, sandbox logs, or error telemetry.
        command = (
            f"rm -rf {mount_path} {bundle_path} && "
            f'curl -fsSL "$(cat {shlex.quote(url_path)})" -o {bundle_path} && '
            f"git clone --quiet {bundle_path} {mount_path} && "
            f"git -C {mount_path} checkout --quiet main; "
            f"status=$?; rm -f {bundle_path} {shlex.quote(url_path)}; exit $status"
        )
        try:
            sandbox = get_sandbox_class_for_sandbox_id(input.sandbox_id).get_by_id(input.sandbox_id)
            sandbox.write_file(url_path, mount.bundle_url.encode())
            result = sandbox.execute(command, timeout_seconds=MOUNT_TIMEOUT_SECONDS)
        except Exception as error:
            # Best-effort by contract: a failure reaching the sandbox (not running,
            # timeout, execution error) degrades to "no wiki" instead of failing
            # provisioning, so the activity never raises out of here.
            logger.warning(
                "context_layer.mount.failed",
                organization_id=str(ctx.organization_id),
                run_id=str(ctx.run_id),
                error=str(error),
            )
            emit_agent_log(
                ctx.run_id,
                "debug",
                f"Could not mount the context wiki; continuing without it: {error}",
            )
            return MaterializeContextLayerOutput(mounted=False)
        if result.exit_code != 0:
            logger.warning(
                "context_layer.mount.failed",
                organization_id=str(ctx.organization_id),
                run_id=str(ctx.run_id),
                error=result.stderr[-500:],
            )
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
