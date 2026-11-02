import json
import uuid
import tempfile
from pathlib import Path

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

import requests
from parameterized import parameterized
from rest_framework import status

import posthog.api.snuffle_proxy as snuffle_proxy
from posthog.clickhouse.client import connection
from posthog.clickhouse.client.connection import ClickHouseCredentials, ClickHouseUser
from posthog.clickhouse.query_log_archive import _V3_LOG_COMMENT_FIELDS, _V3_LOG_COMMENT_TRAILING_FIELDS
from posthog.clickhouse.query_tagging import AccessMethod, Feature, Product, reset_query_tags, tags_context
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

SNUFFLE_APM_SETTINGS = {
    "SNUFFLE_APM_URL": "http://snuffle.test:9091/",
    "SNUFFLE_APM_USER": "reader",
    "SNUFFLE_APM_PASSWORD": "secret",
    "SNUFFLE_APM_TIMEOUT_SECONDS": 12,
}


def _upstream(status_code: int = 200, body: bytes = b'{"status":"success","data":{}}') -> MagicMock:
    response = MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.content = body
    response.headers = {"Content-Type": "application/json; charset=utf-8", "X-Snuffle-ClickHouse-Read-Bytes": "1234"}
    return response


@override_settings(**SNUFFLE_APM_SETTINGS)
class TestLokiQueryApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base = f"/api/projects/{self.team.pk}/logs/loki/api/v1"
        patcher = patch("posthog.api.snuffle_proxy.internal_requests.request", return_value=_upstream())
        self.request_mock = patcher.start()
        self.addCleanup(patcher.stop)
        # Enable the Snuffle flag for the Loki proxy tests.
        # The gate test sets the flag to False.
        ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        ff_patcher.start()
        self.addCleanup(ff_patcher.stop)
        debit_patcher = patch("posthog.api.snuffle_proxy.schedule_snuffle_budget_debit")
        self.schedule_budget_debit = debit_patcher.start()
        self.addCleanup(debit_patcher.stop)

    @parameterized.expand([("bare", "query_range"), ("trailing_slash", "query_range/")])
    def test_get_is_forwarded_with_team_header_and_credentials(self, _name: str, path: str):
        response = self.client.get(
            f"{self.base}/{path}",
            {"query": '{service_name="api"} |= "error"', "start": "1", "end": "2", "limit": "100"},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response["Content-Type"] == "application/json; charset=utf-8"
        assert response.content == b'{"status":"success","data":{}}'
        assert response["X-PostHog-Query-Bytes-Read"] == "1234"
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

    def test_read_bytes_are_debited_from_the_project_budget(self):
        response = self.client.get(f"{self.base}/query", {"query": '{service_name="api"}'})

        assert response.status_code == status.HTTP_200_OK
        self.schedule_budget_debit.assert_called_once_with(str(self.team.pk), 1234)
        assert "X-PostHog-Query-Budget-Remaining-Bytes" not in response

    @patch("posthog.api.snuffle_proxy.api_queries_budget_enforcement_enabled", return_value=True)
    @patch("posthog.api.snuffle_proxy.get_api_queries_budget_status")
    def test_exhausted_byte_budget_refuses_before_reaching_snuffle(self, budget_status, enforced):
        budget_status.return_value = MagicMock(remaining_bytes=0, retry_after_seconds=42)

        response = self.client.get(f"{self.base}/query", {"query": '{service_name="api"}'})

        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert response["Retry-After"] == "42"
        enforced.assert_called_once_with(self.team)
        budget_status.assert_called_once_with(self.team)
        self.request_mock.assert_not_called()

    @patch("posthog.api.snuffle_proxy.api_queries_budget_enforcement_enabled", return_value=False)
    @patch("posthog.api.snuffle_proxy.get_api_queries_budget_status")
    def test_disabled_byte_budget_does_not_read_budget_status(self, budget_status, enforced):
        response = self.client.get(f"{self.base}/query", {"query": '{service_name="api"}'})

        assert response.status_code == status.HTTP_200_OK
        enforced.assert_called_once_with(self.team)
        budget_status.assert_not_called()

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

    @override_settings(SNUFFLE_APM_URL="")
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

    def test_snuffle_flag_gates_the_api(self):
        with patch("posthoganalytics.feature_enabled", return_value=False):
            response = self.client.get(f"{self.base}/labels")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        self.request_mock.assert_not_called()

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

    @parameterized.expand([("bearer", "headers"), ("query_param", "query")])
    def test_public_project_token_does_not_authenticate(self, _name: str, placement: str):
        self.client.logout()
        project_token = self.team.api_token
        if placement == "headers":
            response = self.client.get(f"{self.base}/labels", headers={"authorization": f"Bearer {project_token}"})
        else:
            response = self.client.get(f"{self.base}/labels", {"api_key": project_token, "token": project_token})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        self.request_mock.assert_not_called()


class TestSnuffleBudgetDebit(SimpleTestCase):
    @patch("posthog.api.snuffle_proxy.debit")
    @patch("posthog.api.snuffle_proxy._get_snuffle_budget_debit_executor")
    def test_debit_runs_after_scheduling(self, executor, debit_mock):
        pending: list = []
        executor.return_value.submit.side_effect = pending.append

        snuffle_proxy.schedule_snuffle_budget_debit("1", 1234)

        debit_mock.assert_not_called()
        (debit_task,) = pending
        debit_task()
        debit_mock.assert_called_once_with("1", 1234)


@override_settings(**SNUFFLE_APM_SETTINGS)
class TestSnuffleRequest(SimpleTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("posthog.api.snuffle_proxy.internal_requests.request", return_value=_upstream())
        self.request_mock = patcher.start()
        self.addCleanup(patcher.stop)
        tokens = tempfile.TemporaryDirectory()
        self.addCleanup(tokens.cleanup)
        self.tokens = Path(tokens.name)

    def _register(self, *users: ClickHouseUser) -> None:
        registered = {ClickHouseUser.DEFAULT: ClickHouseCredentials(user="default", password="main-cluster")}
        for user in users:
            token = self.tokens / user.value
            token.write_text(f"{user.value}-token-1")
            registered[user] = ClickHouseCredentials(user=user.value, password="", password_file=str(token))
        user_dict = patch.object(connection, "__user_dict", registered)
        user_dict.start()
        self.addCleanup(user_dict.stop)

    @parameterized.expand(
        [
            ("logql_signal_user", "/loki/api/v1/query_range", True, ("logs", "logs-token-1")),
            ("logql_fallback", "/loki/api/v1/query_range", False, ("reader", "secret")),
            ("promql_signal_user", "/api/v1/query_range", True, ("metrics", "metrics-token-1")),
            ("promql_fallback", "/api/v1/query_range", False, ("reader", "secret")),
        ]
    )
    def test_credential_follows_the_signal_of_the_route(
        self, _name: str, path: str, registered: bool, expected_auth: tuple[str, str]
    ):
        self._register(*((ClickHouseUser.LOGS, ClickHouseUser.METRICS) if registered else ()))

        snuffle_proxy.snuffle_request(1, "GET", path)

        assert self.request_mock.call_args.kwargs["auth"] == expected_auth

    def test_signal_user_token_is_read_on_each_request(self):
        self._register(ClickHouseUser.METRICS)

        snuffle_proxy.snuffle_request(1, "GET", "/api/v1/query")
        (self.tokens / "metrics").write_text("metrics-token-2")
        snuffle_proxy.snuffle_request(1, "GET", "/api/v1/query")

        assert [call.kwargs["auth"] for call in self.request_mock.call_args_list] == [
            ("metrics", "metrics-token-1"),
            ("metrics", "metrics-token-2"),
        ]

    @parameterized.expand(
        [
            ("logql_route_product", "/loki/api/v1/query_range", None, "logs"),
            ("promql_route_product", "/api/v1/query_range", None, "metrics"),
            ("route_product_wins_over_the_tag", "/api/v1/query_range", Product.MAX_AI, "metrics"),
        ]
    )
    def test_query_tags_header_carries_log_comment_tags_without_the_team(
        self, _name: str, path: str, product: Product | None, expected_product: str
    ):
        org_id = uuid.uuid4()
        reset_query_tags()
        with tags_context(
            team_id=99,
            user_id=7,
            org_id=org_id,
            kind="request",
            id="/api/projects/99/metrics/prometheus/api/v1/query_range",
            route_id="api/projects/{parent_lookup_team_id}/metrics/prometheus/",
            access_method=AccessMethod.PERSONAL_API_KEY,
            feature=Feature.QUERY,
            query_type="SnuffleQuery",
            http_user_agent="grafana",
            chargeable=1,
            is_impersonated=False,
            dashboard_id=12,
            **({"product": product} if product else {}),
        ):
            snuffle_proxy.snuffle_request(99, "GET", path)

        header = json.loads(self.request_mock.call_args.kwargs["headers"]["X-PostHog-Query-Tags"])
        assert header == {
            "access_method": "personal_api_key",
            "dashboard_id": 12,
            "feature": "query",
            "id": "/api/projects/99/metrics/prometheus/api/v1/query_range",
            "is_impersonated": False,
            "kind": "request",
            "org_id": str(org_id),
            "product": expected_product,
            "route_id": "api/projects/{parent_lookup_team_id}/metrics/prometheus/",
            "user_id": 7,
        }
        forwarded_keys = (
            snuffle_proxy.FORWARDED_STRING_TAGS | snuffle_proxy.FORWARDED_INT_TAGS | snuffle_proxy.FORWARDED_BOOL_TAGS
        )
        assert {*forwarded_keys, "product"} <= {*_V3_LOG_COMMENT_FIELDS, *_V3_LOG_COMMENT_TRAILING_FIELDS}

    def test_oversized_query_tags_shrink_to_the_product(self):
        reset_query_tags()
        with tags_context(kind="request", name="x" * 5000):
            snuffle_proxy.snuffle_request(99, "GET", "/loki/api/v1/query_range")

        assert self.request_mock.call_args.kwargs["headers"]["X-PostHog-Query-Tags"] == '{"product":"logs"}'
