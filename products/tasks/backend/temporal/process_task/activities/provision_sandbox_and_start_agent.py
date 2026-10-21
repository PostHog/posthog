import time
import logging
import threading
from functools import partial

import posthoganalytics
from temporalio import activity

from posthog.dataclasses import frozen
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
    run_with_creation_heartbeat,
)
from .start_agent_server import StartAgentServerInput, StartAgentServerOutput, start_agent_server_in_sandbox

logger = logging.getLogger(__name__)


@frozen
class ProvisionSandboxAndStartAgentInput:
    context: TaskProcessingContext
    posthog_mcp_scopes: PosthogMcpScopes = "read_only"
    workflow_start_at: str | None = None


@frozen
class ProvisionSandboxAndStartAgentOutput:
    created: CreateSandboxForRepositoryOutput
    agent_server: StartAgentServerOutput
    image_source: str
    sandbox_creation_cancellable: bool


@frozen
class CleanupBootSandboxInput:
    run_id: str
    sandbox_backend: str


class _BootCancelled(Exception):
    pass


class _CreationClock:
    def __init__(self, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds
        self._started_at: float | None = None

    def start(self) -> None:
        self._started_at = time.monotonic()

    def stop(self) -> None:
        self._started_at = None

    def expired(self) -> bool:
        started_at = self._started_at
        return started_at is not None and time.monotonic() - started_at > self._timeout_seconds


def _cleanup_sandbox(sandbox_id: str, run_id: str, sandbox_backend: str) -> None:
    sandbox_class = get_sandbox_class_for_run_backend(sandbox_backend)
    try:
        with sandbox_class.creation_cancellation_scope(threading.Event()):
            cleanup_sandbox_now(
                CleanupSandboxInput(sandbox_id=sandbox_id, run_id=run_id, stop_agent_server_on_cleanup=True)
            )
    except Exception:
        logger.warning("boot_sandbox_cleanup_failed", extra={"sandbox_id": sandbox_id, "run_id": run_id}, exc_info=True)


def _cleanup_recorded_sandbox(run_id: str, sandbox_backend: str) -> None:
    state = TaskRun.objects.filter(id=run_id).values_list("state", flat=True).first() or {}
    sandbox_id = state.get("sandbox_id")
    if isinstance(sandbox_id, str) and sandbox_id:
        _cleanup_sandbox(sandbox_id, run_id, sandbox_backend)


@asyncify
@posthoganalytics.scoped(fresh=True, capture_exceptions=False)
def _provision_sandbox_and_start_agent(
    input: ProvisionSandboxAndStartAgentInput, creation_clock: _CreationClock, cancel_event: threading.Event
) -> ProvisionSandboxAndStartAgentOutput:
    ctx = input.context
    if current_activity_attempt() > 1:
        _cleanup_recorded_sandbox(ctx.run_id, ctx.sandbox_backend)

    prepared = prepare_repository_sandbox(PrepareSandboxForRepositoryInput(context=ctx))
    if cancel_event.is_set():
        raise _BootCancelled
    creation_clock.start()
    created, sandbox = create_repository_sandbox(CreateSandboxForRepositoryInput(context=ctx, prepared=prepared))
    creation_clock.stop()
    try:
        if cancel_event.is_set():
            raise _BootCancelled
        if prepared.environment_variables.get("POSTHOG_CONTEXT_LAYER_PATH"):
            materialize_context_layer(MaterializeContextLayerInput(context=ctx, sandbox_id=created.sandbox_id), sandbox)
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
        _cleanup_sandbox(created.sandbox_id, ctx.run_id, ctx.sandbox_backend)
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
    creation_clock = _CreationClock(sandbox_class.creation_timeout_seconds)

    async def cleanup_after_cancellation(_booted: ProvisionSandboxAndStartAgentOutput | None) -> None:
        await asyncify(_cleanup_recorded_sandbox)(input.context.run_id, input.context.sandbox_backend)

    return await run_with_creation_heartbeat(
        sandbox_class,
        partial(_provision_sandbox_and_start_agent, input, creation_clock),
        run_id=input.context.run_id,
        on_cancelled=cleanup_after_cancellation,
        creation_expired=creation_clock.expired,
    )


@activity.defn
@asyncify
def cleanup_boot_sandbox(input: CleanupBootSandboxInput) -> None:
    _cleanup_recorded_sandbox(input.run_id, input.sandbox_backend)
