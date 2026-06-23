"""Delivery: persist findings to Postgres, then fan out one in-app notification to the team."""

from datetime import UTC, datetime
from typing import Any

from django.db import transaction

import structlog

from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.pulse.backend.models import PulseDigest, PulseDigestStatus, PulseFinding, PulseSubscription
from products.pulse.backend.temporal.types import EnrichedFinding

logger = structlog.get_logger(__name__)


def _persist_findings_sync(digest_id: str, team_id: int, findings: list[EnrichedFinding]) -> list[str]:
    """Persist findings once and return their row IDs. Idempotent: short-circuits if the digest is
    already DELIVERED or already has findings (returns the existing rows' IDs).

    Does NOT flip the digest to DELIVERED — the workflow does that only after synthesis + notification,
    so DELIVERED means the digest is fully ready (findings AND the "big picture" summary)."""
    with team_scope(team_id, canonical=True):
        digest = PulseDigest.objects.get(id=digest_id, team_id=team_id)

        existing = list(PulseFinding.objects.filter(digest_id=digest_id).order_by("rank"))
        if digest.status == PulseDigestStatus.DELIVERED or existing:
            return [str(row.id) for row in existing]

        rows = [
            PulseFinding(
                team_id=team_id,  # denormalized from the digest so the row is fail-closed
                digest=digest,
                metric_descriptor=f.descriptor.model_dump(),
                metric_label=f.descriptor.label[:255],
                current_value=f.current_value,
                baseline_value=f.baseline_value,
                change_pct=f.change_pct,
                impact=f.impact,
                robust_z=f.robust_z,
                attribution_breakdown=f.attribution_breakdown,
                evidence=f.evidence,
                narrative=f.narrative,
                rank=idx,
            )
            for idx, f in enumerate(findings)
        ]
        created = PulseFinding.objects.bulk_create(rows)

        return [str(row.id) for row in created]


def _pulse_notification_title(findings: list[EnrichedFinding]) -> str:
    top = findings[0]
    direction = "up" if top.change_pct > 0 else "down"
    headline = f"{top.descriptor.label} is {direction} {abs(top.change_pct):.0%}"
    if len(findings) > 1:
        headline += f" (+{len(findings) - 1} more)"
    return headline[:255]


def _dispatch_pulse_notifications(team_id: int, digest_id: str, findings: list[EnrichedFinding]) -> None:
    """Fan out a single in-app notification to the team for a delivered digest.

    The notifications facade resolves the team's members (TargetType.TEAM) and applies their
    per-user preference filtering. Idempotent: one team-level dispatch check keyed on the digest
    means a Temporal retry that re-enters delivery is a no-op once the digest has been notified.
    """
    # Lazy import: the pulse package is eagerly preloaded via posthog.api, and importing the
    # notifications facade at module level triggers an app-init circular import. It resolves
    # fine at activity-call time, matching the pattern in selection.py.
    from products.notifications.backend.facade.api import (  # noqa: PLC0415
        NotificationData,
        NotificationType,
        Priority,
        SourceType,
        TargetType,
        create_notification,
        has_been_dispatched,
    )

    if not findings:
        return

    if has_been_dispatched(
        notification_type=NotificationType.PULSE_DIGEST,
        target_type=TargetType.TEAM,
        target_id=str(team_id),
        resource_id=digest_id,
        source_id=digest_id,
    ):
        return

    create_notification(
        NotificationData(
            team_id=team_id,
            notification_type=NotificationType.PULSE_DIGEST,
            priority=Priority.NORMAL,
            title=_pulse_notification_title(findings),
            body=findings[0].narrative,
            target_type=TargetType.TEAM,
            target_id=str(team_id),
            resource_id=digest_id,
            source_url=f"/pulse?digest={digest_id}",
            source_type=SourceType.PULSE,
            source_id=digest_id,
        )
    )


def _update_subscription_timestamps_sync(team_id: int) -> None:
    with team_scope(team_id, canonical=True):
        subscription = PulseSubscription.objects.filter(team_id=team_id).first()
        if subscription:
            subscription.last_scan_at = datetime.now(UTC)
            subscription.save(update_fields=["last_scan_at"])


