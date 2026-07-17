import pytest
from unittest.mock import MagicMock, patch

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackSettings
from products.slack_app.backend.services.commands import _handle_help, _handle_project_set_workspace

WORKSPACE_HELP_LINE = "`@PostHog project workspace <id>`"


def _slack_user_info(*, is_admin: bool = False, is_owner: bool = False) -> dict:
    return {"user": {"is_admin": is_admin, "is_owner": is_owner, "profile": {"email": "u@example.com"}}}


class TestHandleProjectSetWorkspace:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Org")
        self.team = Team.objects.create(organization=self.organization, name="Team A")
        self.other_team = Team.objects.create(organization=Organization.objects.create(name="Other"), name="Team B")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_WS",
            sensitive_config={"access_token": "xoxb-a"},
        )
        self.user = User.objects.create_and_join(self.organization, "admin@example.com", "pw")
        self.slack = MagicMock()

    def _run(self, target_team_id: int) -> None:
        _handle_project_set_workspace(
            self.slack,
            self.integration,
            channel="C1",
            thread_ts="111.1",
            slack_user_id="U1",
            slack_workspace_id="T_WS",
            user_id=self.user.id,
            target_team_id=target_team_id,
            workspace_candidates=[self.integration],
        )

    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    def test_admin_sets_workspace_default(self, mock_info):
        mock_info.return_value = _slack_user_info(is_admin=True)

        self._run(self.team.id)

        row = SlackSettings.objects.get(slack_workspace_id="T_WS", slack_user_id__isnull=True)
        assert row.default_integration_id == self.integration.id
        self.slack.client.chat_postEphemeral.assert_called_once()

    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    def test_owner_sets_workspace_default(self, mock_info):
        mock_info.return_value = _slack_user_info(is_owner=True)

        self._run(self.team.id)

        assert SlackSettings.objects.filter(slack_workspace_id="T_WS", slack_user_id__isnull=True).exists()

    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    def test_non_admin_is_refused(self, mock_info):
        mock_info.return_value = _slack_user_info(is_admin=False, is_owner=False)

        self._run(self.team.id)

        assert not SlackSettings.objects.filter(slack_workspace_id="T_WS").exists()
        text = self.slack.client.chat_postEphemeral.call_args.kwargs["text"]
        assert "admins or owners" in text

    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    def test_admin_without_team_access_is_refused(self, mock_info):
        mock_info.return_value = _slack_user_info(is_admin=True)

        self._run(self.other_team.id)

        assert not SlackSettings.objects.filter(slack_workspace_id="T_WS").exists()
        text = self.slack.client.chat_postEphemeral.call_args.kwargs["text"]
        assert "don't have access" in text

    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    def test_workspace_default_replaces_existing(self, mock_info):
        mock_info.return_value = _slack_user_info(is_admin=True)
        second_team = Team.objects.create(organization=self.organization, name="Team C")
        second_integration = Integration.objects.create(
            team=second_team,
            kind="slack",
            integration_id="T_WS",
            sensitive_config={"access_token": "xoxb-c"},
        )
        SlackSettings.objects.create(
            default_integration=second_integration,
            slack_workspace_id="T_WS",
            slack_user_id=None,
        )

        self._run(self.team.id)

        rows = SlackSettings.objects.filter(slack_workspace_id="T_WS", slack_user_id__isnull=True)
        assert rows.count() == 1
        assert rows.get().default_integration_id == self.integration.id


class TestHandleHelp:
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
        self.slack = MagicMock()

    def _help_text(self) -> str:
        _handle_help(self.slack, self.integration, "C1", "111.1", "U1")
        return self.slack.client.chat_postMessage.call_args.kwargs["text"]

    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    def test_admin_sees_workspace_line(self, mock_info):
        mock_info.return_value = _slack_user_info(is_admin=True)
        assert WORKSPACE_HELP_LINE in self._help_text()

    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    def test_owner_sees_workspace_line(self, mock_info):
        mock_info.return_value = _slack_user_info(is_owner=True)
        assert WORKSPACE_HELP_LINE in self._help_text()

    @patch("products.slack_app.backend.services.slack_user_info.get_slack_user_info")
    def test_non_admin_does_not_see_workspace_line(self, mock_info):
        mock_info.return_value = _slack_user_info(is_admin=False, is_owner=False)
        text = self._help_text()
        assert WORKSPACE_HELP_LINE not in text
        # The rest of the help is still posted.
        assert "Available commands" in text
