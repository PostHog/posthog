import pytest
from unittest.mock import patch

from products.tasks.backend.logic.services.custom_prompt_internals import _check_logs, _stream_new_lines
from products.tasks.backend.tests.agent_log_fixtures import (
    FakeTaskRun,
    _agent_message_line,
    _end_turn_line,
    _refusal_line,
    _usage_update_line,
    _user_message_line,
)


class TestCheckLogs:
    def test_returns_agent_message_when_both_present(self):
        log = "\n".join([_agent_message_line("hello"), _end_turn_line()])
        with patch("posthog.storage.object_storage.read", return_value=log):
            state = _check_logs(FakeTaskRun())
        assert state.agent_finished is True
        assert state.last_message == "hello"
        assert state.empty_end_turn is False

    def test_end_turn_without_agent_message_flags_empty_end_turn(self):
        """Regression: when skip_lines puts us past the agent_message but end_turn
        is in the new lines, _check_logs must NOT rescan from 0 and return a
        stale message from a previous turn. Instead it must flag empty_end_turn
        so the caller can retry."""
        turn_1 = [_agent_message_line("turn-1-response"), _end_turn_line()]
        turn_2_prompt = [_user_message_line("next question")]
        # end_turn for turn 2 arrived, but agent_message never did (the SDK short-circuit)
        turn_2_partial = [_end_turn_line()]

        log = "\n".join(turn_1 + turn_2_prompt + turn_2_partial)
        skip = len(turn_1) + len(turn_2_prompt)

        with patch("posthog.storage.object_storage.read", return_value=log):
            state = _check_logs(FakeTaskRun(), skip_lines=skip)

        assert state.agent_finished is False
        assert state.last_message is None
        assert state.empty_end_turn is True
        assert state.total_lines == len(turn_1) + len(turn_2_prompt) + len(turn_2_partial)

    def test_skip_lines_returns_only_new_agent_message(self):
        turn_1 = [_agent_message_line("old"), _end_turn_line()]
        turn_2 = [_user_message_line("prompt"), _agent_message_line("new"), _end_turn_line()]

        log = "\n".join(turn_1 + turn_2)
        skip = len(turn_1)

        with patch("posthog.storage.object_storage.read", return_value=log):
            state = _check_logs(FakeTaskRun(), skip_lines=skip)

        assert state.agent_finished is True
        assert state.last_message == "new"
        assert state.empty_end_turn is False

    def test_empty_log_returns_all_defaults(self):
        with patch("posthog.storage.object_storage.read", return_value=""):
            state = _check_logs(FakeTaskRun())
        assert (
            state.agent_finished,
            state.last_message,
            state.full_log,
            state.total_lines,
            state.empty_end_turn,
            state.refused,
        ) == (
            False,
            None,
            None,
            0,
            False,
            False,
        )

    def test_no_new_lines_since_skip_does_not_flag_empty(self):
        """Eventual-consistency case: S3 hasn't caught up yet, no new data to parse."""
        turn_1 = [_agent_message_line("x"), _end_turn_line()]
        log = "\n".join(turn_1)
        with patch("posthog.storage.object_storage.read", return_value=log):
            state = _check_logs(FakeTaskRun(), skip_lines=len(turn_1))
        assert state.agent_finished is False
        assert state.last_message is None
        assert state.empty_end_turn is False
        assert state.total_lines == len(turn_1)

    def test_empty_end_turn_flagged_on_first_turn_too(self):
        """SDK short-circuit on the very first turn must surface as empty_end_turn too.
        Otherwise MultiTurnSession.start silently polls until timeout."""
        log = "\n".join([_end_turn_line()])
        with patch("posthog.storage.object_storage.read", return_value=log):
            state = _check_logs(FakeTaskRun(), skip_lines=0)
        assert state.agent_finished is False
        assert state.last_message is None
        assert state.empty_end_turn is True

    def test_usage_updates_alone_between_prompt_and_end_turn_flags_empty(self):
        """This is the exact pattern seen in the production incident:
        user_message_chunk → 2× usage_update → end_turn, with no agent_message."""
        turn_1 = [_agent_message_line("first"), _end_turn_line()]
        turn_2_empty = [
            _user_message_line("priority prompt"),
            _usage_update_line(0),
            _usage_update_line(0),
            _end_turn_line(),
        ]

        log = "\n".join(turn_1 + turn_2_empty)
        with patch("posthog.storage.object_storage.read", return_value=log):
            state = _check_logs(FakeTaskRun(), skip_lines=len(turn_1))

        assert state.agent_finished is False
        assert state.last_message is None
        assert state.empty_end_turn is True

    def test_refusal_flags_refused_and_suppresses_partial_text(self):
        """Regression: a provider refusal used to look like a still-running turn, so every
        refusing unit polled out the full budget (30 min). It must surface as refused, and any
        pre-refusal partial text must not be mistaken for the turn's response."""
        log = "\n".join([_agent_message_line("partial reasoning"), _refusal_line()])
        with patch("posthog.storage.object_storage.read", return_value=log):
            state = _check_logs(FakeTaskRun())
        assert state.refused is True
        assert state.agent_finished is False
        assert state.last_message is None
        assert state.empty_end_turn is False

    @pytest.mark.parametrize(
        "lines,expected_text",
        [
            pytest.param(
                [_refusal_line(), _agent_message_line("recovered"), _end_turn_line()],
                "recovered",
                id="refusal-then-end-turn",
            ),
            pytest.param(
                [_agent_message_line("done"), _end_turn_line(), _refusal_line()],
                "done",
                id="end-turn-then-refusal",
            ),
        ],
    )
    def test_end_turn_outranks_refusal_in_either_order(self, lines: list[str], expected_text: str):
        """A successful end_turn outranks a refusal in the same slice regardless of order —
        failing a finished turn as refused would discard a good response."""
        log = "\n".join(lines)
        with patch("posthog.storage.object_storage.read", return_value=log):
            state = _check_logs(FakeTaskRun())
        assert state.refused is False
        assert state.agent_finished is True
        assert state.last_message == expected_text
        assert state.empty_end_turn is False


class TestStreamNewLinesMonotonic:
    def test_no_duplicate_output_after_s3_regression_then_recovery(self):
        """Across three polls the user must see each line exactly once, even if S3
        eventual-consistency briefly served a shorter snapshot between polls.
        Without the cursor clamp, poll 3 would re-emit lines already streamed in poll 1.
        """
        captured: list[str] = []
        # Poll 1: 5 lines visible, all streamed.
        cursor = _stream_new_lines("a\nb\nc\nd\ne", printed_lines=0, output_fn=captured.append, verbose=True)
        assert captured == ["a", "b", "c", "d", "e"]
        # Poll 2: S3 regressed to 3 lines. Cursor must stay at 5 so poll 3 doesn't re-stream.
        cursor = _stream_new_lines("a\nb\nc", printed_lines=cursor, output_fn=captured.append, verbose=True)
        # Poll 3: S3 grew to 7 lines. Only the two genuinely new ones should stream.
        _stream_new_lines("a\nb\nc\nd\ne\nf\ng", printed_lines=cursor, output_fn=captured.append, verbose=True)
        assert captured == ["a", "b", "c", "d", "e", "f", "g"]
