from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
from posthog.slack.markdown import SLACK_MARKDOWN_TEXT_MAX_LEN

from products.slack_app.backend.services.slack_messages import RunFooter
from products.slack_app.backend.slack_thread import (
    UPSTREAM_PROVIDER_FAILURE_MESSAGE,
    SlackThreadContext,
    SlackThreadHandler,
    _format_task_error,
)


def _streamed_text(mock_client: MagicMock) -> str:
    return "".join(
        chunk.get("text", "")
        for call in mock_client.chat_appendStream.call_args_list
        for chunk in call.kwargs["chunks"]
    )


class TestSlackThreadHandler(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty", "", "Unknown error"),
            ("whitespace", "   ", "Unknown error"),
            ("passthrough", "Internal error: something else", "Internal error: something else"),
            ("stripped_passthrough", "  Internal error: something else  ", "Internal error: something else"),
            ("rate_limit", "Internal error: API Error: 429 rate_limit_error", UPSTREAM_PROVIDER_FAILURE_MESSAGE),
            (
                "task_spend_limit",
                "Internal error: API Error: 429 Rate limit exceeded: This agent run reached its spend limit. Try again in about 24 hours.",
                "Internal error: API Error: 429 Rate limit exceeded: This agent run reached its spend limit. Try again in about 24 hours.",
            ),
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

        streamed = _streamed_text(mock_client)
        assert "<@U094TR1E59V>" in streamed
        assert "Radu Raicea" not in streamed

    @patch.object(SlackThreadHandler, "_get_client")
    def test_stop_status_stream_skips_trailing_mention_when_answer_mentions_recipient(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        context = SlackThreadContext(
            integration_id=1, channel="C001", thread_ts="1234.5678", mentioning_slack_user_id="U123"
        )

        SlackThreadHandler(context).stop_status_stream(ts="1234.9999", final_markdown="Done, <@U123|Jane Doe>.")

        assert _streamed_text(mock_client).count("<@U123>") == 1

    @parameterized.expand(
        [
            ("thread_creator", None, "Signups grew.", "U123", "<@U123> Signups grew."),
            # A later participant asked this turn, so the reply is for them, not the thread's creator.
            ("follow_up_sender", "U456", "Signups grew.", "U456", "<@U456> Signups grew."),
            # Markdown reads a heading only at the start of a line.
            ("heading_answer", None, "## Signups\nThey grew.", "U123", "<@U123>\n\n## Signups\nThey grew."),
        ]
    )
    @patch("products.slack_app.backend.slack_thread.slack_message_exists", return_value=True)
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_start_status_stream_leads_an_answer_with_the_mention(
        self, _name, actor, answer, expected_recipient, expected_text, mock_get_client, _mock_integration, _exists
    ):
        # An answer that opens the stream is the whole reply, so it carries the one ping.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        context = SlackThreadContext(
            integration_id=1, channel="C001", thread_ts="1234.5678", mentioning_slack_user_id="U123"
        )

        SlackThreadHandler(context, actor_slack_user_id=actor).start_status_stream(first_markdown_text=answer)

        kwargs = mock_client.chat_startStream.call_args.kwargs
        assert kwargs["recipient_user_id"] == expected_recipient
        assert [chunk.get("text") for chunk in kwargs["chunks"]] == [expected_text]

    @parameterized.expand(
        [
            ("answer", "Signups grew.", False, None, ["plan_update", "<@U123> Signups grew.", "blocks"]),
            # The answer went out when the stream opened, and carried the mention there.
            ("answer_streamed_at_start", None, True, None, ["plan_update", "blocks"]),
            # A stopped run has no answer, so the mention alone notifies the requester.
            ("no_answer", None, False, None, ["plan_update", "blocks", "\n\n<@U123>"]),
            ("follow_up_no_answer", None, False, "U456", ["plan_update", "blocks", "\n\n<@U456>"]),
        ]
    )
    @patch.object(SlackThreadHandler, "_get_client")
    def test_stop_status_stream_mentions_the_requester_once_before_the_answer(
        self, _name, final_markdown, mention_sent, actor, expected_order, mock_get_client
    ):
        # Chart cards describe the answer above them, and the reply pings the requester once.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        context = SlackThreadContext(
            integration_id=1, channel="C001", thread_ts="1234.5678", mentioning_slack_user_id="U123"
        )
        handler = SlackThreadHandler(context, actor_slack_user_id=actor)

        def append_attachments() -> None:
            handler.append_status_blocks("1234.9999", [{"type": "image"}])

        handler.stop_status_stream(
            ts="1234.9999",
            final_markdown=final_markdown,
            plan_title="Done",
            append_attachments=append_attachments,
            mention_sent=mention_sent,
        )

        order = [
            chunk.get("text") or chunk["type"]
            for call in mock_client.chat_appendStream.call_args_list
            for chunk in call.kwargs["chunks"]
        ]
        assert order == expected_order

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

    @parameterized.expand(
        [
            ("closed", False, "<@U456> *Pull request closed without merging*", True),
            ("merged", True, "<@U456> *Pull request merged* :tada:", False),
        ]
    )
    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_pr_closed_replies_in_thread_and_keeps_progress(
        self, _name, merged, expected_text, expects_retry_hint, mock_get_client
    ):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        context = SlackThreadContext(integration_id=1, channel="C001", thread_ts="1234.5678")
        handler = SlackThreadHandler(context)

        handler.post_pr_closed(
            "https://github.com/org/repo/pull/1",
            "https://posthog.com/task/1",
            reply_target_slack_user_id="U456",
            merged=merged,
        )

        mock_client.chat_delete.assert_not_called()
        mock_client.chat_postMessage.assert_called_once()
        kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert kwargs["thread_ts"] == "1234.5678"
        assert kwargs["text"] == expected_text
        assert _button_texts(_action_blocks(kwargs)[0]) == ["View PR", "Open in PostHog"]
        assert any(block["type"] == "context" for block in kwargs["blocks"]) == expects_retry_hint

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

    @patch.object(SlackThreadHandler, "_find_progress_message_ts", return_value=None)
    @patch.object(SlackThreadHandler, "_get_client")
    def test_post_or_update_progress_names_the_project_it_runs_against(self, mock_get_client, _mock_find_progress):
        # A task that routed itself to another project says so while it works, not only
        # in the footer of the answer minutes later.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        handler = SlackThreadHandler(
            self._make_context(),
            RunFooter(model="claude-opus-5", reasoning_effort="high", project="Staging"),
        )

        handler.post_or_update_progress("Building", task_url=None)

        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        context_text = next(b["elements"][0]["text"] for b in blocks if b["type"] == "context")
        assert context_text == "*Claude Opus 5* [High] · Project: *Staging*"

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

    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_streamed_reply_carries_the_footer(self, mock_get_client, mock_get_integration) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(config={}, integration_id="T1")

        self._handler().stop_status_stream(ts="1.0", final_markdown="Done.")

        chunks = mock_client.chat_appendStream.call_args.kwargs["chunks"]
        # The footer rides as a `blocks` chunk: a `context` block is the only muted text,
        # and Slack's streamed markdown_text has no equivalent.
        assert any(chunk.get("type") == "blocks" for chunk in chunks)


