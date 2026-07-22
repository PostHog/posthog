import pytest
from unittest.mock import MagicMock

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackSettings
from products.slack_app.backend.services.commands import _handle_project_set


class TestHandleProjectSet:
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
        self.user = User.objects.create_and_join(self.organization, "user@example.com", "pw")
        self.slack = MagicMock()

    def _run(self, target_team_id: int, candidates: list[Integration], command_prefix: str = "@PostHog") -> None:
        _handle_project_set(
            self.slack,
            channel="C1",
            thread_ts="111.1",
            slack_user_id="U1",
            slack_workspace_id="T_WS",
            user_id=self.user.id,
            target_team_id=target_team_id,
            workspace_candidates=candidates,
            command_prefix=command_prefix,
        )

    def _second_integration(self) -> Integration:
        second_team = Team.objects.create(organization=self.organization, name="Team B")
        return Integration.objects.create(
            team=second_team,
            kind="slack",
            integration_id="T_WS",
            sensitive_config={"access_token": "xoxb-b"},
        )

    def test_personal_default_already_on_target_confirms_without_silence(self):
        second = self._second_integration()
        SlackSettings.objects.create(
            default_integration=self.integration,
            slack_workspace_id="T_WS",
            slack_user_id="U1",
        )

        self._run(self.team.id, [self.integration, second])

        text = self.slack.client.chat_postMessage.call_args.kwargs["text"]
        assert "already connected" in text
        assert f"`{self.team.id}`" in text
        assert "What would you like to work on?" in text
        self.slack.client.chat_postEphemeral.assert_not_called()

    def test_sole_candidate_match_confirms_and_pins_durable_default(self):
        self._run(self.team.id, [self.integration])

        text = self.slack.client.chat_postMessage.call_args.kwargs["text"]
        assert "already connected" in text
        # The explicit command must survive a second project being connected later.
        row = SlackSettings.objects.get(slack_workspace_id="T_WS", slack_user_id="U1")
        assert row.default_integration_id == self.integration.id

    def test_workspace_default_match_confirms_and_pins_personal_default(self):
        second = self._second_integration()
        SlackSettings.objects.create(
            default_integration=self.integration,
            slack_workspace_id="T_WS",
            slack_user_id=None,
        )

        self._run(self.team.id, [self.integration, second])

        text = self.slack.client.chat_postMessage.call_args.kwargs["text"]
        assert "already connected" in text
        # The explicit pin must hold even if an admin later moves the workspace default.
        row = SlackSettings.objects.get(slack_workspace_id="T_WS", slack_user_id="U1")
        assert row.default_integration_id == self.integration.id

    def test_slash_surface_confirmation_is_ephemeral_without_mention_invite(self):
        self._run(self.team.id, [self.integration], command_prefix="/posthog")

        text = self.slack.client.chat_postEphemeral.call_args.kwargs["text"]
        assert "already connected" in text
        assert "Mention me" not in text
        # A slash invocation is invisible to the channel, so the confirmation
        # must not post project metadata publicly.
        self.slack.client.chat_postMessage.assert_not_called()

    def test_switching_to_different_project_still_sets_default(self):
        second = self._second_integration()
        SlackSettings.objects.create(
            default_integration=self.integration,
            slack_workspace_id="T_WS",
            slack_user_id="U1",
        )

        self._run(second.team_id, [self.integration, second])

        row = SlackSettings.objects.get(slack_workspace_id="T_WS", slack_user_id="U1")
        assert row.default_integration_id == second.id
        text = self.slack.client.chat_postEphemeral.call_args.kwargs["text"]
        assert "Default set to" in text
        self.slack.client.chat_postMessage.assert_not_called()
