"""Logs alerts whose destinations native delivery cannot take over, and why."""

from __future__ import annotations

from collections.abc import Iterator
from uuid import UUID

from posthog.dataclasses import frozen

from products.alerts.backend.facade.contracts import DestinationEligibility
from products.alerts.backend.facade.destinations import classify_alert_destinations, unbound_alert_destinations
from products.logs.backend.alert_destinations import LOGS_ALERT_EVENT_IDS
from products.logs.backend.models import LogsAlertConfiguration


@frozen
class HeldBackDestination:
    team_id: int
    alert_id: UUID
    destination: DestinationEligibility


def held_back_destinations(*, team_id: int | None = None) -> Iterator[HeldBackDestination]:
    """Every destination of an enabled logs alert that native delivery cannot send as it does today."""
    alerts = LogsAlertConfiguration.objects.filter(enabled=True).order_by("team_id", "created_at")
    if team_id is not None:
        alerts = alerts.filter(team_id=team_id)
    for alert in alerts.only("id", "team_id").iterator():
        for destination in classify_alert_destinations(
            team_id=alert.team_id, alert_id=str(alert.id), allowed_event_ids=LOGS_ALERT_EVENT_IDS
        ):
            if destination.hold_backs:
                yield HeldBackDestination(team_id=alert.team_id, alert_id=alert.id, destination=destination)


def unbound_destinations(*, team_id: int | None = None) -> Iterator[tuple[int, UUID]]:
    """Every enabled logs alert function bound to no single alert, as (team id, function id), for teams with an enabled alert."""
    teams = LogsAlertConfiguration.objects.filter(enabled=True)
    if team_id is not None:
        teams = teams.filter(team_id=team_id)
    for alert_team_id in teams.order_by("team_id").values_list("team_id", flat=True).distinct().iterator():
        for function_id in unbound_alert_destinations(team_id=alert_team_id, allowed_event_ids=LOGS_ALERT_EVENT_IDS):
            yield alert_team_id, function_id
