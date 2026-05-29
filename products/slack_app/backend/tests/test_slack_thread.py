from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from products.slack_app.backend.slack_thread import (
    RANDOM_ACK_EMOJIS,
    UPSTREAM_PROVIDER_FAILURE_MESSAGE,
    SlackThreadContext,
    SlackThreadHandler,
    _format_task_error,
    ack_emoji_for,
    stale_ack_emojis_for,
)


class TestSlackThreadHandler(TestCase):
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

        handler.post_or_update_progress("In progress...", task_url="posthog-code://task/abc/run/xyz")

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
    def test_update_reaction_clears_stale_ack_emojis(self, mock_get_client):
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

        removed_names = [call.kwargs["name"] for call in mock_client.reactions_remove.call_args_list]
        # Only the candidate ack reactions for this specific ts are removed (not the whole pool),
        # so cleanup stays cheap regardless of pool size.
        assert removed_names == list(stale_ack_emojis_for("1234.5678"))
        mock_client.reactions_add.assert_called_once_with(channel="C001", timestamp="1234.5678", name="hedgehog")

    def test_ack_emoji_for_is_deterministic_per_ts(self):
        # Same ts must always pick the same emoji — activity retries depend on this for
        # `_safe_react`'s `already_reacted` short-circuit to keep the ack idempotent.
        assert ack_emoji_for("1700000001.000100") == ack_emoji_for("1700000001.000100")
        assert ack_emoji_for("1700000001.000100") in RANDOM_ACK_EMOJIS
        # Different ts values should reach across the pool (sanity check, not a uniformity claim).
        reached = {ack_emoji_for(f"1700000000.{i:06d}") for i in range(500)}
        assert len(reached) >= len(RANDOM_ACK_EMOJIS) // 2

    def test_stale_ack_emojis_for_includes_legacy_seedling_and_eyes(self):
        # `seedling` was the fixed pre-pool ack; tasks ack'd before this code shipped
        # must still be cleanable. `eyes` is the follow-up ack.
        stale = stale_ack_emojis_for("1234.5678")
        assert "eyes" in stale
        assert "seedling" in stale
        assert ack_emoji_for("1234.5678") in stale

    def test_stale_ack_emojis_for_dedupes_when_pick_is_seedling(self):
        # `seedling` is both in the pool and the legacy ack — when the deterministic
        # pick coincidentally lands on it, the tuple should not contain a duplicate.
        seedling_ts = "1700000000.000005"
        assert ack_emoji_for(seedling_ts) == "seedling", "fixture ts no longer maps to seedling"
        stale = stale_ack_emojis_for(seedling_ts)
        assert stale == ("eyes", "seedling")
        assert stale.count("seedling") == 1

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
        assert actions[1]["text"]["text"] == "Open in PostHog Code"

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


def _action_blocks(call_kwargs: dict) -> list[dict]:
    return [block for block in call_kwargs["blocks"] if block.get("type") == "actions"]


def _button_texts(action_block: dict) -> list[str]:
    return [element["text"]["text"] for element in action_block["elements"]]


class TestSlackThreadHandlerWithoutTaskUrl(TestCase):
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
    def test_post_pr_opened_sandbox_cleaned_without_task_url_keeps_pr_button(
        self, mock_get_client, _mock_delete_progress
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(self._make_context())

        handler.post_pr_opened_sandbox_cleaned("https://github.com/org/repo/pull/1", task_url=None)

        mock_client.chat_postMessage.assert_called_once()
        actions = _action_blocks(mock_client.chat_postMessage.call_args.kwargs)
        assert len(actions) == 1
        assert _button_texts(actions[0]) == ["View PR"]

    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_pr_opened_without_task_url_keeps_pr_button(self, mock_get_client):
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
    def test_post_completion_without_task_url_keeps_pr_button(self, mock_get_client, _mock_delete_progress):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(self._make_context())

        handler.post_completion("https://github.com/org/repo/pull/1", task_url=None)

        mock_client.chat_postMessage.assert_called_once()
        actions = _action_blocks(mock_client.chat_postMessage.call_args.kwargs)
        assert len(actions) == 1
        assert _button_texts(actions[0]) == ["View PR"]

    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_completion_without_pr_or_task_url_drops_actions(self, mock_get_client, _mock_delete_progress):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(self._make_context())

        handler.post_completion(pr_url=None, task_url=None)

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
