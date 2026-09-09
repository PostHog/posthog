from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.exceptions import ClickHouseAtCapacity


class TestWeeklyDigestAPI(ClickhouseTestMixin, APIBaseTest):
    def _url(self, action: str) -> str:
        return f"/api/projects/{self.team.id}/web_analytics/{action}/"

    @parameterized.expand([("weekly_digest",), ("recap",)])
    def test_returns_the_digest_for_a_project_with_no_traffic(self, action: str) -> None:
        response = self.client.get(self._url(action))

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["visitors"]["current"] == 0

    @parameterized.expand([("weekly_digest",), ("recap",)])
    def test_reports_unavailable_rather_than_zero_traffic_when_the_query_fails(self, action: str) -> None:
        with patch(
            "products.web_analytics.backend.hogql_queries.web_overview.WebOverviewQueryRunner.run",
            side_effect=ClickHouseAtCapacity(),
        ):
            response = self.client.get(self._url(action))

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["code"] == "web_analytics_digest_unavailable"
