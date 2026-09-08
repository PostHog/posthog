from types import SimpleNamespace

import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app.activities.rules import handle_posthog_code_slack_mention_command_activity
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionCommandWorkflowInputs

from products.slack_app.backend.services.commands import MENTION_HELP_REDIRECT


class TestMentionCommandActivity:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=self.organization, name="Team A")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_WS",
            sensitive_config={"access_token": "xoxb-a"},
        )
        self.user = User.objects.create_and_join(self.organization, "u@example.com", "pw")

    def _inputs(
        self, *, command_prefix: str, event_extra: dict[str, str], event_text: str = "help"
    ) -> PostHogCodeSlackMentionCommandWorkflowInputs:
        event = {"channel": "C1", "user": "U1", "text": event_text, **event_extra}
        return PostHogCodeSlackMentionCommandWorkflowInputs(
            event=event,
            integration_ids=[self.integration.id],
            slack_team_id="T_WS",
            user_id=self.user.id,
            command_prefix=command_prefix,
        )

    @parameterized.expand(
        [
            # A slash command outside a thread carries neither ts nor thread_ts, so the reply
            # anchors to the channel root.
            ("slash_outside_thread", "/posthog", {}, "help", "", "*Available commands:*"),
            # A top-level mention carries only its own ts (no thread_ts). The reply
            # must anchor to the channel root, not that ts — a thread-anchored reply
            # is invisible to a user who isn't already viewing the thread.
            ("mention_top_level", "@PostHog", {"ts": "111.1"}, "help", "", MENTION_HELP_REDIRECT),
            # A mention inside a real thread carries thread_ts; the reply threads there.
            (
                "mention_in_thread",
                "@PostHog",
                {"ts": "222.2", "thread_ts": "111.1"},
                "help",
                "111.1",
                MENTION_HELP_REDIRECT,
            ),
        ]
    )
    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    @patch("posthog.models.integration.SlackIntegration")
    def test_dispatches_with_surface_prefix(
        self,
        _name: str,
        command_prefix: str,
        event_extra: dict[str, str],
        event_text: str,
        expected_thread_ts: str,
        expected_text: str,
        mock_slack_cls,
        mock_info,
    ) -> None:
        mock_info.return_value = {"user": {"is_admin": False, "is_owner": False}}
        client = mock_slack_cls.return_value.client

        result = handle_posthog_code_slack_mention_command_activity(
            self._inputs(command_prefix=command_prefix, event_extra=event_extra, event_text=event_text), self.user.id
        )

        assert result.status == "done"
        # Both surfaces answer only the caller, so nothing lands in the channel.
        assert client.chat_postMessage.call_count == 0
        client.chat_postEphemeral.assert_called_once()
        # A channel-root reply carries no anchor at all rather than an empty one.
        assert client.chat_postEphemeral.call_args.kwargs.get("thread_ts", "") == expected_thread_ts
        assert expected_text in client.chat_postEphemeral.call_args.kwargs["text"]

    @patch(
        "products.slack_app.backend.services.commands.build_usage_report",
        return_value=SimpleNamespace(message="## PostHog AI usage\n\n**Billing period**: 800 credits"),
    )
    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    @patch("posthog.models.integration.SlackIntegration")
    def test_usage_answers_in_a_markdown_block(self, mock_slack_cls, mock_info, _mock_report) -> None:
        # The report is Markdown, so a plain `text` reply would show its syntax rather than render it.
        mock_info.return_value = {"user": {"is_admin": False, "is_owner": False}}
        client = mock_slack_cls.return_value.client

        result = handle_posthog_code_slack_mention_command_activity(
            self._inputs(command_prefix="/posthog", event_extra={}, event_text="usage"), self.user.id
        )

        assert result.status == "done"
        assert client.chat_postMessage.call_count == 0
        blocks = client.chat_postEphemeral.call_args.kwargs["blocks"]
        assert blocks[0]["type"] == "markdown"
        assert "**Billing period**: 800 credits" in blocks[0]["text"]
