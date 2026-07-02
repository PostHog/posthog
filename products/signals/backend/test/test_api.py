import uuid

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import pydantic
import temporalio.exceptions

from products.signals.backend.contracts import SignalRemediation
from products.signals.backend.facade.api import (
    _MAX_TELEMETRY_STR_LEN,
    MAX_SIGNAL_REMEDIATION_TOKENS,
    _telemetry_props_from_extra,
    emit_signal,
)
from products.signals.backend.models import SignalSourceConfig
from products.signals.backend.temporal.buffer import BufferSignalsWorkflow
from products.signals.backend.temporal.emitter import SignalEmitterWorkflow


@pytest.fixture
def team_stub() -> MagicMock:
    org = MagicMock()
    org.is_ai_data_processing_approved = True
    team = MagicMock()
    team.id = 1
    team.uuid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    team.organization = org
    return team


SESSION_PROBLEM_EXTRA = {
    "session_id": "abc-123",
    "segment_title": "Checkout flow failure",
    "start_time": "00:30",
    "end_time": "02:15",
    "problem_type": "confusion",
    "distinct_id": "user-1",
    "session_start_time": "2025-01-01T00:00:00Z",
    "session_end_time": "2025-01-01T00:05:00Z",
    "event_history": [
        {"event": "$pageview", "timestamp": "00:30", "current_url": "https://app.example.com/checkout"},
        {"event": "$autocapture", "timestamp": "00:45", "event_type": "click", "interaction_text": "Submit order"},
        {"event": "$exception", "timestamp": "01:02"},
    ],
}

EVALUATION_EXTRA = {
    "evaluation_id": "eval-001",
    "trace_id": "trace-abc",
}

ZENDESK_TICKET_EXTRA = {
    "url": "https://example.zendesk.com/tickets/1",
    "type": "problem",
    "tags": ["billing", "urgent"],
    "created_at": "2025-06-01T12:00:00Z",
    "priority": "high",
    "status": "open",
}

GITHUB_ISSUE_EXTRA = {
    "html_url": "https://github.com/org/repo/issues/42",
    "number": 42,
    "labels": ["bug", "critical"],
    "created_at": "2025-06-01T12:00:00Z",
    "updated_at": "2025-06-02T08:00:00Z",
    "locked": False,
    "state": "open",
}

PULSE_OPPORTUNITY_EXTRA = {
    "brief_id": "0197a000-0000-0000-0000-000000000000",
    "evidence": [{"type": "insight", "ref": "abc123", "label": "Pageviews"}],
}


@pytest.mark.asyncio
class TestEmitSignalValidation:
    @pytest.mark.parametrize(
        "source_product, source_type, extra",
        [
            ("session_replay", "session_problem", SESSION_PROBLEM_EXTRA),
            ("llm_analytics", "evaluation", EVALUATION_EXTRA),
            ("zendesk", "ticket", ZENDESK_TICKET_EXTRA),
            ("github", "issue", GITHUB_ISSUE_EXTRA),
            ("pulse", "opportunity_build", PULSE_OPPORTUNITY_EXTRA),
            ("pulse", "opportunity_fix", PULSE_OPPORTUNITY_EXTRA),
            ("pulse", "opportunity_instrument", PULSE_OPPORTUNITY_EXTRA),
        ],
        ids=[
            "session_problem",
            "evaluation",
            "ticket",
            "issue",
            "pulse_opportunity_build",
            "pulse_opportunity_fix",
            "pulse_opportunity_instrument",
        ],
    )
    async def test_emit_signal_accepts_valid_input(self, source_product, source_type, extra, team_stub):
        client = AsyncMock()
        # Buffer workflow already running
        client.start_workflow.side_effect = [
            temporalio.exceptions.WorkflowAlreadyStartedError("already started", "buffer-signals-1"),
            AsyncMock(),  # emitter start
        ]

        with (
            patch("products.signals.backend.facade.api.async_connect", return_value=client),
            patch.object(SignalSourceConfig, "is_source_enabled", return_value=True),
        ):
            await emit_signal(
                team=team_stub,
                source_product=source_product,
                source_type=source_type,
                source_id="test-id-1",
                description="A valid signal",
                extra=extra,
            )

        assert client.start_workflow.await_count == 2
        # First call: buffer workflow ensure
        assert client.start_workflow.call_args_list[0].args[0] == BufferSignalsWorkflow.run
        # Second call: emitter workflow
        assert client.start_workflow.call_args_list[1].args[0] == SignalEmitterWorkflow.run

    @pytest.mark.parametrize(
        "source_product, source_type, extra",
        [
            ("session_replay", "nonexistent", {}),
            ("github", "issue", {}),
            ("zendesk", "ticket", {**ZENDESK_TICKET_EXTRA, "tags": "not-a-list"}),
            ("llm_analytics", "evaluation", {**EVALUATION_EXTRA, "bogus": 1}),
        ],
        ids=["unknown_source_type", "missing_extra_fields", "wrong_extra_field_type", "unexpected_extra_field"],
    )
    async def test_emit_signal_rejects_invalid_input(self, source_product, source_type, extra, team_stub):
        client = AsyncMock()

        with (
            patch("products.signals.backend.facade.api.async_connect", return_value=client),
            patch.object(SignalSourceConfig, "is_source_enabled", return_value=True),
        ):
            with pytest.raises(pydantic.ValidationError):
                await emit_signal(
                    team=team_stub,
                    source_product=source_product,
                    source_type=source_type,
                    source_id="test-id-1",
                    description="An invalid signal",
                    extra=extra,
                )

        client.start_workflow.assert_not_awaited()

    async def test_emit_signal_rejects_oversized_remediation(self, team_stub):
        client = AsyncMock()

        with (
            patch("products.signals.backend.facade.api.async_connect", return_value=client),
            patch.object(SignalSourceConfig, "is_source_enabled", return_value=True),
        ):
            with pytest.raises(ValueError, match="remediation exceeds"):
                await emit_signal(
                    team=team_stub,
                    source_product="github",
                    source_type="issue",
                    source_id="test-id-1",
                    description="A valid signal",
                    extra=GITHUB_ISSUE_EXTRA,
                    remediation=SignalRemediation(human="fix it", agent="step " * (MAX_SIGNAL_REMEDIATION_TOKENS + 1)),
                )

        client.start_workflow.assert_not_awaited()

    async def test_emit_signal_accepts_remediation_within_limit(self, team_stub):
        client = AsyncMock()
        client.start_workflow.side_effect = [
            temporalio.exceptions.WorkflowAlreadyStartedError("already started", "buffer-signals-1"),
            AsyncMock(),
        ]

        with (
            patch("products.signals.backend.facade.api.async_connect", return_value=client),
            patch.object(SignalSourceConfig, "is_source_enabled", return_value=True),
        ):
            await emit_signal(
                team=team_stub,
                source_product="github",
                source_type="issue",
                source_id="test-id-1",
                description="A valid signal",
                extra=GITHUB_ISSUE_EXTRA,
                remediation=SignalRemediation(human="Re-run the materialization.", agent="Open the model and retry."),
            )

        assert client.start_workflow.await_count == 2


