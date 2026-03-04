from unittest.mock import MagicMock, patch

from django.test import TestCase

from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler


class TestSlackThreadHandler(TestCase):
    @patch.object(SlackThreadHandler, "_find_progress_message_ts", return_value=None)
    @patch.object(SlackThreadHandler, "_get_client")
    def test_progress_message_has_no_terminate_button(self, mock_get_client, _mock_find_progress):
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

        handler.post_or_update_progress("In progress...", task_url="https://example.com/task")

        mock_client.chat_postMessage.assert_called_once()
        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        actions = blocks[1]["elements"]

        assert len(actions) == 1
        assert actions[0]["text"]["text"] == "View agent logs"

    @patch.object(SlackThreadHandler, "_find_progress_message_ts", return_value="1234.9999")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_delete_progress_deletes_message(self, mock_get_client, _mock_find_progress):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        context = SlackThreadContext(
            integration_id=1,
            channel="C001",
            thread_ts="1234.5678",
        )
        handler = SlackThreadHandler(context)
        handler.delete_progress()

        mock_client.chat_delete.assert_called_once_with(channel="C001", ts="1234.9999")

    @patch.object(SlackThreadHandler, "_find_progress_message_ts", return_value=None)
    @patch.object(SlackThreadHandler, "_get_client")
    def test_delete_progress_noop_when_no_message(self, mock_get_client, _mock_find_progress):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        context = SlackThreadContext(
            integration_id=1,
            channel="C001",
            thread_ts="1234.5678",
        )
        handler = SlackThreadHandler(context)
        handler.delete_progress()

        mock_client.chat_delete.assert_not_called()

    @patch.object(SlackThreadHandler, "_get_client")
    def test_update_reaction_removes_seedling_and_eyes(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        context = SlackThreadContext(
            integration_id=1,
            channel="C001",
            thread_ts="1234.5678",
            user_message_ts="1234.5678",
        )
        handler = SlackThreadHandler(context)
        handler.update_reaction("white_check_mark")

        remove_calls = mock_client.reactions_remove.call_args_list
        assert len(remove_calls) == 2
        assert remove_calls[0].kwargs["name"] == "seedling"
        assert remove_calls[1].kwargs["name"] == "eyes"
        mock_client.reactions_add.assert_called_once_with(
            channel="C001", timestamp="1234.5678", name="white_check_mark"
        )

    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_pr_opened_posts_buttons(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        context = SlackThreadContext(
            integration_id=1,
            channel="C001",
            thread_ts="1234.5678",
            mentioning_slack_user_id="U123",
        )
        handler = SlackThreadHandler(context)

        handler.post_pr_opened("https://github.com/org/repo/pull/1", "https://posthog.com/task/1")

        mock_client.chat_postMessage.assert_called_once()
        kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C001"
        assert kwargs["thread_ts"] == "1234.5678"
        assert "Pull request opened" in kwargs["text"]
        actions = kwargs["blocks"][1]["elements"]
        assert actions[0]["text"]["text"] == "View PR"
        assert actions[1]["text"]["text"] == "Open in PostHog"
