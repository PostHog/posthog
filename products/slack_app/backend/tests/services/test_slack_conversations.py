import pytest
from unittest.mock import MagicMock

from slack_sdk.errors import SlackApiError

from products.slack_app.backend.models import SlackThreadTaskMapping
from products.slack_app.backend.services.slack_conversations import channel_is_ext_shared, resolve_conversation_type

ConversationType = SlackThreadTaskMapping.ConversationType


def _slack(channel: dict | None = None, error: Exception | None = None) -> MagicMock:
    slack = MagicMock()
    if error is not None:
        slack.client.conversations_info.side_effect = error
    else:
        slack.client.conversations_info.return_value = {"channel": channel or {}}
    return slack


class TestResolveConversationType:
    @pytest.mark.parametrize(
        "channel_type,expected",
        [
            ("im", ConversationType.IM),
            ("mpim", ConversationType.MPIM),
            ("group", ConversationType.PRIVATE_CHANNEL),
            ("channel", ConversationType.PUBLIC_CHANNEL),
        ],
    )
    def test_message_event_channel_type_is_authoritative(self, channel_type: str, expected: str) -> None:
        slack = _slack()

        result = resolve_conversation_type(slack, {"channel_type": channel_type}, "C123")

        assert result == expected
        slack.client.conversations_info.assert_not_called()

    def test_app_mention_in_dm_falls_back_to_the_id_prefix(self) -> None:
        result = resolve_conversation_type(_slack(), {"type": "app_mention"}, "D123")

        assert result == ConversationType.IM

    def test_dm_never_calls_slack(self) -> None:
        # `conversations.info` on a `D…` id needs `im:read`, which the app does not request —
        # in production the call fails, so reordering the checks would misclassify every DM
        # reached through `app_mention`. Stubbing the client hides that, asserting it doesn't.
        slack = _slack()

        resolve_conversation_type(slack, {"type": "app_mention"}, "D123")

        slack.client.conversations_info.assert_not_called()

    @pytest.mark.parametrize(
        "channel,expected",
        [
            ({"is_private": True}, ConversationType.PRIVATE_CHANNEL),
            ({"is_private": False}, ConversationType.PUBLIC_CHANNEL),
            ({"is_mpim": True}, ConversationType.MPIM),
            ({}, ConversationType.UNKNOWN),
        ],
    )
    def test_app_mention_in_channel_asks_slack(self, channel: dict, expected: str) -> None:
        result = resolve_conversation_type(_slack(channel), {"type": "app_mention"}, "C123")

        assert result == expected

    @pytest.mark.parametrize(
        "error",
        [
            SlackApiError("missing_scope", {"error": "missing_scope"}),
            RuntimeError("boom"),
        ],
    )
    def test_unresolvable_channel_is_unknown_rather_than_an_exception(self, error: Exception) -> None:
        # Task creation must survive this: UNKNOWN reads as non-private downstream, so the
        # thread keeps the access it would have had before the lookup existed.
        result = resolve_conversation_type(_slack(error=error), {"type": "app_mention"}, "C123")

        assert result == ConversationType.UNKNOWN


class TestChannelIsExtShared:
    @pytest.mark.parametrize(
        "channel_id,expected",
        [
            ("D123", False),
            ("C123", True),
        ],
    )
    def test_failed_lookup_fails_closed_except_for_a_dm(self, channel_id: str, expected: bool) -> None:
        # `conversations.info` fails on every `D…` id in production because the app lacks
        # `im:read`. A DM must not fall into the fail-closed path, or every DM click is sent to
        # a channel approval it can never get. A channel still fails closed.
        slack = _slack(error=SlackApiError("missing_scope", {"error": "missing_scope"}))

        assert channel_is_ext_shared(slack, channel_id) is expected
