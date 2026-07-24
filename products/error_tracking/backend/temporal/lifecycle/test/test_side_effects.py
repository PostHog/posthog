import copy

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from confluent_kafka import KafkaError, KafkaException

from posthog.cdp.internal_events import InternalEventEvent
from posthog.helpers.tiktoken_encoding import LLM_TOKEN_COUNT_PROXY_MODEL, get_tiktoken_encoding_for_model

from products.error_tracking.backend.temporal.lifecycle.issue_created.types import (
    IssueCreatedSnapshot,
    IssueCreatedWorkflowInputs,
)
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import (
    IssueReopenedSnapshot,
    IssueReopenedWorkflowInputs,
)
from products.error_tracking.backend.temporal.lifecycle.rendering import SIGNAL_MAX_TOKENS
from products.error_tracking.backend.temporal.lifecycle.side_effects import (
    emit_issue_lifecycle_signal,
    produce_issue_lifecycle_internal_event,
)


def _inputs() -> IssueReopenedWorkflowInputs:
    return IssueReopenedWorkflowInputs(
        notification_id="01982721-5e00-7000-8000-000000000001",
        team_id=42,
        issue_id="01982721-5e00-7000-8000-000000000002",
        issue=IssueReopenedSnapshot(
            name="TypeError",
            description="Something failed",
            status="pending_release",
            created_at="2026-07-21T12:00:00Z",
        ),
        fingerprint="fingerprint",
        event_uuid="01982721-5e00-7000-8000-000000000003",
        event_timestamp="2026-07-21T12:05:00Z",
        assignee='{"type":"user","id":1}',
    )


def test_created_internal_event_preserves_raw_status() -> None:
    inputs = IssueCreatedWorkflowInputs(
        notification_id="01982721-5e00-7000-8000-000000000001",
        team_id=42,
        issue_id="01982721-5e00-7000-8000-000000000002",
        issue=IssueCreatedSnapshot(
            name="TypeError",
            description="Something failed",
            status="active",
            created_at="2026-07-21T12:00:00Z",
        ),
        fingerprint="fingerprint",
        event_uuid="01982721-5e00-7000-8000-000000000003",
        event_timestamp="2026-07-21T12:05:00Z",
    )
    result = MagicMock()
    sent_events: list[InternalEventEvent] = []

    def capture_event(_team_id: int, event: InternalEventEvent) -> MagicMock:
        sent_events.append(copy.deepcopy(event))
        return result

    with (
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.Team.objects.get",
            return_value=MagicMock(),
        ),
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.fetch_event_properties",
            return_value={},
        ),
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.produce_internal_event",
            side_effect=capture_event,
        ),
        patch("products.error_tracking.backend.temporal.lifecycle.side_effects.flush_internal_events_producer"),
    ):
        produce_issue_lifecycle_internal_event(
            inputs,
            event="$error_tracking_issue_created",
            exception_timestamp=inputs.event_timestamp,
            humanize_status=False,
        )

    assert sent_events[0].event == "$error_tracking_issue_created"
    assert sent_events[0].properties["status"] == "active"


