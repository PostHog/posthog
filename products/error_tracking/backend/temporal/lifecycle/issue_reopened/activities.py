import posthoganalytics
from temporalio import activity

from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import IssueReopenedWorkflowInputs
from products.error_tracking.backend.temporal.lifecycle.side_effects import (
    dispatch_issue_lifecycle_alert,
    emit_issue_lifecycle_signal,
    produce_issue_lifecycle_internal_event,
    record_issue_occurrence,
)


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def dispatch_issue_reopened_alert_activity(inputs: IssueReopenedWorkflowInputs) -> None:
    dispatch_issue_lifecycle_alert(
        inputs, event="$error_tracking_issue_reopened", exception_timestamp=inputs.event_timestamp
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
        event="$error_tracking_issue_reopened",
        exception_timestamp=inputs.event_timestamp,
    )


@activity.defn
def generate_issue_reopened_summary_activity(inputs: IssueReopenedWorkflowInputs) -> None:
    # A no-op that keeps the activity registered. The workflow schedules it behind SUMMARY_ON_REOPEN_PATCH, so removing
    # the call would break the replay of every workflow that already scheduled it.
    pass


@activity.defn
@close_db_connections
def record_issue_reopened_occurrence_activity(inputs: IssueReopenedWorkflowInputs) -> None:
    record_issue_occurrence(inputs, reopened=True)


ACTIVITIES = [
    dispatch_issue_reopened_alert_activity,
    record_issue_reopened_occurrence_activity,
    emit_issue_reopened_internal_event_activity,
    emit_issue_reopened_signal_activity,
    generate_issue_reopened_summary_activity,
]
