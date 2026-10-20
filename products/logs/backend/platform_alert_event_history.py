"""The event history of a logs alert the platform owns, as the logs events API lists it.

The logs API keeps writing the control-plane events (toggles, snoozes, resets, threshold changes),
so those come from `LogsAlertEvent`. The checks come from the platform's history once it owns the
alert, and from `LogsAlertEvent` before then. A logs check row written after the cutover is the
shadow evaluation, so it is left out.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import overload
from uuid import uuid5

from django.db.models import QuerySet

from posthog.api.pagination import stable_queryset_ordering
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception

from products.alerts_platform.backend.facade.api import notable_checks_by_legacy_id
from products.alerts_platform.backend.facade.contracts import PlatformCheckEvent
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.logs.backend.alert_source_cycle import LogsAlertCondition
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.platform_alert_backfill import logs_state_of_platform


@frozen
class EventWindow(Sequence[LogsAlertEvent]):
    """The newest rows of a history merged from two sources, sized as the whole history.

    `LimitOffsetPagination` pages it as it pages a list: it takes its length, then slices one page.
    It holds only the rows up to the end of the page the request asked for.
    """

    newest: Sequence[LogsAlertEvent]
    total: int

    def __len__(self) -> int:
        return self.total

    @overload
    def __getitem__(self, index: int) -> LogsAlertEvent: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[LogsAlertEvent]: ...

    def __getitem__(self, index: int | slice) -> LogsAlertEvent | Sequence[LogsAlertEvent]:
        return self.newest[index]


def platform_event_history(
    alert: LogsAlertConfiguration, events: QuerySet[LogsAlertEvent], *, kind: str | None, rows_needed: int
) -> QuerySet[LogsAlertEvent] | EventWindow:
    """`events` with the platform's checks in place of the shadow ones, newest first.

    `events` is the alert's filtered `LogsAlertEvent` rows, newest first. `rows_needed` is the end
    of the requested page, because a merged page needs that many rows from each source.

    Returns `events` unchanged for an alert the logs stack owns, and when ClickHouse fails, because
    the shadow checks are a better answer than a failed list.
    """
    cutover_at = alert.owner_changed_at
    if not alert.platform_owned or cutover_at is None:
        return events
    if kind is not None and kind != LogsAlertEvent.Kind.CHECK:
        return events
    # The viewset adds the same tie-break to a queryset it pages, which this merge bypasses.
    logs_events = stable_queryset_ordering(events.exclude(kind=LogsAlertEvent.Kind.CHECK, created_at__gte=cutover_at))
    try:
        page = notable_checks_by_legacy_id(
            team_id=alert.team_id, legacy_configuration_id=alert.id, since=cutover_at, limit=rows_needed
        )
    except Exception as error:
        capture_exception(error)
        return events
    if page is None:
        return events
    merged = [*logs_events[:rows_needed], *(_as_logs_event(alert, check) for check in page.events)]
    merged.sort(key=lambda event: event.created_at, reverse=True)
    return EventWindow(newest=merged[:rows_needed], total=logs_events.count() + page.total)


def _as_logs_event(alert: LogsAlertConfiguration, check: PlatformCheckEvent) -> LogsAlertEvent:
    """An unsaved row in the shape `LogsAlertEventSerializer` reads."""
    return LogsAlertEvent(
        # Derived from the check, so the same check keeps its id from one page load to the next.
        id=uuid5(alert.id, check.evaluation_key),
        alert=alert,
        kind=LogsAlertEvent.Kind.CHECK,
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
