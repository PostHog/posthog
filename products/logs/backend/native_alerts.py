"""The logs API's view of a logs alert with no logs row, which only the alerts platform keeps.

The logs API serves such an alert under its configuration's id, with the same fields as an alert that
has a logs row, so its clients, Terraform among them, cannot tell the two apart. Each one is presented
as an unsaved `LogsAlertConfiguration` built from the configuration. Nothing saves it: every write goes
to the platform.
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from django.utils import timezone

from products.alerts_platform.backend.facade.api import (
    delete_configuration,
    get_configuration,
    list_native_configurations,
    update_configuration,
)
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    Grouping,
    PlatformAlertConfigurationView,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import CONDITION_FIELDS
from products.logs.backend.platform_ownership import platform_change_of
from products.logs.backend.platform_source_config import filters_of

_LOGS: Final = (SourceKind.LOGS.value,)


def _no_logs_row(*_: object, **__: object) -> None:
    raise RuntimeError("This logs alert has no logs row. Write it through the platform.")


def is_native(alert: LogsAlertConfiguration) -> bool:
    """Whether the alert has no logs row, so `as_logs_alert` built it."""
    return alert._state.adding and alert.owner == PlatformAlertOwner.PLATFORM


def as_logs_alert(view: PlatformAlertConfigurationView, *, team_id: int, now: datetime) -> LogsAlertConfiguration:
    condition = view.source_config[SOURCE_CONDITION_KEY]
    snoozed = view.snooze_until is not None and view.snooze_until > now
    alert = LogsAlertConfiguration(
        id=view.id,
        team_id=team_id,
        name=view.name,
        enabled=view.enabled,
        filters=filters_of(view.source_config),
        **{field: condition[field] for field in CONDITION_FIELDS},
        check_interval_minutes=view.check_interval_minutes,
        evaluation_periods=view.evaluation_periods,
        datapoints_to_alarm=view.datapoints_to_alarm,
        cooldown_minutes=view.cooldown_minutes,
        schedule_restriction=view.schedule_restriction,
        snooze_until=view.snooze_until,
        next_check_at=view.next_check_at,
        consecutive_failures=view.consecutive_failures,
        # The serializer takes the state from the platform. Only a snooze is kept on this side, as on a
        # logs row the platform owns.
        state=LogsAlertConfiguration.State.SNOOZED if snoozed else LogsAlertConfiguration.State.NOT_FIRING,
        owner=PlatformAlertOwner.PLATFORM,
        # The platform checked the alert from its creation, so its whole history is the platform's.
        owner_changed_at=view.created_at,
        created_by_id=view.created_by_id,
        first_enabled_at=view.first_enabled_at,
        created_at=view.created_at,
        updated_at=view.updated_at,
    )
    # What the viewset annotates on a logs row. No logs check ever ran, so there is no logs event.
    alert._state_timeline_events = []  # type: ignore[attr-defined]
    alert._latest_error_message = None  # type: ignore[attr-defined]
    alert._pre_window_toggle_kind = None  # type: ignore[attr-defined]
    # A write path that forgets the alert has no logs row fails here instead of creating one.
    for method in ("save", "delete"):
        setattr(alert, method, _no_logs_row)
    return alert


def native_alert(*, team_id: int, alert_id: UUID, lock: bool = False) -> LogsAlertConfiguration | None:
    """The team's logs alert with no logs row under `alert_id`, or None. With `lock`, call it inside a
    transaction."""
    view = get_configuration(team_id=team_id, source_kinds=_LOGS, configuration_id=alert_id, lock=lock)
    if view is None or view.legacy_configuration_id is not None:
        return None
    return as_logs_alert(view, team_id=team_id, now=timezone.now())


def native_alerts(team_id: int, *, created_by_uuid: UUID | None = None) -> list[LogsAlertConfiguration]:
    views = list_native_configurations(team_id=team_id, source_kind=SourceKind.LOGS, created_by_uuid=created_by_uuid)
    now = timezone.now()
    return [as_logs_alert(view, team_id=team_id, now=now) for view in views]


def update_native(
    alert: LogsAlertConfiguration,
    changes: Mapping[str, Any],
    *,
    grouping: Grouping | None,
    snooze_until: datetime | None,
    snooze_changed: bool,
) -> LogsAlertConfiguration | None:
    """Writes a logs API edit onto the configuration. `changes` holds the logs API's fields, only the
    ones the edit names. None when the alert is gone.

    Raises `InvalidPlatformAlertEdit` for an edit the platform's logs schema rejects.
    """

    # The same settings a logs row carries onto its copy, so the two kinds of alert edit alike.
    for field, value in changes.items():
        setattr(alert, field, value)

    view = update_configuration(
        team_id=alert.team_id,
        source_kinds=_LOGS,
        configuration_id=alert.id,
        change=platform_change_of(alert, grouping),
        snooze_until=snooze_until,
        snooze_changed=snooze_changed,
    )
    return None if view is None else as_logs_alert(view, team_id=alert.team_id, now=timezone.now())


def delete_native(alert: LogsAlertConfiguration) -> bool:
    """Deletes the configuration, closing its firing and removing its destinations. False when it was
    already gone."""
    return delete_configuration(team_id=alert.team_id, source_kinds=_LOGS, configuration_id=alert.id)
