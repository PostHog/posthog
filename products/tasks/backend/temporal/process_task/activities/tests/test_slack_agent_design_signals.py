from typing import Any

from unittest.mock import MagicMock, patch

from products.tasks.backend.temporal.process_task.activities.slack_agent_design_signals import (
    SlackAgentDesignSignalEmitter,
    _event_method,
    _resume_position,
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

    def test_seeded_turn_active_does_not_reopen_mid_turn_resume(self) -> None:
        # A retry that resumes mid-turn seeds turn_active=True, so the first resumed session/update
        # streams text without emitting a duplicate turn_started.
        emitter = SlackAgentDesignSignalEmitter(SLACK_CTX, turn_active=True)

        signals = emitter.process(_text_chunk("resumed"))

        assert signals == [("agent_text_delta", "resumed")]

    def test_events_before_any_turn_are_ignored(self) -> None:
        emitter = SlackAgentDesignSignalEmitter(SLACK_CTX)

        # A tool_call without a preceding session/update still opens the turn (it is a
        # session/update itself), but a non-session event must not leak signals.
        assert emitter.process({"type": "keepalive"}) == []


class TestEventMethod:
    def test_returns_notification_method(self) -> None:
        assert _event_method(_text_chunk("hi")) == "session/update"

    def test_returns_none_without_notification(self) -> None:
        assert _event_method({"type": "keepalive"}) is None


class TestResumePosition:
    def _with_details(self, details: tuple) -> Any:
        info = MagicMock()
        info.heartbeat_details = details
        return patch(
            "products.tasks.backend.temporal.process_task.activities.slack_agent_design_signals.activity.info",
            return_value=info,
        )

    def test_returns_id_and_turn_state_from_prior_attempt(self) -> None:
        with self._with_details(("1700-0", True)):
            assert _resume_position() == ("1700-0", True)

    def test_returns_defaults_on_first_attempt(self) -> None:
        # No prior heartbeat — resume from the start of the stream with no turn open.
        with self._with_details(()):
            assert _resume_position() == (None, False)

    def test_turn_active_defaults_false_when_absent(self) -> None:
        # A pre-turn-state heartbeat (id only) resumes with no turn open.
        with self._with_details(("1700-0",)):
            assert _resume_position() == ("1700-0", False)

    def test_ignores_empty_or_non_string_id(self) -> None:
        with self._with_details(("", True)):
            assert _resume_position() == (None, True)
        with self._with_details((123, False)):
            assert _resume_position() == (None, False)
