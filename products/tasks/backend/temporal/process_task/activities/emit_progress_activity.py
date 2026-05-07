from dataclasses import dataclass
from typing import Optional

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.temporal.observability import emit_progress


@dataclass
class EmitProgressInput:
    run_id: str
    step: str
    status: str
    label: str
    group: str
    detail: Optional[str] = None


@activity.defn
@asyncify
def emit_progress_activity(input: EmitProgressInput) -> None:
    """Emit a `_posthog/progress` notification for the given task run.

    Drives the client-side progress card. Best-effort: failures are swallowed so
    progress glitches never take down a task run.
    """
    emit_progress(
        run_id=input.run_id,
        step=input.step,
        status=input.status,
        label=input.label,
        group=input.group,
        detail=input.detail,
    )
