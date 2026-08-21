from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration

from products.slack_app.backend.services.slack_messages import RunFooter
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

    @patch.object(SlackThreadHandler, "_get_client")
    def test_stop_status_stream_posts_labeled_mention_as_bare(self, mock_get_client):
        # The streaming path posts the agent's final answer, which can echo a participant in
        # the labeled `<@U…|display name>` form. A name with a space renders as inert text when
        # a bot posts it, so it must be normalized to the bare `<@U…>` that actually notifies.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        context = SlackThreadContext(
            integration_id=1,
            channel="C001",
            thread_ts="1234.5678",
            mentioning_slack_user_id="U123",
        )
        handler = SlackThreadHandler(context)

        handler.stop_status_stream(ts="1234.9999", final_markdown="Answering <@U094TR1E59V|Radu Raicea> now.")

        chunks = mock_client.chat_appendStream.call_args.kwargs["chunks"]
        streamed = "".join(chunk.get("text", "") for chunk in chunks)
        assert "<@U094TR1E59V>" in streamed
        assert "Radu Raicea" not in streamed

    @patch.object(SlackThreadHandler, "_find_progress_message_ts", return_value=None)
    @patch.object(SlackThreadHandler, "_get_client")
    def test_progress_message_carries_only_the_logs_button(self, mock_get_client, _mock_find_progress):
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
    """A ``task_url=None`` payload signals the recipient does not have PostHog Desktop access.

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


class TestPostPrOpenedPersonalGithubHint(SimpleTestCase):
    @parameterized.expand([("bot_authored", True, True), ("user_authored", False, False)])
    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "_get_integration", return_value=Integration(team_id=7))
    @patch.object(SlackThreadHandler, "_get_client")
    def test_only_a_bot_authored_pr_asks_for_a_personal_github(
        self,
        _name: str,
        bot_authored: bool,
        expect_hint: bool,
        mock_get_client,
        _mock_get_integration,
        _mock_delete_progress,
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(SlackThreadContext(integration_id=1, channel="C001", thread_ts="1.0"))

        handler.post_pr_opened(
            "https://github.com/org/repo/pull/1",
            task_url=None,
            bot_authored=bot_authored,
        )

        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        contexts = [b for b in blocks if b["type"] == "context"]
        assert bool(contexts) is expect_hint
        if expect_hint:
            text = contexts[0]["elements"][0]["text"]
            assert "/project/7/settings/user-personal-integrations|Connect your GitHub>" in text


class TestReplyFooterGate(SimpleTestCase):
    def _handler(self, footer: RunFooter | None = None) -> SlackThreadHandler:
        context = SlackThreadContext(
            integration_id=1,
            channel="C001",
            thread_ts="1234.5678",
            mentioning_slack_user_id="U123",
        )
        return SlackThreadHandler(context, footer or RunFooter(model="claude-opus-5"))

    @parameterized.expand([("withheld", False), ("granted", True)])
    @patch("products.slack_app.backend.slack_thread.is_slack_app_home_enabled", return_value=True)
    @patch("products.slack_app.backend.slack_thread.is_slack_app_model_classifier_enabled", return_value=True)
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_withholding_the_links_still_leaves_the_model_and_configure(
        self,
        _name: str,
        code_access: bool,
        mock_get_client,
        mock_get_integration,
        _mock_flag,
        _mock_home,
    ) -> None:
        # Whether this reader can open a task page changes which segments render, never
        # whether the line appears: the model and the way to change it are theirs either way.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(config={"app_id": "A1"}, integration_id="T1")
        footer = RunFooter(
            task_url="https://app/project/1/tasks/t",
            desktop_url="https://us.posthog.com/code/task/t",
            model="claude-opus-5",
        )

        with patch.object(SlackThreadHandler, "viewer_can_open_code_links", return_value=code_access):
            self._handler(footer).post_thread_message("the answer", with_footer=True)

        line = mock_client.chat_postMessage.call_args.kwargs["blocks"][-1]["elements"][0]["text"]
        assert "*Claude Opus 5*" in line
        assert "|Configure>" in line
        assert ("View on web" in line) is code_access
        assert ("View on desktop" in line) is code_access

    @parameterized.expand([("off", False, False), ("on", True, True)])
    @patch("products.slack_app.backend.slack_thread.is_slack_app_home_enabled", return_value=False)
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_streamed_reply_carries_the_footer_only_inside_the_rollout(
        self,
        _name: str,
        flag_enabled: bool,
        expected: bool,
        mock_get_client,
        mock_get_integration,
        _mock_home_enabled,
    ) -> None:
        # Losing this gate would put the footer under every workspace's replies at once.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(config={}, integration_id="T1")

        with patch(
            "products.slack_app.backend.slack_thread.is_slack_app_model_classifier_enabled",
            return_value=flag_enabled,
        ):
            self._handler().stop_status_stream(ts="1.0", final_markdown="Done.")

        chunks = mock_client.chat_appendStream.call_args.kwargs["chunks"]
        # The footer rides as a `blocks` chunk: a `context` block is the only muted text,
        # and Slack's streamed markdown_text has no equivalent.
        assert any(chunk.get("type") == "blocks" for chunk in chunks) is expected


class TestFooterNeverCostsTheAnswer(SimpleTestCase):
    @patch("products.slack_app.backend.slack_thread.is_slack_app_home_enabled", return_value=False)
    @patch("products.slack_app.backend.slack_thread.is_slack_app_model_classifier_enabled", return_value=True)
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_a_rejected_footer_reposts_the_answer_as_plain_text(
        self, mock_get_client, mock_get_integration, _mock_flag, _mock_home
    ) -> None:
        # Slack fails the whole request when blocks are invalid — the text fallback does
        # not rescue it — so without this the reader loses the answer, not just its footer.
        mock_client = MagicMock()
        mock_client.chat_postMessage.side_effect = [
            SlackApiError("invalid_blocks", {"error": "invalid_blocks"}),
            MagicMock(),
        ]
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(config={}, integration_id="T1")
        context = SlackThreadContext(integration_id=1, channel="C001", thread_ts="1234.5678")

        SlackThreadHandler(context, RunFooter(model="claude-opus-5")).post_thread_message(
            "the answer", with_footer=True
        )

        assert mock_client.chat_postMessage.call_count == 2
        retry = mock_client.chat_postMessage.call_args_list[1].kwargs
        assert retry["text"] == "the answer"
        assert not retry.get("blocks")


class TestRelayedAnswerFooter(SimpleTestCase):
    def _handler(self, footer: RunFooter) -> SlackThreadHandler:
        context = SlackThreadContext(integration_id=1, channel="C001", thread_ts="1234.5678")
        return SlackThreadHandler(context, footer)

    @parameterized.expand(
        [
            ("final_chunk_with_model", RunFooter(model="claude-opus-5"), True, True),
            ("final_chunk_nothing_to_say", RunFooter(), True, False),
            ("earlier_chunk", RunFooter(model="claude-opus-5"), False, False),
        ]
    )
    @patch("products.slack_app.backend.slack_thread.is_slack_app_home_enabled", return_value=False)
    @patch("products.slack_app.backend.slack_thread.is_slack_app_model_classifier_enabled", return_value=True)
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_footer_rides_the_last_chunk_only(
        self,
        _name: str,
        footer: RunFooter,
        with_footer: bool,
        expected: bool,
        mock_get_client,
        mock_get_integration,
        _mock_flag,
        _mock_home,
    ) -> None:
        # A non-streamed answer is split only to fit Slack's length cap, so a footer on
        # any chunk but the last would appear mid-answer.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(config={}, integration_id="T1")

        self._handler(footer).post_thread_message("the answer", with_footer=with_footer)

        kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert kwargs["text"] == "the answer"
        # Without a footer the message carries no blocks, staying the plain-text post it
        # has always been.
        assert bool(kwargs.get("blocks")) is expected
        if expected:
            assert kwargs["blocks"][-1]["type"] == "context"
            # A section collapses behind "Show more" unless it is told to expand.
            assert kwargs["blocks"][0]["expand"] is True


class TestDeletedTriggerMessage(SimpleTestCase):
    """A run whose prompt has been deleted has nobody left to answer, so it says nothing."""

    def setUp(self) -> None:
        cache.clear()

    def tearDown(self) -> None:
        cache.clear()

    def _handler(self) -> SlackThreadHandler:
        return SlackThreadHandler(
            SlackThreadContext(
                integration_id=1,
                channel="C_DELETED",
                thread_ts="1700000000.000100",
                mentioning_slack_user_id="U123",
            )
        )

    @parameterized.expand(
        [
            ("relayed_answer", lambda h: h.post_thread_message("here is the answer")),
            ("completion_card", lambda h: h.post_completion(task_url=None)),
            ("failure_card", lambda h: h.post_error("boom", task_url=None)),
            ("progress_update", lambda h: h.post_or_update_progress("planning")),
        ]
    )
    @patch.object(SlackThreadHandler, "_find_progress_message_ts", return_value=None)
    @patch.object(SlackThreadHandler, "_get_client")
    def test_nothing_is_posted_once_the_prompt_is_deleted(
        self, _name, post, mock_get_client, _mock_find_progress
    ) -> None:
        mock_client = MagicMock()
        mock_client.conversations_history.return_value = {"messages": []}
        mock_get_client.return_value = mock_client

        post(self._handler())

        mock_client.chat_postMessage.assert_not_called()

    @patch.object(SlackThreadHandler, "_get_client")
    def test_status_stream_does_not_start_for_a_deleted_prompt(self, mock_get_client) -> None:
        mock_client = MagicMock()
        mock_client.conversations_history.return_value = {"messages": []}
        mock_get_client.return_value = mock_client

        assert self._handler().start_status_stream(first_markdown_text="thinking") is None

        mock_client.chat_startStream.assert_not_called()


class TestForkMenuOnReplies(SimpleTestCase):
    """Where the fork menu attaches, on the plain-post path."""

    def _handler(self) -> SlackThreadHandler:
        context = SlackThreadContext(
            integration_id=1,
            channel="C001",
            thread_ts="1234.5678",
            mentioning_slack_user_id="U123",
        )
        return SlackThreadHandler(context, RunFooter(model="claude-opus-5"))

    @patch("products.slack_app.backend.slack_thread.is_slack_app_forking_enabled", return_value=True)
    @patch("products.slack_app.backend.slack_thread.is_slack_app_home_enabled", return_value=True)
    @patch("products.slack_app.backend.slack_thread.is_slack_app_model_classifier_enabled", return_value=True)
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_non_streamed_answer_hangs_the_menu_off_the_answer_not_the_footer(
        self, mock_get_client, mock_get_integration, _flag, _home, _forking
    ) -> None:
        # Hanging it off the answer's section buys both things the footer alone cannot
        # give: no extra line, and a footer that stays muted. A context block rejects
        # interactive elements, so a footer carrying the menu would have to be a section
        # and would render at body weight.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(id=7, config={"app_id": "A1"}, integration_id="T1")

        self._handler().post_thread_message("the answer", with_footer=True)

        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        assert len(blocks) == 2
        # The menu hangs off the answer, so it costs no line…
        assert blocks[0]["accessory"]["type"] == "overflow"
        # …and the footer stays a context block, which is the only muted text Block Kit has.
        assert blocks[1]["type"] == "context"

    @patch("products.slack_app.backend.slack_thread.is_slack_app_forking_enabled", return_value=False)
    @patch("products.slack_app.backend.slack_thread.is_slack_app_home_enabled", return_value=True)
    @patch("products.slack_app.backend.slack_thread.is_slack_app_model_classifier_enabled", return_value=True)
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_outside_the_rollout_the_footer_closes_the_message(
        self, mock_get_client, mock_get_integration, _flag, _home, _forking
    ) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(id=7, config={"app_id": "A1"}, integration_id="T1")

        self._handler().post_thread_message("the answer", with_footer=True)

        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        assert blocks[-1]["type"] == "context"
        assert "accessory" not in blocks[0]
