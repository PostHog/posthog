from django.utils import timezone

from temporalio import activity

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.temporal.types import (
    MarkObservationFailedInputs,
    MarkObservationRunningInputs,
    MarkObservationSucceededInputs,
)


@activity.defn
def mark_observation_running_activity(inputs: MarkObservationRunningInputs) -> None:
    """Flip pending → running. Idempotent: an at-least-once retry against the now-RUNNING row is a no-op."""
    ReplayObservation.objects.filter(
        pk=inputs.observation_id,
        status=ObservationStatus.PENDING,
    ).update(
        status=ObservationStatus.RUNNING,
        started_at=timezone.now(),
    )


@activity.defn
def mark_observation_failed_activity(inputs: MarkObservationFailedInputs) -> None:
    """Flip pending/running → failed. Idempotent: FAILED is not in the source filter."""
    ReplayObservation.objects.filter(
        pk=inputs.observation_id,
        status__in=[ObservationStatus.PENDING, ObservationStatus.RUNNING],
    ).update(
        status=ObservationStatus.FAILED,
        error_reason=inputs.error_reason,
        completed_at=timezone.now(),
    )


@activity.defn
def mark_observation_succeeded_activity(inputs: MarkObservationSucceededInputs) -> None:
    """Flip pending/running → succeeded and persist the scanner result. Idempotent: SUCCEEDED is not in the source filter."""
    ReplayObservation.objects.filter(
        pk=inputs.observation_id,
        status__in=[ObservationStatus.PENDING, ObservationStatus.RUNNING],
    ).update(
        status=ObservationStatus.SUCCEEDED,
        completed_at=timezone.now(),
        scanner_result=inputs.scanner_result.model_dump(mode="json"),
    )
