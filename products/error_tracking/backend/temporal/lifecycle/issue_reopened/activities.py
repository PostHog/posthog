import posthoganalytics
from temporalio import activity

from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import IssueReopenedWorkflowInputs
from products.error_tracking.backend.temporal.lifecycle.side_effects import (
    emit_issue_lifecycle_signal,
    produce_issue_lifecycle_internal_event,
)


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def emit_issue_reopened_internal_event_activity(inputs: IssueReopenedWorkflowInputs) -> None:
    produce_issue_lifecycle_internal_event(
        inputs,
        event="$error_tracking_issue_reopened",
        exception_timestamp=inputs.event_timestamp,
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def emit_issue_reopened_signal_activity(inputs: IssueReopenedWorkflowInputs) -> None:
    await emit_issue_lifecycle_signal(
        inputs,
        source_type="issue_reopened",
        preamble=(
            "Previously resolved error tracking issue has reappeared - this particular exception was observed "
            "previously, and thought to be resolved, but has reappeared"
        ),
    )


ACTIVITIES = [
    emit_issue_reopened_internal_event_activity,
    emit_issue_reopened_signal_activity,
]
