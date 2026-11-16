"""The checks and control-plane changes of a logs alert the platform owns, as the logs events API
lists them.

The checks come from the platform's history once it owns the alert, and from `LogsAlertEvent`
before then. The platform records the control-plane changes (toggles, snoozes, resets, threshold
changes) of every alert it owns. An alert with a logs row has them in `LogsAlertEvent` too.
"""

from collections.abc import Collection
from datetime import datetime
from typing import Final
from uuid import UUID, uuid5

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.api import (
    control_changes_by_public_id,
    control_history_by_public_id,
    notable_checks_by_public_id,
)
from products.alerts_platform.backend.facade.contracts import ControlChangeKind, PlatformCheckEvent
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.logs.backend.alert_source_cycle import LogsAlertCondition
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.platform_alert_backfill import logs_state_of_platform

# A merged page loads every row up to its end from both sources, so the end is bounded. The events
# tab loads pages of 100 and never comes near it.
MAX_MERGED_EVENT_ROWS: Final = 10_000


@frozen
class PlatformCheckRow:
    """One check of a logs alert the platform owns, in the shape of a logs alert event."""

    # Derived from the check, so the same check keeps its id from one page load to the next.
    id: UUID
    created_at: datetime
    state_before: str
    state_after: str
    threshold_breached: bool
    result_count: int | None
    error_message: str | None
    query_duration_ms: int | None


@frozen
class PlatformCheckRows:
    """The newest checks of an alert that moved its state or failed, and how many there are in all."""

    rows: tuple[PlatformCheckRow, ...]
    total: int


def platform_check_rows(*, team_id: int, alert_id: UUID, since: datetime, limit: int) -> PlatformCheckRows | None:
    """The newest `limit` checks since `since` that moved the alert's state or failed, or None when
    the platform does not own the alert.

    Raises when ClickHouse fails.
    """
    page = notable_checks_by_public_id(team_id=team_id, public_id=alert_id, since=since, limit=limit)
    if page is None:
        return None
    return PlatformCheckRows(rows=tuple(_as_row(alert_id, check) for check in page.events), total=page.total)


def _as_row(alert_id: UUID, check: PlatformCheckEvent) -> PlatformCheckRow:
    return PlatformCheckRow(
        id=uuid5(alert_id, check.evaluation_key),
        created_at=check.occurred_at,
        state_before=_logs_state(check.previous_state, check.occurred_at),
        state_after=_logs_state(check.state, check.occurred_at),
        threshold_breached=_breached(check),
        result_count=round(check.value) if check.value is not None else None,
        error_message=check.error_message,
        query_duration_ms=check.query_duration_ms,
    )


def _logs_state(state: PlatformAlertState, at: datetime) -> str:
    # With no snooze the alert's own state cannot change the mapping, so none is passed.
    return logs_state_of_platform(state, logs_state="", snooze_until=None, at=at).value


def _breached(check: PlatformCheckEvent) -> bool:
    if check.value is None:
        return False
    try:
        condition = LogsAlertCondition.from_condition(check.condition)
    except (KeyError, TypeError, ValueError):
        # A row whose snapshot holds no valid logs bound has nothing to compare against.
        return False
    return condition.breached(check.value)


_LOGS_KIND_OF_CHANGE: Final[dict[ControlChangeKind, LogsAlertEvent.Kind]] = {
    ControlChangeKind.ENABLE: LogsAlertEvent.Kind.ENABLE,
    ControlChangeKind.DISABLE: LogsAlertEvent.Kind.DISABLE,
    ControlChangeKind.SNOOZE: LogsAlertEvent.Kind.SNOOZE,
    ControlChangeKind.UNSNOOZE: LogsAlertEvent.Kind.UNSNOOZE,
    ControlChangeKind.RESET: LogsAlertEvent.Kind.RESET,
    ControlChangeKind.CONFIG_CHANGE: LogsAlertEvent.Kind.THRESHOLD_CHANGE,
}
_CHANGE_OF_LOGS_KIND: Final[dict[str, ControlChangeKind]] = {
    logs_kind.value: change for change, logs_kind in _LOGS_KIND_OF_CHANGE.items()
}
PLATFORM_CONTROL_KINDS: Final = frozenset(_CHANGE_OF_LOGS_KIND)


@frozen
class PlatformControlRow:
    """One control-plane change of a logs alert the platform owns, in the shape of a logs alert event."""

    # Derived from the change, so the same change keeps its id from one page load to the next.
    id: UUID
    kind: LogsAlertEvent.Kind
    created_at: datetime
    state_before: str
    state_after: str


@frozen
class PlatformControlRows:
    """The newest control-plane changes of an alert, how many there are in all, and when the oldest
    one the platform still keeps happened."""

    rows: tuple[PlatformControlRow, ...]
    total: int
    oldest_at: datetime | None


def platform_control_rows(
    *, team_id: int, alert_id: UUID, kinds: Collection[str], limit: int
) -> PlatformControlRows | None:
    """The newest `limit` control-plane changes of the logs `kinds`, or None when the platform does
    not own the alert. A kind the platform does not record is ignored.

    Raises when ClickHouse fails.
    """
    changes = [_CHANGE_OF_LOGS_KIND[kind] for kind in kinds if kind in _CHANGE_OF_LOGS_KIND]
    page = control_changes_by_public_id(team_id=team_id, public_id=alert_id, kinds=changes, limit=limit)
    if page is None:
        return None
    return PlatformControlRows(
        rows=tuple(
            PlatformControlRow(
                id=uuid5(alert_id, change.evaluation_key),
                kind=_LOGS_KIND_OF_CHANGE[change.kind],
                created_at=change.occurred_at,
                state_before=_shown_state(change.previous_state, change.occurred_at),
                state_after=_shown_state(change.state, change.occurred_at),
            )
            for change in page.changes
        ),
        total=page.total,
        oldest_at=page.oldest_at,
    )


def _shown_state(state: PlatformAlertState, at: datetime) -> str:
    # A change records the snooze as a state, where a check keeps it on `snooze_until`.
    if state == PlatformAlertState.SNOOZED:
        return LogsAlertConfiguration.State.SNOOZED
    return _logs_state(state, at)


@frozen
class PlatformControlBoundary:
    """One control-plane change, as a logs alert's state timeline reads it."""

    kind: LogsAlertEvent.Kind
    created_at: datetime


@frozen
class PlatformControlTimeline:
    """What a logs alert's state timeline reads from the platform's control-plane changes: the
    window's changes oldest first, when the oldest kept change happened, and the newest enable or
    disable before the window."""

    changes: tuple[PlatformControlBoundary, ...]
    oldest_at: datetime
    toggle_before: LogsAlertEvent.Kind | None


def platform_control_timelines(
    *, team_id: int, alert_ids: Collection[UUID], since: datetime, until: datetime
) -> dict[UUID, PlatformControlTimeline]:
    """Each named alert's control-plane timeline in `[since, until)`. An alert the platform does not
    own, or that has no kept change, is left out.

    Raises when ClickHouse fails.
    """
    histories = control_history_by_public_id(team_id=team_id, public_ids=alert_ids, since=since, until=until)
    return {
        alert_id: PlatformControlTimeline(
            changes=tuple(
                PlatformControlBoundary(kind=_LOGS_KIND_OF_CHANGE[change.kind], created_at=change.occurred_at)
                for change in history.changes
            ),
            oldest_at=history.oldest_at,
            toggle_before=_LOGS_KIND_OF_CHANGE[history.toggle_before] if history.toggle_before else None,
        )
        for alert_id, history in histories.items()
    }
