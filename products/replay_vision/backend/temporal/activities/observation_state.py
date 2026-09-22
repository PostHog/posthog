from collections.abc import Callable, Container
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog
import posthoganalytics
from temporalio import activity

from posthog.settings import SITE_URL
from posthog.usage_ingestion.client import UsageRecord, report_usage

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_observation_usage import ReplayObservationUsage
from products.replay_vision.backend.temporal.constants import replay_vision_distinct_id
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind, IneligibleSessionKind
from products.replay_vision.backend.temporal.metrics import (
    record_credits_consumed,
    record_failure_kind,
    record_ineligible_kind,
    record_observation,
    record_observation_e2e,
)
from products.replay_vision.backend.temporal.types import (
    MarkObservationFailedInputs,
    MarkObservationIneligibleInputs,
    MarkObservationRunningInputs,
    MarkObservationSucceededInputs,
)
from products.replay_vision.backend.temporal.vision_alerts.match_hook import record_alert_matches_guarded

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


# One event per terminal status, so a scan that produced nothing is countable next to
# `replay_vision_scan_completed` instead of only reaching Prometheus.
_TERMINAL_SCAN_EVENTS: dict[str, str] = {
    ObservationStatus.FAILED: "replay_vision_scan_failed",
    ObservationStatus.INELIGIBLE: "replay_vision_scan_ineligible",
}


def _capture_terminal_scan(*, observation_id: UUID, status: ObservationStatus, scanner_type: str, kind: str) -> None:
    """Internal cross-customer telemetry for a scan that ended with no result.

    `replay_vision_scan_completed` fires only on success, so on its own it is a numerator with no
    denominator: no failure rate is computable for any team, model, or scanner type. The
    human-readable half of `error_reason` stays out, because a provider message can quote session
    content, and `kind` is the enum a rate would be segmented by anyway.
    """
    event = _TERMINAL_SCAN_EVENTS.get(status)
    if event is None:
        return
    obs = ReplayObservation.objects.values(
        "team_id",
        "team__organization_id",
        "team__uuid",
        "scanner_id",
        "triggered_by",
        "scanner_snapshot__model",
        "scanner_snapshot__scanner_version",
    ).get(pk=observation_id)
    posthoganalytics.capture(
        distinct_id=replay_vision_distinct_id(obs["team_id"]),
        event=event,
        # Deterministic dedup key. Exactly one terminal transition ever lands per observation, so
        # sharing the key with `replay_vision_scan_completed` also stops one scan being counted as
        # both a success and a failure.
        uuid=str(observation_id),
        properties={
            "observation_id": str(observation_id),
            "scanner_id": str(obs["scanner_id"]),
            "scanner_type": str(scanner_type),
            "model": obs["scanner_snapshot__model"] or "",
            "triggered_by": obs["triggered_by"],
            "kind": kind,
            # The version that produced this scan, from the snapshot rather than the live scanner, so a
            # later edit cannot retro-attribute a failure to the config that replaced it.
            "scanner_version": obs["scanner_snapshot__scanner_version"],
            "team_id": obs["team_id"],
            "organization_id": str(obs["team__organization_id"]),
        },
        # Mirrors posthog.event_usage.groups() without fetching the Team row.
        groups={
            "instance": SITE_URL,
            "organization": str(obs["team__organization_id"]),
            "project": str(obs["team__uuid"]),
        },
    )


@activity.defn
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
    record_observation(status.value, scanner_type)
    count_kind(kind)
    logger.info(
        f"replay_vision.observation.{status.value}",
        observation_id=str(observation_id),
        scanner_type=scanner_type,
        kind=kind,
        error_reason=error_reason,
    )
    try:
        _capture_terminal_scan(observation_id=observation_id, status=status, scanner_type=scanner_type, kind=kind)
    except Exception:
        # Fail-soft: the row is already settled, and the transition is sticky, so raising here would
        # retry an activity that has nothing left to do.
        logger.exception("replay_vision.observation.terminal_capture_failed", observation_id=str(observation_id))
    return True


