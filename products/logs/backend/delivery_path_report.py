"""Which path each logs alert of a team delivers through once the platform owns it.

Native delivery sends an alert whose destinations are all stock. Every other alert keeps sending
through its HogFunctions, from the `$logs_alert_*` events the platform emits for it. Both paths
can deliver any destination, so the report only informs a cutover: it never stops one.

Delivery decides the path again at send time, so an edit after the report changes what it says.
"""

from __future__ import annotations

from uuid import UUID

from posthog.dataclasses import frozen

from products.alerts.backend.facade.contracts import DeliveryPathChoice
from products.alerts.backend.facade.destinations import (
    team_delivery_paths as alert_delivery_paths,
    unbound_alert_destinations,
)
from products.alerts_platform.backend.facade.contracts import SourceKind
from products.logs.backend.alert_destinations import LOGS_ALERT_EVENT_IDS
from products.logs.backend.models import LogsAlertConfiguration


@frozen
class AlertDeliveryPath:
    alert_id: UUID
    choice: DeliveryPathChoice


@frozen
class TeamDeliveryPaths:
    alerts: tuple[AlertDeliveryPath, ...]
    unbound_functions: tuple[UUID, ...]


def team_delivery_paths(team_id: int) -> TeamDeliveryPaths:
    # Disabled alerts and destinations count too, because a person can enable either after the move.
    alert_ids = list(
        LogsAlertConfiguration.objects.filter(team_id=team_id).order_by("created_at", "id").values_list("id", flat=True)
    )
    choices = alert_delivery_paths(
        source=SourceKind.LOGS,
        team_id=team_id,
        alert_ids=[str(alert_id) for alert_id in alert_ids],
        allowed_event_ids=LOGS_ALERT_EVENT_IDS,
    )
    return TeamDeliveryPaths(
        alerts=tuple(AlertDeliveryPath(alert_id=alert_id, choice=choices[str(alert_id)]) for alert_id in alert_ids),
        unbound_functions=unbound_alert_destinations(
            team_id=team_id, allowed_event_ids=LOGS_ALERT_EVENT_IDS, include_disabled=True
        ),
    )
