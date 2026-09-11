from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

SNUFFLE_SETTINGS = {
    "SNUFFLE_URL": "http://snuffle.test:9091/",
    "SNUFFLE_USER": "reader",
    "SNUFFLE_PASSWORD": "secret",
    "SNUFFLE_TIMEOUT_SECONDS": 12,
}


def _upstream(status_code: int = 200, body: bytes = b'{"status":"success","data":{}}') -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.content = body
    response.headers = {"Content-Type": "application/json; charset=utf-8"}
    return response


@override_settings(**SNUFFLE_SETTINGS)
class TestLokiQueryApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base = f"/api/projects/{self.team.pk}/logs/loki/api/v1"
        patcher = patch("posthog.api.snuffle_proxy.internal_requests.request", return_value=_upstream())
        self.request_mock = patcher.start()
        self.addCleanup(patcher.stop)

    def test_get_is_forwarded_with_team_header_and_credentials(self):
        response = self.client.get(
            f"{self.base}/query_range",
            {"query": '{service_name="api"} |= "error"', "start": "1", "end": "2", "limit": "100"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "application/json; charset=utf-8"
        assert response.content == b'{"status":"success","data":{}}'
        self.request_mock.assert_called_once()
        method, url = self.request_mock.call_args.args
        kwargs = self.request_mock.call_args.kwargs
        assert method == "GET"
        assert url == "http://snuffle.test:9091/loki/api/v1/query_range"
        assert kwargs["params"] == {
            "query": ['{service_name="api"} |= "error"'],
            "start": ["1"],
            "end": ["2"],
            "limit": ["100"],
        }
        assert kwargs["headers"]["X-Team-ID"] == str(self.team.pk)
        assert kwargs["auth"] == ("reader", "secret")
        assert kwargs["timeout"] == 12
        assert kwargs["data"] is None

    def test_post_form_body_is_forwarded(self):
        body = "query=%7Bservice_name%3D%22api%22%7D&start=1&end=2"
        response = self.client.post(f"{self.base}/query_range", body, content_type="application/x-www-form-urlencoded")

        assert response.status_code == status.HTTP_200_OK
        method, url = self.request_mock.call_args.args
        kwargs = self.request_mock.call_args.kwargs
        assert method == "POST"
        assert url == "http://snuffle.test:9091/loki/api/v1/query_range"
        assert kwargs["data"] == {"query": ['{service_name="api"}'], "start": ["1"], "end": ["2"]}
        assert kwargs["headers"]["X-Team-ID"] == str(self.team.pk)

    def test_tenant_and_credential_params_are_stripped(self):
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="grafana", user=self.user, secure_value=hash_key_value(token), scopes=["logs:read"]
        )
        self.client.logout()

        response = self.client.post(
            f"{self.base}/labels?team_id=999&start=1&personal_api_key={token}",
            "team_id=999&end=2",
            content_type="application/x-www-form-urlencoded",
        )

        assert response.status_code == status.HTTP_200_OK
        kwargs = self.request_mock.call_args.kwargs
        assert kwargs["params"] == {"start": ["1"]}
        assert kwargs["data"] == {"end": ["2"]}
        assert kwargs["headers"]["X-Team-ID"] == str(self.team.pk)

    @parameterized.expand(
        [
            ("push", "push"),
            ("nested_unknown", "index/volume"),
            ("label_without_values", "label/service_name"),
        ]
    )
    def test_unsupported_paths_never_reach_snuffle(self, _name: str, path: str):
        response = self.client.post(f"{self.base}/{path}", "query=x", content_type="application/x-www-form-urlencoded")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["status"] == "error"
        self.request_mock.assert_not_called()

    @override_settings(SNUFFLE_URL="")
    def test_unconfigured_returns_501(self):
        response = self.client.get(f"{self.base}/query", {"query": '{a="b"}'})

        assert response.status_code == status.HTTP_501_NOT_IMPLEMENTED
        assert response.json()["errorType"] == "unavailable"
        self.request_mock.assert_not_called()

    def test_upstream_error_status_and_body_pass_through(self):
        self.request_mock.return_value = _upstream(400, b'{"status":"error","errorType":"bad_data","error":"parse"}')

        response = self.client.get(f"{self.base}/query", {"query": "{"})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["errorType"] == "bad_data"

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403)])
    def test_upstream_credential_rejection_is_a_gateway_error(self, _name: str, upstream_status: int):
        self.request_mock.return_value = _upstream(upstream_status, b"auth failed")

        response = self.client.get(f"{self.base}/labels")

        assert response.status_code == status.HTTP_502_BAD_GATEWAY
        assert response.json()["errorType"] == "unavailable"

    @parameterized.expand(
        [
            ("timeout", requests.Timeout(), status.HTTP_504_GATEWAY_TIMEOUT),
            ("connection_error", requests.ConnectionError(), status.HTTP_502_BAD_GATEWAY),
        ]
    )
    def test_transport_failures_map_to_gateway_errors(self, _name: str, error: Exception, expected_status: int):
        self.request_mock.side_effect = error

        response = self.client.get(f"{self.base}/labels")

        assert response.status_code == expected_status
        assert response.json()["status"] == "error"

    @parameterized.expand(
        [
            ("logs_read", ["logs:read"], status.HTTP_200_OK),
            ("other_scope", ["metrics:read"], status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_personal_api_key_needs_logs_read_even_for_post(self, _name: str, scopes: list[str], expected_status: int):
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="grafana", user=self.user, secure_value=hash_key_value(token), scopes=scopes
        )
        self.client.logout()

        response = self.client.post(
            f"{self.base}/query_range",
            "query=%7Ba%3D%22b%22%7D",
            content_type="application/x-www-form-urlencoded",
            headers={"authorization": f"Bearer {token}"},
        )

        assert response.status_code == expected_status
        if expected_status == status.HTTP_403_FORBIDDEN:
            self.request_mock.assert_not_called()
