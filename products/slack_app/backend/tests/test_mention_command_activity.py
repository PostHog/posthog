import pytest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.temporal.ai.slack_app.activities.rules import handle_posthog_code_slack_mention_command_activity
from posthog.temporal.ai.slack_app.types import PostHogCodeSlackMentionCommandWorkflowInputs


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

    def _inputs(self, *, event_extra: dict[str, str]) -> PostHogCodeSlackMentionCommandWorkflowInputs:
        event = {"channel": "C1", "user": "U1", "text": "help", **event_extra}
        return PostHogCodeSlackMentionCommandWorkflowInputs(
            event=event,
            integration_ids=[self.integration.id],
            slack_team_id="T_WS",
            user_id=self.user.id,
            command_prefix="/posthog",
        )

    @parameterized.expand(
        [
            # A slash command outside a thread carries neither ts nor thread_ts, so the reply
            # anchors to the channel root.
            ("outside_thread", {}, ""),
            ("in_thread", {"thread_ts": "111.1"}, "111.1"),
        ]
    )
    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    @patch("posthog.models.integration.SlackIntegration")
    def test_reply_is_anchored_to_the_surface_the_caller_is_looking_at(
        self,
        _name: str,
        event_extra: dict[str, str],
        expected_thread_ts: str,
        mock_slack_cls,
        mock_info,
    ) -> None:
        mock_info.return_value = {"user": {"is_admin": False, "is_owner": False}}
        client = mock_slack_cls.return_value.client

        result = handle_posthog_code_slack_mention_command_activity(self._inputs(event_extra=event_extra), self.user.id)

        assert result.status == "done"
        # A command answers only the caller, so nothing lands in the channel.
        assert client.chat_postMessage.call_count == 0
        client.chat_postEphemeral.assert_called_once()
        # A channel-root reply carries no anchor at all rather than an empty one.
        assert client.chat_postEphemeral.call_args.kwargs.get("thread_ts", "") == expected_thread_ts
        assert "*Available commands:*" in client.chat_postEphemeral.call_args.kwargs["text"]