@pytest.mark.asyncio
class TestEmitSignalAnalytics:
    async def test_capture_called_on_emit(self, team_stub):
        client = AsyncMock()
        client.start_workflow.side_effect = [
            temporalio.exceptions.WorkflowAlreadyStartedError("already started", "buffer-signals-1"),
            AsyncMock(),
        ]

        with (
            patch("products.signals.backend.facade.api.async_connect", return_value=client),
            patch.object(SignalSourceConfig, "is_source_enabled", return_value=True),
            patch("products.signals.backend.facade.api.posthoganalytics.capture") as capture,
        ):
            await emit_signal(
                team=team_stub,
                source_product="github",
                source_type="issue",
                source_id="posthog/posthog#42",
                description="A valid signal",
                extra=GITHUB_ISSUE_EXTRA,
            )

        # Both the "started" marker and the final "emitted" event fire
        events = [call.kwargs["event"] for call in capture.call_args_list]
        assert events == ["signal_emission_started", "signal_emitted"]
        # Only top-level scalar `extra` values are flattened onto the event (the `labels`
        # list is dropped); the core `source_*` keys win on conflict.
        expected_properties = {
            "html_url": "https://github.com/org/repo/issues/42",
            "number": 42,
            "created_at": "2025-06-01T12:00:00Z",
            "updated_at": "2025-06-02T08:00:00Z",
            "locked": False,
            "state": "open",
            "source_product": "github",
            "source_type": "issue",
            "source_id": "posthog/posthog#42",
        }
        for call in capture.call_args_list:
            assert call.kwargs["distinct_id"] == str(team_stub.uuid)
            assert call.kwargs["properties"] == expected_properties
            assert "labels" not in call.kwargs["properties"]
            assert "project" in call.kwargs["groups"]


class TestTelemetryPropsFromExtra:
    def test_none_and_empty(self) -> None:
        assert _telemetry_props_from_extra(None) == {}
        assert _telemetry_props_from_extra({}) == {}

    def test_keeps_scalars_drops_nested(self) -> None:
        props = _telemetry_props_from_extra(
            {
                "scout_run_id": "run-1",
                "number": 42,
                "confidence": 0.9,
                "locked": False,
                "labels": ["bug", "p1"],  # list — dropped
                "references": [{"queryText": "SELECT * FROM customers"}],  # nested — dropped
                "time_range": {"date_from": "a", "date_to": "b"},  # dict — dropped
            }
        )
        assert props == {"scout_run_id": "run-1", "number": 42, "confidence": 0.9, "locked": False}

    def test_truncates_long_strings(self) -> None:
        props = _telemetry_props_from_extra({"error_message": "x" * 1000})
        assert len(props["error_message"]) == _MAX_TELEMETRY_STR_LEN
