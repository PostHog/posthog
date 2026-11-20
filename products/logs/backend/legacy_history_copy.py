"""A logs alert's own history in `LogsAlertEvent`, as the platform's history copies it.

The logs events API and state timeline read a moved alert's changes, and its checks since the
cutover, from the platform. Changes from before the platform recorded them, and checks from before
the cutover, exist only in `LogsAlertEvent`, which goes when the logs row is deleted, so they are
copied first. A check after the cutover is the shadow's, which the API never shows, so it is not.
"""

from collections.abc import Iterable
from typing import Final
from uuid import UUID

from django.db.models import F, Q

from products.alerts_platform.backend.facade.contracts import AlertEventKind, LegacyAlertHistory, LegacyHistoryEntry
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.platform_alert_backfill import PLATFORM_HANDOVER_STATE
from products.logs.backend.platform_alert_event_history import BREACHED_KEY, CHANGE_OF_LOGS_KIND

_CHUNK: Final = 2_000


def team_alert_ids(team_id: int) -> Iterable[UUID]:
    return LogsAlertConfiguration.objects.filter(team_id=team_id).order_by("id").values_list("id", flat=True).iterator()


def legacy_history(team_id: int, alert_id: UUID) -> LegacyAlertHistory:
    cutover_at = (
        LogsAlertConfiguration.objects.filter(id=alert_id, team_id=team_id)
        .values_list("owner_changed_at", flat=True)
        .first()
    )
    rows = LogsAlertEvent.objects.filter(alert_id=alert_id, alert__team_id=team_id)
    kept = rows.filter(kind__in=list(CHANGE_OF_LOGS_KIND))
    if cutover_at is not None:
        # Only the checks the events list shows: one that moved the state or failed.
        shown_checks = rows.filter(kind=LogsAlertEvent.Kind.CHECK, created_at__lt=cutover_at).filter(
            Q(error_message__isnull=False) | ~Q(state_before=F("state_after"))
        )
        kept = kept | shown_checks
    events = kept.order_by("created_at", "id").only(
        "id",
        "kind",
        "created_at",
        "state_before",
        "state_after",
        "result_count",
        "threshold_breached",
        "error_message",
        "query_duration_ms",
    )
    return LegacyAlertHistory(
        entries=tuple(_entry(event) for event in events.iterator(chunk_size=_CHUNK)),
        platform_checks_replace_source=False,
    )


def _entry(event: LogsAlertEvent) -> LegacyHistoryEntry:
    if event.kind == LogsAlertEvent.Kind.CHECK:
        return LegacyHistoryEntry(
            legacy_id=event.id,
            kind=AlertEventKind.CHECK,
            occurred_at=event.created_at,
            previous_state=_platform_state(event.state_before),
            state=_platform_state(event.state_after),
            value=event.result_count,
            error_message=event.error_message or None,
            query_duration_ms=event.query_duration_ms,
            # A copy has no condition to measure its value against, so it keeps the verdict.
            source_detail={BREACHED_KEY: event.threshold_breached},
        )
    return LegacyHistoryEntry(
        legacy_id=event.id,
        kind=CHANGE_OF_LOGS_KIND[event.kind],
        occurred_at=event.created_at,
        previous_state=_platform_state(event.state_before),
        state=_platform_state(event.state_after),
    )


def _platform_state(logs_state: str) -> PlatformAlertState:
    # A change records a snooze as a state, as the platform's own changes do.
    if logs_state == LogsAlertConfiguration.State.SNOOZED:
        return PlatformAlertState.SNOOZED
    return PLATFORM_HANDOVER_STATE.get(logs_state, PlatformAlertState.NOT_FIRING)
