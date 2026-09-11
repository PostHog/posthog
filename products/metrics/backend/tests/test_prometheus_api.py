"""Viewset tests for the Grafana-facing Prometheus reverse proxy.

Snuffle is mocked at the `forward_prometheus_request` seam, so these cover the
PostHog-side contract: auth, scope, both feature flags, the allowlist, the
tenant header binding, and the failure envelope.
"""

import json

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.metrics.backend.facade.contracts import METRICS_FEATURE_FLAG, METRICS_PROMETHEUS_API_FEATURE_FLAG
from products.metrics.backend.prometheus_proxy import PrometheusUpstreamResponse, PrometheusUpstreamUnavailable


def _flags(prometheus_enabled: bool = True, metrics_enabled: bool = True):
    def _enabled(flag_key: str, *args: object, **kwargs: object) -> bool:
        if flag_key == METRICS_PROMETHEUS_API_FEATURE_FLAG:
            return prometheus_enabled
        if flag_key == METRICS_FEATURE_FLAG:
            return metrics_enabled
        return False

    return _enabled


def _upstream(path: str = "query_range", status_code: int = 200):
    return PrometheusUpstreamResponse(
        status_code=status_code,
        content=json.dumps({"status": "success", "data": {"resultType": "matrix", "result": []}}).encode(),
        content_type="application/json",
    )


def _base_url(team_id: int, path: str = "query_range") -> str:
    return f"/api/projects/{team_id}/metrics/prometheus/api/v1/{path}"


class TestPrometheusApiGate(APIBaseTest):
    @parameterized.expand(
        [
            ("both_on", True, True, status.HTTP_200_OK),
            ("prometheus_flag_off", False, True, status.HTTP_403_FORBIDDEN),
            ("metrics_flag_off", True, False, status.HTTP_403_FORBIDDEN),
            ("both_off", False, False, status.HTTP_403_FORBIDDEN),
        ]
    )
    def test_requires_both_flags(
        self, _name: str, prometheus_enabled: bool, metrics_enabled: bool, expected: int
    ) -> None:
        with (
            patch("posthoganalytics.feature_enabled", side_effect=_flags(prometheus_enabled, metrics_enabled)),
            patch(
                "products.metrics.backend.presentation.prometheus_api.forward_prometheus_request",
                return_value=_upstream(),
            ),
        ):
            response = self.client.get(_base_url(self.team.id), {"query": "up"})
        assert response.status_code == expected
        if expected == status.HTTP_403_FORBIDDEN:
            assert response.json().get("code") == "feature_flag_required"

    def test_personal_api_key_needs_metrics_read_scope(self) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="grafana", user=self.user, secure_value=hash_key_value(token), scopes=["error_tracking:read"]
        )
        self.client.logout()
        with patch("posthoganalytics.feature_enabled", side_effect=_flags()):
            response = self.client.get(_base_url(self.team.id), {"query": "up"}, headers={"authorization": f"Bearer {token}"})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert "metrics:read" in response.json()["detail"]

    def test_personal_api_key_with_metrics_read_scope_passes(self) -> None:
        token = generate_random_token_personal()
        PersonalAPIKey.objects.create(
            label="grafana", user=self.user, secure_value=hash_key_value(token), scopes=["metrics:read"]
        )
        self.client.logout()
        with (
            patch("posthoganalytics.feature_enabled", side_effect=_flags()),
            patch(
                "products.metrics.backend.presentation.prometheus_api.forward_prometheus_request",
                return_value=_upstream(),
            ),
        ):
            response = self.client.get(_base_url(self.team.id), {"query": "up"}, headers={"authorization": f"Bearer {token}"})
        assert response.status_code == status.HTTP_200_OK


class TestPrometheusApiAllowlist(APIBaseTest):
    @parameterized.expand([("write",), ("read",), ("admin/tsdb/snapshot",), ("status/config",)])
    def test_blocked_paths_return_404_envelope(self, path: str) -> None:
        with (
            patch("posthoganalytics.feature_enabled", side_effect=_flags()),
            patch(
                "products.metrics.backend.presentation.prometheus_api.forward_prometheus_request",
            ) as forward,
        ):
            response = self.client.post(_base_url(self.team.id, path))
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json()["status"] == "error"
        assert response.json()["errorType"] == "not_found"
        forward.assert_not_called()

    def test_buildinfo_is_forwarded(self) -> None:
        with (
            patch("posthoganalytics.feature_enabled", side_effect=_flags()),
            patch(
                "products.metrics.backend.presentation.prometheus_api.forward_prometheus_request",
                return_value=_upstream("status/buildinfo"),
            ) as forward,
        ):
            response = self.client.get(_base_url(self.team.id, "status/buildinfo"))
        assert response.status_code == status.HTTP_200_OK
        assert forward.call_args.kwargs["upstream_path"] == "status/buildinfo"

    def test_trailing_slash_routes(self) -> None:
        with (
            patch("posthoganalytics.feature_enabled", side_effect=_flags()),
            patch(
                "products.metrics.backend.presentation.prometheus_api.forward_prometheus_request",
                return_value=_upstream(),
            ),
        ):
            response = self.client.get(_base_url(self.team.id) + "/", {"query": "up"})
        assert response.status_code == status.HTTP_200_OK


class TestPrometheusApiForwarding(APIBaseTest):
    def test_team_header_bound_to_url_team(self) -> None:
        with (
            patch("posthoganalytics.feature_enabled", side_effect=_flags()),
            patch(
                "products.metrics.backend.presentation.prometheus_api.forward_prometheus_request",
                return_value=_upstream(),
            ) as forward,
        ):
            # A client-asserted X-Team-ID must be overridden by the URL team.
            self.client.get(_base_url(self.team.id), {"query": "up"}, headers={"X-Team-ID": "9999"})
        assert forward.call_args.kwargs["team_id"] == self.team.pk

    def test_upstream_status_and_body_pass_through(self) -> None:
        body = {"status": "error", "errorType": "bad_data", "error": "parse error"}
        with (
            patch("posthoganalytics.feature_enabled", side_effect=_flags()),
            patch(
                "products.metrics.backend.presentation.prometheus_api.forward_prometheus_request",
                return_value=PrometheusUpstreamResponse(
                    status_code=422, content=json.dumps(body).encode(), content_type="application/json"
                ),
            ),
        ):
            response = self.client.get(_base_url(self.team.id), {"query": "sum(("})
        assert response.status_code == 422
        assert response.json() == body

    def test_unconfigured_or_downstream_failure_is_503_envelope(self) -> None:
        with (
            patch("posthoganalytics.feature_enabled", side_effect=_flags()),
            patch(
                "products.metrics.backend.presentation.prometheus_api.forward_prometheus_request",
                side_effect=PrometheusUpstreamUnavailable("PromQL backend is not configured"),
            ),
        ):
            response = self.client.get(_base_url(self.team.id), {"query": "up"})
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["status"] == "error"
        assert response.json()["errorType"] == "unavailable"
