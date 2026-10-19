"""Hands a team's logs alerts to the alerts platform and back, one alert at a time.

Each alert moves in its own transaction, under its own row lock. An alert that cannot move now is
skipped with a reason, and a later run picks it up. The command is safe to run again.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.api import give_back_ownership, take_ownership, upsert_configuration
from products.alerts_platform.backend.facade.contracts import HandbackRefusal, PlatformOwnershipHandover
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.logs.backend.alert_state_machine import FIRING_STATES, ControlPlaneOutcome, apply_outcome
from products.logs.backend.alert_utils import due_alerts_q
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.platform_alert_backfill import (
    PLATFORM_HANDOVER_STATE,
    logs_state_of_platform,
    platform_upsert_of,
)

State = LogsAlertConfiguration.State


class CutoverSkip(StrEnum):
    """Why an alert stays with the logs stack for now."""

    ALREADY_MOVED = "already_moved"
    # The two stacks key incidents differently, so a firing moves only after it resolves.
    FIRING = "firing"
    # The logs scheduler owes this alert a check, which may already be running and could notify
    # after the move.
    CHECK_DUE = "check_due"
    # A team on live delivery can have the platform copy inside a firing of its own.
    PLATFORM_FIRING = "platform_firing"


@frozen
class AlertCutover:
    alert_id: UUID
    skipped: CutoverSkip | None


def _team_alert_ids(team_id: int) -> list[UUID]:
    return list(
        LogsAlertConfiguration.objects.filter(team_id=team_id).order_by("created_at", "id").values_list("id", flat=True)
    )


def _logs_check_owed(alert_id: UUID, at: datetime) -> bool:
    # A logs check advances `next_check_at` when it saves, so an alert the scheduler does not owe
    # a check under the caller's lock has no logs check between reading it and notifying for it.
    return (
        LogsAlertConfiguration.objects.filter(id=alert_id)
        .filter(due_alerts_q(at, broken_state=State.BROKEN, snoozed_state=State.SNOOZED))
        .exists()
    )


def cut_over_team(team_id: int, *, now: datetime | None = None) -> tuple[AlertCutover, ...]:
    """Hands every logs alert of one team to the platform, or says why one stays.

    No destination holds an alert back: delivery sends a customized one through its HogFunction.
    """
    return tuple(
        AlertCutover(alert_id=alert_id, skipped=_cut_over_alert(alert_id, now)) for alert_id in _team_alert_ids(team_id)
    )


def _cut_over_alert(alert_id: UUID, now: datetime | None) -> CutoverSkip | None:
    with transaction.atomic():
        alert = LogsAlertConfiguration.objects.select_for_update().get(id=alert_id)
        # Read after the lock, so a check that became due while earlier alerts moved is seen as due.
        at = now or timezone.now()
        if alert.platform_owned:
            return CutoverSkip.ALREADY_MOVED
        if alert.state in FIRING_STATES:
            return CutoverSkip.FIRING
        if _logs_check_owed(alert.id, at):
            return CutoverSkip.CHECK_DUE

        savepoint = transaction.savepoint()
        upsert_configuration(platform_upsert_of(alert))
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
            return CutoverSkip.PLATFORM_FIRING
        transaction.savepoint_commit(savepoint)
        LogsAlertConfiguration.objects.filter(id=alert.id).update(
            owner=PlatformAlertOwner.PLATFORM, owner_changed_at=at
        )
    return None


class RollbackSkip(StrEnum):
    """Why an alert stays with the platform for now."""

    NOT_MOVED = "not_moved"
    # During the shadow the logs stack still checks the alert, and a check it started would save
    # over the state carried back.
    LOGS_CHECK_DUE = "logs_check_due"
    PLATFORM_FIRING = "platform_firing"
    PLATFORM_CHECK_DUE = "platform_check_due"
    NOT_PORTABLE = "not_portable"


_ROLLBACK_SKIP: dict[HandbackRefusal, RollbackSkip] = {
    HandbackRefusal.FIRING: RollbackSkip.PLATFORM_FIRING,
    HandbackRefusal.CHECK_DUE: RollbackSkip.PLATFORM_CHECK_DUE,
    HandbackRefusal.NOT_PORTABLE: RollbackSkip.NOT_PORTABLE,
}


@frozen
class AlertRollback:
    alert_id: UUID
    skipped: RollbackSkip | None


def roll_back_team(team_id: int, *, now: datetime | None = None) -> tuple[AlertRollback, ...]:
    """Hands every logs alert of one team back from the platform, or says why one stays."""
    return tuple(
        AlertRollback(alert_id=alert_id, skipped=_roll_back_alert(alert_id, now))
        for alert_id in _team_alert_ids(team_id)
    )


def _roll_back_alert(alert_id: UUID, now: datetime | None) -> RollbackSkip | None:
    with transaction.atomic():
        alert = LogsAlertConfiguration.objects.select_for_update().get(id=alert_id)
        # Read after the lock, for the same reason as the cutover.
        at = now or timezone.now()
        if not alert.platform_owned:
            return RollbackSkip.NOT_MOVED
        if _logs_check_owed(alert.id, at):
            return RollbackSkip.LOGS_CHECK_DUE

        handback = give_back_ownership(team_id=alert.team_id, legacy_configuration_id=alert.id, at=at)
        if isinstance(handback, HandbackRefusal):
            return _ROLLBACK_SKIP[handback]

        update_fields = apply_outcome(
            alert,
            ControlPlaneOutcome(
                new_state=logs_state_of_platform(
                    handback.state, logs_state=alert.state, snooze_until=alert.snooze_until, at=at
                ),
                consecutive_failures=handback.consecutive_failures,
            ),
            kind=LogsAlertEvent.Kind.HANDBACK,
        )
        alert.owner = PlatformAlertOwner.SOURCE
        alert.owner_changed_at = at
        alert.last_notified_at = handback.last_notified_at
        alert.next_check_at = handback.next_check_at
        alert.save(update_fields=[*update_fields, "owner", "owner_changed_at", "last_notified_at", "next_check_at"])
    return None
