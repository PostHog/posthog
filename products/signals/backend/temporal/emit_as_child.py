"""Helpers for emitting signals as child workflows from a parent Temporal workflow.

This module is deliberately kept free of Django-bound imports so parent
workflows can import it without dragging heavy modules into the Temporal
workflow sandbox.

Use this from **workflow code only** — the public ``emit_signal()`` helper in
``products.signals.backend.api`` is the entry point for non-Temporal callers
and for activities that don't need child-workflow semantics. When called from
a parent workflow, ``emit_signal_as_child`` starts ``BufferSignalsWorkflow``
(idempotent, per-team singleton) and ``SignalEmitterWorkflow`` as children of
the parent, with ``ParentClosePolicy.ABANDON`` so signal emission continues
independently when the parent closes.
"""

from datetime import timedelta

from django.conf import settings

import temporalio
from temporalio import workflow
from temporalio.workflow import ParentClosePolicy

from products.signals.backend.temporal.types import BufferSignalsInput, EmitSignalInputs, SignalEmitterInput


async def emit_signal_as_child(signal_input: EmitSignalInputs) -> None:
    """Start the signal emission workflows as children of the current workflow.

    Must be called from inside a Temporal workflow. The caller is responsible
    for gating/validation (see ``prepare_signal_for_emission``) — this function
    is a pure workflow-dispatch helper.
    """
    # Ensure the buffer workflow is running. It's a per-team singleton; if
    # another workflow already started it, ``WorkflowAlreadyStartedError`` is
    # swallowed. ABANDON so the buffer survives the parent's close.
    try:
        await workflow.start_child_workflow(
            "buffer-signals",
            BufferSignalsInput(team_id=signal_input.team_id),
            id=f"buffer-signals-{signal_input.team_id}",
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            parent_close_policy=ParentClosePolicy.ABANDON,
            run_timeout=timedelta(hours=1),
        )
    except temporalio.exceptions.WorkflowAlreadyStartedError:
        pass

    # Ephemeral per-signal emitter. ID uses workflow.uuid4() for determinism;
    # ABANDON so the signal finishes enqueuing even if the parent closes first.
    emitter_id = f"signal-emitter-{signal_input.team_id}-{workflow.uuid4()}"
    await workflow.start_child_workflow(
        "signal-emitter",
        SignalEmitterInput(team_id=signal_input.team_id, signal=signal_input),
        id=emitter_id,
        task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
        parent_close_policy=ParentClosePolicy.ABANDON,
        run_timeout=timedelta(minutes=10),
    )
