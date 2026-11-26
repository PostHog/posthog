"""The issue change log rows for the changes ingestion made.

The lifecycle workflows write them, so the rows follow the same rate limits as the alerts:
an issue whose created workflow the limiter cut gets no row.
"""

import dataclasses

from temporalio import workflow
from temporalio.exceptions import ActivityError

from products.error_tracking.backend.temporal.lifecycle.policies import (
    ACTIVITY_RETRY_POLICY,
    ACTIVITY_START_TO_CLOSE_TIMEOUT,
)

CHANGE_LOG_PATCH = "error-tracking-change-log-activity"


@dataclasses.dataclass(frozen=True)
class LifecycleChangeInputs:
    notification_id: str
    team_id: int
    issue_id: str
    kind: str
    event_uuid: str
    event_timestamp: str
    previous_status: str | None = None
    computed_baseline: float | None = None
    current_bucket_value: float | None = None


async def record_lifecycle_change(inputs: LifecycleChangeInputs) -> None:
    """Write the row from a workflow. A failure loses the row and nothing else."""
    # Patched: executions in flight when this activity shipped replay the old sequence.
    if not workflow.patched(CHANGE_LOG_PATCH):
        return
    try:
        await workflow.execute_activity(
            "record_lifecycle_change_activity",
            inputs,
            start_to_close_timeout=ACTIVITY_START_TO_CLOSE_TIMEOUT,
            retry_policy=ACTIVITY_RETRY_POLICY,
        )
    except ActivityError:
        workflow.logger.warning("Issue change log activity failed; the change has no row", extra={"kind": inputs.kind})
        (
            workflow.metric_meter()
            .with_additional_attributes({"kind": inputs.kind})
            .create_counter(
                "error_tracking_lifecycle_change_log_fail_open",
                "Lifecycle workflows whose issue change log row could not be written",
            )
            .add(1)
        )
