"""The `$logs_alert_*` events the platform emits for a logs alert it owns on the HogFunction path.

The alert's HogFunctions filter on these events and render these properties, so the platform
reproduces what the logs stack emits, from what the check recorded.

Imported from `ready()`, so it stays light: no models, no query layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any, Final, cast
from uuid import NAMESPACE_URL, uuid5

from posthog.dataclasses import frozen

from products.alerts.backend.facade.contracts import AlertInternalEvent
from products.alerts.backend.facade.destinations import emit_alert_internal_events
from products.alerts_platform.backend.facade.contracts import (
    AlertDeliveryRequest,
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
    IncidentAction,
    LegacyEventEmission,
)
from products.logs.backend.alert_destinations import (
    EVENT_KIND_CONFIG,
    LOGS_ALERT_INCIDENT_CLOSED_EVENT,
    LOGS_ALERT_INCIDENT_OPENED_EVENT,
    EventKind,
)
from products.logs.backend.alert_event_properties import (
    failure_event_properties,
    incident_closed_event_properties,
    threshold_event_properties,
)
from products.logs.backend.alert_lookback import rolling_check_lookback_minutes
from products.logs.backend.alert_state_machine import IncidentCloseReason
from products.logs.backend.platform_alert_wording import check_window_end, in_utc
from products.logs.backend.platform_source_config import filters_of

# Below the delivery activity's own timeout, which a flush must not use up.
FLUSH_TIMEOUT_SECONDS: Final = 5.0


def emit_logs_legacy_events(
    *, request: AlertDeliveryRequest, announcement: EvaluationAnnouncement, emissions: Sequence[LegacyEventEmission]
) -> None:
    alert = _Alert(
        team_id=request.team_id,
        alert_id=request.destination_alert_id,
        alert_name=announcement.alert_name,
        consecutive_failures=announcement.consecutive_failures,
    )
    events: list[AlertInternalEvent] = []
    for emission in emissions:
        transition = in_utc(emission.transition)
        if emission.sends_message:
            events.append(_message_event(transition, alert))
        if emission.incident_action is not None:
            events.append(_incident_event(transition, emission.incident_action, alert))
    emit_alert_internal_events(
        team_id=alert.team_id, alert_id=alert.alert_id, events=events, flush_timeout_seconds=FLUSH_TIMEOUT_SECONDS
    )


@frozen
class _Alert:
    team_id: int
    alert_id: str
    alert_name: str
    consecutive_failures: int

    def event(self, event_name: str, properties: dict[str, Any], transition: AnnouncedTransition) -> AlertInternalEvent:
        # The occurrence is in the seed too, so two firings recorded without an evaluation key keep distinct ids.
        seed = (
            f"{self.alert_id}|{transition.grouping_key}|{event_name}|{transition.evaluation_key}|"
            f"{transition.occurred_at.isoformat()}"
        )
        return AlertInternalEvent(
            event_name=event_name,
            properties=properties,
            timestamp=transition.occurred_at,
            uuid=str(uuid5(NAMESPACE_URL, seed)),
        )


def _message_event(transition: AnnouncedTransition, alert: _Alert) -> AlertInternalEvent:
    event_name = EVENT_KIND_CONFIG[cast(EventKind, transition.kind.value)].event_id
    if transition.kind in (AlertEventKind.FIRING, AlertEventKind.RESOLVED):
        return alert.event(event_name, _threshold_properties(transition, alert), transition)
    error_key = "last_error_message" if transition.kind == AlertEventKind.BROKEN else "error_message"
    properties = failure_event_properties(
        alert_id=alert.alert_id,
        alert_name=alert.alert_name,
        team_id=alert.team_id,
        consecutive_failures=alert.consecutive_failures,
        filters=filters_of(transition.source_config),
        triggered_at=transition.occurred_at,
    )
    return alert.event(event_name, {**properties, error_key: transition.error_message or ""}, transition)


def _incident_event(transition: AnnouncedTransition, action: IncidentAction, alert: _Alert) -> AlertInternalEvent:
    if action == IncidentAction.TRIGGER:
        return alert.event(LOGS_ALERT_INCIDENT_OPENED_EVENT, _threshold_properties(transition, alert), transition)
    reason = IncidentCloseReason.BROKEN if transition.kind == AlertEventKind.BROKEN else IncidentCloseReason.RESOLVED
    properties = incident_closed_event_properties(
        alert_id=alert.alert_id,
        alert_name=alert.alert_name,
        team_id=alert.team_id,
        reason=reason.value,
        triggered_at=transition.occurred_at,
    )
    return alert.event(LOGS_ALERT_INCIDENT_CLOSED_EVENT, properties, transition)


def _threshold_properties(transition: AnnouncedTransition, alert: _Alert) -> dict[str, Any]:
    condition = transition.condition
    date_to = check_window_end(transition)
    # The logs stack links every window a check read, not only the latest. A row recorded before
    # the snapshot held the interval falls back to one window.
    lookback = rolling_check_lookback_minutes(
        condition["window_minutes"],
        condition.get("check_interval_minutes") or 0,
        condition.get("evaluation_periods") or 1,
    )
    return threshold_event_properties(
        alert_id=alert.alert_id,
        alert_name=alert.alert_name,
        team_id=alert.team_id,
        threshold_count=condition["threshold_count"],
        threshold_operator=condition["threshold_operator"],
        window_minutes=condition["window_minutes"],
        result_count=int(transition.value) if transition.value is not None else None,
        filters=filters_of(transition.source_config),
        date_from=date_to - timedelta(minutes=lookback),
        date_to=date_to,
        triggered_at=transition.occurred_at,
    )
