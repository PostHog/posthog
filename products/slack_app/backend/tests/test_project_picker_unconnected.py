import pytest
from unittest.mock import MagicMock, patch

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackSettings
from products.slack_app.backend.services.commands import (
    _handle_project_set,
    _handle_project_set_workspace,
    _handle_project_show,
)


def _slack_user_info(*, is_admin: bool = True) -> dict:
    return {"user": {"is_admin": is_admin, "is_owner": False, "profile": {"email": "u@example.com"}}}


class TestProjectPickerWithUnconnectedProjects:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Org")
        self.connected_team = Team.objects.create(organization=self.organization, name="Connected")
        self.unconnected_team = Team.objects.create(organization=self.organization, name="Unconnected")
        self.foreign_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Foreign")
        self.integration = Integration.objects.create(
            team=self.connected_team,
            kind="slack",
            integration_id="T_WS",
            sensitive_config={"access_token": "xoxb-a"},
        )
        self.user = User.objects.create_and_join(self.organization, "admin@example.com", "pw")
        self.slack = MagicMock()

    def _ephemeral_text(self) -> str:
        return self.slack.client.chat_postEphemeral.call_args.kwargs["text"]

    def test_show_lists_projects_without_an_integration(self):
        _handle_project_show(
            self.slack,
            "C1",
            "111.1",
            "U1",
            "T_WS",
            self.user.id,
            workspace_candidates=[self.integration],
        )

        text = self._ephemeral_text()
        assert f"`{self.unconnected_team.id}`" in text
        assert f"`{self.connected_team.id}`" in text
        assert f"/project/{self.unconnected_team.id}/settings/environment-integrations" in text
        # Already-connected projects don't need a connect link.
        assert f"/project/{self.connected_team.id}/settings/environment-integrations" not in text

    def test_set_on_unconnected_project_returns_a_connect_link(self):
        _handle_project_set(
            self.slack,
            "C1",
            "111.1",
            "U1",
            "T_WS",
            self.user.id,
            self.unconnected_team.id,
            workspace_candidates=[self.integration],
        )

        text = self._ephemeral_text()
        assert f"/project/{self.unconnected_team.id}/settings/environment-integrations" in text
        assert f"@PostHog project {self.unconnected_team.id}" in text
        assert not SlackSettings.objects.filter(slack_workspace_id="T_WS").exists()

    def test_set_on_inaccessible_project_points_at_the_picker(self):
        _handle_project_set(
            self.slack,
            "C1",
            "111.1",
            "U1",
            "T_WS",
            self.user.id,
            self.foreign_team.id,
            workspace_candidates=[self.integration],
        )

        assert "don't have access" in self._ephemeral_text()
        assert not SlackSettings.objects.filter(slack_workspace_id="T_WS").exists()

    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    def test_set_workspace_on_unconnected_project_returns_a_connect_link(self, mock_info):
        mock_info.return_value = _slack_user_info()

        _handle_project_set_workspace(
            self.slack,
            self.integration,
            channel="C1",
            thread_ts="111.1",
            slack_user_id="U1",
            slack_workspace_id="T_WS",
            user_id=self.user.id,
            target_team_id=self.unconnected_team.id,
            workspace_candidates=[self.integration],
        )

        text = self._ephemeral_text()
        assert f"/project/{self.unconnected_team.id}/settings/environment-integrations" in text
        assert f"@PostHog project workspace {self.unconnected_team.id}" in text
        assert not SlackSettings.objects.filter(slack_workspace_id="T_WS").exists()
