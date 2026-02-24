import json

from unittest.mock import MagicMock, patch

from django.test import TestCase

from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler


class TestSlackThreadHandler(TestCase):
    @patch.object(SlackThreadHandler, "_find_progress_message_ts", return_value=None)
    @patch.object(SlackThreadHandler, "_get_client")
    def test_progress_message_includes_terminate_button(self, mock_get_client, _mock_find_progress):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        context = SlackThreadContext(
            integration_id=1,
            channel="C001",
            thread_ts="1234.5678",
            user_message_ts="1234.5678",
            mentioning_slack_user_id="U123",
        )
        handler = SlackThreadHandler(context)

        handler.post_or_update_progress("In progress...", task_url="https://example.com/task", run_id="run-1")

        mock_client.chat_postMessage.assert_called_once()
        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        actions = blocks[1]["elements"]

        assert len(actions) == 2
        assert actions[0]["text"]["text"] == "View agent logs"
        assert actions[1]["action_id"] == "twig_terminate_task"
        assert actions[1]["style"] == "danger"

        value = json.loads(actions[1]["value"])
        assert value["run_id"] == "run-1"
        assert value["integration_id"] == 1
        assert value["mentioning_slack_user_id"] == "U123"
        assert value["thread_ts"] == "1234.5678"