@activity.defn
@track_activity()
def mark_observation_failed_activity(inputs: MarkObservationFailedInputs) -> None:
    """Flip pending/running → failed. Idempotent: FAILED is not in the source filter."""
    mark_observation_terminal(
        observation_id=inputs.observation_id,
        status=ObservationStatus.FAILED,
        error_reason=inputs.error_reason,
        scanner_type=inputs.scanner_type,
        valid_kinds=_FAILURE_KIND_VALUES,
        count_kind=lambda kind: record_failure_kind(kind, inputs.scanner_type),
    )


@activity.defn
@track_activity()
def mark_observation_ineligible_activity(inputs: MarkObservationIneligibleInputs) -> None:
    """Flip pending/running → ineligible. Idempotent: INELIGIBLE is not in the source filter."""
    mark_observation_terminal(
        observation_id=inputs.observation_id,
        status=ObservationStatus.INELIGIBLE,
        error_reason=inputs.error_reason,
        scanner_type=inputs.scanner_type,
        valid_kinds=_INELIGIBLE_KIND_VALUES,
        count_kind=lambda kind: record_ineligible_kind(kind),
    )


@activity.defn
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
            "team_id",
            "team__organization_id",
            "team__uuid",
            "scanner_id",
            "triggered_by",
            "created_at",
            "scanner_snapshot__model",
            "scanner_snapshot__scanner_version",
        ).get(pk=inputs.observation_id)
        model = obs["scanner_snapshot__model"] or ""
        credits = observation_credits_for_model(model)
        _, receipt_created = ReplayObservationUsage.objects.get_or_create(
            observation_id=inputs.observation_id,
            defaults={
                "organization_id": obs["team__organization_id"],
                "team_id": obs["team_id"],
                "scanner_id": obs["scanner_id"],
                "observation_created_at": obs["created_at"],
                "model": model,
                "credits": credits,
            },
        )
        record_alert_matches_guarded(
            observation_id=inputs.observation_id,
            team_id=obs["team_id"],
            scanner_id=obs["scanner_id"],
            model_output=inputs.scanner_result.model_output.model_dump(mode="json"),
        )
    record_observation("succeeded", inputs.scanner_type)
    record_observation_e2e(inputs.scanner_type, (timezone.now() - obs["created_at"]).total_seconds())
    if receipt_created:
        # Gate on the receipt so a lost-result retry can't double count the burn rate.
        record_credits_consumed(inputs.scanner_type, model, credits)
    logger.info(
        "replay_vision.observation.succeeded",
        observation_id=str(inputs.observation_id),
        scanner_type=inputs.scanner_type,
    )
    # Internal cross-customer telemetry: one event per succeeded scan, for adoption/volume dashboards.
    # Gated on the transition above so an at-least-once retry can't double-count a scan.
    posthoganalytics.capture(
        distinct_id=replay_vision_distinct_id(obs["team_id"]),
        event="replay_vision_scan_completed",
        # Deterministic event uuid (dedup key) so an ingestion-side retry can't produce a duplicate row.
        uuid=str(inputs.observation_id),
        properties={
            "observation_id": str(inputs.observation_id),
            "scanner_id": str(obs["scanner_id"]),
            "scanner_type": inputs.scanner_type.value,
            "model": model,
            "credits": credits,
            "triggered_by": obs["triggered_by"],
            # Pairs with the same property on the failure events, so a failure rate splits by the
            # config that produced it and a prompt edit's effect on quality becomes measurable.
            "scanner_version": obs["scanner_snapshot__scanner_version"],
            "team_id": obs["team_id"],
            "organization_id": str(obs["team__organization_id"]),
        },
        # Mirrors posthog.event_usage.groups() without fetching the Team row.
        groups={
            "instance": SITE_URL,
            "organization": str(obs["team__organization_id"]),
            "project": str(obs["team__uuid"]),
        },
    )
    # Last, and off the receipt rather than the receipt being new: the transition above already
    # committed the credits, and `record_id` deduplicates a resend, so a retry that gets this far
    # again costs nothing. Everything that has to happen for a scan happens before this line.
    report_usage(
        [
            UsageRecord(
                record_id=str(inputs.observation_id),
                producer_id="replay-vision",
                team_id=obs["team_id"],
                usage_key="replay_vision_credits",
                unit="credits",
                quantity=credits,
            )
        ],
        site="replay_vision",
    )
