from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightdash import lightdash as lightdash_module
from products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.lightdash import (
    HOST_NOT_ALLOWED_ERROR,
    LightdashHostNotAllowedError,
    get_resource,
    lightdash_source,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.settings import LIGHTDASH_ENDPOINTS


class _FakeDltResource:
    def __init__(self, name: str, rows: list[dict]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper):
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self):
        return iter(self._rows)


class TestNormalizeHost:
    @parameterized.expand(
        [
            ("bare_host", "app.lightdash.cloud", "https://app.lightdash.cloud"),
            ("https_host", "https://app.lightdash.cloud", "https://app.lightdash.cloud"),
            ("trailing_slash", "https://app.lightdash.cloud/", "https://app.lightdash.cloud"),
            ("trailing_api_path", "https://app.lightdash.cloud/api/v1", "https://app.lightdash.cloud"),
            ("whitespace", "  app.lightdash.cloud  ", "https://app.lightdash.cloud"),
            ("loopback_http_kept", "http://localhost:8080", "http://localhost:8080"),
            ("loopback_ip_http_kept", "http://127.0.0.1:8080", "http://127.0.0.1:8080"),
            ("remote_http_upgraded", "http://lightdash.example.com", "https://lightdash.example.com"),
            ("uppercase_scheme", "HTTP://lightdash.example.com/api/v1/", "https://lightdash.example.com"),
        ]
    )
    def test_normalize_host(self, _name: str, raw: str, expected: str) -> None:
        assert normalize_host(raw) == expected


class TestValidateCredentials:
    def test_403_at_source_create_is_accepted(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]):
            assert validate_credentials("https://x.lightdash.cloud", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self) -> None:
        with scripted_network([ScriptedResponse(status=403)]):
            valid, msg = validate_credentials("https://x.lightdash.cloud", "tok", schema_name="projects")
            assert valid is False
            assert msg is not None

    @pytest.mark.parametrize("bad_host", ["", "https://", "not a host!"])
    def test_invalid_host_short_circuits(self, bad_host: str) -> None:
        valid, msg = validate_credentials(bad_host, "tok")
        assert valid is False
        assert msg == "Invalid Lightdash instance URL"

    def test_rejects_redirect_response(self) -> None:
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://other.example.com/api/v1/user"})]
        ) as network:
            valid, msg = validate_credentials("https://x.lightdash.cloud", "tok")
            assert valid is False
            assert msg == HOST_NOT_ALLOWED_ERROR
            assert [request.path for request in network.requests_log] == ["/api/v1/user"]

    def test_blocks_unsafe_host(self) -> None:
        with (
            mock.patch.object(lightdash_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network([ScriptedResponse(status=200)]) as network,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            assert network.requests_log == []

    def test_probes_user_endpoint_with_api_key_header(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("https://x.lightdash.cloud", "tok") == (True, None)
            assert len(network.requests_log) == 1
            request = network.requests_log[0]
            assert request.method == "GET"
            assert request.url == "https://x.lightdash.cloud/api/v1/user"
            assert request.headers["authorization"] == "ApiKey tok"


class TestGetResource:
    def test_fanout_endpoint_raises_via_get_resource(self) -> None:
        with pytest.raises(ValueError, match="fan-out path"):
            get_resource(LIGHTDASH_ENDPOINTS["spaces"])


class TestLightdashSourceResponse:
    @parameterized.expand(
        [
            ("projects", ["projectUuid"], "createdAt", "asc"),
            ("spaces", ["uuid"], None, None),
            ("dashboards", ["uuid"], None, None),
            ("charts", ["uuid"], None, None),
            ("metrics_catalog", ["catalogSearchUuid"], None, None),
            ("org_users", ["userUuid"], "userCreatedAt", "asc"),
            ("explores", ["projectUuid", "name"], None, None),
            ("schedulers", ["schedulerUuid"], "createdAt", None),
            ("scheduler_runs", ["runId"], "scheduledTime", None),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.lightdash.rest_api_resource"
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_response_shape(
        self,
        endpoint: str,
        primary_keys: list[str],
        partition_key: str | None,
        sort_mode: str | None,
        mock_rest_api_resources: mock.MagicMock,
        mock_rest_api_resource: mock.MagicMock,
    ) -> None:
        mock_rest_api_resource.return_value = mock.MagicMock()
        mock_rest_api_resources.return_value = [
            _FakeDltResource("projects", [{"projectUuid": "p1"}]),
            _FakeDltResource(endpoint, [{"_projects_projectUuid": "p1"}]),
        ]

        response = lightdash_source(
            instance_url="https://x.lightdash.cloud", api_token="tok", endpoint=endpoint, team_id=1, job_id="job-1"
        )

        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        assert response.sort_mode == sort_mode
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestLightdashSourceTransport:
    @parameterized.expand(
        [
            ("explores", "/api/v1/projects/{projectUuid}/explores", {}),
            (
                "schedulers",
                "/api/v1/schedulers/{projectUuid}/list",
                {"sortBy": "createdAt", "sortDirection": "asc", "pageSize": 100},
            ),
            (
                "scheduler_runs",
                "/api/v1/schedulers/{projectUuid}/runs",
                {"sortBy": "scheduledTime", "sortDirection": "asc", "pageSize": 100},
            ),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_child_request_params(
        self, endpoint: str, path: str, params: dict[str, Any], mock_rest_api_resources: mock.MagicMock
    ) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("projects", []),
            _FakeDltResource(endpoint, []),
        ]

        lightdash_source(
            instance_url="https://x.lightdash.cloud", api_token="tok", endpoint=endpoint, team_id=1, job_id="job-1"
        )

        resources = mock_rest_api_resources.call_args.args[0]["resources"]
        child = next(r for r in resources if isinstance(r, dict) and r["name"] == endpoint)
        assert child["endpoint"]["path"] == path
        assert {k: v for k, v in child["endpoint"]["params"].items() if k != "projectUuid"} == params

    def test_blocks_unsafe_host_at_runtime(self) -> None:
        with mock.patch.object(lightdash_module, "_is_host_safe", return_value=(False, "internal address")):
            with pytest.raises(LightdashHostNotAllowedError):
                lightdash_source(
                    instance_url="https://10.0.0.1", api_token="tok", endpoint="projects", team_id=1, job_id="job-1"
                )

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout.rest_api_resources"
    )
    def test_spaces_fanout_injects_parent_project_id(self, mock_rest_api_resources: mock.MagicMock) -> None:
        mock_rest_api_resources.return_value = [
            _FakeDltResource("projects", [{"projectUuid": "proj_1"}]),
            _FakeDltResource("spaces", [{"uuid": "space_1", "_projects_projectUuid": "proj_1"}]),
        ]

        response = lightdash_source(
            instance_url="https://x.lightdash.cloud", api_token="tok", endpoint="spaces", team_id=1, job_id="job-1"
        )

        rows = list(cast(Any, response.items()))
        assert rows == [{"uuid": "space_1", "projectUuid": "proj_1"}]
