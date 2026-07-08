import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.services.slack_messages import (
    collect_thread_messages,
    decode_slack_event_text,
    extract_message_text,
    flatten_block_text,
    labeled_mentions_to_display_names,
    resolve_user_mentions_text,
)


class TestFlattenBlockText:
    @parameterized.expand(
        [
            ("none", None, []),
            ("plain_string", "hello", ["hello"]),
            ("whitespace_string", "   ", []),
            ("padded_string", "  hi  ", ["hi"]),
            ("non_str_scalar", 12345, []),
            ("empty_section", {"type": "section"}, []),
            (
                "section_text",
                {"type": "section", "text": {"type": "mrkdwn", "text": "🔴 Alert firing"}},
                ["🔴 Alert firing"],
            ),
            (
                "section_fields",
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": "*Threshold:* 10"},
                        {"type": "mrkdwn", "text": "*Value:* 42"},
                    ],
                },
                ["*Threshold:* 10", "*Value:* 42"],
            ),
            (
                "header",
                {"type": "header", "text": {"type": "plain_text", "text": "High error rate"}},
                ["High error rate"],
            ),
            (
                "context_elements",
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": "service: web"},
                        {"type": "mrkdwn", "text": "severity: critical"},
                    ],
                },
                ["service: web", "severity: critical"],
            ),
            (
                "rich_text_nested",
                {
                    "type": "rich_text",
                    "elements": [
                        {
                            "type": "rich_text_section",
                            "elements": [{"type": "text", "text": "hello world"}],
                        }
                    ],
                },
                ["hello world"],
            ),
        ]
    )
    def test_flatten_cases(self, _name: str, node, expected: list[str]) -> None:
        assert flatten_block_text(node) == expected

    def test_skips_actions_and_dividers(self) -> None:
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "Title"}},
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Click me"}}],
            },
        ]
        assert flatten_block_text(blocks) == ["Title"]


class TestExtractMessageText:
    @parameterized.expand(
        [
            (
                "text_only_no_blocks",
                {"text": "hello world"},
                "hello world",
            ),
            (
                "text_and_block_with_extra_detail_combines",
                {
                    "text": "🔴 Alert firing",
                    "blocks": [
                        {"type": "header", "text": {"type": "plain_text", "text": "🔴 Alert firing"}},
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "value 42 exceeded threshold 10"},
                        },
                    ],
                },
                "🔴 Alert firing\nvalue 42 exceeded threshold 10",
            ),
            (
                "blocks_only_falls_back",
                {
                    "text": "",
                    "blocks": [
                        {"type": "section", "text": {"type": "mrkdwn", "text": "real content"}},
                    ],
                },
                "real content",
            ),
            (
                "attachments_fallback",
                {
                    "text": "",
                    "blocks": [],
                    "attachments": [
                        {"fallback": "PostHog alert: signups dropped 30% week over week"},
                    ],
                },
                "PostHog alert: signups dropped 30% week over week",
            ),
            (
                "whitespace_text_treated_as_empty",
                {
                    "text": "   ",
                    "blocks": [
                        {"type": "section", "text": {"type": "mrkdwn", "text": "real content"}},
                    ],
                },
                "real content",
            ),
            (
                "dedupes_repeats_across_text_and_blocks",
                {
                    "text": "duplicated",
                    "blocks": [
                        {"type": "section", "text": {"type": "mrkdwn", "text": "duplicated"}},
                        {"type": "section", "text": {"type": "mrkdwn", "text": "different"}},
                    ],
                },
                "duplicated\ndifferent",
            ),
            (
                "no_content_returns_empty",
                {"text": "", "blocks": [], "attachments": []},
                "",
            ),
            (
                "missing_keys_returns_empty",
                {},
                "",
            ),
        ]
    )
    def test_extract_cases(self, _name: str, msg: dict, expected: str) -> None:
        assert extract_message_text(msg) == expected