@database_sync_to_async
def _persist_sync(team_id: int, digest_id: str, findings: list[EnrichedFinding]) -> list[str]:
    with transaction.atomic():
        finding_ids = _persist_findings_sync(digest_id, team_id, findings)
        _update_subscription_timestamps_sync(team_id)
    return finding_ids


async def persist_findings(team_id: int, digest_id: str, findings: list[EnrichedFinding]) -> list[str]:
    """Persist findings and record the scan time on the subscription. Does NOT mark the digest
    DELIVERED — the workflow does that only after synthesis + notification, so DELIVERED means
    fully-ready. Notification fan-out is a separate step."""
    return await _persist_sync(team_id, digest_id, findings)


async def notify_digest(team_id: int, digest_id: str, findings: list[EnrichedFinding]) -> None:
    """Fan out in-app notifications for a delivered digest.

    Runs after persist_findings so a rolled-back persist never produces orphan notifications.
    create_notification defers the Kafka publish to on_commit, so the row write and the
    notification stay consistent.
    """
    await database_sync_to_async(_dispatch_pulse_notifications)(team_id, digest_id, findings)


# PostHog-emitted event, captured into the team's own project so customers can trigger CDP destinations
# / workflows on findings. Specific enough to not collide with customer events.
PULSE_FINDING_EVENT = "pulse_finding_surfaced"


def _pulse_event_properties(digest_id: str, rank: int, finding: EnrichedFinding) -> dict[str, Any]:
    attribution = finding.attribution_breakdown or {}
    return {
        "pulse_digest_id": digest_id,
        "pulse_finding_rank": rank,
        "metric": finding.descriptor.label,
        "direction": "up" if finding.change_pct > 0 else "down",
        "change_pct": round(finding.change_pct, 4),
        "absolute_change": round(finding.current_value - finding.baseline_value, 2),
        "current_value": finding.current_value,
        "baseline_value": finding.baseline_value,
        "robust_z": round(finding.robust_z, 2),
        "impact": round(finding.impact, 2),
        "segment_property": attribution.get("property"),
        "segment_value": attribution.get("value"),
        "narrative": finding.narrative,
        "insight_url": finding.descriptor.url,
        "source_url": f"/pulse?digest={digest_id}",
    }


def _emit_pulse_events_sync(team_id: int, digest_id: str, findings: list[EnrichedFinding]) -> None:
    """Emit one ``pulse_finding_surfaced`` event per finding INTO the team's own project, so customers can
    build CDP destinations / workflows (Slack, webhook, ...) on top of Pulse findings.

    Best-effort: a capture failure for one finding is logged and skipped — it never blocks delivery, since
    the events are an additive trigger, not the digest itself. Person processing is off (system signals,
    not user activity).
    """
    # Lazy import: the pulse package is eagerly preloaded via posthog.api, so importing the capture path
    # at module level risks an app-init import cycle (matches the notifications import above).
    from posthog.api.capture import capture_internal  # noqa: PLC0415

    if not findings:
        return
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return
    now = datetime.now(UTC)
    for rank, finding in enumerate(findings):
        try:
            response = capture_internal(
                token=team.api_token,
                event_name=PULSE_FINDING_EVENT,
                event_source="pulse",
                distinct_id=f"pulse-digest-{digest_id}",
                timestamp=now,
                properties=_pulse_event_properties(digest_id, rank, finding),
                process_person_profile=False,
            )
            response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "pulse_emit_event_failed",
                team_id=team_id,
                digest_id=digest_id,
                metric=finding.descriptor.label[:80],
                error=str(exc),
            )


async def emit_pulse_events(team_id: int, digest_id: str, findings: list[EnrichedFinding]) -> None:
    """Emit ``pulse_finding_surfaced`` events into the team's project (CDP/workflow trigger). Best-effort."""
    await database_sync_to_async(_emit_pulse_events_sync, thread_sensitive=False)(team_id, digest_id, findings)
