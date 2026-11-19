from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.constants import AvailableFeature
from posthog.models import Team
from posthog.models.organization import OrganizationMembership

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig


class TestWorkflowSendingRulesAPI(APIBaseTest):
    def _url(self) -> str:
        return f"/api/projects/{self.team.id}/workflow_sending_rules/current/"

    def _set_level(self, level: OrganizationMembership.Level) -> None:
        self.organization_membership.level = level
        self.organization_membership.save()

    def test_an_admin_sets_the_cap_and_reads_it_back(self) -> None:
        self._set_level(OrganizationMembership.Level.ADMIN)

        response = self.client.patch(
            self._url(),
            {
                "marketing_frequency_cap_max_messages": 1,
                "marketing_frequency_cap_window_days": 2,
                "marketing_frequency_cap_hold_hours": 48,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = self.client.get(self._url()).json()
        assert body["marketing_frequency_cap_max_messages"] == 1
        assert body["marketing_frequency_cap_window_days"] == 2
        assert body["marketing_frequency_cap_hold_hours"] == 48

    @parameterized.expand(
        [
            ("a member", OrganizationMembership.Level.MEMBER, {"capture_workflows_engagement_events": True}, 403),
            ("half a cap", OrganizationMembership.Level.ADMIN, {"marketing_frequency_cap_max_messages": 3}, 400),
            (
                "another project",
                OrganizationMembership.Level.ADMIN,
                {
                    "expected_project_id": 999999,
                    "marketing_frequency_cap_max_messages": 1,
                    "marketing_frequency_cap_window_days": 2,
                },
                400,
            ),
        ]
    )
    def test_an_update_is_rejected_for(self, _name, level, payload, expected_status) -> None:
        self._set_level(level)

        response = self.client.patch(self._url(), payload, format="json")

        assert response.status_code == expected_status, response.json()
        assert self.client.get(self._url()).json()["marketing_frequency_cap_max_messages"] is None


class TestEngagementEventsDefault(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def _captures(self, team_id: int) -> bool:
        response = self.client.get(f"/api/projects/{team_id}/workflow_sending_rules/current/")
        assert response.status_code == status.HTTP_200_OK, response.json()
        return response.json()["capture_workflows_engagement_events"]

    def _create_project(self) -> int:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ORGANIZATIONS_PROJECTS, "name": "Projects", "limit": None}
        ]
        self.organization.save()
        response = self.client.post("/api/projects/", {"name": "New project"})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return response.json()["id"]

    def _create_organization(self) -> int:
        with self.is_cloud(True):
            response = self.client.post("/api/organizations/", {"name": "New organization"})
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        return Team.objects.get(organization_id=response.json()["id"]).id

    @parameterized.expand([("a new project", "_create_project"), ("a new organization", "_create_organization")])
    def test_a_team_created_for_captures_engagement_events(self, _name: str, create: str) -> None:
        team_id = getattr(self, create)()

        assert self._captures(team_id) is True
        assert TeamWorkflowsConfig.objects.get(team_id=team_id).capture_workflows_engagement_events is True

    @parameterized.expand([("no saved setting", None), ("capture on", True), ("capture off", False)])
    def test_an_existing_team_keeps_its_value_with(self, _name: str, saved: bool | None) -> None:
        TeamWorkflowsConfig.objects.filter(team=self.team).delete()
        if saved is not None:
            TeamWorkflowsConfig.objects.create(team=self.team, capture_workflows_engagement_events=saved)

        assert self._captures(self.team.id) is bool(saved)
        renamed = self.client.patch(f"/api/environments/{self.team.id}/", {"name": "Renamed"})
        assert renamed.status_code == status.HTTP_200_OK, renamed.json()
        assert renamed.json()["workflows_config"]["capture_workflows_engagement_events"] is bool(saved)
        assert self._captures(self.team.id) is bool(saved)
        assert TeamWorkflowsConfig.objects.get(team=self.team).capture_workflows_engagement_events is bool(saved)
