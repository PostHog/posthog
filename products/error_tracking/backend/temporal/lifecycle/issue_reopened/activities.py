import dataclasses

from django.db import transaction

import posthoganalytics
from temporalio import activity

from posthog.models.activity_logging.activity_log import ActivityLog, Change, Detail, Trigger, log_activity
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.models import ErrorTrackingIssue
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import IssueReopenedWorkflowInputs
from products.error_tracking.backend.temporal.lifecycle.side_effects import (
    dispatch_issue_lifecycle_alert,
    emit_issue_lifecycle_signal,
    produce_issue_lifecycle_internal_event,
)

INGESTION_REOPEN_TRIGGER_JOB_TYPE = "error_tracking_ingestion"


def reopened_event_properties(inputs: IssueReopenedWorkflowInputs) -> dict[str, object]:
    properties: dict[str, object] = {"reopen_reason": inputs.reopen_reason.value}
    release = inputs.reopened_by_release
    if release is not None:
        properties["reopened_by_release_version"] = release.version
        properties["reopened_by_release_project"] = release.project
        properties["reopened_by_release_id"] = release.id
    return properties


def record_ingestion_reopen(inputs: IssueReopenedWorkflowInputs) -> None:
    """Write one activity log entry for the reopen, at most once per notification."""
    payload: dict[str, object] = {
        "reason": inputs.reopen_reason.value,
        "event_uuid": inputs.event_uuid,
        # The entry is stamped when this activity runs, which a Temporal backlog can delay. The
        # exception's own time says when the issue reopened.
        "exception_timestamp": inputs.event_timestamp,
    }
    if inputs.reopened_by_release is not None:
        payload["release"] = dataclasses.asdict(inputs.reopened_by_release)
    with transaction.atomic():
        # The issue row lock serializes attempts of this activity, so a retry that overlaps a slow
        # earlier attempt still sees its entry. `of` keeps the lock off the team row the join reads.
        issue = (
            ErrorTrackingIssue.objects.select_for_update(of=("self",))
            .select_related("team")
            .filter(team_id=inputs.team_id, id=inputs.issue_id)
            .first()
        )
        if issue is None:
            return
        already_recorded = ActivityLog.objects.filter(
            team_id=inputs.team_id,
            scope="ErrorTrackingIssue",
            item_id=inputs.issue_id,
            detail__trigger__job_type=INGESTION_REOPEN_TRIGGER_JOB_TYPE,
            detail__trigger__job_id=inputs.notification_id,
        ).exists()
        if already_recorded:
            return
        log_activity(
            organization_id=issue.team.organization_id,
            team_id=inputs.team_id,
            user=None,
            was_impersonated=False,
            item_id=inputs.issue_id,
            scope="ErrorTrackingIssue",
            activity="updated",
            # Write inside the transaction, so that the existence check above and this insert hold
            # the same lock. A failed write raises, and the activity retries it.
            strict=True,
            detail=Detail(
                name=issue.name,
                changes=[
                    Change(
                        type="ErrorTrackingIssue",
                        field="status",
                        before=inputs.previous_status or ErrorTrackingIssue.Status.RESOLVED,
                        after=ErrorTrackingIssue.Status.ACTIVE,
                        action="changed",
                    )
                ],
                trigger=Trigger(
                    job_type=INGESTION_REOPEN_TRIGGER_JOB_TYPE, job_id=inputs.notification_id, payload=payload
                ),
            ),
        )


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def dispatch_issue_reopened_alert_activity(inputs: IssueReopenedWorkflowInputs) -> None:
    dispatch_issue_lifecycle_alert(
        inputs,
        event="$error_tracking_issue_reopened",
        exception_timestamp=inputs.event_timestamp,
        extra_properties=reopened_event_properties(inputs),
    )


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def emit_issue_reopened_internal_event_activity(inputs: IssueReopenedWorkflowInputs) -> None:
    produce_issue_lifecycle_internal_event(
        inputs,
        event="$error_tracking_issue_reopened",
        exception_timestamp=inputs.event_timestamp,
        extra_properties=reopened_event_properties(inputs),
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
        extra_properties=reopened_event_properties(inputs),
    )


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def record_issue_reopened_activity_log_activity(inputs: IssueReopenedWorkflowInputs) -> None:
    record_ingestion_reopen(inputs)


@activity.defn
def generate_issue_reopened_summary_activity(inputs: IssueReopenedWorkflowInputs) -> None:
    # A no-op that keeps the activity registered. The workflow schedules it behind SUMMARY_ON_REOPEN_PATCH, so removing
    # the call would break the replay of every workflow that already scheduled it.
    pass


ACTIVITIES = [
    dispatch_issue_reopened_alert_activity,
    emit_issue_reopened_internal_event_activity,
    emit_issue_reopened_signal_activity,
    generate_issue_reopened_summary_activity,
    record_issue_reopened_activity_log_activity,
]
