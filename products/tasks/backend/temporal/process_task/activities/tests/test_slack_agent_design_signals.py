import importlib
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import AsyncMock

from products.tasks.backend.temporal.process_task.activities.slack_agent_design_signals import (
    HEARTBEAT_LAST_PROCESSED_STREAM_ID_KEY,
    RelayAgentDesignSignalsInput,
    SlackAgentDesignSignalEmitter,
    relay_agent_design_signals,
)

from ee.hogai.sandbox import TURN_COMPLETE_METHOD

slack_agent_design_signals_module = importlib.import_module(
    "products.tasks.backend.temporal.process_task.activities.slack_agent_design_signals"
)


class StubWorkflowHandle:
    def __init__(self, signals: list[tuple[str, Any]]) -> None:
        self.signals = signals

    async def signal(self, signal_name: str, arg: Any = None) -> None:
        self.signals.append((signal_name, arg))


class StubTemporalClient:
    def __init__(self, signals: list[tuple[str, Any]]) -> None:
        self.signals = signals

    def get_workflow_handle(self, _workflow_id: str) -> StubWorkflowHandle:
        return StubWorkflowHandle(self.signals)


@pytest.mark.asyncio
async def test_relay_agent_design_signals_resumes_from_last_heartbeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    signals: list[tuple[str, Any]] = []
    heartbeats: list[tuple[Any, ...]] = []

    class StubTaskRunRedisStream:
        def __init__(self, stream_key: str) -> None:
            captured["stream_key"] = stream_key

        async def read_stream_entries(
            self, *, start_id: str, keepalive_interval_seconds: int
        ) -> AsyncGenerator[tuple[str, dict[str, Any]] | None]:
            captured["start_id"] = start_id
            captured["keepalive_interval_seconds"] = keepalive_interval_seconds
            yield None
            yield "124-0", _text_chunk("Hello")

    async_connect = AsyncMock(return_value=StubTemporalClient(signals))
    monkeypatch.setattr("posthog.temporal.common.client.async_connect", async_connect)
    monkeypatch.setattr(slack_agent_design_signals_module, "TaskRunRedisStream", StubTaskRunRedisStream)
    monkeypatch.setattr(
        slack_agent_design_signals_module.TaskRunModel,
        "get_workflow_id",
        lambda task_id, run_id: f"{task_id}-{run_id}",
    )
    monkeypatch.setattr(
        slack_agent_design_signals_module.activity,
        "info",
        lambda: SimpleNamespace(heartbeat_details=[{HEARTBEAT_LAST_PROCESSED_STREAM_ID_KEY: "123-0"}]),
    )
    monkeypatch.setattr(slack_agent_design_signals_module.activity, "heartbeat", lambda *args: heartbeats.append(args))

    await relay_agent_design_signals(RelayAgentDesignSignalsInput(run_id="run-id", task_id="task-id"))

    assert captured["stream_key"] == "task-run-stream:run-id"
    assert captured["start_id"] == "123-0"
    assert signals == [
        ("turn_started", {"slack_thread_context": {}}),
        ("agent_text_delta", "Hello"),
    ]
    assert heartbeats == [
        ({HEARTBEAT_LAST_PROCESSED_STREAM_ID_KEY: "123-0"},),
        ({HEARTBEAT_LAST_PROCESSED_STREAM_ID_KEY: "124-0"},),
    ]


@pytest.mark.asyncio
async def test_relay_agent_design_signals_retries_handle_init_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async_connect = AsyncMock(side_effect=RuntimeError("temporal unavailable"))
    monkeypatch.setattr("posthog.temporal.common.client.async_connect", async_connect)

    with pytest.raises(RuntimeError, match="temporal unavailable"):
        await relay_agent_design_signals(RelayAgentDesignSignalsInput(run_id="run-id", task_id="task-id"))


SLACK_CTX = {"channel": "C1", "integration_id": 7}


def _text_chunk(text: str) -> dict[str, Any]:
    return {
        "type": "notification",
        "notification": {
            "method": "session/update",
            "params": {"update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}},
        },
    }


def _tool_call(tool_call_id: str, tool_name: str, file_path: str) -> dict[str, Any]:
    return {
        "type": "notification",
        "notification": {
            "method": "session/update",
            "params": {
                "update": {
                    "sessionUpdate": "tool_call",
                    "toolCallId": tool_call_id,
                    "_meta": {"claudeCode": {"toolName": tool_name}},
                    "rawInput": {"file_path": file_path},
                }
            },
        },
    }


def _turn_complete() -> dict[str, Any]:
    return {"type": "notification", "notification": {"method": TURN_COMPLETE_METHOD}}


class TestSlackAgentDesignSignalEmitter:
    def test_first_session_update_opens_turn_and_streams_text(self) -> None:
        emitter = SlackAgentDesignSignalEmitter(SLACK_CTX)

        signals = emitter.process(_text_chunk("Hello"))

        assert signals == [
            ("turn_started", {"slack_thread_context": SLACK_CTX}),
            ("agent_text_delta", "Hello"),
        ]

    def test_turn_started_fires_once_per_turn(self) -> None:
        emitter = SlackAgentDesignSignalEmitter(SLACK_CTX)
        emitter.process(_text_chunk("first"))

        signals = emitter.process(_text_chunk("second"))

        assert signals == [("agent_text_delta", "second")]

    def test_tool_call_emits_status_update_and_dedupes(self) -> None:
        emitter = SlackAgentDesignSignalEmitter(SLACK_CTX)
        emitter.process(_text_chunk("thinking"))

        first = emitter.process(_tool_call("call-1", "Read", "/etc/hosts"))
        repeat = emitter.process(_tool_call("call-1", "Read", "/etc/hosts"))

        assert first == [("agent_status_update", {"title": "Read", "details": "/etc/hosts"})]
        assert repeat == []

    def test_turn_completed_emitted_only_when_turn_active(self) -> None:
        emitter = SlackAgentDesignSignalEmitter(SLACK_CTX)

        # No turn open yet — a stray completion is a no-op.
        assert emitter.process(_turn_complete()) == []

        emitter.process(_text_chunk("hi"))
        assert emitter.process(_turn_complete()) == [("turn_completed", None)]

    def test_second_turn_reopens_after_completion(self) -> None:
        emitter = SlackAgentDesignSignalEmitter(SLACK_CTX)
        emitter.process(_text_chunk("turn one"))
        emitter.process(_turn_complete())

        signals = emitter.process(_text_chunk("turn two"))

        assert signals == [
            ("turn_started", {"slack_thread_context": SLACK_CTX}),
            ("agent_text_delta", "turn two"),
        ]

    def test_events_before_any_turn_are_ignored(self) -> None:
        emitter = SlackAgentDesignSignalEmitter(SLACK_CTX)

        # A tool_call without a preceding session/update still opens the turn (it is a
        # session/update itself), but a non-session event must not leak signals.
        assert emitter.process({"type": "keepalive"}) == []
