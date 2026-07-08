from typing import Any

from products.tasks.backend.temporal.process_task.activities.slack_agent_design_signals import (
    SlackAgentDesignSignalEmitter,
)

from ee.hogai.sandbox import TURN_COMPLETE_METHOD

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
