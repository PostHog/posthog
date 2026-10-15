"""Hands a team's logs alerts to the alerts platform, one alert at a time.

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

from products.alerts_platform.backend.facade.api import take_ownership, upsert_configuration
from products.alerts_platform.backend.facade.contracts import PlatformOwnershipHandover
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner
from products.logs.backend.alert_state_machine import FIRING_STATES
from products.logs.backend.alert_utils import due_alerts_q
from products.logs.backend.cutover_gate import CutoverRefused, TeamGate
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import PLATFORM_HANDOVER_STATE, platform_upsert_of

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
    # A destination changed after the team passed the gate, and native delivery cannot send it now.
    DESTINATION_CHANGED = "destination_changed"


@frozen
class AlertCutover:
    alert_id: UUID
    skipped: CutoverSkip | None


def cut_over_team(team_id: int, *, now: datetime | None = None) -> tuple[AlertCutover, ...]:
    """Hands every logs alert of one team to the platform, or says why one stays.

    Raises `CutoverRefused`, moving nothing, when native delivery cannot yet send one of the team's
    destinations the way the team receives it today.
    """
    gate = TeamGate(team_id)
    refusals = gate.refusals()
    if refusals:
        raise CutoverRefused(team_id, refusals)
    alert_ids = list(
        LogsAlertConfiguration.objects.filter(team_id=team_id).order_by("created_at", "id").values_list("id", flat=True)
    )
    return tuple(
        AlertCutover(alert_id=alert_id, skipped=_cut_over_alert(alert_id, gate, now)) for alert_id in alert_ids
    )


def _cut_over_alert(alert_id: UUID, gate: TeamGate, now: datetime | None) -> CutoverSkip | None:
    with transaction.atomic():
        alert = LogsAlertConfiguration.objects.select_for_update().get(id=alert_id)
        # Read after the lock, so a check that became due while earlier alerts moved is seen as due.
        at = now or timezone.now()
        if alert.platform_owned:
            return CutoverSkip.ALREADY_MOVED
        if alert.state in FIRING_STATES:
            return CutoverSkip.FIRING
        # A logs check advances `next_check_at` when it saves, so an alert the scheduler does not
        # owe a check under this lock has no logs check between reading it and notifying for it.
        if (
            LogsAlertConfiguration.objects.filter(id=alert.id)
            .filter(due_alerts_q(at, broken_state=State.BROKEN, snoozed_state=State.SNOOZED))
            .exists()
        ):
            return CutoverSkip.CHECK_DUE
        # Locks the alert's destinations, so no edit lands between this check and the move.
        if gate.alert_refusals(alert.id, lock=True):
            return CutoverSkip.DESTINATION_CHANGED

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