@patch("products.slack_app.backend.services.slack_messages.get_slack_user_info")
class TestResolveUserMentionsText:
    def setup_method(self) -> None:
        self.slack = MagicMock(spec=SlackIntegration)
        self.integration = MagicMock(spec=Integration)

    def _profiles(self, mapping: dict[str, str]):
        def _lookup(_slack, _integration, uid):
            return {"user": {"profile": {"display_name": mapping.get(uid, "")}}}

        return _lookup

    def test_strips_bot_mention_keeps_and_labels_user_mention(self, mock_get_user_info):
        mock_get_user_info.side_effect = self._profiles({"UCLEO": "cleo"})

        result = resolve_user_mentions_text(
            self.slack,
            self.integration,
            "<@UBOT> can you do what <@UCLEO> asked",
            strip_bot_user_id="UBOT",
        )

        assert result == "can you do what <@UCLEO|cleo> asked"

    def test_keeps_user_mention_when_no_bot_id_given(self, mock_get_user_info):
        mock_get_user_info.side_effect = self._profiles({"UCLEO": "cleo"})

        result = resolve_user_mentions_text(self.slack, self.integration, "ping <@UCLEO>")

        assert result == "ping <@UCLEO|cleo>"

    def test_unresolvable_user_becomes_unknown(self, mock_get_user_info):
        mock_get_user_info.side_effect = RuntimeError("slack down")

        result = resolve_user_mentions_text(self.slack, self.integration, "hey <@UCLEO>")

        assert result == "hey <@UCLEO|Unknown>"

    def test_no_mentions_passes_through_unchanged(self, mock_get_user_info):
        result = resolve_user_mentions_text(self.slack, self.integration, "just some text", strip_bot_user_id="UBOT")

        assert result == "just some text"
        mock_get_user_info.assert_not_called()

    def test_collapses_gap_left_by_removed_bot_mention(self, mock_get_user_info):
        result = resolve_user_mentions_text(
            self.slack, self.integration, "do <@UBOT> the thing", strip_bot_user_id="UBOT"
        )

        assert result == "do the thing"

    def test_strips_bot_user_mentions_via_is_bot_flag(self, mock_get_user_info):
        # A workspace bot (e.g. Grafana) is identified by ``users.info``'s ``is_bot``
        # flag, not by wire-format syntax — bot user IDs are ``U…``-prefixed just
        # like humans. The mention should be dropped, not labeled, so the agent
        # doesn't echo it and ping the bot back.
        def lookup(_slack, _integration, uid):
            if uid == "UGRAFANA":
                return {"user": {"is_bot": True, "profile": {"display_name": "grafana"}}}
            return {"user": {"is_bot": False, "profile": {"display_name": "cleo"}}}

        mock_get_user_info.side_effect = lookup

        result = resolve_user_mentions_text(self.slack, self.integration, "<@UGRAFANA> is paging <@UCLEO> again")

        assert result == "is paging <@UCLEO|cleo> again"

    def test_failed_lookup_falls_back_to_labeled_unknown_not_stripped(self, mock_get_user_info):
        # An exception during ``users.info`` lookup must not be mistaken for
        # ``is_bot=True``: silently dropping the mention would re-introduce the
        # original bug where real users get erased from the agent's context.
        mock_get_user_info.side_effect = RuntimeError("slack down")

        result = resolve_user_mentions_text(self.slack, self.integration, "ping <@UCLEO>")

        assert result == "ping <@UCLEO|Unknown>"


class TestDecodeSlackEventText:
    """The wrapper at the 3 trigger sites — look up the bot, label the rest, strip."""

    def setup_method(self) -> None:
        self.slack = MagicMock(spec=SlackIntegration)
        self.integration = MagicMock(spec=Integration)

    @patch("products.slack_app.backend.services.slack_messages.get_cached_bot_user_id")
    @patch("products.slack_app.backend.services.slack_messages.get_slack_user_info")
    def test_strips_bot_self_mention_when_lookup_succeeds(self, mock_get_user_info, mock_get_bot_user_id):
        mock_get_bot_user_id.return_value = "UBOT"
        mock_get_user_info.return_value = {"user": {"profile": {"display_name": "cleo"}}}

        result = decode_slack_event_text(self.slack, self.integration, "<@UBOT> ping <@UCLEO> ")

        assert result == "ping <@UCLEO|cleo>"

    @patch("products.slack_app.backend.services.slack_messages.get_cached_bot_user_id")
    @patch("products.slack_app.backend.services.slack_messages.get_slack_user_info")
    def test_leaves_bot_mention_labeled_when_lookup_returns_none(self, mock_get_user_info, mock_get_bot_user_id):
        # auth_test() failure → no bot user id → the bot's own mention falls
        # through the strip_bot_user_id fast path, but is_bot stripping still
        # catches it once the lookup returns is_bot=True.
        mock_get_bot_user_id.return_value = None
        mock_get_user_info.return_value = {"user": {"is_bot": True, "profile": {"display_name": "bot"}}}

        result = decode_slack_event_text(self.slack, self.integration, "<@UBOT> ping")

        assert result == "ping"

    @patch("products.slack_app.backend.services.slack_messages.get_cached_bot_user_id")
    @patch("products.slack_app.backend.services.slack_messages.get_slack_user_info")
    def test_strips_surrounding_whitespace_from_result(self, mock_get_user_info, mock_get_bot_user_id):
        mock_get_bot_user_id.return_value = "UBOT"
        mock_get_user_info.return_value = {"user": {"profile": {"display_name": ""}}}

        result = decode_slack_event_text(self.slack, self.integration, "  <@UBOT>  hello world  ")

        assert result == "hello world"


