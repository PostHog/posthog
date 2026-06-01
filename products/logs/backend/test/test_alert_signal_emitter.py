import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from posthog.schema import LogsAlertStateChangeSignalExtra

from posthog.models import Team

from products.logs.backend.alert_signal_emitter import (
    NotifiedAlert,
    build_signal_description,
    build_signal_extra,
    emit_alert_state_change_signal,
    signal_action_and_weight,
)
from products.logs.backend.alert_state_machine import NotificationAction


def _notified(action: str = "firing") -> NotifiedAlert:
    return NotifiedAlert(
        alert_id="11111111-1111-1111-1111-111111111111",
        team_id=7,
        alert_name="Checkout 5xx",
        action=action,
        weight=1.0,
        threshold_count=100,
        threshold_operator="above",
        window_minutes=5,
        result_count=250,
        consecutive_failures=0,
        filters={"serviceNames": ["checkout"], "severityLevels": ["error"]},
    )


class TestSignalActionAndWeight:
    @parameterized.expand(
        [
            (NotificationAction.FIRE, "firing", 1.0),
            (NotificationAction.BROKEN, "broken", 1.0),
        ]
    )
    def test_maps_action_and_weight(self, notification, expected_action, expected_weight):
        result = signal_action_and_weight(notification)
        assert result is not None
        action, weight = result
        assert action == expected_action
        assert weight == expected_weight

    @parameterized.expand(
        [
            (NotificationAction.NONE,),
            (NotificationAction.RESOLVE,),
            (NotificationAction.ERROR,),
        ]
    )
    def test_non_signalable_actions_return_none(self, notification):
        assert signal_action_and_weight(notification) is None


class TestBuildSignalExtra:
    def test_contains_alert_context(self):
        extra = build_signal_extra(_notified("firing"))
        assert extra["alert_id"] == "11111111-1111-1111-1111-111111111111"
        assert extra["action"] == "firing"
        assert extra["threshold_count"] == 100
        assert extra["result_count"] == 250
        assert extra["filters"] == {"serviceNames": ["checkout"], "severityLevels": ["error"]}
        assert extra["url"].endswith("/project/7/logs")

    @parameterized.expand([("firing",), ("broken",)])
    def test_built_extra_satisfies_signal_schema(self, action):
        # emit_signal validates extra against this variant with extra="forbid";
        # if build_signal_extra drifts from the schema, every emit fails validation.
        LogsAlertStateChangeSignalExtra.model_validate(build_signal_extra(_notified(action)))


class TestBuildSignalDescription:
    def test_firing_description_is_embedding_friendly(self):
        desc = build_signal_description(_notified("firing"))
        assert "Checkout 5xx" in desc
        assert "firing" in desc
        assert "checkout" in desc

    def test_broken_description_mentions_failures(self):
        na = _notified("broken")
        na = NotifiedAlert(**{**na.__dict__, "consecutive_failures": 5})
        desc = build_signal_description(na)
        assert "5" in desc
        assert "broken" in desc or "disabled" in desc


class TestEmitAlertStateChangeSignal:
    @pytest.mark.asyncio
    async def test_calls_emit_signal_with_weight_and_extra(self):
        team = MagicMock(spec=Team)
        with patch("products.logs.backend.alert_signal_emitter.emit_signal", new=AsyncMock()) as mock_emit:
            ok = await emit_alert_state_change_signal(team, _notified("firing"))

        assert ok is True
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["source_product"] == "logs"
        assert kwargs["source_type"] == "alert_state_change"
        assert kwargs["weight"] == 1.0
        assert kwargs["source_id"].startswith("11111111-1111-1111-1111-111111111111:firing")
        assert kwargs["extra"]["action"] == "firing"

    @pytest.mark.asyncio
    async def test_swallows_emit_signal_failure(self):
        with patch(
            "products.logs.backend.alert_signal_emitter.emit_signal",
            new=AsyncMock(side_effect=RuntimeError("temporal down")),
        ):
            ok = await emit_alert_state_change_signal(MagicMock(spec=Team), _notified("broken"))

        assert ok is False
