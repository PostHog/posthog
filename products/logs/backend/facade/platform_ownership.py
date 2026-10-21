"""Facade for the logs API's half of keeping both rows of a platform-owned logs alert in step.

Each call reads the logs row by id inside the caller's transaction, after the caller saved or locked it.
"""

from datetime import datetime
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import Grouping
from products.logs.backend import platform_ownership
from products.logs.backend.alert_deletion import delete_alert
from products.logs.backend.models import LogsAlertConfiguration

__all__ = ["delete_alert", "on_created", "on_updated"]


def _alert(team_id: int, alert_id: UUID) -> LogsAlertConfiguration | None:
    return LogsAlertConfiguration.objects.filter(team_id=team_id, id=alert_id).first()


def on_created(*, team_id: int, alert_id: UUID, at: datetime, grouping: Grouping | None = None) -> bool:
    """Hands a new alert to the platform when its team has begun the cutover, with its copy grouped
    by `grouping`. False when the alert stays with logs.

    Raises `InvalidPlatformAlertEdit` when the alert cannot take the grouping. Only an alert the
    platform owns can take one other than single.
    """
    alert = _alert(team_id, alert_id)
    return alert is not None and platform_ownership.on_created(alert, at, grouping=grouping)


def on_updated(*, team_id: int, alert_id: UUID, snooze_changed: bool, grouping: Grouping | None = None) -> None:
    """Writes an edit the logs API saved onto the platform's copy, with the grouping the edit set.
    A `grouping` of None keeps the copy's own.

    Raises `InvalidPlatformAlertEdit` when the platform's schema rejects the edit, or when the
    alert cannot take the grouping. Only an alert the platform owns can take one other than single.
    """
    alert = _alert(team_id, alert_id)
    if alert is not None:
        platform_ownership.on_updated(alert, snooze_changed=snooze_changed, grouping=grouping)
