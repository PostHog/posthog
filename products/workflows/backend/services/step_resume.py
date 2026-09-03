"""Wake a workflow step that parked while an external run (an AI task, a scout run) finished.

The step sent its dispatch key as the run's idempotency key. On the run's terminal transition the
owning product calls `resume_workflow_step` with that key, and the CDP subscription matcher wakes
exactly that job (nodejs/src/cdp/consumers/cdp-hogflow-subscription-matcher.consumer.ts). The
parked step has its own deadline, so a lost wake fails the step late rather than stranding it.
"""

from collections.abc import Mapping
from typing import Any, Literal

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event

logger = structlog.get_logger(__name__)

WORKFLOW_STEP_RESUME_EVENT = "$workflow_step_resume"

# The step result lands in workflow variables, which are capped at 5KB in total.
RESULT_STRING_CAP = 1500

WorkflowStepResumeStatus = Literal["completed", "failed", "cancelled"]


def _cap_strings(result: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value[:RESULT_STRING_CAP] if isinstance(value, str) else value
        for key, value in result.items()
        if value is not None
    }


def resume_workflow_step(
    *,
    team_id: int,
    origin_key: str,
    status: WorkflowStepResumeStatus,
    result: Mapping[str, Any] | None = None,
) -> None:
    """Emit the wake for the step that dispatched `origin_key`. Never raises: callers are on a
    terminal-status path, and a failed emit must not mask the status write."""
    try:
        produce_internal_event(
            team_id=team_id,
            event=InternalEventEvent(
                event=WORKFLOW_STEP_RESUME_EVENT,
                distinct_id=f"team_{team_id}",
                properties={"origin_key": origin_key, "status": status, "result": _cap_strings(result or {})},
            ),
        )
    except Exception:
        logger.exception("workflow_step_resume_emit_failed", team_id=team_id, origin_key=origin_key, status=status)
