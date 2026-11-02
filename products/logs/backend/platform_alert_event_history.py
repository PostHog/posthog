"""The checks of a logs alert the platform owns, as the logs events API lists them.

The logs API keeps writing the control-plane events (toggles, snoozes, resets, threshold changes),
so those come from `LogsAlertEvent`. The checks come from the platform's history once it owns the
alert, and from `LogsAlertEvent` before then.
"""

from datetime import datetime
from typing import Final
from uuid import UUID, uuid5

from posthog.dataclasses import frozen

from products.alerts_platform.backend.facade.api import notable_checks_by_legacy_id
from products.alerts_platform.backend.facade.contracts import PlatformCheckEvent
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.logs.backend.alert_source_cycle import LogsAlertCondition
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

    Raises when ClickHouse fails, so the caller can fall back to the logs rows.
    """
    page = notable_checks_by_legacy_id(team_id=team_id, legacy_configuration_id=alert_id, since=since, limit=limit)
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
