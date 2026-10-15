"""Which of a team's logs alert destinations native delivery cannot take over yet. A team moves whole or not at all."""

from __future__ import annotations

from enum import StrEnum
from functools import cached_property
from uuid import UUID

from posthog.dataclasses import frozen
from posthog.models import Team

from products.alerts.backend.facade.contracts import DestinationBucket
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


class TeamGate:
    """One team's destination checks. The unbound lookup and the webhook body flag are read once per team."""

    def __init__(self, team_id: int) -> None:
        self.team_id = team_id
        self._unbound = unbound_alert_destinations(
            team_id=team_id, allowed_event_ids=LOGS_ALERT_EVENT_IDS, include_disabled=True
        )
        self._webhook_template_id = destination_template_id(DestinationType.WEBHOOK)

    def refusals(self) -> tuple[DestinationRefusal, ...]:
        """Every destination that stops this team moving, or nothing when all of them can move."""
        refusals: list[DestinationRefusal] = []
        # Disabled alerts and disabled destinations count too, because a person can enable either after the move.
        alerts = LogsAlertConfiguration.objects.filter(team_id=self.team_id).order_by("created_at", "id")
        for alert_id in alerts.values_list("id", flat=True):
            refusals.extend(self.alert_refusals(alert_id))
        refusals.extend(
            DestinationRefusal(hog_function_id=function_id, alert_id=None, bucket=None, reason=GateRefusal.UNBOUND)
            for function_id in self._unbound
        )
        return tuple(refusals)

    def alert_refusals(self, alert_id: UUID, *, lock: bool = False) -> list[DestinationRefusal]:
        """One alert's refusals. `lock` keeps its destinations locked until the caller's transaction ends."""
        refusals: list[DestinationRefusal] = []
        for destination in classify_alert_destinations(
            team_id=self.team_id, alert_id=str(alert_id), allowed_event_ids=LOGS_ALERT_EVENT_IDS, lock=lock
        ):
            # A function that excludes one alert id also matches that alert here. It is refused once, as unbound.
            if destination.hog_function_id in self._unbound:
                continue
            bucket = bucket_for(destination)
            if bucket not in _READY_BUCKETS:
                reason: GateRefusal | None = GateRefusal.NOT_READY
            elif destination.template_id == self._webhook_template_id:
                reason = self._webhook_body_refusal
            else:
                reason = None
            if reason is not None:
                refusals.append(
                    DestinationRefusal(
                        hog_function_id=destination.hog_function_id, alert_id=alert_id, bucket=bucket, reason=reason
                    )
                )
        return refusals

    @cached_property
    def _webhook_body_refusal(self) -> GateRefusal | None:
        keeps_legacy_body = keeps_legacy_webhook_body(Team.objects.get(id=self.team_id))
        if keeps_legacy_body is None:
            return GateRefusal.WEBHOOK_BODY_UNKNOWN
        return None if keeps_legacy_body else GateRefusal.NEW_WEBHOOK_BODY
