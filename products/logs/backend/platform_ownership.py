"""Keeps both rows of a logs alert the platform owns in step.

A logs alert the platform owns keeps its logs row until every team is cut over: the logs page reads
it, the shadow evaluation runs it, and a rollback hands it back. So every write to either row reaches
the other in the same transaction, and every writer locks the logs row before the platform's copy.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from django.utils import timezone

from products.alerts_platform.backend.facade.api import close_owned_firings_now, delete_owned_copy, update_owned_copy
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    PlatformAlertConfigurationEdit,
    PlatformAlertNotEditable,
)
from products.logs.backend.alert_state_machine import apply_enabled
from products.logs.backend.facade.api import close_incident_before_delete
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import CONDITION_FIELDS, SETTINGS_FIELDS, platform_upsert_of
from products.logs.backend.platform_cutover import hand_over, has_begun_cutover, in_an_environment
from products.logs.backend.platform_source_config import filters_of


def on_created(alert: LogsAlertConfiguration, at: datetime) -> bool:
    """Hands a new alert to the platform when its team has begun the cutover, so the team never has
    to be cut over again for it. False when the alert stays with logs."""
    return not in_an_environment(alert) and has_begun_cutover(alert.team_id) and hand_over(alert, at)


def on_updated(alert: LogsAlertConfiguration, *, snooze_changed: bool) -> None:
    """Writes an edit the logs API saved onto the platform's copy.

    Raises `InvalidPlatformAlertEdit` when the platform's schema rejects the edit.
    """
    update_owned_copy(
        team_id=alert.team_id,
        legacy_configuration_id=alert.id,
        change=_platform_change_of(alert),
        snooze_until=alert.snooze_until,
        snooze_changed=snooze_changed,
    )


def on_deleted(*, team_id: int, alert_id: UUID) -> None:
    delete_owned_copy(team_id=team_id, legacy_configuration_id=alert_id)


def _platform_change_of(
    alert: LogsAlertConfiguration,
) -> Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit]:
    # Only the settings a logs alert has. The platform's own, such as grouping, keep what the copy
    # stores, so an edit through the logs API never resets them.
    upsert = platform_upsert_of(alert)
    shared = {field: getattr(upsert, field) for field in SETTINGS_FIELDS}
    return lambda stored: replace(stored, enabled=upsert.enabled, **shared)


def mirror_platform_edit(
    *, team_id: int, legacy_configuration_id: UUID
) -> Callable[[PlatformAlertConfigurationEdit], None] | None:
    """Locks the logs row of an alert edited through the platform API, and returns its writer."""
    alert = LogsAlertConfiguration.objects.select_for_update().filter(id=legacy_configuration_id).first()
    if alert is None:
        return None
    if alert.team_id != team_id:
        # A copy lives on the project, and its logs row on the environment. The platform API checked
        # access to the project only.
        raise PlatformAlertNotEditable(
            "This alert belongs to one of this project's environments. Edit it on that environment's logs alerts page."
        )
    return lambda edit: _write_logs_row(alert, edit)


def _write_logs_row(alert: LogsAlertConfiguration, edit: PlatformAlertConfigurationEdit) -> None:
    # The inverse of `platform_upsert_of`, over the same field lists.
    condition = edit.source_config[SOURCE_CONDITION_KEY]
    # The shadow evaluation still runs this row, so an on or off moves its state the way the logs API does.
    enabled_fields = apply_enabled(alert, edit.enabled, now=timezone.now())
    alert.filters = filters_of(edit.source_config)
    for field in CONDITION_FIELDS:
        setattr(alert, field, condition[field])
    for field in SETTINGS_FIELDS:
        if field != "source_config":
            setattr(alert, field, getattr(edit, field))
    alert.save(
        update_fields=[
            *enabled_fields,
            "filters",
            *CONDITION_FIELDS,
            *(field for field in SETTINGS_FIELDS if field != "source_config"),
            "updated_at",
        ]
    )


def before_delete(alert: LogsAlertConfiguration) -> None:
    """Closes the incident of a firing alert while its destinations still exist, on whichever stack
    owns it."""
    if alert.platform_owned:
        close_owned_firings_now(team_id=alert.team_id, legacy_configuration_id=alert.id)
    else:
        close_incident_before_delete(team_id=alert.team_id, alert_id=str(alert.id), state=alert.state)
