from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

import pytest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.alerts.backend.facade.contracts import AlertInternalEventsNotDelivered
from products.alerts_platform.backend.facade.contracts import (
    SOURCE_CONDITION_KEY,
    AlertDeliveryRequest,
    AlertEventKind,
    AnnouncedTransition,
    EvaluationAnnouncement,
    IncidentAction,
    LegacyEventEmission,
    SourceKind,
)
from products.logs.backend.alert_evaluation_key import WINDOW_MARKER
from products.logs.backend.alert_state_machine import (
    AlertCheckOutcome,
    AlertState,
    CheckResult,
    IncidentCloseReason,
    NotificationAction,
)
from products.logs.backend.models import LogsAlertConfiguration
from products.logs.backend.platform_alert_legacy_events import emit_logs_legacy_events
from products.logs.backend.temporal import activities

_ACTIVITIES_PRODUCE = "products.logs.backend.temporal.activities.produce_alert_internal_event"
_PRODUCER = "products.alerts.backend.logic.destinations"
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
WINDOW_END = NOW - timedelta(seconds=30)
ALERT_ID = UUID("01900000-0000-0000-0000-000000000001")
FILTERS: dict[str, Any] = {"severityLevels": ["error"], "serviceNames": ["checkout"]}
CONDITION = {"threshold_count": 10, "threshold_operator": "above", "window_minutes": 5}
# Three rolling windows a minute apart, so the link reaches back past the latest window, as the logs stack's does.
SCHEDULE = {"check_interval_minutes": 1, "evaluation_periods": 3}


REQUEST = AlertDeliveryRequest(
    source=SourceKind.LOGS,
    team_id=7,
    configuration_id="cfg-1",
    evaluation_key="eval-1",
    destination_alert_id=str(ALERT_ID),
    event_ids_by_kind={},
)
ANNOUNCEMENT = EvaluationAnnouncement(
    configuration_id="cfg-1", source=SourceKind.LOGS, alert_name="Errors", consecutive_failures=3, transitions=()
)


def _alert() -> LogsAlertConfiguration:
    return LogsAlertConfiguration(id=ALERT_ID, team_id=7, name="Errors", filters=FILTERS, **CONDITION, **SCHEDULE)


# A copy stores its filters nested, and a history row written before the nesting keeps them flat.
NESTED_SOURCE_CONFIG: Final = {"filters": FILTERS, SOURCE_CONDITION_KEY: CONDITION}
FLAT_SOURCE_CONFIG: Final = {**FILTERS, SOURCE_CONDITION_KEY: CONDITION}


def _transition(kind: AlertEventKind, source_config: dict[str, Any] = NESTED_SOURCE_CONFIG) -> AnnouncedTransition:
    return AnnouncedTransition(
        grouping_key="",
        kind=kind,
        episode_started_at=NOW,
        value=42.0 if kind in (AlertEventKind.FIRING, AlertEventKind.RESOLVED) else None,
        labels={},
        condition={**CONDITION, **SCHEDULE},
        source_config=source_config,
        error_message="query timed out",
        occurred_at=NOW,
        evaluation_key=f"slot:1|{WINDOW_MARKER}{WINDOW_END.isoformat()}",
    )


def _failure(notification: NotificationAction) -> AlertCheckOutcome:
    return AlertCheckOutcome(
        new_state=AlertState.ERRORED,
        notification=notification,
        consecutive_failures=3,
        update_last_notified_at=True,
        error_message="query timed out",
    )


def _legacy_emit(event_name: str) -> None:
    alert = _alert()
    check = CheckResult(result_count=42, threshold_breached=True)
    window = {"date_from": WINDOW_END - timedelta(minutes=7), "date_to": WINDOW_END}
    if event_name == "$logs_alert_errored":
        activities._emit_alert_errored_event(alert, _failure(NotificationAction.ERROR), NOW)
    elif event_name == "$logs_alert_auto_disabled":
        activities._emit_auto_disabled_event(alert, _failure(NotificationAction.BROKEN), NOW)
    elif event_name == "$logs_alert_incident_closed":
        activities._emit_incident_closed_event(alert, IncidentCloseReason.RESOLVED, NOW)
    else:
        activities._emit_alert_event(alert, event_name, check, NOW, **window)


class TestEmitLogsLegacyEvents(SimpleTestCase):
    def _emit(self, *emissions: LegacyEventEmission, delivered: bool = True) -> MagicMock:
        with (
            patch(f"{_PRODUCER}.produce_alert_internal_event", return_value=MagicMock()) as produce,
            patch(f"{_PRODUCER}.flush_alert_internal_events"),
            patch(f"{_PRODUCER}.alert_internal_event_delivered", return_value=delivered),
        ):
            emit_logs_legacy_events(request=REQUEST, announcement=ANNOUNCEMENT, emissions=emissions)
        return produce

    @parameterized.expand(
        [
            (f"{name}_{shape}", kind, sends_message, incident_action, event_name, source_config)
            for name, kind, sends_message, incident_action, event_name in [
                ("firing", AlertEventKind.FIRING, True, None, "$logs_alert_firing"),
                ("resolved", AlertEventKind.RESOLVED, True, None, "$logs_alert_resolved"),
                ("errored", AlertEventKind.ERRORED, True, None, "$logs_alert_errored"),
                ("auto_disabled", AlertEventKind.BROKEN, True, None, "$logs_alert_auto_disabled"),
                # Cooldown held the message, and the incident still opens.
                (
                    "incident_opened",
                    AlertEventKind.FIRING,
                    False,
                    IncidentAction.TRIGGER,
                    "$logs_alert_incident_opened",
                ),
                (
                    "incident_closed",
                    AlertEventKind.RESOLVED,
                    False,
                    IncidentAction.RESOLVE,
                    "$logs_alert_incident_closed",
                ),
            ]
            for shape, source_config in [("nested", NESTED_SOURCE_CONFIG), ("flat", FLAT_SOURCE_CONFIG)]
        ]
    )
    def test_an_event_carries_what_the_logs_stack_emits_for_the_same_check(
        self,
        _name: str,
        kind: AlertEventKind,
        sends_message: bool,
        incident_action: IncidentAction | None,
        event_name: str,
        source_config: dict[str, Any],
    ) -> None:
        with patch(_ACTIVITIES_PRODUCE) as legacy:
            _legacy_emit(event_name)

        produce = self._emit(
            LegacyEventEmission(
                transition=_transition(kind, source_config),
                sends_message=sends_message,
                incident_action=incident_action,
            )
        )

        (call,) = produce.call_args_list
        assert (call.kwargs["event_name"], call.kwargs["properties"]) == (
            legacy.call_args.kwargs["event_name"],
            legacy.call_args.kwargs["properties"],
        )

    def test_a_retried_emission_reuses_each_event_id_so_a_receiver_can_drop_it(self) -> None:
        emission = LegacyEventEmission(
            transition=_transition(AlertEventKind.FIRING), sends_message=True, incident_action=IncidentAction.TRIGGER
        )

        first = [call.kwargs["uuid"] for call in self._emit(emission).call_args_list]
        second = [call.kwargs["uuid"] for call in self._emit(emission).call_args_list]

        assert first == second
        assert len(set(first)) == 2

    def test_an_event_the_broker_did_not_take_raises_so_the_delivery_retries(self) -> None:
        emission = LegacyEventEmission(
            transition=_transition(AlertEventKind.FIRING), sends_message=True, incident_action=None
        )

        with pytest.raises(AlertInternalEventsNotDelivered):
            self._emit(emission, delivered=False)
