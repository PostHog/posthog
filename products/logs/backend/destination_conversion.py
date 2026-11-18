"""Moves the stock destinations of a team's platform-owned logs alerts off HogFunctions.

Each stock HogFunction group becomes one `AlertDestination` row that copies it, and the group's
HogFunctions are retired in the same transaction. Delivery skips a row while any HogFunction it
copies exists, so the row starts sending only once they are gone, and never beside them. A row the
alert page already wrote for the group is replaced, because an edit through the HogFunction API
since then changed the HogFunctions and not the row.

Each alert converts in its own transaction, under its logs row's lock, which the destination routes
and the rollback also take first, then its HogFunctions' locks. A run is safe to repeat: a retired
group is no longer listed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Sequence
from datetime import timedelta
from enum import StrEnum
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.alerts.backend.facade.destinations import (
    choose_delivery_path,
    classify_alert_destinations,
    configured_destination_template_ids,
    customized_alert_destination_ids,
    list_alert_destination_groups,
    list_owned_alert_destinations,
    lock_alert_destinations,
    soft_delete_alert_destinations,
)
from products.alerts_platform.backend.facade.api import (
    copied_by_source_rows,
    delete_source_destination_rows,
    legacy_events_emitted_since,
    list_source_destinations,
    record_source_destination,
    runtime_by_public_id,
)
from products.alerts_platform.backend.facade.contracts import (
    AlertDestinationData,
    AlertDestinationGroup,
    AlertDestinationValidationError,
    DestinationType,
    SourceKind,
)
from products.alerts_platform.backend.facade.enums import DeliveryPath, PlatformAlertOwner, PlatformAlertState
from products.logs.backend.alert_destinations import EVENT_KIND_CONFIG, LOGS_ALERT_EVENT_IDS, EventKind, row_event_kinds
from products.logs.backend.models import LogsAlertConfiguration

_KIND_BY_EVENT_ID: dict[str, EventKind] = {spec.event_id: kind for kind, spec in EVENT_KIND_CONFIG.items()}

# An emitted event waits in the internal events queue until the CDP consumer picks its HogFunctions, so
# retiring them sooner loses a message the platform already counted as delivered.
LEGACY_EVENTS_QUIET_PERIOD = timedelta(minutes=15)


class GroupOutcome(StrEnum):
    CONVERTED = "converted"
    REPLACED_ROW = "replaced_row"
    CUSTOMIZED = "customized"
    # A HogFunction opened the firing's incident under a key the row's resolve would not match, so the
    # alert waits for a run after the firing ends.
    FIRING = "firing"
    RECENTLY_EMITTED = "recently_emitted"
    # Some of the group's HogFunctions are switched off. A row is on or off for every kind it hears.
    PARTLY_ENABLED = "partly_enabled"
    # A row copies only some of the group, so a second row would send to the same place twice.
    PARTLY_COPIED = "partly_copied"
    REFUSED = "refused"
    NO_SOURCE_DESTINATIONS = "no_source_destinations"


@frozen
class GroupConversion:
    alert_id: UUID
    hog_function_ids: tuple[UUID, ...]
    outcome: GroupOutcome
    detail: str = ""


def convert_team(team_id: int, *, apply: bool) -> tuple[GroupConversion, ...]:
    """Converts the stock destinations of every platform-owned logs alert of one team. Without `apply`,
    each alert is decided as a real run would decide it, then its transaction is rolled back."""
    alert_ids = (
        LogsAlertConfiguration.objects.filter(team_id=team_id, owner=PlatformAlertOwner.PLATFORM)
        .order_by("created_at", "id")
        .values_list("id", flat=True)
    )
    return tuple(conversion for alert_id in alert_ids for conversion in _convert_alert(alert_id, apply=apply))


def outcome_counts(conversions: Collection[GroupConversion]) -> Counter[str]:
    return Counter(str(conversion.outcome) for conversion in conversions)


def _convert_alert(alert_id: UUID, *, apply: bool) -> list[GroupConversion]:
    with transaction.atomic():
        try:
            alert = LogsAlertConfiguration.objects.select_for_update().filter(id=alert_id).first()
            # A rollback can hand the alert back between listing and locking it.
            if alert is None or not alert.platform_owned:
                return []
            lock_alert_destinations(
                team_id=alert.team_id, alert_id=str(alert.id), allowed_event_ids=LOGS_ALERT_EVENT_IDS
            )
            candidates = _stock_candidates(alert)
            if not candidates:
                return []
            runtime = runtime_by_public_id(team_id=alert.team_id, public_ids=[alert.id]).get(alert.id)
            if runtime is not None and runtime.state == PlatformAlertState.FIRING:
                return [
                    GroupConversion(
                        alert_id=alert.id, hog_function_ids=group.hog_function_ids, outcome=GroupOutcome.FIRING
                    )
                    for group, _ in candidates
                ]
            if legacy_events_emitted_since(
                team_id=alert.team_id, public_id=alert.id, since=timezone.now() - LEGACY_EVENTS_QUIET_PERIOD
            ):
                return [
                    GroupConversion(
                        alert_id=alert.id,
                        hog_function_ids=group.hog_function_ids,
                        outcome=GroupOutcome.RECENTLY_EMITTED,
                    )
                    for group, _ in candidates
                ]
            groups = [group for group, _ in candidates]
            # On the HogFunction path the stock webhook template sends the legacy body, which a row on a
            # team the webhook body flags moved to Alertmanager would not. Read before any group moves.
            sends_legacy_body = (
                choose_delivery_path(
                    source=SourceKind.LOGS,
                    team_id=alert.team_id,
                    alert_id=str(alert.id),
                    allowed_event_ids=LOGS_ALERT_EVENT_IDS,
                )
                == DeliveryPath.HOG_FUNCTION
            )
            return [
                _convert_group(alert, group, facts, groups, sends_legacy_body=sends_legacy_body)
                for group, facts in candidates
            ]
        finally:
            # After the last query, because a block marked for rollback refuses queries.
            if not apply:
                transaction.set_rollback(True)


@frozen
class _GroupFacts:
    customized: bool
    enabled_count: int
    event_kinds: tuple[EventKind, ...]
    data: AlertDestinationData


def _stock_candidates(alert: LogsAlertConfiguration) -> list[tuple[AlertDestinationGroup, _GroupFacts]]:
    alert_id = str(alert.id)
    groups = list_alert_destination_groups(
        team_id=alert.team_id, alert_id=alert_id, allowed_event_ids=LOGS_ALERT_EVENT_IDS
    )
    if not groups:
        return []
    customized = customized_alert_destination_ids(
        team_id=alert.team_id, alert_id=alert_id, allowed_event_ids=LOGS_ALERT_EVENT_IDS
    )
    event_ids_by_id = {
        eligibility.hog_function_id: eligibility.event_ids
        for eligibility in classify_alert_destinations(
            team_id=alert.team_id, alert_id=alert_id, allowed_event_ids=LOGS_ALERT_EVENT_IDS
        )
    }
    data_by_group = {
        listed.hog_function_ids: listed.data
        for listed in list_source_destinations(team_id=alert.team_id, public_id=alert.id, hog_function_groups=groups)
    }
    enabled_ids = {
        owned.hog_function_id
        for owned in list_owned_alert_destinations(
            team_id=alert.team_id,
            alert_ids=[alert_id],
            allowed_event_ids=LOGS_ALERT_EVENT_IDS,
            template_ids=configured_destination_template_ids(
                team_id=alert.team_id, alert_id=alert_id, allowed_event_ids=LOGS_ALERT_EVENT_IDS
            ),
            enabled=True,
        )
    }
    return [
        (
            group,
            _GroupFacts(
                customized=not customized.isdisjoint(group.hog_function_ids),
                enabled_count=len(enabled_ids.intersection(group.hog_function_ids)),
                event_kinds=tuple(
                    dict.fromkeys(
                        _KIND_BY_EVENT_ID[event_id]
                        for hog_function_id in group.hog_function_ids
                        for event_id in sorted(event_ids_by_id.get(hog_function_id, ()))
                        if event_id in _KIND_BY_EVENT_ID
                    )
                ),
                data=data_by_group.get(group.hog_function_ids, group.data),
            ),
        )
        for group in groups
    ]


def _convert_group(
    alert: LogsAlertConfiguration,
    group: AlertDestinationGroup,
    facts: _GroupFacts,
    groups: Sequence[AlertDestinationGroup],
    *,
    sends_legacy_body: bool,
) -> GroupConversion:
    def result(outcome: GroupOutcome, detail: str = "") -> GroupConversion:
        return GroupConversion(
            alert_id=alert.id, hog_function_ids=group.hog_function_ids, outcome=outcome, detail=detail
        )

    if facts.customized:
        return result(GroupOutcome.CUSTOMIZED)
    if 0 < facts.enabled_count < len(group.hog_function_ids):
        return result(GroupOutcome.PARTLY_ENABLED)
    copied = copied_by_source_rows(team_id=alert.team_id, public_id=alert.id, hog_function_ids=group.hog_function_ids)
    if copied and copied != set(group.hog_function_ids):
        return result(GroupOutcome.PARTLY_COPIED)

    try:
        with transaction.atomic():
            if copied:
                delete_source_destination_rows(
                    team_id=alert.team_id, public_id=alert.id, destination_ids=(), hog_function_ids=copied
                )
            recorded = record_source_destination(
                team_id=alert.team_id,
                public_id=alert.id,
                data=facts.data,
                event_kinds=row_event_kinds(facts.event_kinds),
                hog_function_ids=group.hog_function_ids,
                # Every group, so a second group that sends to the same place keeps both on HogFunctions.
                hog_function_groups=groups,
                enabled=facts.enabled_count > 0,
                keeps_legacy_webhook_body=sends_legacy_body and facts.data["type"] == DestinationType.WEBHOOK,
            )
            if recorded is None:
                raise _NoSourceDestinations
            # A queryset update, not a save: a HogFunction saved as deleted deletes every row that copies it.
            soft_delete_alert_destinations(
                team_id=alert.team_id,
                alert_id=str(alert.id),
                allowed_event_ids=LOGS_ALERT_EVENT_IDS,
                hog_function_ids=list(group.hog_function_ids),
            )
    except AlertDestinationValidationError as error:
        return result(GroupOutcome.REFUSED, str(error))
    except _NoSourceDestinations:
        return result(GroupOutcome.NO_SOURCE_DESTINATIONS)
    return result(GroupOutcome.REPLACED_ROW if copied else GroupOutcome.CONVERTED)


class _NoSourceDestinations(Exception):
    """Raised inside the group's savepoint, so a row deleted for replacement comes back."""
