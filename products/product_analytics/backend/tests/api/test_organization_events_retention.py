from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization, Team
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_events_retention_setting import OrganizationEventsRetentionSetting


class TestOrganizationEventsRetentionAPI(APIBaseTest):
    def url(self) -> str:
        return f"/api/organizations/{self.organization.id}/events_retention_setting/"

    def _set_plan_years(self, years: int) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(
            available_product_features=[{"key": "product_analytics_data_retention", "limit": years, "unit": "years"}]
        )

    def _make_organization_admin(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

    def test_reports_no_choice_and_the_plan_maximum(self) -> None:
        self._set_plan_years(5)

        response = self.client.get(self.url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"retention_months": None, "max_retention_months": 60}

    def test_organization_admin_sets_a_window_for_every_project(self) -> None:
        self._make_organization_admin()
        self._set_plan_years(5)
        other_team = Team.objects.create(organization=self.organization, name="other")

        response = self.client.post(self.url(), {"retention_months": 24})

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"retention_months": 24, "max_retention_months": 60}
        for team in (self.team, other_team):
            team.refresh_from_db()
            assert team.event_retention_months == 24
        assert ActivityLog.objects.filter(
            organization_id=self.organization.id, scope="Organization", activity="updated"
        ).exists()

    @parameterized.expand(
        [
            ("longer_than_the_plan", True, 36, status.HTTP_403_FORBIDDEN),
            ("not_an_allowed_value", True, 18, status.HTTP_400_BAD_REQUEST),
            ("not_an_organization_admin", False, 12, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_rejects_a_window(self, _name: str, is_admin: bool, retention_months: int, expected_status: int) -> None:
        if is_admin:
            self._make_organization_admin()
        self._set_plan_years(2)
        self.team.event_retention_months = 24
        self.team.save()

        response = self.client.post(self.url(), {"retention_months": retention_months})

        assert response.status_code == expected_status
        self.team.refresh_from_db()
        assert self.team.event_retention_months == 24
        assert not OrganizationEventsRetentionSetting.objects.filter(organization=self.organization).exists()

    @parameterized.expand([("patch",), ("put",), ("delete",)])
    def test_rejects_other_writes(self, method: str) -> None:
        self._make_organization_admin()

        response = getattr(self.client, method)(self.url(), {"retention_months": 12})

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
