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

    def _inputs(self, *, command_prefix: str, with_thread: bool) -> PostHogCodeSlackMentionCommandWorkflowInputs:
        event = {"channel": "C1", "user": "U1", "text": "help"}
        if with_thread:
            event["ts"] = "111.1"
        return PostHogCodeSlackMentionCommandWorkflowInputs(
            event=event,
            integration_ids=[self.integration.id],
            slack_team_id="T_WS",
            user_id=self.user.id,
            command_prefix=command_prefix,
        )

    @parameterized.expand(
        [
            # A slash command outside a thread carries no ``ts``; the reply must
            # still go out (channel-root anchor) rather than silently no-op on the
            # guard, and it must speak the ``/posthog`` surface.
            ("slash_outside_thread", "/posthog", False, ""),
            # The mention surface always carries a ``ts`` and keeps its copy.
            ("mention_in_thread", "@PostHog", True, "111.1"),
        ]
    )
    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    @patch("posthog.models.integration.SlackIntegration")
    def test_dispatches_with_surface_prefix(
        self,
        _name: str,
        command_prefix: str,
        with_thread: bool,
        expected_thread_ts: str,
        mock_slack_cls,
        mock_info,
    ) -> None:
        mock_info.return_value = {"user": {"is_admin": False, "is_owner": False}}
        client = mock_slack_cls.return_value.client

        result = handle_posthog_code_slack_mention_command_activity(
            self._inputs(command_prefix=command_prefix, with_thread=with_thread), self.user.id
        )

        assert result.status == "done"
        client.chat_postMessage.assert_called_once()
        assert client.chat_postMessage.call_args.kwargs["thread_ts"] == expected_thread_ts
        assert command_prefix in client.chat_postMessage.call_args.kwargs["text"]
