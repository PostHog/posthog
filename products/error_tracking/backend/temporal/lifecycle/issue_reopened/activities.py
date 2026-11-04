from typing import TYPE_CHECKING

import posthoganalytics
from temporalio import activity

from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.temporal.lifecycle.event_properties import fetch_event_properties
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import IssueReopenedWorkflowInputs
from products.error_tracking.backend.temporal.lifecycle.side_effects import (
    dispatch_issue_lifecycle_alert,
    emit_issue_lifecycle_signal,
    produce_issue_lifecycle_internal_event,
)
from products.error_tracking.backend.temporal.lifecycle.summary_worker import generate_summary_on_worker

if TYPE_CHECKING:
    from products.error_tracking.backend.logic.issue_summaries import IssueSummaryOutcome


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
    )


def _refresh_issue_reopened_summary(inputs: IssueReopenedWorkflowInputs) -> "IssueSummaryOutcome":
    # issue_summaries imports the lifecycle rendering module, whose package imports this module.
    from products.error_tracking.backend.logic.issue_summaries import (  # noqa: PLC0415
        IssueSummaryTrigger,
        refresh_issue_summary_on_reopen,
    )

    return generate_summary_on_worker(
        inputs.team_id,
        inputs.issue_id,
        IssueSummaryTrigger.REOPEN,
        lambda: refresh_issue_summary_on_reopen(
            inputs.team_id, inputs.issue_id, lambda team: fetch_event_properties(team, inputs)
        ),
    )


@activity.defn
@posthoganalytics.scoped(capture_exceptions=False)
@close_db_connections
def generate_issue_reopened_summary_activity(inputs: IssueReopenedWorkflowInputs) -> str:
    # Model and output failures return an outcome, so an exception here is an infrastructure failure worth a retry.
    return _refresh_issue_reopened_summary(inputs).value


ACTIVITIES = [
    dispatch_issue_reopened_alert_activity,
    emit_issue_reopened_internal_event_activity,
    emit_issue_reopened_signal_activity,
    generate_issue_reopened_summary_activity,
]