def test_oversized_internal_event_retries_without_exception_properties() -> None:
    inputs = _inputs()
    event_properties = {"$exception_list": [{"type": "TypeError", "value": "boom"}]}
    oversized_result = MagicMock()
    oversized_result.get.side_effect = KafkaException(KafkaError(KafkaError.MSG_SIZE_TOO_LARGE))  # type: ignore[attr-defined]
    retry_result = MagicMock()
    results = iter([oversized_result, retry_result])
    sent_events: list[InternalEventEvent] = []

    def capture_event(_team_id: int, event: InternalEventEvent) -> MagicMock:
        sent_events.append(copy.deepcopy(event))
        return next(results)

    with (
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.Team.objects.get",
            return_value=MagicMock(),
        ),
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.fetch_event_properties",
            return_value=event_properties,
        ),
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.produce_internal_event",
            side_effect=capture_event,
        ) as produce_internal_event,
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.flush_internal_events_producer"
        ) as flush,
    ):
        produce_issue_lifecycle_internal_event(
            inputs,
            event="$error_tracking_issue_reopened",
            exception_timestamp="2026-07-21T12:05:00",
        )

    assert produce_internal_event.call_count == 2
    assert len(sent_events) == 2
    assert sent_events[0].event == "$error_tracking_issue_reopened"
    assert sent_events[0].distinct_id == inputs.issue_id
    assert sent_events[0].uuid == inputs.notification_id
    assert sent_events[0].properties == {
        "name": "TypeError",
        "description": "Something failed",
        "issue_description": "Something failed",
        "first_seen": "2026-07-21T12:00:00Z",
        "fingerprint": "fingerprint",
        "exception_timestamp": "2026-07-21T12:05:00+00:00",
        "exception_props": event_properties,
        "status": "Pending Release",
        "assignee": inputs.assignee,
    }
    assert sent_events[1].properties == {
        key: value for key, value in sent_events[0].properties.items() if key != "exception_props"
    } | {"message_was_too_large": True}
    assert flush.call_count == 2
    oversized_result.get.assert_called_once_with(timeout=0)
    retry_result.get.assert_called_once_with(timeout=0)


def test_internal_event_reraises_non_size_kafka_errors() -> None:
    result = MagicMock()
    result.get.side_effect = KafkaException(KafkaError(KafkaError._TRANSPORT))  # type: ignore[attr-defined]
    sent_events: list[InternalEventEvent] = []

    def capture_event(_team_id: int, event: InternalEventEvent) -> MagicMock:
        sent_events.append(copy.deepcopy(event))
        return result

    with (
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.Team.objects.get",
            return_value=MagicMock(),
        ),
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.fetch_event_properties",
            return_value={},
        ),
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.produce_internal_event",
            side_effect=capture_event,
        ),
        patch("products.error_tracking.backend.temporal.lifecycle.side_effects.flush_internal_events_producer"),
        pytest.raises(KafkaException),
    ):
        produce_issue_lifecycle_internal_event(
            _inputs(),
            event="$error_tracking_issue_reopened",
            exception_timestamp="invalid",
        )

    assert len(sent_events) == 1


@pytest.mark.asyncio
async def test_signal_is_truncated_and_uses_notification_id_for_idempotency() -> None:
    inputs = _inputs()
    team = MagicMock()
    event_properties = {"$exception_list": [{"type": "TypeError", "value": "boom"}]}
    stacktrace = "repeated stack frame\n" * 10_000

    with (
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.Team.objects.aget",
            new=AsyncMock(return_value=team),
        ),
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.fetch_event_properties",
            return_value=event_properties,
        ),
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.render_stacktrace",
            return_value=stacktrace,
        ),
        patch(
            "products.error_tracking.backend.temporal.lifecycle.side_effects.emit_signal",
            new=AsyncMock(),
        ) as emit_signal,
    ):
        await emit_issue_lifecycle_signal(
            inputs,
            source_type="issue_reopened",
            preamble="Previously resolved issue reappeared",
        )

    emit_signal.assert_awaited_once()
    assert emit_signal.await_args is not None
    call = emit_signal.await_args.kwargs
    description = call["description"]
    encoding = get_tiktoken_encoding_for_model(LLM_TOKEN_COUNT_PROXY_MODEL)
    assert description.startswith("Previously resolved issue reappeared:\nTypeError: Something failed\n")
    assert len(encoding.encode(description)) <= SIGNAL_MAX_TOKENS
    assert call == {
        "team": team,
        "source_product": "error_tracking",
        "source_type": "issue_reopened",
        "source_id": inputs.issue_id,
        "description": description,
        "weight": 1.0,
        "extra": {"fingerprint": inputs.fingerprint},
        "idempotency_key": inputs.notification_id,
    }
