import time_machine
from posthog.test.base import APIBaseTest

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models import Organization
from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.team import TeamEventsRetentionSetting


@override_settings(EVENTS_DATA_RETENTION_ENFORCED=True)
class TestEventsRetentionAPI(APIBaseTest):
    def url(self) -> str:
        return f"/api/projects/{self.team.id}/events_retention/"

    def _set_plan_years(self, years: int) -> None:
        Organization.objects.filter(pk=self.organization.pk).update(
            available_product_features=[{"key": "product_analytics_data_retention", "limit": years, "unit": "years"}]
        )

    def _make_project_admin(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

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
            "max_retention_months": 12,
            "docs_url": "https://posthog.com/docs/data/events-retention",
        }

    @override_settings(EVENTS_DATA_RETENTION_ENFORCED=False)
    def test_reports_no_window_until_retention_is_enforced(self) -> None:
        response = self.client.get(self.url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "retention_months": None,
            "retained_from": None,
            "max_retention_months": None,
            "docs_url": "https://posthog.com/docs/data/events-retention",
        }

    def test_project_admin_sets_a_window_within_the_plan(self) -> None:
        self._make_project_admin()
        self._set_plan_years(5)

        response = self.client.post(self.url(), {"retention_months": 24})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["retention_months"] == 24
        assert response.json()["max_retention_months"] == 60
        self.team.refresh_from_db()
        assert self.team.event_retention_months == 24
        assert TeamEventsRetentionSetting.objects.get(team=self.team).retention_months == 24
        assert ActivityLog.objects.filter(team_id=self.team.pk, scope="Team", activity="updated").exists()

    @parameterized.expand(
        [
            ("longer_than_the_plan", True, 36, status.HTTP_403_FORBIDDEN),
            ("not_an_allowed_value", True, 18, status.HTTP_400_BAD_REQUEST),
            ("not_a_project_admin", False, 12, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_rejects_a_window(self, _name: str, is_admin: bool, retention_months: int, expected_status: int) -> None:
        if is_admin:
            self._make_project_admin()
        self._set_plan_years(2)
        self.team.event_retention_months = 24
        self.team.save()

        response = self.client.post(self.url(), {"retention_months": retention_months})

        assert response.status_code == expected_status
        self.team.refresh_from_db()
        assert self.team.event_retention_months == 24
        assert not TeamEventsRetentionSetting.objects.filter(team=self.team).exists()

    @parameterized.expand([("patch",), ("put",), ("delete",)])
    def test_rejects_other_writes(self, method: str) -> None:
        self._make_project_admin()

        response = getattr(self.client, method)(self.url(), {"retention_months": 12})

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
