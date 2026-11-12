"""Facade for the logs API's half of keeping both rows of a platform-owned logs alert in step.

Each call reads the logs row by id inside the caller's transaction, after the caller saved or locked it.
"""

from datetime import datetime
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import Grouping
from products.logs.backend import platform_cutover, platform_ownership
from products.logs.backend.alert_deletion import delete_alert
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.native_alerts import (
    create_native,
    delete_native,
    native_alert_keys,
    native_alert_view,
    native_alert_views,
    update_native,
)

__all__ = [
    "create_native",
    "creates_native_alert",
    "delete_alert",
    "delete_native",
    "native_alert_keys",
    "native_alert_view",
    "native_alert_views",
    "on_created",
    "on_updated",
    "update_native",
]


def _alert(team_id: int, alert_id: UUID) -> LogsAlertConfiguration | None:
    return LogsAlertConfiguration.objects.filter(team_id=team_id, id=alert_id).first()


def on_created(
    *,
    team_id: int,
    alert_id: UUID,
    at: datetime,
    grouping: Grouping | None = None,
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
) -> bool:
    """Hands a new alert to the platform, with its copy grouped by `grouping` and carrying `labels` and `annotations`,
    unless its team keeps its alerts on logs. False when the alert stays with logs.

    Raises `InvalidPlatformAlertEdit` when the alert cannot take the grouping, the labels or the
    annotations. Only an alert the platform owns can take labels, annotations, or a grouping other than
    single.
    """
    alert = _alert(team_id, alert_id)
    return alert is not None and platform_ownership.on_created(
        alert, at, grouping=grouping, labels=labels, annotations=annotations
    )


def on_updated(
    *,
    team_id: int,
    alert_id: UUID,
    snooze_changed: bool,
    grouping: Grouping | None = None,
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
    at: datetime | None = None,
) -> None:
    """Writes an edit the logs API saved onto the platform's copy, with the grouping, labels and
    annotations the edit set. A `grouping`, `labels` or `annotations` of None keeps the copy's own.
    `at` is when the edit started, before its logs history row.

    Raises `InvalidPlatformAlertEdit` when the platform's schema rejects the edit, or when the
    alert cannot take the grouping, the labels or the annotations. Only an alert the platform owns can
    take labels, annotations, or a grouping other than single.
    """
    alert = _alert(team_id, alert_id)
    if alert is not None:
        platform_ownership.on_updated(
            alert,
            snooze_changed=snooze_changed,
            grouping=grouping,
            labels=labels,
            annotations=annotations,
            at=at,
        )


def creates_native_alert(team_id: int) -> bool:
    """Whether the team's next logs alert gets no logs row, so the platform alone keeps it."""
    return platform_cutover.creates_native_alert(team_id)
