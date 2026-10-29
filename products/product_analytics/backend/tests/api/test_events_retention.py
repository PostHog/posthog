import time_machine
from posthog.test.base import APIBaseTest

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.events_retention_config import OrganizationEventsRetentionConfig, TeamEventsRetentionConfig
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.facade.testing import create_access_control


@override_settings(EVENTS_DATA_RETENTION_ENFORCED=True)
class TestEventsRetentionAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self._set_plan_years(2)
        self.team.event_retention_months = 24
        self.team.save()

    def url(self) -> str:
        return f"/api/projects/{self.team.id}/events_retention/"

    def organization_url(self) -> str:
        return f"/api/organizations/{self.organization.id}/events_retention_setting/"

    def _set_plan_years(self, years: int) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(
            available_product_features=[
                {"key": "product_analytics_data_retention", "limit": years, "unit": "years"},
                {"key": "access_control", "name": "Access control"},
            ]
        )

    def _set_membership(self, level: str) -> None:
        if level == "organization_admin":
            self.organization_membership.level = OrganizationMembership.Level.ADMIN
            self.organization_membership.save()
        else:
            create_access_control(
                team_id=self.team.id,
                resource="project",
                resource_id=str(self.team.id),
                access_level="admin",
                organization_member_id=self.organization_membership.id,
            )

    @parameterized.expand(
        [
            ("utc", "UTC", "2025-09-22"),
            ("ahead_of_utc", "Pacific/Auckland", "2025-09-23"),
        ]
    )
    @time_machine.travel("2026-09-22T23:30:00Z", tick=False)
    def test_reports_the_window_in_the_project_timezone(self, _name: str, tz: str, retained_from: str) -> None:
        self._set_plan_years(1)
        self.team.timezone = tz
        self.team.event_retention_months = 12
        self.team.save()

        response = self.client.get(self.url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "retention_months": 12,
            "retained_from": retained_from,
            "docs_url": "https://posthog.com/docs/data/events-retention",
            "project_retention_months": None,
            "organization_retention_months": None,
            "plan_retention_months": 12,
            "min_retention_months": 1,
            "max_retention_months": 12,
        }

    @override_settings(EVENTS_DATA_RETENTION_ENFORCED=False)
    def test_reports_no_window_until_retention_is_enforced(self) -> None:
        response = self.client.get(self.url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["retention_months"] is None
        assert response.json()["retained_from"] is None

    def test_organization_admin_sets_and_clears_the_project_window(self) -> None:
        self._set_membership("organization_admin")
        OrganizationEventsRetentionConfig.objects.create(
            organization=self.organization, default_events_retention_months=12
        )

        response = self.client.post(self.url(), {"retention_months": 6}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["retention_months"] == 6
        assert response.json()["project_retention_months"] == 6
        assert ActivityLog.objects.filter(team_id=self.team.id, scope="Team", activity="updated").exists()

        response = self.client.post(self.url(), {"retention_months": None}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["retention_months"] == 12
        assert response.json()["project_retention_months"] is None
        assert not TeamEventsRetentionConfig.objects.filter(team=self.team).exists()

    @parameterized.expand(
        [
            ("longer_than_the_plan", "organization_admin", 36, status.HTTP_400_BAD_REQUEST),
            ("shorter_than_the_staff_minimum", "organization_admin", 3, status.HTTP_400_BAD_REQUEST),
            ("only_a_project_admin", "project_admin", 6, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_rejects_a_project_window(self, _name: str, level: str, months: int, expected_status: int) -> None:
        self._set_membership(level)
        OrganizationEventsRetentionConfig.objects.create(organization=self.organization, min_events_retention_months=6)

        response = self.client.post(self.url(), {"retention_months": months}, format="json")

        assert response.status_code == expected_status
        assert not TeamEventsRetentionConfig.objects.filter(team=self.team).exists()

    def test_organization_admin_sets_and_clears_the_default_window(self) -> None:
        self._set_membership("organization_admin")

        response = self.client.post(self.organization_url(), {"retention_months": 12}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "organization_retention_months": 12,
            "plan_retention_months": 24,
            "min_retention_months": 1,
            "max_retention_months": 24,
        }
        assert self.client.get(self.url()).json()["retention_months"] == 12
        assert ActivityLog.objects.filter(
            organization_id=self.organization.id, scope="Organization", activity="updated"
        ).exists()

        response = self.client.post(self.organization_url(), {"retention_months": None}, format="json")

        assert response.status_code == status.HTTP_200_OK
        assert self.client.get(self.url()).json()["retention_months"] == 24
        assert not OrganizationEventsRetentionConfig.objects.filter(organization=self.organization).exists()

    @parameterized.expand(
        [
            ("longer_than_the_staff_maximum", "organization_admin", 18, status.HTTP_400_BAD_REQUEST),
            ("only_a_project_admin", "project_admin", 6, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_rejects_an_organization_window(self, _name: str, level: str, months: int, expected_status: int) -> None:
        self._set_membership(level)
        OrganizationEventsRetentionConfig.objects.create(organization=self.organization, max_events_retention_months=12)

        response = self.client.post(self.organization_url(), {"retention_months": months}, format="json")

        assert response.status_code == expected_status
        assert (
            OrganizationEventsRetentionConfig.objects.get(
                organization=self.organization
            ).default_events_retention_months
            is None
        )

    @override_settings(EVENTS_DATA_RETENTION_ENFORCED=False)
    def test_accepts_windows_before_retention_is_enforced(self) -> None:
        self._set_membership("organization_admin")

        for url in (self.url(), self.organization_url()):
            response = self.client.post(url, {"retention_months": 12}, format="json")

            assert response.status_code == status.HTTP_200_OK
        assert (
            OrganizationEventsRetentionConfig.objects.get(
                organization=self.organization
            ).default_events_retention_months
            == 12
        )
        assert TeamEventsRetentionConfig.objects.get(team=self.team).events_retention_months == 12

    @parameterized.expand([("patch",), ("put",), ("delete",)])
    def test_rejects_other_writes(self, method: str) -> None:
        self._set_membership("organization_admin")

        for url in (self.url(), self.organization_url()):
            response = getattr(self.client, method)(url, {"retention_months": 1})

            assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
