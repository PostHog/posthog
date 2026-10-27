from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, OrganizationMembership, User
from posthog.models.integration import Integration
from posthog.models.team.team import Team

from products.slack_app.backend.models import SlackSettings

SLACK_TEAM_ID = "T12345"


class TestSlackAppWorkspaceSetup(APIBaseTest):
    def _slack_install(self, team: Team, created_by: User | None = None, config: dict | None = None) -> Integration:
        return Integration.objects.create(
            team=team,
            kind="slack",
            integration_id=SLACK_TEAM_ID,
            config={"app_id": "A777", "team": {"id": SLACK_TEAM_ID, "name": "Hedgebox"}} if config is None else config,
            sensitive_config={"access_token": "xoxb-test"},
            created_by=created_by,
        )

    def _url(self, integration_id: int, suffix: str = "") -> str:
        return f"/api/projects/{self.team.id}/slack_app_workspace_setup/{integration_id}/{suffix}"

    def _second_project(self) -> Team:
        return Team.objects.create(organization=self.organization, name="Hedgebox mobile")

    @parameterized.expand(
        [
            ("nothing_to_do", True, False, False, []),
            ("ai_not_allowed", False, False, False, ["ai_consent"]),
            ("two_projects_no_default", True, True, False, ["default_project"]),
            ("two_projects_with_default", True, True, True, []),
            ("both", False, True, False, ["ai_consent", "default_project"]),
        ]
    )
    def test_steps(self, _name: str, ai_allowed: bool, two_projects: bool, has_default: bool, expected: list) -> None:
        self.organization.is_ai_data_processing_approved = ai_allowed
        self.organization.save()
        integration = self._slack_install(self.team, created_by=self.user)
        if two_projects:
            other = self._slack_install(self._second_project())
            if has_default:
                SlackSettings.objects.create(
                    slack_workspace_id=SLACK_TEAM_ID, slack_user_id=None, default_integration=other
                )

        response = self.client.get(self._url(integration.id))

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["steps"] == expected
        assert body["slack_workspace_name"] == "Hedgebox"
        assert body["open_slack_url"] == f"https://slack.com/app_redirect?app=A777&team={SLACK_TEAM_ID}"
        expected_options = 2 if "default_project" in expected else 0
        assert len(body["project_options"]) == expected_options

    def test_project_options_leave_out_projects_the_person_cannot_open(self) -> None:
        integration = self._slack_install(self.team, created_by=self.user)
        self._slack_install(self._second_project())
        other_org = Organization.objects.create(name="Other company")
        self._slack_install(Team.objects.create(organization=other_org, name="Not mine"))

        body = self.client.get(self._url(integration.id)).json()

        assert body["steps"] == ["default_project"]
        assert [option["project_name"] for option in body["project_options"]] == [self.team.name, "Hedgebox mobile"]

    @parameterized.expand([("other_team",), ("other_kind",)])
    def test_returns_404_for_an_integration_it_must_not_read(self, case: str) -> None:
        if case == "other_team":
            integration = self._slack_install(self._second_project())
        else:
            integration = Integration.objects.create(team=self.team, kind="github", integration_id="1", config={})

        response = self.client.get(self._url(integration.id))

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_installer_sets_the_workspace_default(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        integration = self._slack_install(self.team, created_by=self.user)
        other = self._slack_install(self._second_project())

        response = self.client.post(self._url(integration.id, "default_project/"), {"integration_id": other.id})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["steps"] == []
        stored = SlackSettings.objects.get(slack_workspace_id=SLACK_TEAM_ID, slack_user_id__isnull=True)
        assert stored.default_integration_id == other.id

    @parameterized.expand([("not_installer_or_admin",), ("project_not_reachable",)])
    def test_default_project_is_refused(self, case: str) -> None:
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        if case == "not_installer_or_admin":
            installer = User.objects.create_and_join(self.organization, "installer@example.com", None)
            integration = self._slack_install(self.team, created_by=installer)
            target = self._slack_install(self._second_project())
        else:
            integration = self._slack_install(self.team, created_by=self.user)
            target = self._slack_install(Team.objects.create(organization=Organization.objects.create(name="Other")))

        response = self.client.post(self._url(integration.id, "default_project/"), {"integration_id": target.id})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not SlackSettings.objects.filter(slack_workspace_id=SLACK_TEAM_ID, slack_user_id__isnull=True).exists()
