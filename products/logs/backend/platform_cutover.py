"""Hands a team's logs alerts to the alerts platform, one alert at a time.

Each alert moves in its own transaction, under its own row lock. An alert that cannot move now is
skipped with a reason, and a later run picks it up. The command is safe to run again.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.api import take_ownership, upsert_configuration
from products.alerts_platform.backend.facade.contracts import PlatformOwnershipHandover
from products.alerts_platform.backend.facade.enums import PlatformAlertOwner, PlatformAlertState
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_backfill import platform_upsert_of

State = LogsAlertConfiguration.State

# A muted logs alert is a state of its own. On the platform a mute only silences notifications,
# so the copy keeps checking with the snooze carried on `snooze_until`.
_PLATFORM_STATE: dict[str, PlatformAlertState] = {
    State.NOT_FIRING: PlatformAlertState.NOT_FIRING,
    State.SNOOZED: PlatformAlertState.NOT_FIRING,
    State.ERRORED: PlatformAlertState.ERRORED,
    State.BROKEN: PlatformAlertState.BROKEN,
}


class CutoverSkip(StrEnum):
    """Why an alert stays with the logs stack for now."""

    ALREADY_MOVED = "already_moved"
    # The two stacks key incidents differently, so a firing moves only after it resolves.
    FIRING = "firing"
    # A logs check may be running, and it could notify after the move.
    CHECK_DUE = "check_due"


@frozen
class AlertCutover:
    alert_id: UUID
    skipped: CutoverSkip | None


def cut_over_team(team_id: int, *, now: datetime | None = None) -> tuple[AlertCutover, ...]:
    """Hands every logs alert of one team to the platform, or says why one stays."""
    at = now or timezone.now()
    alert_ids: Sequence[UUID] = list(
        LogsAlertConfiguration.objects.filter(team_id=team_id).order_by("created_at", "id").values_list("id", flat=True)
    )
    return tuple(AlertCutover(alert_id=alert_id, skipped=_cut_over_alert(alert_id, at)) for alert_id in alert_ids)


def _cut_over_alert(alert_id: UUID, at: datetime) -> CutoverSkip | None:
    with transaction.atomic():
        alert = LogsAlertConfiguration.objects.select_for_update().get(id=alert_id)
        if alert.platform_owned:
            return CutoverSkip.ALREADY_MOVED
        platform_state = _PLATFORM_STATE.get(alert.state)
        if platform_state is None:
            return CutoverSkip.FIRING
        # A logs check advances `next_check_at` when it saves, so a later one under this lock means
        # no logs check is between reading the alert and notifying for it.
        if alert.enabled and (alert.next_check_at is None or alert.next_check_at <= at):
            return CutoverSkip.CHECK_DUE

        upsert_configuration(platform_upsert_of(alert))
        take_ownership(
            PlatformOwnershipHandover(
                legacy_configuration_id=alert.id,
                team_id=alert.team_id,
                state=platform_state,
                last_notified_at=alert.last_notified_at,
                consecutive_failures=alert.consecutive_failures,
                next_check_at=alert.next_check_at if alert.enabled else None,
                at=at,
            )
        )
        LogsAlertConfiguration.objects.filter(id=alert.id).update(
            owner=PlatformAlertOwner.PLATFORM, owner_changed_at=at
        )
    return None
