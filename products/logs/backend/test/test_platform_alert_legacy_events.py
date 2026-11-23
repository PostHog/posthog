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
from products.logs.backend.platform_alert_legacy_events import emit_logs_legacy_events

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


_IDENTITY: Final = {"alert_id": str(ALERT_ID), "alert_name": "Errors", "team_id": 7}
_SCOPE: Final = {"service_names": ["checkout"], "severity_levels": ["error"]}
_THRESHOLD: Final = {
    **_IDENTITY,
    "threshold_count": 10,
    "threshold_operator": "above",
    "window_minutes": 5,
    "result_count": 42,
    "filters": FILTERS,
    **_SCOPE,
    "logs_url_params": (
        "severityLevels=%5B%22error%22%5D&serviceNames=%5B%22checkout%22%5D&dateRange=%7B%22date_from%22%3A+"
        "%222026-10-16T11%3A52%3A30%2B00%3A00%22%2C+%22date_to%22%3A+%222026-10-16T11%3A59%3A30%2B00%3A00%22%7D"
    ),
    "triggered_at": NOW.isoformat(),
}
_FAILURE: Final = {**_IDENTITY, "consecutive_failures": 3, **_SCOPE, "triggered_at": NOW.isoformat()}
# What the retired logs stack emitted for the same check, which logs destinations still read.
EXPECTED_PROPERTIES: Final[dict[str, dict[str, Any]]] = {
    "$logs_alert_firing": _THRESHOLD,
    "$logs_alert_resolved": _THRESHOLD,
    "$logs_alert_incident_opened": _THRESHOLD,
    "$logs_alert_errored": {**_FAILURE, "error_message": "query timed out"},
    "$logs_alert_auto_disabled": {**_FAILURE, "last_error_message": "query timed out"},
    "$logs_alert_incident_closed": {**_IDENTITY, "reason": "resolved", "triggered_at": NOW.isoformat()},
}


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
        produce = self._emit(
            LegacyEventEmission(
                transition=_transition(kind, source_config),
                sends_message=sends_message,
                incident_action=incident_action,
            )
        )

        (call,) = produce.call_args_list
        assert (call.kwargs["event_name"], call.kwargs["properties"]) == (event_name, EXPECTED_PROPERTIES[event_name])

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
