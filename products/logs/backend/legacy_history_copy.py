"""A logs alert's control-plane rows in `LogsAlertEvent`, as the platform's history copies them.

The platform records each change to an alert it owns, and the logs events API and state timeline
read the changes from there. Changes from before it started recording exist only in
`LogsAlertEvent`, which goes when the logs row is deleted, so they are copied first.
"""

from collections.abc import Iterable
from typing import Final
from uuid import UUID

from products.alerts_platform.backend.facade.contracts import LegacyHistoryEntry
from products.alerts_platform.backend.facade.enums import PlatformAlertState
from products.logs.backend.models import LogsAlertConfiguration, LogsAlertEvent
from products.logs.backend.platform_alert_backfill import PLATFORM_HANDOVER_STATE
from products.logs.backend.platform_alert_event_history import CHANGE_OF_LOGS_KIND

_CHUNK: Final = 2_000


def team_alert_ids(team_id: int) -> Iterable[UUID]:
    return LogsAlertConfiguration.objects.filter(team_id=team_id).order_by("id").values_list("id", flat=True).iterator()


def control_history(team_id: int, alert_id: UUID) -> tuple[LegacyHistoryEntry, ...]:
    events = (
        LogsAlertEvent.objects.filter(alert_id=alert_id, alert__team_id=team_id, kind__in=list(CHANGE_OF_LOGS_KIND))
        .order_by("created_at", "id")
        .only("id", "kind", "created_at", "state_before", "state_after")
    )
    return tuple(
        LegacyHistoryEntry(
            legacy_id=event.id,
            kind=CHANGE_OF_LOGS_KIND[event.kind],
            occurred_at=event.created_at,
            previous_state=_platform_state(event.state_before),
            state=_platform_state(event.state_after),
        )
        for event in events.iterator(chunk_size=_CHUNK)
    )


def _platform_state(logs_state: str) -> PlatformAlertState:
    # A change records a snooze as a state, as the platform's own changes do.
    if logs_state == LogsAlertConfiguration.State.SNOOZED:
        return PlatformAlertState.SNOOZED
    return PLATFORM_HANDOVER_STATE.get(logs_state, PlatformAlertState.NOT_FIRING)
