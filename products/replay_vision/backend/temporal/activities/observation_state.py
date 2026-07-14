from collections.abc import Callable, Container
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog
from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind, IneligibleSessionKind
from products.replay_vision.backend.temporal.metrics import (
    REPLAY_VISION_FAILURE_KINDS,
    REPLAY_VISION_INELIGIBLE_KINDS,
    REPLAY_VISION_OBSERVATIONS,
)
from products.replay_vision.backend.temporal.types import (
    MarkObservationFailedInputs,
    MarkObservationIneligibleInputs,
    MarkObservationRunningInputs,
    MarkObservationSucceededInputs,
)

logger = structlog.get_logger(__name__)

# Pre-built so the kind label can be enum-validated without recomputing per call.
_FAILURE_KIND_VALUES: frozenset[str] = frozenset(k.value for k in FailureKind)
_INELIGIBLE_KIND_VALUES: frozenset[str] = frozenset(k.value for k in IneligibleSessionKind)


def _kind_from_error_reason(error_reason: str, valid_kinds: Container[str]) -> str:
    """Parse the leading `kind:` and validate against the enum; unknown or unparseable → `"unknown"`."""
    idx = error_reason.find(":")
    if idx <= 0:
        return "unknown"
    kind = error_reason[:idx]
    return kind if kind in valid_kinds else "unknown"


@activity.defn
@close_db_connections
@track_activity()
def mark_observation_running_activity(inputs: MarkObservationRunningInputs) -> None:
    """Flip pending → running. Idempotent: an at-least-once retry against the now-RUNNING row is a no-op."""
    ReplayObservation.objects.filter(
        pk=inputs.observation_id,
        status=ObservationStatus.PENDING,
    ).update(
        status=ObservationStatus.RUNNING,
        started_at=timezone.now(),
    )


def mark_observation_terminal(
    *,
    observation_id: UUID,
    status: ObservationStatus,
    error_reason: str,
    scanner_type: str,
    valid_kinds: Container[str],
    count_kind: Callable[[str], None],
) -> bool:
    """Flip pending/running → `status` and record metrics/logs; idempotent no-op against already-terminal rows."""
    updated = ReplayObservation.objects.filter(
        pk=observation_id,
        status__in=[ObservationStatus.PENDING, ObservationStatus.RUNNING],
    ).update(
        status=status,
        error_reason=error_reason,
        completed_at=timezone.now(),
    )
    if not updated:
        return False  # No state transition — retry against an already-terminal row.
    kind = _kind_from_error_reason(error_reason, valid_kinds)
    REPLAY_VISION_OBSERVATIONS.labels(status=status.value, scanner_type=scanner_type).inc()
    count_kind(kind)
    logger.info(
        f"replay_vision.observation.{status.value}",
        observation_id=str(observation_id),
        scanner_type=scanner_type,
        kind=kind,
        error_reason=error_reason,
    )
    return True


@activity.defn
@close_db_connections
@track_activity()
def mark_observation_failed_activity(inputs: MarkObservationFailedInputs) -> None:
    """Flip pending/running → failed. Idempotent: FAILED is not in the source filter."""
    mark_observation_terminal(
        observation_id=inputs.observation_id,
        status=ObservationStatus.FAILED,
        error_reason=inputs.error_reason,
        scanner_type=inputs.scanner_type,
        valid_kinds=_FAILURE_KIND_VALUES,
        count_kind=lambda kind: REPLAY_VISION_FAILURE_KINDS.labels(kind=kind, scanner_type=inputs.scanner_type).inc(),
    )


@activity.defn
@close_db_connections
@track_activity()
def mark_observation_ineligible_activity(inputs: MarkObservationIneligibleInputs) -> None:
    """Flip pending/running → ineligible. Idempotent: INELIGIBLE is not in the source filter."""
    mark_observation_terminal(
        observation_id=inputs.observation_id,
        status=ObservationStatus.INELIGIBLE,
        error_reason=inputs.error_reason,
        scanner_type=inputs.scanner_type,
        valid_kinds=_INELIGIBLE_KIND_VALUES,
        count_kind=lambda kind: REPLAY_VISION_INELIGIBLE_KINDS.labels(kind=kind).inc(),
    )


@activity.defn
@close_db_connections
@track_activity()
def mark_observation_succeeded_activity(inputs: MarkObservationSucceededInputs) -> None:
    """Flip pending/running → succeeded and persist the scanner result. Idempotent: SUCCEEDED is not in the source filter."""
    with transaction.atomic():
        updated = ReplayObservation.objects.filter(
            pk=inputs.observation_id,
            status__in=[ObservationStatus.PENDING, ObservationStatus.RUNNING],
        ).update(
            status=ObservationStatus.SUCCEEDED,
            completed_at=timezone.now(),
            scanner_result=inputs.scanner_result.model_dump(mode="json"),
        )
        if not updated:
            return  # No state transition — retry against an already-terminal row.
        # Write the usage receipt in the same transaction as the transition so a crash can't undercount.
        obs = ReplayObservation.objects.values(
            "team_id", "team__organization_id", "created_at", "scanner_snapshot__model"
        ).get(pk=inputs.observation_id)
        model = obs["scanner_snapshot__model"] or ""
        ReplayObservationUsage.objects.get_or_create(
            observation_id=inputs.observation_id,
            defaults={
                "organization_id": obs["team__organization_id"],
                "team_id": obs["team_id"],
                "observation_created_at": obs["created_at"],
                "model": model,
                "credits": observation_credits_for_model(model),
            },
        )
    REPLAY_VISION_OBSERVATIONS.labels(status="succeeded", scanner_type=inputs.scanner_type).inc()
    logger.info(
        "replay_vision.observation.succeeded",
        observation_id=str(inputs.observation_id),
        scanner_type=inputs.scanner_type,
    )