class TestFooterNeverCostsTheAnswer(SimpleTestCase):
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_a_rejected_footer_reposts_the_answer_as_plain_text(self, mock_get_client, mock_get_integration) -> None:
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


class TestStreamClosedBySlack(SimpleTestCase):
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_the_answer_is_posted_in_the_thread_and_the_closed_stream_gets_nothing_more(
        self, mock_get_client, mock_get_integration
    ) -> None:
        mock_client = MagicMock()
        mock_client.chat_appendStream.side_effect = SlackApiError(
            "message_not_in_streaming_state", {"error": "message_not_in_streaming_state"}
        )
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(id=1, config={}, integration_id="T1")
        context = SlackThreadContext(integration_id=1, channel="C001", thread_ts="1234.5678")
        handler = SlackThreadHandler(context, RunFooter(model="claude-opus-5"), actor_slack_user_id="U123")

        assert (
            handler.append_status_chunks(ts="1.0", task_updates=[{"id": "a", "title": "Read", "status": "in_progress"}])
            is False
        )
        handler.stop_status_stream(ts="1.0", final_markdown="Signups grew.")

        assert mock_client.chat_appendStream.call_count == 1
        mock_client.chat_stopStream.assert_not_called()
        posted = mock_client.chat_postMessage.call_args.kwargs
        assert posted["thread_ts"] == "1234.5678"
        assert "Signups grew." in posted["text"]
        assert posted["text"].startswith("<@U123>")


