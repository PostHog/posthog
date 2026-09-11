from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value


def _upstream() -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = 200
    response.content = b'{"status":"success","data":{"resultType":"vector","result":[]}}'
    response.headers = {"Content-Type": "application/json"}
    return response


@override_settings(SNUFFLE_URL="http://snuffle.test:9091", SNUFFLE_USER="reader", SNUFFLE_PASSWORD="secret")
class TestPrometheusQueryApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base = f"/api/projects/{self.team.pk}/metrics/prometheus/api/v1"
        patcher = patch("posthog.api.snuffle_proxy.internal_requests.request", return_value=_upstream())
        self.request_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def test_query_is_forwarded_to_the_prometheus_api_with_team_header(self):
        response = self.client.get(f"{self.base}/query", {"query": "sum(rate(http_requests_total[5m]))"})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "success"
        method, url = self.request_mock.call_args.args
        kwargs = self.request_mock.call_args.kwargs
        assert method == "GET"
        assert url == "http://snuffle.test:9091/api/v1/query"
        assert kwargs["params"] == {"query": ["sum(rate(http_requests_total[5m]))"]}
        assert kwargs["headers"]["X-Team-ID"] == str(self.team.pk)
        assert kwargs["auth"] == ("reader", "secret")

    @parameterized.expand(
        [
            ("label_values", "label/__name__/values"),
            ("metadata", "metadata"),
            ("buildinfo", "status/buildinfo"),
        ]
    )
    def test_read_endpoints_are_allowed(self, _name: str, path: str):
        response = self.client.get(f"{self.base}/{path}")

        assert response.status_code == status.HTTP_200_OK
        _, url = self.request_mock.call_args.args
        assert url == f"http://snuffle.test:9091/api/v1/{path}"

    @parameterized.expand([("remote_write", "write"), ("remote_read", "read")])
    def test_remote_storage_endpoints_are_rejected(self, _name: str, path: str):
        response = self.client.post(f"{self.base}/{path}", "query=up", content_type="application/x-www-form-urlencoded")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        self.request_mock.assert_not_called()

    def test_metrics_flag_gates_the_api(self):
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.get(f"{self.base}/query", {"query": "up"})

        assert response.status_code == status.HTTP_403_FORBIDDEN
        self.request_mock.assert_not_called()

    @parameterized.expand(
        [
            ("metrics_read", ["metrics:read"], status.HTTP_200_OK),
            ("logs_read_only", ["logs:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_personal_api_key_needs_metrics_read(self, _name: str, scopes: list[str], expected_status: int):
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="grafana", user=self.user, secure_value=hash_key_value(token), scopes=scopes
        )
        self.client.logout()

        response = self.client.get(f"{self.base}/query", {"query": "up"}, headers={"authorization": f"Bearer {token}"})

        assert response.status_code == expected_status