class TestLabeledMentionsToDisplayNames:
    def test_unwraps_labeled_mention(self):
        assert labeled_mentions_to_display_names("ping <@UCLEO|cleo> please") == "ping @cleo please"

    def test_unwraps_multiple_labeled_mentions(self):
        assert labeled_mentions_to_display_names("<@UA|andy> and <@UB|bob>") == "@andy and @bob"

    def test_leaves_bare_id_mention_alone(self):
        # Bare `<@U…>` (no label) is something we never emit on the agent path,
        # but if it shows up we leave it as-is rather than dropping the user id.
        assert labeled_mentions_to_display_names("hi <@UCLEO>") == "hi <@UCLEO>"

    def test_no_op_on_plain_text(self):
        assert labeled_mentions_to_display_names("just some text") == "just some text"


class TestCollectThreadMessages:
    @pytest.fixture(autouse=True)
    def setup(self, db, monkeypatch):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.slack = MagicMock(spec=SlackIntegration)
        self.slack.client = MagicMock()
        # ``collect_thread_messages`` and ``resolve_user_mentions_text`` both look up
        # users via ``get_slack_user_info``, imported into ``services.slack_messages``
        # at module load. Patching the binding inside that module makes both call
        # sites resolve to the same mock for a single test.
        self.mock_get_user_info = MagicMock()
        monkeypatch.setattr(
            "products.slack_app.backend.services.slack_messages.get_slack_user_info", self.mock_get_user_info
        )

    def _set_thread(self, messages: list[dict]) -> None:
        self.slack.client.conversations_replies.return_value = {"messages": messages}

    def test_alert_blocks_only_message_is_included(self):
        # PostHog alert: substantive content lives only in blocks, no text field.
        self._set_thread(
            [
                {
                    "bot_id": "B_ALERTS",
                    "bot_profile": {"name": "PostHog"},
                    "text": "",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {"type": "plain_text", "text": "🔴 Log alert 'High Error Rate' is firing"},
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "Result count *42* exceeded threshold *10* over 5m",
                            },
                        },
                    ],
                },
                {"user": "U_ANDY", "text": "<@UBOT> was that really an anomaly?"},
            ]
        )
        self.mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        result = collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id="B_OUR_CODE_BOT")

        assert len(result) == 2
        assert result[0]["user"] == "PostHog"
        assert "🔴 Log alert 'High Error Rate' is firing" in result[0]["text"]
        assert "Result count *42* exceeded threshold *10*" in result[0]["text"]
        assert result[1]["user"] == "andy"
        assert "was that really an anomaly?" in result[1]["text"]

    def test_skips_our_own_bot_reply_messages(self):
        # Our own bot replies (e.g. "Working on it...") must be filtered so the agent
        # doesn't ingest its own status updates as context on a re-mention.
        self._set_thread(
            [
                {"user": "U_ANDY", "text": "@PostHog please look at this", "ts": "1.000"},
                {"bot_id": "B_OUR_CODE_BOT", "text": "Working on it...", "ts": "2.000"},
                {"user": "U_ANDY", "text": "thanks", "ts": "3.000"},
            ]
        )
        self.mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        result = collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id="B_OUR_CODE_BOT")

        assert [m["ts"] for m in result] == ["1.000", "3.000"]
        assert all(m["user"] == "andy" for m in result)

    def test_keeps_thread_root_even_when_bot_id_matches_our_own(self):
        # Regression: in workspaces where the alerting Slack app and the `@PostHog` code
        # app share an installation identity, the alert that opened the thread has the same
        # `bot_id` as `our_bot_id`. We must still include it — the agent only posts as a
        # reply, never as a thread root, so msg 0 is always the originating context.
        self._set_thread(
            [
                {
                    "bot_id": "B_OUR_CODE_BOT",
                    "bot_profile": {"name": "PostHog"},
                    "text": "",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": "Alert 'Headline anomaly: Trial activated' firing for insight",
                            },
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": "Anomaly detected on 2026-05-19"},
                        },
                    ],
                    "ts": "1.000",
                },
                {"user": "U_ANDY", "text": "<@UBOT> lets investigate this one", "ts": "2.000"},
            ]
        )
        self.mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        result = collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id="B_OUR_CODE_BOT")

        assert len(result) == 2
        assert result[0]["user"] == "PostHog"
        assert "Alert 'Headline anomaly: Trial activated'" in result[0]["text"]
        assert result[1]["user"] == "andy"

    def test_other_bot_uses_bot_profile_name(self):
        self._set_thread(
            [
                {
                    "bot_id": "B_GRAFANA",
                    "bot_profile": {"name": "Grafana"},
                    "text": "alert: latency p95 above 2s",
                    "ts": "1.000",
                }
            ]
        )

        result = collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id="B_OUR_CODE_BOT")

        # Bot posts carry no raw user id, so `user_id` is empty — downstream prompt
        # builders fall back to the plain name instead of building a labeled mention.
        assert result == [{"user": "Grafana", "user_id": "", "text": "alert: latency p95 above 2s", "ts": "1.000"}]
        self.mock_get_user_info.assert_not_called()

    def test_bot_without_profile_falls_back_to_username_field(self):
        self._set_thread([{"bot_id": "B_HOOK", "username": "PostHog Webhook", "text": "ping", "ts": "2.000"}])

        result = collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id=None)

        assert result == [{"user": "PostHog Webhook", "user_id": "", "text": "ping", "ts": "2.000"}]

    def test_includes_raw_user_id_for_real_users(self):
        # Downstream prompt builders render each message author as a labeled
        # `<@U…|displayname>` mention so the agent can echo the token verbatim
        # to ping the participant back — that requires the raw Slack id, not
        # just the resolved display name.
        self._set_thread([{"user": "U_ANDY", "text": "hi", "ts": "1.000"}])
        self.mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        result = collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id=None)

        assert result == [{"user": "andy", "user_id": "U_ANDY", "text": "hi", "ts": "1.000"}]

    def test_includes_ts_for_initiator_disambiguation(self):
        self._set_thread(
            [
                {"user": "U_ANDY", "text": "context", "ts": "1.000"},
                {"user": "U_ANDY", "text": "@PostHog fix this", "ts": "2.000"},
            ]
        )
        self.mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        result = collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id="B_OUR")

        assert [m["ts"] for m in result] == ["1.000", "2.000"]

    def test_preserves_user_mention_replacement(self):
        self._set_thread([{"user": "U_ANDY", "text": "hey <@UBOT> can you help"}])
        self.mock_get_user_info.return_value = {"user": {"profile": {"display_name": "posthog-code"}}}

        result = collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id=None)

        assert result[0]["text"] == "hey <@UBOT|posthog-code> can you help"

    def test_includes_thread_root_when_our_bot_id_is_none(self):
        # Defensive: if auth_test() somehow returned no bot_id we still process the thread.
        self._set_thread(
            [
                {"bot_id": "B_ALERT", "bot_profile": {"name": "PostHog"}, "text": "alert"},
                {"user": "U_ANDY", "text": "follow up"},
            ]
        )
        self.mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        result = collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id=None)

        assert [m["user"] for m in result] == ["PostHog", "andy"]

    def test_registers_rate_limit_retry_handler(self):
        self.slack.client.retry_handlers = []
        self._set_thread([{"user": "U_ANDY", "text": "hi"}])
        self.mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id=None)

        assert any(isinstance(h, RateLimitErrorRetryHandler) for h in self.slack.client.retry_handlers)

        handlers = [h for h in self.slack.client.retry_handlers if isinstance(h, RateLimitErrorRetryHandler)]
        assert len(handlers) == 1
        assert handlers[0].max_retry_count == 3
        # If block flattening blows up for one message, the rest of the thread still flows.
        self._set_thread(
            [
                {
                    "bot_id": "B_ALERT",
                    "bot_profile": {"name": "PostHog"},
                    "text": "",
                    "blocks": [{"type": "section"}],
                },
                {"user": "U_ANDY", "text": "still here"},
            ]
        )
        self.mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        with patch(
            "products.slack_app.backend.services.slack_messages.flatten_block_text",
            side_effect=RuntimeError("boom"),
        ):
            result = collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id="B_OUR")

        assert len(result) == 2
        assert result[0]["user"] == "PostHog"
        assert result[1]["text"] == "still here"
