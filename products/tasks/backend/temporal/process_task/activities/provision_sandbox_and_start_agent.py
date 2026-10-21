import asyncio
import logging
import threading
from dataclasses import dataclass

import posthoganalytics
from temporalio import activity

from posthog.temporal.common.activity_context import current_activity_attempt
from posthog.temporal.common.utils import asyncify
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.logic.services.sandbox import get_sandbox_class_for_run_backend
from products.tasks.backend.models import TaskRun

from .cleanup_sandbox import CleanupSandboxInput, cleanup_sandbox_now
from .get_task_processing_context import TaskProcessingContext
from .materialize_context_layer import MaterializeContextLayerInput, materialize_context_layer
from .provision_sandbox import (
    CreateSandboxForRepositoryInput,
    CreateSandboxForRepositoryOutput,
    PrepareSandboxForRepositoryInput,
    create_repository_sandbox,
    prepare_repository_sandbox,
)
from .start_agent_server import StartAgentServerInput, StartAgentServerOutput, start_agent_server_in_sandbox

BOOT_HEARTBEAT_SECONDS = 1
BOOT_CANCELLATION_WAIT_SECONDS = 30

logger = logging.getLogger(__name__)


@dataclass
class ProvisionSandboxAndStartAgentInput:
    context: TaskProcessingContext
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"
    workflow_start_at: str | None = None


@dataclass
class ProvisionSandboxAndStartAgentOutput:
    created: CreateSandboxForRepositoryOutput
    agent_server: StartAgentServerOutput
    image_source: str
    sandbox_creation_cancellable: bool


class _BootCancelled(Exception):
    pass


def _cleanup_sandbox(sandbox_id: str, run_id: str) -> None:
    try:
        cleanup_sandbox_now(
            CleanupSandboxInput(sandbox_id=sandbox_id, run_id=run_id, stop_agent_server_on_cleanup=True)
        )
    except Exception:
        logger.warning("boot_sandbox_cleanup_failed", extra={"sandbox_id": sandbox_id, "run_id": run_id}, exc_info=True)


def _cleanup_recorded_sandbox(run_id: str) -> None:
    state = TaskRun.objects.filter(id=run_id).values_list("state", flat=True).first() or {}
    sandbox_id = state.get("sandbox_id")
    if isinstance(sandbox_id, str) and sandbox_id:
        _cleanup_sandbox(sandbox_id, run_id)


@asyncify
@posthoganalytics.scoped(fresh=True, capture_exceptions=False)
def _provision_sandbox_and_start_agent(
    input: ProvisionSandboxAndStartAgentInput, cancel_event: threading.Event
) -> ProvisionSandboxAndStartAgentOutput:
    ctx = input.context
    if current_activity_attempt() > 1:
        _cleanup_recorded_sandbox(ctx.run_id)

    prepared = prepare_repository_sandbox(PrepareSandboxForRepositoryInput(context=ctx))
    created, sandbox = create_repository_sandbox(CreateSandboxForRepositoryInput(context=ctx, prepared=prepared))
    try:
        if cancel_event.is_set():
            raise _BootCancelled(created.sandbox_id)
        if prepared.environment_variables.get("POSTHOG_CONTEXT_LAYER_PATH"):
            materialize_context_layer(MaterializeContextLayerInput(context=ctx, sandbox_id=created.sandbox_id))
        agent_server = start_agent_server_in_sandbox(
            StartAgentServerInput(
                context=ctx,
                sandbox_id=created.sandbox_id,
                sandbox_url=created.sandbox_url,
                sandbox_connect_token=created.connect_token,
                posthog_mcp_scopes=input.posthog_mcp_scopes,
                boot_path="classic",
                used_snapshot=created.used_snapshot,
                workflow_start_at=input.workflow_start_at,
            ),
            sandbox,
        )
    except BaseException:
        _cleanup_sandbox(created.sandbox_id, ctx.run_id)
        raise

    return ProvisionSandboxAndStartAgentOutput(
        created=created,
        agent_server=agent_server,
        image_source=prepared.image_source,
        sandbox_creation_cancellable=prepared.sandbox_creation_cancellable,
    )


@activity.defn
async def provision_sandbox_and_start_agent(
    input: ProvisionSandboxAndStartAgentInput,
) -> ProvisionSandboxAndStartAgentOutput:
    sandbox_class = get_sandbox_class_for_run_backend(input.context.sandbox_backend)
    cancel_event = threading.Event()

    with sandbox_class.creation_cancellation_scope(cancel_event):
        boot_task = asyncio.create_task(_provision_sandbox_and_start_agent(input, cancel_event))
        try:
            while True:
                activity.heartbeat()
                try:
                    return await asyncio.wait_for(asyncio.shield(boot_task), timeout=BOOT_HEARTBEAT_SECONDS)
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            cancel_event.set()
            try:
                await asyncio.wait_for(asyncio.shield(boot_task), timeout=BOOT_CANCELLATION_WAIT_SECONDS)
            except TimeoutError:
                logger.exception("boot_sandbox_cancellation_wait_timed_out", extra={"run_id": input.context.run_id})
            except Exception as error:
                logger.debug(
                    "boot_sandbox_stopped_after_cancellation",
                    extra={"run_id": input.context.run_id, "error_type": type(error).__name__},
                )
            await asyncify(_cleanup_recorded_sandbox)(input.context.run_id)
            raise
