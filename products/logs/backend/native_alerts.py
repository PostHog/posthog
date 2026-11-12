"""Logs alerts with no logs row, which only the alerts platform keeps.

Each function takes ids and returns the platform's view, so the logs API presents the alert with
`LogsAlertConfiguration.from_platform_view` and never holds a row it could save.
"""

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from django.utils import timezone

from products.alerts_platform.backend.facade.api import (
    create_configuration,
    delete_configuration,
    get_configuration,
    list_configurations,
    native_configuration_keys,
    update_configuration,
)
from products.alerts_platform.backend.facade.contracts import Grouping, PlatformAlertConfigurationView, SourceKind
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_ownership import platform_change_of, platform_edit_of

_LOGS: Final = (SourceKind.LOGS.value,)


def native_alert_view(*, team_id: int, alert_id: UUID, lock: bool = False) -> PlatformAlertConfigurationView | None:
    """The team's logs alert with no logs row under `alert_id`, or None. With `lock`, call it inside a
    transaction."""
    view = get_configuration(team_id=team_id, source_kinds=_LOGS, configuration_id=alert_id, lock=lock)
    return view if view is not None and view.legacy_configuration_id is None else None


def native_alert_keys(team_id: int, *, created_by_uuid: UUID | None = None) -> tuple[tuple[datetime, UUID], ...]:
    """`(created_at, id)` of each of the team's logs alerts with no logs row, for paging them beside logs rows."""
    return native_configuration_keys(team_id=team_id, source_kind=SourceKind.LOGS, created_by_uuid=created_by_uuid)


def native_alert_views(team_id: int, alert_ids: Collection[UUID]) -> tuple[PlatformAlertConfigurationView, ...]:
    """The named logs alerts with no logs row, in no particular order."""
    if not alert_ids:
        return ()
    page = list_configurations(
        team_id=team_id, source_kinds=_LOGS, limit=len(alert_ids), offset=0, configuration_ids=alert_ids
    )
    return tuple(view for view in page.configurations if view.legacy_configuration_id is None)


def create_native(
    *,
    team_id: int,
    fields: Mapping[str, Any],
    grouping: Grouping | None,
    labels: dict[str, str] | None,
    annotations: dict[str, str] | None,
    created_by_id: int,
) -> PlatformAlertConfigurationView:
    """Creates a logs alert on the platform alone, from the logs API's settings with their defaults applied.

    Raises `PlatformAlertCreateRefused` at the team's cap, and `InvalidPlatformAlertEdit` for settings the
    platform's logs schema rejects.
    """
    edit = platform_edit_of(
        LogsAlertConfiguration(team_id=team_id, **fields),
        grouping if grouping is not None else Grouping(),
        labels,
        annotations,
    )
    return create_configuration(
        team_id=team_id, source_kind=SourceKind.LOGS, edit=edit, created_by_id=created_by_id, natively=True
    )


def update_native(
    *,
    team_id: int,
    alert_id: UUID,
    changes: Mapping[str, Any],
    grouping: Grouping | None,
    labels: dict[str, str] | None,
    annotations: dict[str, str] | None,
    snooze_until: datetime | None,
    snooze_changed: bool,
) -> PlatformAlertConfigurationView | None:
    """Writes a logs API edit onto the configuration. `changes` holds the logs API's fields, only the
    ones the edit names. None when the alert is gone.

    Raises `InvalidPlatformAlertEdit` for an edit the platform's logs schema rejects.
    """
    view = native_alert_view(team_id=team_id, alert_id=alert_id, lock=True)
    if view is None:
        return None
    alert = LogsAlertConfiguration.from_platform_view(view, team_id=team_id, now=timezone.now())
    for field, value in changes.items():
        setattr(alert, field, value)
    return update_configuration(
        team_id=team_id,
        source_kinds=_LOGS,
        configuration_id=alert_id,
        change=platform_change_of(alert, grouping, labels, annotations),
        snooze_until=snooze_until,
        snooze_changed=snooze_changed,
    )


def delete_native(*, team_id: int, alert_id: UUID) -> bool:
    """Deletes the configuration, closing its firing and removing its destinations. False when it was
    already gone."""
    return delete_configuration(team_id=team_id, source_kinds=_LOGS, configuration_id=alert_id)
