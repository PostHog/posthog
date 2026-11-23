"""Creates and deletes the logs row of a logs alert the platform owns.

The platform's copy is the whole alert, and an edit writes the copy only. The logs row keeps the id the
alert is known by, its creation time, and its logs history, for the logs API to show beside the copy.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Final
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.models.team.team import Team

from products.alerts_platform.backend.facade.api import (
    close_owned_firings_now,
    delete_copy,
    take_ownership,
    update_owned_copy,
    upsert_configuration,
)
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    Grouping,
    GroupingMode,
    InvalidPlatformAlertEdit,
    PlatformAlertConfigurationEdit,
    PlatformAlertCreateRefused,
    PlatformOwnershipHandover,
)
from products.alerts_platform.backend.facade.delivery import team_flag_enabled
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.logs.backend.alert_creation import AlertLimitReached, check_alert_slot, first_check_at
from products.logs.backend.alert_group_columns import grouping_problem
from products.logs.backend.facade.api import close_incident_before_delete
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import (
    CONDITION_FIELDS,
    PLATFORM_HANDOVER_STATE,
    SETTINGS_FIELDS,
    platform_upsert_of,
)
from products.logs.backend.platform_source_config import filters_of

GROUPING_NOT_AVAILABLE: Final = "Grouping isn't available for this alert yet. Set the mode to single to save it."
LABELS_NOT_AVAILABLE: Final = "Labels aren't available for this alert yet. Remove them to save it."
ANNOTATIONS_NOT_AVAILABLE: Final = "Annotations aren't available for this alert yet. Remove them to save it."


def in_an_environment(alert: LogsAlertConfiguration) -> bool:
    """Whether the alert belongs to a child environment, whose copy would live on its project."""
    return alert.team.parent_team_id is not None


def hand_over(alert: LogsAlertConfiguration, at: datetime, *, grouping: Grouping | None = None) -> bool:
    """Copies a logs alert locked by the caller onto the platform and makes the platform its owner,
    on both rows. False, changing nothing, when the platform copy is inside a firing of its own.

    `grouping` applies only to a copy this creates, because the logs row stores none."""
    upsert = platform_upsert_of(alert)
    savepoint = transaction.savepoint_create()
    upsert_configuration(upsert if grouping is None else replace(upsert, grouping=grouping))
    taken = take_ownership(
        PlatformOwnershipHandover(
            legacy_configuration_id=alert.id,
            team_id=alert.team_id,
            state=PLATFORM_HANDOVER_STATE[alert.state],
            last_notified_at=alert.last_notified_at,
            consecutive_failures=alert.consecutive_failures,
            next_check_at=alert.next_check_at or at,
            at=at,
        )
    )
    if not taken:
        # The copy stays as live delivery left it. A copy disabled here would drop out of
        # discovery and never resolve the firing it is inside.
        transaction.savepoint_rollback(savepoint)
        return False
    transaction.savepoint_commit(savepoint)
    # `update()` rather than `save()`: a handover is not a user's edit, and `save()` would log one.
    LogsAlertConfiguration.objects.filter(id=alert.id).update(owner=PlatformAlertOwner.PLATFORM, owner_changed_at=at)
    alert.owner = PlatformAlertOwner.PLATFORM
    alert.owner_changed_at = at
    return True


# Turns on, per team, creates that make no logs row.
NATIVE_CREATE_FLAG: Final = "logs-alerts-native-create"


def creates_native_alert(team_id: int) -> bool:
    """Whether a new logs alert of the team gets no logs row. An environment, whose alert the platform
    cannot store, keeps the logs row."""
    team = Team.objects.only("id", "uuid", "organization_id", "parent_team_id").get(id=team_id)
    if team.parent_team_id is not None:
        return False
    return bool(team_flag_enabled(NATIVE_CREATE_FLAG, team))


def _refuse_grouping_on_logs(grouping: Grouping | None) -> None:
    # The logs stack cannot group. A single grouping is what the API reads for such an alert, so a
    # client that sends back what it read still saves.
    if grouping is not None and grouping.mode != GroupingMode.SINGLE:
        raise InvalidPlatformAlertEdit("grouping", GROUPING_NOT_AVAILABLE)


def _refuse_metadata_on_logs(labels: dict[str, str] | None, annotations: dict[str, str] | None) -> None:
    if labels:
        raise InvalidPlatformAlertEdit("labels", LABELS_NOT_AVAILABLE)
    if annotations:
        raise InvalidPlatformAlertEdit("annotations", ANNOTATIONS_NOT_AVAILABLE)


def on_created(
    alert: LogsAlertConfiguration,
    at: datetime,
    *,
    grouping: Grouping | None = None,
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
) -> bool:
    """Hands a new alert to the platform, and creates the copy with `grouping`, `labels` and
    `annotations`, unless it belongs to an environment. False when the alert stays with logs.

    Raises `InvalidPlatformAlertEdit` when the alert cannot take the grouping, the labels or the
    annotations.
    """
    grouping = grouping if grouping is not None else Grouping()
    if in_an_environment(alert):
        _refuse_grouping_on_logs(grouping)
        _refuse_metadata_on_logs(labels, annotations)
        return False
    if grouping.mode != GroupingMode.SINGLE and (problem := grouping_problem(grouping.keys, alert.threshold_operator)):
        raise InvalidPlatformAlertEdit("grouping", problem)
    if hand_over(alert, at, grouping=grouping):
        if labels or annotations:
            # The hand-over's upsert validates neither labels nor annotations. The edit path does.
            update_owned_copy(
                team_id=alert.team_id,
                legacy_configuration_id=alert.id,
                change=lambda stored: replace(stored, labels=labels or {}, annotations=annotations or {}),
                snooze_until=None,
                snooze_changed=False,
            )
        return True
    _refuse_grouping_on_logs(grouping)
    _refuse_metadata_on_logs(labels, annotations)
    return False


def admit_platform_write(
    *,
    team_id: int,
    current: PlatformAlertConfigurationEdit | None,
    edit: PlatformAlertConfigurationEdit,
    check_interval_minutes: int | None,
) -> None:
    """The per-team cap on a logs alert created through the platform. The platform holds the cap lock
    the logs API's creates also take."""
    if current is not None:
        return
    try:
        check_alert_slot(team_id)
    except AlertLimitReached as error:
        raise PlatformAlertCreateRefused(str(error)) from error


