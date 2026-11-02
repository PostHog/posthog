from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models.organization import OrganizationMembership


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
            {"marketing_frequency_cap_max_messages": 1, "marketing_frequency_cap_window_days": 2},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        body = self.client.get(self._url()).json()
        assert body["marketing_frequency_cap_max_messages"] == 1
        assert body["marketing_frequency_cap_window_days"] == 2

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