_STREAM_ENDED = SlackApiError("message_not_in_streaming_state", {"error": "message_not_in_streaming_state"})


def _stop_with_answer(handler: SlackThreadHandler) -> None:
    handler.stop_status_stream(ts="1.0", final_markdown="Done.")


class TestReplyPostedCapture(SimpleTestCase):
    @parameterized.expand(
        [
            ("streamed_answer", None, None, False, _stop_with_answer, ("answer", True)),
            ("closed_stream_answer_reposted", _STREAM_ENDED, None, False, _stop_with_answer, ("answer", True)),
            (
                "closed_stream_repost_fails",
                _STREAM_ENDED,
                RuntimeError("slack down"),
                False,
                _stop_with_answer,
                ("answer", False),
            ),
            (
                "answer_seeded_before_the_stop",
                None,
                None,
                False,
                lambda h: h.stop_status_stream(ts="1.0", mention_sent=True),
                ("answer", True),
            ),
            ("turn_stopped_before_answering", None, None, False, lambda h: h.stop_status_stream(ts="1.0"), None),
            (
                "completion_card",
                None,
                None,
                False,
                lambda h: h.post_completion(task_url=None),
                ("completion", True),
            ),
            (
                "completion_card_fails",
                None,
                RuntimeError("slack down"),
                False,
                lambda h: h.post_completion(task_url=None),
                ("completion", False),
            ),
            (
                "completion_card_for_a_deleted_prompt",
                None,
                None,
                True,
                lambda h: h.post_completion(task_url=None),
                ("completion", False),
            ),
            (
                "error_card",
                None,
                None,
                False,
                lambda h: h.post_error("boom", task_url=None),
                ("error", True),
            ),
        ]
    )
    @patch("products.slack_app.backend.api.resolve_posthog_user_from_event")
    @patch("products.slack_app.backend.services.slack_messages.slack_message_exists")
    @patch("products.slack_app.backend.slack_thread.capture_slack_event")
    @patch.object(SlackThreadHandler, "delete_progress")
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_reply_is_captured_with_its_outcome_and_thread(
        self,
        _name: str,
        append_error: Exception | None,
        post_error: Exception | None,
        prompt_deleted: bool,
        reply,
        expected: tuple[str, bool] | None,
        mock_get_client,
        mock_get_integration,
        _mock_delete_progress,
        mock_capture,
        mock_message_exists,
        mock_resolve_user,
    ) -> None:
        mock_client = MagicMock()
        mock_client.chat_appendStream.side_effect = append_error
        mock_client.chat_postMessage.side_effect = post_error
        mock_get_client.return_value = mock_client
        mock_message_exists.return_value = not prompt_deleted
        integration = Integration(id=1, config={}, integration_id="T1")
        mock_get_integration.return_value = integration
        reader = MagicMock()
        mock_resolve_user.return_value = reader
        context = SlackThreadContext(integration_id=1, channel="C001", thread_ts="1234.5678")
        handler = SlackThreadHandler(context, RunFooter(run_id="run-1", task_id="task-1"), actor_slack_user_id="U123")

        reply(handler)

        if expected is None:
            mock_capture.assert_not_called()
            return
        mock_capture.assert_called_once()
        assert mock_capture.call_args.args == (integration, "slack app reply posted")
        kwargs = mock_capture.call_args.kwargs
        assert kwargs == {
            "slack_user_id": "U123",
            "posthog_user": reader,
            "reply_kind": expected[0],
            "delivered": expected[1],
            "slack_session_id": "T1:C001:1234.5678",
            "task_id": "task-1",
            "run_id": "run-1",
        }


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
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_non_streamed_answer_hangs_the_menu_off_the_answer_not_the_footer(
        self, mock_get_client, mock_get_integration, _forking
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
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_outside_the_rollout_the_footer_closes_the_message(
        self, mock_get_client, mock_get_integration, _forking
    ) -> None:
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(id=7, config={"app_id": "A1"}, integration_id="T1")

        self._handler().post_thread_message("the answer", with_footer=True)

        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        assert blocks[-1]["type"] == "context"
        assert "accessory" not in blocks[0]


class TestMarkdownAnswerBlocks(SimpleTestCase):
    """Under the gate the answer carries a `markdown` block, which takes no accessory and caps
    at a different length than the `section` it replaces."""

    def _handler(self) -> SlackThreadHandler:
        context = SlackThreadContext(integration_id=1, channel="C001", thread_ts="1234.5678")
        return SlackThreadHandler(context, RunFooter(model="claude-opus-5"))

    @parameterized.expand([("with_footer", True), ("without_footer", False)])
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_the_answer_always_carries_a_markdown_block(
        self, _name: str, with_footer: bool, mock_get_client, mock_get_integration
    ) -> None:
        # A plain-text message renders mrkdwn on its own, which is why a footerless answer
        # used to carry no blocks. Markdown has no such equivalent, so without the block
        # Slack shows the source and `## Heading` reaches the reader as literal text.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(id=7, config={"app_id": "A1"}, integration_id="T1")

        self._handler().post_thread_message("## Heading\n\n**bold**", with_footer=with_footer, markdown=True)

        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        assert blocks[0] == {"type": "markdown", "text": "## Heading\n\n**bold**"}

    @patch("products.slack_app.backend.slack_thread.is_slack_app_forking_enabled", return_value=True)
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_the_menu_gets_its_own_block_because_markdown_takes_no_accessory(
        self, mock_get_client, mock_get_integration, _forking
    ) -> None:
        # Slack rejects the whole message when a block carries a field it does not define,
        # so an accessory left on the answer would cost the reader the answer itself.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(id=7, config={"app_id": "A1"}, integration_id="T1")

        self._handler().post_thread_message("the answer", with_footer=True, markdown=True)

        blocks = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        assert [block["type"] for block in blocks] == ["markdown", "context", "actions"]
        assert "accessory" not in blocks[0]

    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_an_answer_past_the_block_cap_posts_in_full_as_plain_text(
        self, mock_get_client, mock_get_integration
    ) -> None:
        # A markdown block Slack would reject for its length must cost the answer its
        # formatting, never any of its content.
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(id=7, config={"app_id": "A1"}, integration_id="T1")
        text = "x" * (SLACK_MARKDOWN_TEXT_MAX_LEN + 1)

        self._handler().post_thread_message(text, with_footer=True, markdown=True)

        kwargs = mock_client.chat_postMessage.call_args.kwargs
        assert kwargs["text"] == text
        assert not kwargs.get("blocks")

    @parameterized.expand([("invalid_blocks",), ("invalid_blocks_format",)])
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_a_rejected_markdown_block_falls_back_to_plain_text_without_looping(
        self, error_code: str, mock_get_client, mock_get_integration
    ) -> None:
        # Every answer carries a block, and the relay has already claimed the message, so a
        # rejection code this branch does not know loses the answer for good.
        # Recovering by calling post_thread_message again would rebuild the same markdown
        # block, so a rejection Slack repeats would recurse until the stack ran out.
        mock_client = MagicMock()
        mock_client.chat_postMessage.side_effect = SlackApiError(error_code, {"error": error_code})
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(id=7, config={"app_id": "A1"}, integration_id="T1")

        self._handler().post_thread_message("the answer", with_footer=True, markdown=True)

        assert mock_client.chat_postMessage.call_count == 2
        retry = mock_client.chat_postMessage.call_args_list[1].kwargs
        assert retry["text"] == "the answer"
        assert not retry.get("blocks")