def create_platform_owned(*, team_id: int, edit: PlatformAlertConfigurationEdit, created_by_id: int | None) -> UUID:
    """Creates a logs alert through the platform API: the logs row and the platform's copy, both owned
    by the platform. `admit_platform_write` has already checked the cap.
    """
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


def refuse_platform_only_settings(
    grouping: Grouping | None, labels: dict[str, str] | None, annotations: dict[str, str] | None
) -> None:
    """Raises `InvalidPlatformAlertEdit` for a grouping, labels or annotations on an edit of an alert the
    logs stack owns, which has no copy to store them."""
    _refuse_grouping_on_logs(grouping)
    _refuse_metadata_on_logs(labels, annotations)


def on_deleted(*, team_id: int, alert_id: UUID) -> bool:
    """Deletes the alert's copy. True when the copy was the platform's, whose destinations went with it."""
    return delete_copy(team_id=team_id, legacy_configuration_id=alert_id)


def platform_edit_of(
    alert: LogsAlertConfiguration,
    grouping: Grouping,
    labels: dict[str, str] | None,
    annotations: dict[str, str] | None,
) -> PlatformAlertConfigurationEdit:
    """A logs alert's settings as a whole platform edit."""
    upsert = platform_upsert_of(alert)
    return PlatformAlertConfigurationEdit(
        enabled=upsert.enabled,
        grouping=grouping,
        labels=labels or {},
        annotations=annotations or {},
        **{field: getattr(upsert, field) for field in SETTINGS_FIELDS},
    )


def platform_change_of(
    alert: LogsAlertConfiguration,
    grouping: Grouping | None,
    labels: dict[str, str] | None,
    annotations: dict[str, str] | None,
) -> Callable[[PlatformAlertConfigurationEdit], PlatformAlertConfigurationEdit]:
    """The platform edit that carries a logs alert's settings onto its configuration."""
    # Only the settings a logs alert has, and the grouping, labels and annotations the edit named. The logs
    # row stores none of them, so an edit that names none keeps what the copy stores rather than resetting it.
    upsert = platform_upsert_of(alert)
    shared = {field: getattr(upsert, field) for field in SETTINGS_FIELDS}
    return lambda stored: replace(
        stored,
        enabled=upsert.enabled,
        grouping=grouping if grouping is not None else stored.grouping,
        labels=labels if labels is not None else stored.labels,
        annotations=annotations if annotations is not None else stored.annotations,
        **shared,
    )


def _set_settings(alert: LogsAlertConfiguration, edit: PlatformAlertConfigurationEdit) -> None:
    # The inverse of `platform_upsert_of`, over the same field lists.
    condition = edit.source_config[SOURCE_CONDITION_KEY]
    alert.filters = filters_of(edit.source_config)
    for field in CONDITION_FIELDS:
        setattr(alert, field, condition[field])
    for field in SETTINGS_FIELDS:
        if field != "source_config":
            setattr(alert, field, getattr(edit, field))


def before_delete(alert: LogsAlertConfiguration) -> None:
    """Closes the incident of a firing alert while its destinations still exist, on whichever stack
    owns it."""
    if alert.platform_owned:
        close_owned_firings_now(team_id=alert.team_id, legacy_configuration_id=alert.id)
    else:
        close_incident_before_delete(team_id=alert.team_id, alert_id=str(alert.id), state=alert.state)
