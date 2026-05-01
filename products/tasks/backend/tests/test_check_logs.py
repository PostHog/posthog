from unittest.mock import patch

from products.tasks.backend.services.custom_prompt_runner import _check_logs, _stream_new_lines
from products.tasks.backend.tests.agent_log_fixtures import (
    FakeTaskRun,
    _agent_message_line,
    _end_turn_line,
    _usage_update_line,
    _user_message_line,
)


class TestCheckLogs:
    def test_returns_agent_message_when_both_present(self):
        log = "\n".join([_agent_message_line("hello"), _end_turn_line()])
        with patch("posthog.storage.object_storage.read", return_value=log):
            finished, text, _, _, empty_end_turn = _check_logs(FakeTaskRun())
        assert finished is True
        assert text == "hello"
        assert empty_end_turn is False

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
            finished, text, _, total, empty_end_turn = _check_logs(FakeTaskRun(), skip_lines=skip)

        assert finished is False
        assert text is None
        assert empty_end_turn is True
        assert total == len(turn_1) + len(turn_2_prompt) + len(turn_2_partial)

    def test_skip_lines_returns_only_new_agent_message(self):
        turn_1 = [_agent_message_line("old"), _end_turn_line()]
        turn_2 = [_user_message_line("prompt"), _agent_message_line("new"), _end_turn_line()]

        log = "\n".join(turn_1 + turn_2)
        skip = len(turn_1)

        with patch("posthog.storage.object_storage.read", return_value=log):
            finished, text, _, _, empty_end_turn = _check_logs(FakeTaskRun(), skip_lines=skip)

        assert finished is True
        assert text == "new"
        assert empty_end_turn is False

    def test_empty_log_returns_all_defaults(self):
        with patch("posthog.storage.object_storage.read", return_value=""):
            finished, text, full_log, total, empty_end_turn = _check_logs(FakeTaskRun())
        assert (finished, text, full_log, total, empty_end_turn) == (False, None, None, 0, False)

    def test_no_new_lines_since_skip_does_not_flag_empty(self):
        """Eventual-consistency case: S3 hasn't caught up yet, no new data to parse."""
        turn_1 = [_agent_message_line("x"), _end_turn_line()]
        log = "\n".join(turn_1)
        with patch("posthog.storage.object_storage.read", return_value=log):
            finished, text, _, total, empty_end_turn = _check_logs(FakeTaskRun(), skip_lines=len(turn_1))
        assert finished is False
        assert text is None
        assert empty_end_turn is False
        assert total == len(turn_1)

    def test_empty_end_turn_flagged_on_first_turn_too(self):
        """SDK short-circuit on the very first turn must surface as empty_end_turn too.
        Otherwise run_prompt / MultiTurnSession.start silently poll until timeout."""
        log = "\n".join([_end_turn_line()])
        with patch("posthog.storage.object_storage.read", return_value=log):
            finished, text, _, _, empty_end_turn = _check_logs(FakeTaskRun(), skip_lines=0)
        assert finished is False
        assert text is None
        assert empty_end_turn is True

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
            finished, text, _, _, empty_end_turn = _check_logs(FakeTaskRun(), skip_lines=len(turn_1))

        assert finished is False
        assert text is None
        assert empty_end_turn is True


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
