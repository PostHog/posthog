from typing import Any, cast

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
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
    def _patch_session(self, get_response: Any = None, raises: Exception | None = None):
        session = mock.MagicMock()
        if raises is not None:
            session.get.side_effect = raises
        else:
            session.get.return_value = get_response
        return mock.patch.object(lightdash_module, "make_tracked_session", return_value=session)

    @staticmethod
    def _response(status_code: int) -> mock.MagicMock:
        response = mock.MagicMock()
        response.status_code = status_code
        response.is_redirect = status_code in (301, 302, 303, 307, 308)
        response.is_permanent_redirect = status_code in (301, 308)
        return response

    def test_success(self) -> None:
        with self._patch_session(self._response(200)):
            assert validate_credentials("https://x.lightdash.cloud", "tok") == (True, None)

    def test_invalid_token(self) -> None:
        with self._patch_session(self._response(401)):
            valid, msg = validate_credentials("https://x.lightdash.cloud", "tok")
            assert valid is False
            assert msg is not None

    def test_403_at_source_create_is_accepted(self) -> None:
        with self._patch_session(self._response(403)):
            assert validate_credentials("https://x.lightdash.cloud", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self) -> None:
        with self._patch_session(self._response(403)):
            valid, msg = validate_credentials("https://x.lightdash.cloud", "tok", schema_name="projects")
            assert valid is False
            assert msg is not None

    @pytest.mark.parametrize("bad_host", ["", "https://", "not a host!"])
    def test_invalid_host_short_circuits(self, bad_host: str) -> None:
        valid, msg = validate_credentials(bad_host, "tok")
        assert valid is False
        assert msg == "Invalid Lightdash instance URL"

    def test_rejects_redirect_response(self) -> None:
        with self._patch_session(self._response(302)) as patched:
            valid, msg = validate_credentials("https://x.lightdash.cloud", "tok")
            assert valid is False
            assert msg == HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_blocks_unsafe_host(self) -> None:
        with (
            mock.patch.object(lightdash_module, "_is_host_safe", return_value=(False, "internal address")),
            self._patch_session(self._response(200)) as patched,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    def test_unexpected_status(self) -> None:
        with self._patch_session(self._response(500)):
            valid, msg = validate_credentials("https://x.lightdash.cloud", "tok")
            assert valid is False
            assert msg is not None and "500" in msg

    def test_handles_request_exception(self) -> None:
        with self._patch_session(raises=requests.exceptions.RequestException("boom")):
            valid, msg = validate_credentials("https://x.lightdash.cloud", "tok")
            assert valid is False
            assert msg is not None and "boom" in msg

    def test_probes_user_endpoint_with_api_key_header(self) -> None:
        with self._patch_session(self._response(200)) as patched:
            validate_credentials("https://x.lightdash.cloud", "tok")
            call = patched.return_value.get.call_args
            assert call.args[0] == "https://x.lightdash.cloud/api/v1/user"
            assert call.kwargs["headers"]["Authorization"] == "ApiKey tok"


class TestGetResource:
    def test_projects_unpaginated_bare_results(self) -> None:
        resource = cast(dict[str, Any], get_resource(LIGHTDASH_ENDPOINTS["projects"]))
        assert resource["name"] == "projects"
        assert resource["write_disposition"] == "replace"
        assert resource["endpoint"]["path"] == "/api/v1/org/projects"
        assert resource["endpoint"]["data_selector"] == "results"
        assert isinstance(resource["endpoint"]["paginator"], SinglePagePaginator)
        assert resource["endpoint"]["params"] == {}

    def test_org_users_paginated_nested_results(self) -> None:
        resource = cast(dict[str, Any], get_resource(LIGHTDASH_ENDPOINTS["org_users"]))
        assert resource["endpoint"]["data_selector"] == "results.data"
        paginator = resource["endpoint"]["paginator"]
        assert isinstance(paginator, PageNumberPaginator)
        assert paginator.total_path == "results.pagination.totalPageCount"
        assert resource["endpoint"]["params"] == {"pageSize": LIGHTDASH_ENDPOINTS["org_users"].page_size}

    def test_fanout_endpoint_raises_via_get_resource(self) -> None:
        with pytest.raises(ValueError, match="fan-out path"):
            get_resource(LIGHTDASH_ENDPOINTS["spaces"])


class TestLightdashSourceResponse:
    @parameterized.expand(
        [
            ("projects", ["projectUuid"], "createdAt"),
            ("spaces", ["uuid"], None),
            ("dashboards", ["uuid"], None),
            ("charts", ["uuid"], None),
            ("metrics_catalog", ["catalogSearchUuid"], None),
            ("org_users", ["userUuid"], "userCreatedAt"),
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
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None


class TestLightdashSourceTransport:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.lightdash.rest_api_resource"
    )
    def test_projects_top_level_uses_rest_api_resource(self, mock_rest_api_resource: mock.MagicMock) -> None:
        mock_rest_api_resource.return_value = mock.MagicMock()
        lightdash_source(
            instance_url="https://x.lightdash.cloud", api_token="tok", endpoint="projects", team_id=1, job_id="job-1"
        )

        rest_config = mock_rest_api_resource.call_args.args[0]
        assert rest_config["client"]["base_url"] == "https://x.lightdash.cloud"
        assert rest_config["client"]["auth"] == {
            "type": "api_key",
            "name": "Authorization",
            "api_key": "ApiKey tok",
            "location": "header",
        }
        assert rest_config["client"]["allow_redirects"] is False

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.lightdash.build_dependent_resource"
    )
    def test_spaces_fanout_wires_parent_and_child(self, mock_build_dependent_resource: mock.MagicMock) -> None:
        mock_build_dependent_resource.return_value = iter([])

        lightdash_source(
            instance_url="https://x.lightdash.cloud", api_token="tok", endpoint="spaces", team_id=1, job_id="job-1"
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] is None
        assert kwargs["parent_endpoint_extra"]["data_selector"] == "results"
        assert isinstance(kwargs["parent_endpoint_extra"]["paginator"], SinglePagePaginator)
        assert kwargs["child_endpoint_extra"]["data_selector"] == "results"
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], SinglePagePaginator)
        assert kwargs["child_params_extra"] is None
        assert kwargs["db_incremental_field_last_value"] is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.lightdash.lightdash.build_dependent_resource"
    )
    def test_metrics_catalog_fanout_paginates_child_only(self, mock_build_dependent_resource: mock.MagicMock) -> None:
        mock_build_dependent_resource.return_value = iter([])

        lightdash_source(
            instance_url="https://x.lightdash.cloud",
            api_token="tok",
            endpoint="metrics_catalog",
            team_id=1,
            job_id="job-1",
        )

        kwargs = mock_build_dependent_resource.call_args.kwargs
        assert kwargs["page_size_param"] is None
        assert isinstance(kwargs["child_endpoint_extra"]["paginator"], PageNumberPaginator)
        assert kwargs["child_endpoint_extra"]["data_selector"] == "results.data"
        assert kwargs["child_params_extra"] == {"pageSize": LIGHTDASH_ENDPOINTS["metrics_catalog"].page_size}

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
