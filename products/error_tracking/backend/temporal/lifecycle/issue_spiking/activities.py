from django.db import transaction
from django.utils.dateparse import parse_datetime

import posthoganalytics
from temporalio import activity

from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingSpikeEvent
from products.error_tracking.backend.temporal.lifecycle.issue_spiking.types import (
    IssueSpikingWorkflowInputs,
    SpikeEventPersistenceResult,
)
from products.error_tracking.backend.temporal.lifecycle.side_effects import (
    emit_issue_lifecycle_signal,
    produce_issue_lifecycle_internal_event,
)
from products.error_tracking.backend.temporal.lifecycle.types import SpikeEventPersistenceStatus


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def persist_issue_spiking_event_activity(inputs: IssueSpikingWorkflowInputs) -> SpikeEventPersistenceResult:
    detected_at = parse_datetime(inputs.detected_at)
    if detected_at is None:
        raise ValueError(f"Invalid spike detection timestamp: {inputs.detected_at}")

    with transaction.atomic():
        issue = (
            ErrorTrackingIssue.objects.select_for_update()
            .filter(team_id=inputs.team_id, id=inputs.issue_id)
            .only("id")
            .first()
        )
        if issue is None:
            return SpikeEventPersistenceResult(status=SpikeEventPersistenceStatus.MISSING_ISSUE)

        _, created = ErrorTrackingSpikeEvent.objects.get_or_create(
            id=inputs.notification_id,
            team_id=inputs.team_id,
            defaults={
                "issue": issue,
                "detected_at": detected_at,
                "computed_baseline": inputs.computed_baseline,
                "current_bucket_value": int(inputs.current_bucket_value),
            },
        )
    return SpikeEventPersistenceResult(
        status=SpikeEventPersistenceStatus.INSERTED if created else SpikeEventPersistenceStatus.ALREADY_PERSISTED
    )


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def emit_issue_spiking_internal_event_activity(inputs: IssueSpikingWorkflowInputs) -> None:
    produce_issue_lifecycle_internal_event(
        inputs,
        event="$error_tracking_issue_spiking",
        exception_timestamp=inputs.detected_at,
        extra_properties={
            "computed_baseline": inputs.computed_baseline,
            "current_bucket_value": inputs.current_bucket_value,
        },
        include_status=False,
    )


@activity.defn
@scoped_temporal()
@close_db_connections
async def emit_issue_spiking_signal_activity(inputs: IssueSpikingWorkflowInputs) -> None:
    multiplier = inputs.current_bucket_value / inputs.computed_baseline if inputs.computed_baseline else float("inf")
    await emit_issue_lifecycle_signal(
        inputs,
        source_type="issue_spiking",
        preamble=(
            "This error tracking issue is experiencing a spike in occurrences\n"
            f"(baseline: {inputs.computed_baseline:.1f}, current: {inputs.current_bucket_value:.1f}) "
            f"({multiplier:.1f} over baseline)"
        ),
    )


ACTIVITIES = [
    persist_issue_spiking_event_activity,
    emit_issue_spiking_internal_event_activity,
    emit_issue_spiking_signal_activity,
]
