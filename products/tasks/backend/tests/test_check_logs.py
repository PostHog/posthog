import json
from dataclasses import dataclass

from unittest.mock import patch

from products.tasks.backend.services.custom_prompt_runner import _check_logs


def _agent_message_line(text: str) -> str:
    return json.dumps(
        {
            "notification": {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message",
                        "content": {"type": "text", "text": text},
                    }
                },
            }
        }
    )


def _end_turn_line() -> str:
    return json.dumps({"notification": {"result": {"stopReason": "end_turn"}}})


def _user_message_line(text: str) -> str:
    return json.dumps(
        {
            "notification": {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "user_message",
                        "content": {"type": "text", "text": text},
                    }
                },
            }
        }
    )


@dataclass
class FakeTaskRun:
    log_url: str = "s3://fake/log"


class TestCheckLogs:
    def test_returns_agent_message_when_both_present(self):
        log = "\n".join([_agent_message_line("hello"), _end_turn_line()])
        with patch("posthog.storage.object_storage.read", return_value=log):
            finished, text, _, _ = _check_logs(FakeTaskRun())
        assert finished is True
        assert text == "hello"

    def test_end_turn_without_agent_message_does_not_rescan_previous_turn(self):
        """Regression: when skip_lines puts us past the agent_message but end_turn
        is in the new lines, _check_logs must NOT rescan from 0 and return a
        stale message from a previous turn."""
        turn_1 = [_agent_message_line("turn-1-response"), _end_turn_line()]
        turn_2_prompt = [_user_message_line("next question")]
        # end_turn for turn 2 arrived, but agent_message hasn't yet
        turn_2_partial = [_end_turn_line()]

        log = "\n".join(turn_1 + turn_2_prompt + turn_2_partial)
        skip = len(turn_1) + len(turn_2_prompt)

        with patch("posthog.storage.object_storage.read", return_value=log):
            finished, text, _, total = _check_logs(FakeTaskRun(), skip_lines=skip)

        # Must report "not finished" so the polling loop retries
        assert finished is False
        assert text is None
        assert total == len(turn_1) + len(turn_2_prompt) + len(turn_2_partial)

    def test_skip_lines_returns_only_new_agent_message(self):
        turn_1 = [_agent_message_line("old"), _end_turn_line()]
        turn_2 = [_user_message_line("prompt"), _agent_message_line("new"), _end_turn_line()]

        log = "\n".join(turn_1 + turn_2)
        skip = len(turn_1)

        with patch("posthog.storage.object_storage.read", return_value=log):
            finished, text, _, _ = _check_logs(FakeTaskRun(), skip_lines=skip)

        assert finished is True
        assert text == "new"
