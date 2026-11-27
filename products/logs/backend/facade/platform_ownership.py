"""Facade for the logs API's writes of a logs alert the platform owns.

Each call reads the logs row by id inside the caller's transaction, after the caller saved or locked it.
"""

from datetime import datetime
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import Grouping
from products.logs.backend import platform_ownership
from products.logs.backend.alert_deletion import delete_alert
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.native_alerts import (
    create_native,
    delete_native,
    native_alert_keys,
    native_alert_view,
    native_alert_views,
    owned_copy_alert_keys,
    owned_copy_views,
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
    "owned_copy_alert_keys",
    "owned_copy_views",
    "refuse_platform_only_settings",
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


def refuse_platform_only_settings(
    *, grouping: Grouping | None, labels: dict[str, str] | None, annotations: dict[str, str] | None
) -> None:
    """Raises `InvalidPlatformAlertEdit` for a grouping other than single, labels or annotations on an
    edit of an alert the logs stack owns. Only an alert the platform owns can take them."""
    platform_ownership.refuse_platform_only_settings(grouping, labels, annotations)


def creates_native_alert(team_id: int) -> bool:
    """Whether the team's next logs alert gets no logs row, so the platform alone keeps it."""
    return platform_ownership.creates_native_alert(team_id)
