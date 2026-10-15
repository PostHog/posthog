"""Which of a team's logs alert destinations native delivery cannot take over yet. A team moves whole or not at all."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts.backend.facade.contracts import DestinationBucket, DestinationEligibility
from products.alerts.backend.facade.destinations import (
    bucket_for,
    classify_alert_destinations,
    destination_template_id,
    unbound_alert_destinations,
)
from products.alerts_platform.backend.facade.contracts import DestinationType
from products.alerts_platform.backend.facade.delivery import keeps_legacy_webhook_body
from products.logs.backend.alert_destinations import LOGS_ALERT_EVENT_IDS
from products.logs.backend.models import LogsAlertConfiguration

# PORTABLE can hide edited code through `untracked_edit`, so it needs a code check before it joins.
_READY_BUCKETS = frozenset({DestinationBucket.STOCK})


class GateRefusal(StrEnum):
    """Why one destination stops its team from moving."""

    NOT_READY = "not_ready"
    # Native delivery reads destinations per alert, so this function would receive nothing.
    UNBOUND = "unbound"
    # The team's receivers parse the logs stack's body, and native delivery would send the platform body.
    NEW_WEBHOOK_BODY = "new_webhook_body"
    WEBHOOK_BODY_UNKNOWN = "webhook_body_unknown"


@frozen
class DestinationRefusal:
    hog_function_id: UUID
    # None for a function bound to no single alert.
    alert_id: UUID | None
    bucket: DestinationBucket | None
    reason: GateRefusal


class CutoverRefused(Exception):
    """The team keeps every alert on the logs stack, because some destinations cannot move yet."""

    def __init__(self, team_id: int, refusals: tuple[DestinationRefusal, ...]) -> None:
        super().__init__(f"team {team_id} has {len(refusals)} destinations that cannot move yet")
        self.team_id = team_id
        self.refusals = refusals


def destination_refusals(team_id: int) -> tuple[DestinationRefusal, ...]:
    """Every destination that stops this team moving, or nothing when all of them can move."""
    refusals: list[DestinationRefusal] = []
    webhook_template_id = destination_template_id(DestinationType.WEBHOOK)
    ready_webhooks: list[tuple[DestinationEligibility, UUID]] = []
    unbound = unbound_alert_destinations(team_id=team_id, allowed_event_ids=LOGS_ALERT_EVENT_IDS, include_disabled=True)
    # Disabled alerts and disabled destinations count too, because a person can enable either after the move.
    alert_ids = LogsAlertConfiguration.objects.filter(team_id=team_id).order_by("created_at", "id")
    for alert_id in alert_ids.values_list("id", flat=True):
        for destination in classify_alert_destinations(
            team_id=team_id, alert_id=str(alert_id), allowed_event_ids=LOGS_ALERT_EVENT_IDS
        ):
            # A function that excludes one alert id also matches that alert here. It is refused once, as unbound.
            if destination.hog_function_id in unbound:
                continue
            refusal = _bucket_refusal(destination, alert_id)
            if refusal is not None:
                refusals.append(refusal)
            elif destination.template_id == webhook_template_id:
                ready_webhooks.append((destination, alert_id))
    refusals.extend(
        DestinationRefusal(hog_function_id=function_id, alert_id=None, bucket=None, reason=GateRefusal.UNBOUND)
        for function_id in unbound
    )
    if ready_webhooks:
        body_refusal = _webhook_body_refusal(team_id)
        if body_refusal is not None:
            refusals.extend(
                DestinationRefusal(
                    hog_function_id=destination.hog_function_id,
                    alert_id=alert_id,
                    bucket=bucket_for(destination),
                    reason=body_refusal,
                )
                for destination, alert_id in ready_webhooks
            )
    return tuple(refusals)


def _bucket_refusal(destination: DestinationEligibility, alert_id: UUID) -> DestinationRefusal | None:
    bucket = bucket_for(destination)
    if bucket in _READY_BUCKETS:
        return None
    return DestinationRefusal(
        hog_function_id=destination.hog_function_id, alert_id=alert_id, bucket=bucket, reason=GateRefusal.NOT_READY
    )


def _webhook_body_refusal(team_id: int) -> GateRefusal | None:
    keeps_legacy_body = keeps_legacy_webhook_body(Team.objects.get(id=team_id))
    if keeps_legacy_body is None:
        return GateRefusal.WEBHOOK_BODY_UNKNOWN
    return None if keeps_legacy_body else GateRefusal.NEW_WEBHOOK_BODY
