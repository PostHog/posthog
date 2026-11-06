"""The logs API's view of a logs alert with no logs row, which only the alerts platform keeps.

The logs API serves such an alert under its configuration's id, with the same fields as an alert that
has a logs row, so its clients, Terraform among them, cannot tell the two apart. Each one is presented
as an unsaved `LogsAlertConfiguration` built from the configuration. Nothing saves it: every write goes
to the platform.
"""

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from django.utils import timezone

from products.alerts_platform.backend.facade.api import (
    create_configuration,
    delete_configuration,
    get_configuration,
    list_configurations,
    update_configuration,
)
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    Grouping,
    PlatformAlertConfigurationEdit,
    PlatformAlertConfigurationView,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import CONDITION_FIELDS
from products.logs.backend.platform_source_config import filters_of, logs_source_config

_LOGS: Final = (SourceKind.LOGS.value,)
# Large enough for every logs alert of one team on one page. The cap is 20, and an uncapped team stays
# far below this.
_TEAM_PAGE: Final = 1000
# The settings a logs API edit and a platform edit name the same way.
_SHARED_FIELDS: Final = (
    "name",
    "enabled",
    "evaluation_periods",
    "datapoints_to_alarm",
    "cooldown_minutes",
    "schedule_restriction",
)


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
    return alert


def native_alert(*, team_id: int, alert_id: UUID, lock: bool = False) -> LogsAlertConfiguration | None:
    """The team's logs alert with no logs row under `alert_id`, or None. With `lock`, call it inside a
    transaction."""
    view = get_configuration(team_id=team_id, source_kinds=_LOGS, configuration_id=alert_id, lock=lock)
    if view is None or view.legacy_configuration_id is not None:
        return None
    return as_logs_alert(view, team_id=team_id, now=timezone.now())


def native_alerts(team_id: int) -> list[LogsAlertConfiguration]:
    page = list_configurations(team_id=team_id, source_kinds=_LOGS, limit=_TEAM_PAGE, offset=0, native_only=True)
    now = timezone.now()
    return [as_logs_alert(view, team_id=team_id, now=now) for view in page.configurations]


def create_native(
    *, team_id: int, fields: Mapping[str, Any], grouping: Grouping | None, created_by_id: int
) -> LogsAlertConfiguration:
    """Creates a logs alert on the platform alone, from the logs API's fields with their defaults applied.

    Raises `PlatformAlertCreateRefused` at the team's cap, and `InvalidPlatformAlertEdit` for settings the
    platform's logs schema rejects.
    """
    edit = PlatformAlertConfigurationEdit(
        name=fields["name"],
        enabled=fields["enabled"],
        source_config=logs_source_config(
            fields.get("filters", {}), {field: fields[field] for field in CONDITION_FIELDS}
        ),
        grouping=grouping if grouping is not None else Grouping(),
        schedule_restriction=fields.get("schedule_restriction"),
        evaluation_periods=fields["evaluation_periods"],
        datapoints_to_alarm=fields["datapoints_to_alarm"],
        cooldown_minutes=fields["cooldown_minutes"],
    )
    view = create_configuration(team_id=team_id, source_kind=SourceKind.LOGS, edit=edit, created_by_id=created_by_id)
    return as_logs_alert(view, team_id=team_id, now=timezone.now())


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

    def change(stored: PlatformAlertConfigurationEdit) -> PlatformAlertConfigurationEdit:
        condition = {
            **stored.source_config[SOURCE_CONDITION_KEY],
            **{field: changes[field] for field in CONDITION_FIELDS if field in changes},
        }
        filters = changes["filters"] if "filters" in changes else filters_of(stored.source_config)
        return replace(
            stored,
            source_config=logs_source_config(filters, condition),
            grouping=grouping if grouping is not None else stored.grouping,
            **{field: changes[field] for field in _SHARED_FIELDS if field in changes},
        )

    view = update_configuration(
        team_id=alert.team_id,
        source_kinds=_LOGS,
        configuration_id=alert.id,
        change=change,
        snooze_until=snooze_until,
        snooze_changed=snooze_changed,
    )
    return None if view is None else as_logs_alert(view, team_id=alert.team_id, now=timezone.now())


def delete_native(alert: LogsAlertConfiguration) -> bool:
    """Deletes the configuration, closing its firing and removing its destinations. False when it was
    already gone."""
    return delete_configuration(team_id=alert.team_id, source_kinds=_LOGS, configuration_id=alert.id)
