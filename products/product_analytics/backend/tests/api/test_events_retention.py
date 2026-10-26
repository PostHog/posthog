import time_machine
from posthog.test.base import APIBaseTest

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status


@override_settings(EVENTS_DATA_RETENTION_ENFORCED=True)
class TestEventsRetentionAPI(APIBaseTest):
    def url(self) -> str:
        return f"/api/projects/{self.team.id}/events_retention/"

    @parameterized.expand(
        [
            ("utc", "UTC", "2025-09-22"),
            ("ahead_of_utc", "Pacific/Auckland", "2025-09-23"),
        ]
    )
    @time_machine.travel("2026-09-22T23:30:00Z", tick=False)
    def test_reports_the_window_in_the_project_timezone(self, _name: str, tz: str, retained_from: str) -> None:
        self.team.timezone = tz
        self.team.event_retention_months = 12
        self.team.save()

        response = self.client.get(self.url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "retention_months": 12,
            "retained_from": retained_from,
            "docs_url": "https://posthog.com/docs/data/events-retention",
        }

    @override_settings(EVENTS_DATA_RETENTION_ENFORCED=False)
    def test_reports_no_window_until_retention_is_enforced(self) -> None:
        response = self.client.get(self.url())

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {
            "retention_months": None,
            "retained_from": None,
            "docs_url": "https://posthog.com/docs/data/events-retention",
        }

    @parameterized.expand([("patch",), ("put",), ("post",), ("delete",)])
    def test_rejects_writes(self, method: str) -> None:
        response = getattr(self.client, method)(self.url(), {"retention_months": 1})

        assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
