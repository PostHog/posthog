import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration, SlackIntegration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.api import _collect_thread_messages, _extract_message_text, _flatten_block_text


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
        assert _flatten_block_text(node) == expected

    def test_skips_actions_and_dividers(self) -> None:
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "Title"}},
            {"type": "divider"},
            {
                "type": "actions",
                "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Click me"}}],
            },
        ]
        assert _flatten_block_text(blocks) == ["Title"]


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
        assert _extract_message_text(msg) == expected


@patch("products.slack_app.backend.api._get_slack_user_info")
class TestCollectThreadMessages:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack-posthog-code",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.slack = MagicMock(spec=SlackIntegration)
        self.slack.client = MagicMock()

    def _set_thread(self, messages: list[dict]) -> None:
        self.slack.client.conversations_replies.return_value = {"messages": messages}

    def test_alert_blocks_only_message_is_included(self, mock_get_user_info):
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
        mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        result = _collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id="B_OUR_CODE_BOT")

        assert len(result) == 2
        assert result[0]["user"] == "PostHog"
        assert "🔴 Log alert 'High Error Rate' is firing" in result[0]["text"]
        assert "Result count *42* exceeded threshold *10*" in result[0]["text"]
        assert result[1]["user"] == "andy"
        assert "was that really an anomaly?" in result[1]["text"]

    def test_skips_our_own_bot_messages(self, mock_get_user_info):
        self._set_thread(
            [
                {"bot_id": "B_OUR_CODE_BOT", "text": "Working on it..."},
                {"user": "U_ANDY", "text": "thanks"},
            ]
        )
        mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        result = _collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id="B_OUR_CODE_BOT")

        assert len(result) == 1
        assert result[0]["user"] == "andy"

    def test_other_bot_uses_bot_profile_name(self, mock_get_user_info):
        self._set_thread(
            [
                {
                    "bot_id": "B_GRAFANA",
                    "bot_profile": {"name": "Grafana"},
                    "text": "alert: latency p95 above 2s",
                }
            ]
        )

        result = _collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id="B_OUR_CODE_BOT")

        assert result == [{"user": "Grafana", "text": "alert: latency p95 above 2s"}]
        mock_get_user_info.assert_not_called()

    def test_bot_without_profile_falls_back_to_username_field(self, mock_get_user_info):
        self._set_thread([{"bot_id": "B_HOOK", "username": "PostHog Webhook", "text": "ping"}])

        result = _collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id=None)

        assert result == [{"user": "PostHog Webhook", "text": "ping"}]

    def test_preserves_user_mention_replacement(self, mock_get_user_info):
        self._set_thread([{"user": "U_ANDY", "text": "hey <@UBOT> can you help"}])
        mock_get_user_info.return_value = {"user": {"profile": {"display_name": "posthog-code"}}}

        result = _collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id=None)

        assert result[0]["text"] == "hey @posthog-code can you help"

    def test_includes_thread_root_when_our_bot_id_is_none(self, mock_get_user_info):
        # Defensive: if auth_test() somehow returned no bot_id we still process the thread.
        self._set_thread(
            [
                {"bot_id": "B_ALERT", "bot_profile": {"name": "PostHog"}, "text": "alert"},
                {"user": "U_ANDY", "text": "follow up"},
            ]
        )
        mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        result = _collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id=None)

        assert [m["user"] for m in result] == ["PostHog", "andy"]

    def test_block_extraction_failure_does_not_break_collection(self, mock_get_user_info):
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
        mock_get_user_info.return_value = {"user": {"profile": {"display_name": "andy"}}}

        with patch(
            "products.slack_app.backend.api._flatten_block_text",
            side_effect=RuntimeError("boom"),
        ):
            result = _collect_thread_messages(self.slack, self.integration, "C001", "1.234", our_bot_id="B_OUR")

        assert len(result) == 2
        assert result[0]["user"] == "PostHog"
        assert result[1]["text"] == "still here"
