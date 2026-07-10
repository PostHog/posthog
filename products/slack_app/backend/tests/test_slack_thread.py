from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.slack_app.backend.slack_thread import (
    UPSTREAM_PROVIDER_FAILURE_MESSAGE,
    SlackThreadContext,
    SlackThreadHandler,
    _format_task_error,
)


class TestSlackThreadHandler(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty", "", "Unknown error"),
            ("whitespace", "   ", "Unknown error"),
            ("passthrough", "Internal error: something else", "Internal error: something else"),
            ("stripped_passthrough", "  Internal error: something else  ", "Internal error: something else"),
            ("rate_limit", "Internal error: API Error: 429 rate_limit_error", UPSTREAM_PROVIDER_FAILURE_MESSAGE),
            ("overloaded", "Internal error: API Error: 529 overloaded_error", UPSTREAM_PROVIDER_FAILURE_MESSAGE),
            ("server_error", "Internal error: API Error: 500 internal_error", UPSTREAM_PROVIDER_FAILURE_MESSAGE),
        ]
    )
    def test_format_task_error(self, _name: str, error: str, expected: str) -> None:
        assert _format_task_error(error) == expected

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

        handler.post_or_update_progress(
            "In progress...", task_url="https://us.posthog.com/project/1/tasks/abc?runId=xyz"
        )

        mock_client.chat_postMessage.assert_called_once()
        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        actions = blocks[1]["elements"]

        assert len(actions) == 1
        assert actions[0]["text"]["text"] == "View agent logs"
        assert actions[0]["url"] == "https://us.posthog.com/project/1/tasks/abc?runId=xyz"

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
    def test_update_reaction_removes_eyes_then_adds_new(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        context = SlackThreadContext(
            integration_id=1,
            channel="C001",
            thread_ts="1234.5678",
            user_message_ts="1234.5678",
        )
        handler = SlackThreadHandler(context)
        handler.update_reaction("hedgehog")

        remove_calls = mock_client.reactions_remove.call_args_list
        assert len(remove_calls) == 1
        assert remove_calls[0].kwargs["name"] == "eyes"
        mock_client.reactions_add.assert_called_once_with(channel="C001", timestamp="1234.5678", name="hedgehog")

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

    @patch.object(SlackThreadHandler, "_find_progress_message_ts", return_value=None)
    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_error_formats_upstream_provider_failure(self, mock_get_client, _mock_find_progress):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        context = SlackThreadContext(
            integration_id=1,
            channel="C001",
            thread_ts="1234.5678",
        )
        handler = SlackThreadHandler(context)

        handler.post_error(
            'Internal error: API Error: 529 {"error":{"message":"{\\"type\\":\\"error\\",\\"error\\":{\\"type\\":\\"overloaded_error\\"}}"}}',
            "https://posthog.com/task/1",
        )

        mock_client.chat_postMessage.assert_called_once()
        kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert kwargs["text"] == f"*Task Failed* :x:\n{UPSTREAM_PROVIDER_FAILURE_MESSAGE}"
        assert kwargs["blocks"][1]["text"]["text"] == UPSTREAM_PROVIDER_FAILURE_MESSAGE
        assert "retry" in kwargs["blocks"][2]["text"]["text"]

    @patch.object(SlackThreadHandler, "_find_progress_message_ts", return_value=None)
    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_error_includes_custom_recovery_hint(self, mock_get_client, _mock_find_progress):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(SlackThreadContext(integration_id=1, channel="C001", thread_ts="1234.5678"))

        handler.post_error(
            "No connected GitHub account", task_url=None, recovery_hint="Connect GitHub, then reply here."
        )

        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        assert blocks[2]["text"]["text"] == "Connect GitHub, then reply here."


def _action_blocks(call_kwargs: dict) -> list[dict]:
    return [block for block in call_kwargs["blocks"] if block.get("type") == "actions"]


def _button_texts(action_block: dict) -> list[str]:
    return [element["text"]["text"] for element in action_block["elements"]]


class TestSlackThreadHandlerWithoutTaskUrl(SimpleTestCase):
    """A ``task_url=None`` payload signals the recipient does not have PostHog Code access.

    Each renderer must drop the PostHog button (or the entire actions block when
    that was the only button) so the message stays useful without dangling at a
    URL the recipient can't reach.
    """

    def _make_context(self) -> SlackThreadContext:
        return SlackThreadContext(
            integration_id=1,
            channel="C001",
            thread_ts="1234.5678",
            user_message_ts="1234.5678",
            mentioning_slack_user_id="U123",
        )

    @patch.object(SlackThreadHandler, "_find_progress_message_ts", return_value=None)
    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_or_update_progress_without_task_url_drops_button(self, mock_get_client, _mock_find_progress):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(self._make_context())

        handler.post_or_update_progress("Building", task_url=None)

        mock_client.chat_postMessage.assert_called_once()
        assert _action_blocks(mock_client.chat_postMessage.call_args.kwargs) == []

    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_pr_opened_without_task_url_keeps_pr_button(self, mock_get_client, _mock_delete_progress):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(self._make_context())

        handler.post_pr_opened("https://github.com/org/repo/pull/1", task_url=None)

        mock_client.chat_postMessage.assert_called_once()
        actions = _action_blocks(mock_client.chat_postMessage.call_args.kwargs)
        assert len(actions) == 1
        assert _button_texts(actions[0]) == ["View PR"]

    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_completion_without_task_url_drops_actions(self, mock_get_client, _mock_delete_progress):
        # The PR-bearing completion case routes through ``post_pr_opened`` via
        # the activity-level dedupe helper, so ``post_completion`` only handles
        # the no-PR terminal state and never carries a View PR button.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(self._make_context())

        handler.post_completion(task_url=None)

        mock_client.chat_postMessage.assert_called_once()
        assert _action_blocks(mock_client.chat_postMessage.call_args.kwargs) == []

    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_error_without_task_url_drops_actions(self, mock_get_client, _mock_delete_progress):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(self._make_context())

        handler.post_error("boom", task_url=None)

        mock_client.chat_postMessage.assert_called_once()
        kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert _action_blocks(kwargs) == []
        # The error body itself must still surface — only the action block is gated.
        assert kwargs["blocks"][1]["text"]["text"] == "boom"

    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_cancelled_without_task_url_drops_actions(self, mock_get_client, _mock_delete_progress):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(self._make_context())

        handler.post_cancelled(task_url=None)

        mock_client.chat_postMessage.assert_called_once()
        assert _action_blocks(mock_client.chat_postMessage.call_args.kwargs) == []


class TestPostPrOpenedReplyTarget(SimpleTestCase):
    """``post_pr_opened`` no longer owns the mention-target decision — the
    caller resolves the Slack user id and passes it in. The handler just
    embeds it (or omits the prefix entirely when it's ``None``).
    """

    def _context(self) -> SlackThreadContext:
        return SlackThreadContext(integration_id=1, channel="C001", thread_ts="1.0")

    @parameterized.expand(
        [
            ("explicit_actor_tags_them", "ULATEST", "<@ULATEST> *Pull request opened* :rocket:"),
            ("none_means_no_tag", None, "*Pull request opened* :rocket:"),
        ]
    )
    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_pr_opened_uses_caller_supplied_target(
        self,
        _name: str,
        reply_target: str | None,
        expected_text_start: str,
        mock_get_client,
        _mock_delete_progress,
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(self._context())

        handler.post_pr_opened(
            "https://github.com/org/repo/pull/1",
            task_url=None,
            reply_target_slack_user_id=reply_target,
        )

        kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert kwargs["text"].startswith(expected_text_start)
