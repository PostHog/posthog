"""Keeps both rows of a logs alert the platform owns in step.

A logs alert the platform owns keeps its logs row until every team is cut over: the logs page reads
it, the shadow evaluation runs it, and a rollback hands it back. So every write to either row reaches
the other in the same transaction, and every writer locks the logs row before the platform's copy.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Final
from uuid import UUID

from django.utils import timezone

from products.alerts_platform.backend.facade.api import close_owned_firings_now, delete_owned_copy, update_owned_copy
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    Grouping,
    GroupingMode,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    PlatformAlertCreateRefused,
    PlatformAlertNotEditable,
)
from products.logs.backend.alert_creation import AlertLimitReached, claim_alert_slot, first_check_at
from products.logs.backend.alert_group_columns import grouping_problem
from products.logs.backend.alert_state_machine import apply_enabled
from products.logs.backend.facade.api import close_incident_before_delete
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import CONDITION_FIELDS, SETTINGS_FIELDS, platform_upsert_of
from products.logs.backend.platform_cutover import hand_over, has_begun_cutover, in_an_environment
from products.logs.backend.platform_source_config import filters_of

GROUPING_NOT_AVAILABLE: Final = "Grouping isn't available for this alert yet. Set the mode to single to save it."


def _refuse_grouping_on_logs(grouping: Grouping | None) -> None:
    # The logs stack cannot group. A single grouping is what the API reads for such an alert, so a
    # client that sends back what it read still saves.
    if grouping is not None and grouping.mode != GroupingMode.SINGLE:
        raise InvalidPlatformAlertEdit("grouping", GROUPING_NOT_AVAILABLE)


def on_created(alert: LogsAlertConfiguration, at: datetime, *, grouping: Grouping | None = None) -> bool:
    """Hands a new alert to the platform when its team has begun the cutover, so the team never has
    to be cut over again for it, and creates the copy with `grouping`. False when the alert stays
    with logs.

    Raises `InvalidPlatformAlertEdit` when the alert cannot take the grouping.
    """
    grouping = grouping if grouping is not None else Grouping()
    if in_an_environment(alert) or not has_begun_cutover(alert.team_id):
        _refuse_grouping_on_logs(grouping)
        return False
    if grouping.mode != GroupingMode.SINGLE and (problem := grouping_problem(grouping.keys, alert.threshold_operator)):
        raise InvalidPlatformAlertEdit("grouping", problem)
    if hand_over(alert, at, grouping=grouping):
        return True
    _refuse_grouping_on_logs(grouping)
    return False


def create_platform_owned(*, team_id: int, edit: PlatformAlertConfigurationEdit, created_by_id: int | None) -> UUID:
    """Creates a logs alert through the platform API: the logs row and the platform's copy, both owned
    by the platform, as a create through the logs API does in a team that has begun the cutover.

    The team counts as begun from then on, because the platform owns one of its logs alerts.
    """
    try:
        claim_alert_slot(team_id)
    except AlertLimitReached as error:
        raise PlatformAlertCreateRefused(str(error)) from error
    now = timezone.now()
    alert = LogsAlertConfiguration(
        team_id=team_id,
        created_by_id=created_by_id,
        enabled=edit.enabled,
        first_enabled_at=now if edit.enabled else None,
        next_check_at=first_check_at(team_id, edit.schedule_restriction) if edit.schedule_restriction else None,
    )
    _set_settings(alert, edit)
    alert.save()
    if not hand_over(alert, now, grouping=edit.grouping):
        raise RuntimeError(f"Logs alert {alert.id} was created with a platform copy already firing")
    return alert.id


def on_updated(alert: LogsAlertConfiguration, *, snooze_changed: bool, grouping: Grouping | None = None) -> None:
    """Writes an edit the logs API saved onto the platform's copy, with the grouping the edit set.
    A `grouping` of None keeps the copy's own. An alert logs owns has no copy to write.

    Raises `InvalidPlatformAlertEdit` when the platform's schema rejects the edit, or when the
    alert cannot take the grouping.
    """
    if not alert.platform_owned:
        _refuse_grouping_on_logs(grouping)
        return
    update_owned_copy(
        team_id=alert.team_id,
        legacy_configuration_id=alert.id,
        change=_platform_change_of(alert, grouping),
        snooze_until=alert.snooze_until,
        snooze_changed=snooze_changed,
    )


def on_deleted(*, team_id: int, alert_id: UUID) -> None:
    delete_owned_copy(team_id=team_id, legacy_configuration_id=alert_id)


def _platform_change_of(
    alert: LogsAlertConfiguration, grouping: Grouping | None
) -> Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit]:
    # Only the settings a logs alert has, and a grouping the edit named. The logs row has no grouping,
    # so an edit that names none keeps what the copy stores rather than resetting it.
    upsert = platform_upsert_of(alert)
    shared = {field: getattr(upsert, field) for field in SETTINGS_FIELDS}
    return lambda stored: replace(
        stored, enabled=upsert.enabled, grouping=grouping if grouping is not None else stored.grouping, **shared
    )


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


def _set_settings(alert: LogsAlertConfiguration, edit: PlatformAlertConfigurationEdit) -> None:
    # The inverse of `platform_upsert_of`, over the same field lists.
    condition = edit.source_config[SOURCE_CONDITION_KEY]
    alert.filters = filters_of(edit.source_config)
    for field in CONDITION_FIELDS:
        setattr(alert, field, condition[field])
    for field in SETTINGS_FIELDS:
        if field != "source_config":
            setattr(alert, field, getattr(edit, field))


def _write_logs_row(alert: LogsAlertConfiguration, edit: PlatformAlertConfigurationEdit) -> None:
    # The shadow evaluation still runs this row, so an on or off moves its state the way the logs API does.
    enabled_fields = apply_enabled(alert, edit.enabled, now=timezone.now())
    _set_settings(alert, edit)
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
