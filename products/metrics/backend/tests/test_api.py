from posthog.test.base import APIBaseTest

from django.apps import apps

from parameterized import parameterized
from rest_framework import status


def test_metrics_app_is_installed():
    assert apps.is_installed("products.metrics.backend")


class TestMetricsValuesApi(APIBaseTest):
    @parameterized.expand(
        [
            ("zero", "0"),
            ("over_max", "1001"),
            ("not_an_integer", "abc"),
        ]
    )
    def test_invalid_limit_is_rejected_with_400(self, _name: str, limit: str) -> None:
        response = self.client.get(f"/api/projects/{self.team.id}/metrics/values/", {"limit": limit})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "limit"
