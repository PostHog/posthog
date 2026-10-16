from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.optimizely import (
    OptimizelySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.optimizely import (
    optimizely_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.settings import (
    ENDPOINTS,
    OPTIMIZELY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.optimizely.source import OptimizelySource


def _driver() -> SourceDriver:
    return SourceDriver(OptimizelySource(), OptimizelySourceConfig(api_token="token"))


def _response(items: list[dict[str, Any]], *, status: int = 200, next_url: str | None = None) -> ScriptedResponse:
    headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
    return ScriptedResponse(status=status, json=items, headers=headers)


class TestValidateCredentials:
    @parameterized.expand([(200, True), (403, True), (401, False)])
    def test_status_mapping(self, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("token") is expected

        assert [request.path for request in network.requests_log] == ["/v2/projects"]
        assert network.requests_log[0].param("per_page") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer token"
        assert network.session_options[0]["redact_values"] == ("token",)


class TestSimpleEndpoint:
    @parameterized.expand(
        [
            ("attacker_host", "https://evil.example.com/v2/projects?page=2&per_page=100"),
            ("subdomain_spoof", "https://api.optimizely.com.evil.com/v2/projects?page=2"),
            ("internal_metadata", "http://169.254.169.254/latest/meta-data/"),
        ]
    )
    def test_refuses_to_follow_offhost_next_link(self, _name: str, off_host_url: str) -> None:
        # A hostile upstream points the `Link` next URL off-host; the credentialed request must never
        # be sent. The old transport stopped silently; the framework fails loud instead — but the
        # security guarantee (the off-host URL is never fetched) is identical.
        result = _driver().run("projects", [_response([{"id": 1}], next_url=off_host_url)])

        assert isinstance(result.raised, ValueError)
        assert off_host_url not in result.urls
        assert result.urls == ["https://api.optimizely.com/v2/projects?per_page=100"]


class TestProjectScopedFanOut:
    @parameterized.expand([(400,), (403,), (404,)])
    def test_skips_projects_without_feature_access(self, skip_status: int) -> None:
        result = _driver().run(
            "campaigns",
            route(
                {
                    "/v2/projects": [_response([{"id": 11}, {"id": 22}])],
                    "/v2/campaigns": [
                        _response([], status=skip_status),
                        _response([{"id": "camp-22"}]),
                    ],
                }
            ),
        )

        # Project 11 lacks access (4xx) and is skipped; project 22 still syncs.
        assert result.raised is None
        assert result.paths == ["/v2/projects", "/v2/campaigns", "/v2/campaigns"]
        assert result.params("project_id") == [None, "11", "22"]
        assert [row["id"] for row in result.rows] == ["camp-22"]

    def test_raises_on_unexpected_child_error(self) -> None:
        # 401 is not in the skip set (400/403/404), so it fails the whole stream loudly.
        result = _driver().run(
            "experiments",
            route(
                {
                    "/v2/projects": [_response([{"id": 11}])],
                    "/v2/experiments": [_response([], status=401)],
                }
            ),
        )

        assert isinstance(result.raised, requests.HTTPError)
        assert result.paths == ["/v2/projects", "/v2/experiments"]
        assert result.requests[1].param("project_id") == "11"


class TestOptimizelySourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = OPTIMIZELY_ENDPOINTS[endpoint]
        response = optimizely_source("token", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
