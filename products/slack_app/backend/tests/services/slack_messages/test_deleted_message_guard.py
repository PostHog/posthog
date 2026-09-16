import pytest
from unittest.mock import MagicMock

from django.core.cache import cache

from parameterized import parameterized
from slack_sdk.errors import SlackApiError

from products.slack_app.backend.services.slack_messages import post_slack_thread_reply, slack_message_exists

THREAD_TS = "1700000000.000100"

PRESENT = {"messages": [{"ts": THREAD_TS, "user": "U_ANDY", "text": "@PostHog fix the flaky test"}]}
DELETED: dict = {"messages": []}


class TestSlackMessageExists:
    @pytest.fixture(autouse=True)
    def clear_probe_cache(self):
        cache.clear()
        yield
        cache.clear()

    @parameterized.expand(
        [
            ("message_present", PRESENT, True),
            ("message_deleted", DELETED, False),
            ("missing_messages_key", {}, False),
            # None of these is evidence the message is gone, and silencing a real reply is
            # the worse failure, so the probe fails open.
            ("rate_limited", SlackApiError("ratelimited", {"error": "ratelimited"}), True),
            ("missing_scope", SlackApiError("missing_scope", {"error": "missing_scope"}), True),
            ("transport_error", ConnectionError("boom"), True),
        ]
    )
    def test_existence(self, _name, history_outcome, expected):
        client = MagicMock()
        if isinstance(history_outcome, Exception):
            client.conversations_history.side_effect = history_outcome
        else:
            client.conversations_history.return_value = history_outcome

        assert slack_message_exists(client, "C001", THREAD_TS) is expected

    def test_probe_asks_for_that_one_message(self):
        # A one-message window on the ts itself: anything wider would report a neighbouring
        # message as proof this one survives.
        client = MagicMock()
        client.conversations_history.return_value = PRESENT

        slack_message_exists(client, "C001", THREAD_TS)

        client.conversations_history.assert_called_once_with(
            channel="C001", latest=THREAD_TS, oldest=THREAD_TS, inclusive=True, limit=1
        )

    def test_repeated_probes_collapse_onto_one_slack_call(self):
        client = MagicMock()
        client.conversations_history.return_value = PRESENT

        assert slack_message_exists(client, "C001", THREAD_TS) is True
        assert slack_message_exists(client, "C001", THREAD_TS) is True

        assert client.conversations_history.call_count == 1


class TestPostSlackThreadReply:
    @pytest.fixture(autouse=True)
    def clear_probe_cache(self):
        cache.clear()
        yield
        cache.clear()

    def test_reply_posts_while_the_message_is_there(self):
        client = MagicMock()
        client.conversations_history.return_value = PRESENT

        post_slack_thread_reply(client, channel="C001", thread_ts=THREAD_TS, text="on it")

        client.chat_postMessage.assert_called_once_with(channel="C001", thread_ts=THREAD_TS, text="on it")

    def test_reply_is_dropped_once_the_message_is_deleted(self):
        client = MagicMock()
        client.conversations_history.return_value = DELETED

        assert post_slack_thread_reply(client, channel="C001", thread_ts=THREAD_TS, text="on it") is None

        client.chat_postMessage.assert_not_called()

    def test_root_level_post_skips_the_check(self):
        client = MagicMock()

        post_slack_thread_reply(client, channel="C001", thread_ts=None, text="hello")

        client.conversations_history.assert_not_called()
        client.chat_postMessage.assert_called_once_with(channel="C001", text="hello")

    def test_root_placed_reply_is_still_checked_against_its_trigger(self):
        # Top-level @PostHog commands answer at channel root on purpose, so the anchor is
        # empty. The command message they answer must still be checked, or deleting it
        # leaves the reply posting to the whole channel.
        client = MagicMock()
        client.conversations_history.return_value = DELETED

        result = post_slack_thread_reply(client, channel="C001", thread_ts="", trigger_ts=THREAD_TS, text="help text")

        assert result is None
        client.chat_postMessage.assert_not_called()

    def test_root_placed_reply_posts_without_an_anchor_when_its_trigger_lives(self):
        client = MagicMock()
        client.conversations_history.return_value = PRESENT

        post_slack_thread_reply(client, channel="C001", thread_ts="", trigger_ts=THREAD_TS, text="help text")

        client.chat_postMessage.assert_called_once_with(channel="C001", text="help text")

    def test_trigger_takes_precedence_over_the_anchor(self):
        # A command posted inside a live thread: the reply threads under the root, but what
        # it answers is the command message, so that is what decides.
        client = MagicMock()
        client.conversations_history.return_value = DELETED

        result = post_slack_thread_reply(
            client, channel="C001", thread_ts="1700000000.000001", trigger_ts=THREAD_TS, text="hi"
        )

        assert result is None
        client.conversations_history.assert_called_once_with(
            channel="C001", latest=THREAD_TS, oldest=THREAD_TS, inclusive=True, limit=1
        )
