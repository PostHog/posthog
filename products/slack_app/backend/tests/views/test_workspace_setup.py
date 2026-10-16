from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.team.team import Team

from products.slack_app.backend.logic.workspace_setup import SetupStep


class TestSlackAppWorkspaceSetup(APIBaseTest):
    def _create_slack_integration(self, team: Team, config: dict | None = None) -> Integration:
        return Integration.objects.create(
            team=team,
            kind="slack",
            integration_id="T12345",
            config={"app_id": "A777", "team": {"id": "T12345", "name": "Hedgebox"}} if config is None else config,
            sensitive_config={"access_token": "xoxb-test"},
        )

    def _url(self, integration_id: int) -> str:
        return f"/api/projects/{self.team.id}/slack_app_workspace_setup/{integration_id}/"

    def test_returns_only_steps_that_apply_and_are_not_done(self) -> None:
        integration = self._create_slack_integration(self.team)
        steps = (
            SetupStep(key="applies_and_open", applies=lambda _: True, is_done=lambda _: False),
            SetupStep(key="applies_and_done", applies=lambda _: True, is_done=lambda _: True),
            SetupStep(key="does_not_apply", applies=lambda _: False, is_done=lambda _: False),
        )

        with patch("products.slack_app.backend.logic.workspace_setup.SETUP_STEPS", steps):
            response = self.client.get(self._url(integration.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "integration_id": integration.id,
            "slack_workspace_name": "Hedgebox",
            "open_slack_url": "https://slack.com/app_redirect?app=A777&team=T12345",
            "steps": ["applies_and_open"],
        }

    def test_open_slack_url_is_null_without_an_app_id(self) -> None:
        integration = self._create_slack_integration(self.team, config={"team": {"name": "Hedgebox"}})

        response = self.client.get(self._url(integration.id))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["open_slack_url"] is None

    @parameterized.expand([("other_team",), ("other_kind",)])
    def test_returns_404_for_an_integration_it_must_not_read(self, case: str) -> None:
        if case == "other_team":
            other_team = Team.objects.create(organization=self.organization, name="Other project")
            integration = self._create_slack_integration(other_team)
        else:
            integration = Integration.objects.create(team=self.team, kind="github", integration_id="1", config={})

        response = self.client.get(self._url(integration.id))

        assert response.status_code == status.HTTP_404_NOT_FOUND
