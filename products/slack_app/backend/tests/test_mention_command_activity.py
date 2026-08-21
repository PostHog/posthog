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
        self, *, command_prefix: str, event_extra: dict[str, str]
    ) -> PostHogCodeSlackMentionCommandWorkflowInputs:
        event = {"channel": "C1", "user": "U1", "text": "help", **event_extra}
        return PostHogCodeSlackMentionCommandWorkflowInputs(
            event=event,
            integration_ids=[self.integration.id],
            slack_team_id="T_WS",
            user_id=self.user.id,
            command_prefix=command_prefix,
        )

    @parameterized.expand(
        [
            # A slash command is visible only to its caller, so the reply is ephemeral. Outside a
            # thread it carries neither ts nor thread_ts, so it anchors to the channel root.
            ("slash_outside_thread", "/posthog", {}, "", "*Available commands:*", "chat_postEphemeral"),
            # A top-level mention carries only its own ts (no thread_ts). The reply
            # must anchor to the channel root, not that ts — a thread-anchored reply
            # is invisible to a user who isn't already viewing the thread.
            ("mention_top_level", "@PostHog", {"ts": "111.1"}, "", MENTION_HELP_REDIRECT, "chat_postMessage"),
            # A mention inside a real thread carries thread_ts; the reply threads there.
            (
                "mention_in_thread",
                "@PostHog",
                {"ts": "222.2", "thread_ts": "111.1"},
                "111.1",
                MENTION_HELP_REDIRECT,
                "chat_postMessage",
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
        expected_thread_ts: str,
        expected_text: str,
        expected_method: str,
        mock_slack_cls,
        mock_info,
    ) -> None:
        mock_info.return_value = {"user": {"is_admin": False, "is_owner": False}}
        client = mock_slack_cls.return_value.client

        result = handle_posthog_code_slack_mention_command_activity(
            self._inputs(command_prefix=command_prefix, event_extra=event_extra), self.user.id
        )

        assert result.status == "done"
        poster = getattr(client, expected_method)
        poster.assert_called_once()
        # A channel-root reply carries no anchor at all rather than an empty one.
        assert poster.call_args.kwargs.get("thread_ts", "") == expected_thread_ts
        assert expected_text in poster.call_args.kwargs["text"]
