"""Facade for the logs API's half of keeping both rows of a platform-owned logs alert in step.

Each call reads the logs row by id inside the caller's transaction, after the caller saved or locked it.
"""

from datetime import datetime
from uuid import UUID

from products.logs.backend import platform_ownership
from products.logs.backend.models import LogsAlertConfiguration

__all__ = ["on_created", "on_deleted", "on_updated"]


def _alert(team_id: int, alert_id: UUID) -> LogsAlertConfiguration | None:
    return LogsAlertConfiguration.objects.filter(team_id=team_id, id=alert_id).first()


def on_created(*, team_id: int, alert_id: UUID, at: datetime) -> bool:
    """Hands a new alert to the platform when its team has begun the cutover. False when the alert
    stays with logs."""
    alert = _alert(team_id, alert_id)
    return alert is not None and platform_ownership.on_created(alert, at)


def on_updated(*, team_id: int, alert_id: UUID, snooze_changed: bool) -> None:
    """Writes an edit the logs API saved onto the platform's copy.

    Raises `InvalidPlatformAlertEdit` when the platform's schema rejects the edit.
    """
    alert = _alert(team_id, alert_id)
    if alert is not None:
        platform_ownership.on_updated(alert, snooze_changed=snooze_changed)


def on_deleted(*, team_id: int, alert_id: UUID) -> None:
    platform_ownership.on_deleted(team_id=team_id, alert_id=alert_id)
