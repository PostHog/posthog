from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.servicenow import (
    ServiceNowAuthMethodConfig,
    ServiceNowSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow import servicenow as servicenow_module
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.servicenow import (
    SERVICENOW_API_VERSION_V1,
    SERVICENOW_API_VERSION_V2,
    ServiceNowAuth,
    ServiceNowResumeConfig,
    _format_datetime,
    _table_api_url,
    normalize_instance_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.settings import SERVICENOW_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.source import ServiceNowSource


def _result_response(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"result": rows})


class TestNormalizeInstanceUrl:
    @parameterized.expand(
        [
            ("full_url", "https://acme.service-now.com", "https://acme.service-now.com"),
            ("trailing_slash", "https://acme.service-now.com/", "https://acme.service-now.com"),
            ("http_upgraded_host_only", "http://acme.service-now.com", "https://acme.service-now.com"),
            ("bare_subdomain", "dev12345", "https://dev12345.service-now.com"),
            ("host_with_dot_no_scheme", "acme.service-now.com", "https://acme.service-now.com"),
            ("whitespace", "  acme.service-now.com  ", "https://acme.service-now.com"),
            ("strips_path_and_query", "https://acme.service-now.com/foo?x=1", "https://acme.service-now.com"),
            ("strips_path_no_scheme", "acme.service-now.com/foo", "https://acme.service-now.com"),
            ("strips_userinfo", "https://user:pass@acme.service-now.com", "https://acme.service-now.com"),
            ("keeps_port", "https://acme.service-now.com:8443", "https://acme.service-now.com:8443"),
        ]
    )
    def test_normalize(self, _name: str, value: str, expected: str) -> None:
        assert normalize_instance_url(value) == expected

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            normalize_instance_url("")


class TestFormatDatetime:
    @parameterized.expand(
        [
            ("none", None, None),
            ("utc_datetime", datetime(2024, 3, 4, 2, 58, 14, tzinfo=UTC), "2024-03-04 02:58:14"),
            ("naive_datetime", datetime(2024, 3, 4, 2, 58, 14), "2024-03-04 02:58:14"),
            ("date_value", date(2024, 3, 4), "2024-03-04 00:00:00"),
            ("string_passthrough", "2024-03-04 02:58:14", "2024-03-04 02:58:14"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str | None) -> None:
        assert _format_datetime(value) == expected


class TestTableApiUrl:
    @parameterized.expand(
        [
            # v1 keeps the versionless path so existing syncs are unchanged.
            ("v1", SERVICENOW_API_VERSION_V1, "https://acme.service-now.com/api/now/table/incident"),
            ("v2", SERVICENOW_API_VERSION_V2, "https://acme.service-now.com/api/now/v2/table/incident"),
            # an unrecognized pin falls back to the versionless path.
            ("unknown", "v99", "https://acme.service-now.com/api/now/table/incident"),
        ]
    )
    def test_url_for_version(self, _name: str, api_version: str, expected: str) -> None:
        assert _table_api_url("https://acme.service-now.com", "incident", api_version) == expected


class TestServiceNowAuth:
    def test_basic_auth(self) -> None:
        auth = ServiceNowAuth(username="admin", password="secret")
        assert "x-sn-apikey" not in auth.headers()
        assert auth.basic_auth() == ("admin", "secret")

    def test_basic_auth_config(self) -> None:
        config = ServiceNowAuth(username="admin", password="secret").to_auth_config()
        assert config == {"type": "http_basic", "username": "admin", "password": "secret"}


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("forbidden_no_table_accepted", 403, None, True),
            ("not_found", 404, None, False),
            ("forbidden_with_table_rejected", 403, "incident", False),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, table: str | None, expected_valid: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={"result": []}))):
            valid, _ = validate_credentials(
                "https://acme.service-now.com",
                ServiceNowAuth(api_key="x"),
                team_id=1,
                table=table,
                api_version=SERVICENOW_API_VERSION_V1,
            )
        assert valid is expected_valid

    def test_redirect_is_rejected(self) -> None:
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://internal.example/api"})]
        ) as network:
            valid, error = validate_credentials(
                "https://acme.service-now.com",
                ServiceNowAuth(api_key="x"),
                team_id=1,
                api_version=SERVICENOW_API_VERSION_V1,
            )
        assert valid is False
        assert error is not None
        # redirects must not be followed (SSRF guard)
        assert len(network.requests_log) == 1

    def test_invalid_instance_url(self) -> None:
        valid, error = validate_credentials(
            "", ServiceNowAuth(api_key="x"), team_id=1, api_version=SERVICENOW_API_VERSION_V1
        )
        assert valid is False
        assert error is not None


class TestServiceNowSourcePagination:
    def _run(
        self,
        script: list[ScriptedResponse],
        resume_state: ServiceNowResumeConfig | None = None,
        api_version: str = SERVICENOW_API_VERSION_V1,
        **inputs: Any,
    ) -> DriveResult:
        config = ServiceNowSourceConfig(
            instance_url="https://acme.service-now.com",
            auth_method=ServiceNowAuthMethodConfig(selection="api_key", api_key="x"),
        )
        return SourceDriver(ServiceNowSource(), config).run(
            "incidents", script, resume_state=resume_state, api_version=api_version, **inputs
        )

    def test_paginates_until_short_page(self) -> None:
        # limit=2: a full page continues, the short page terminates iteration.
        with mock.patch.object(servicenow_module, "DEFAULT_PAGE_SIZE", 2):
            result = self._run(
                [_result_response([{"sys_id": "1"}, {"sys_id": "2"}]), _result_response([{"sys_id": "3"}])]
            )

        assert [r["sys_id"] for r in result.rows] == ["1", "2", "3"]
        assert result.params("sysparm_offset") == ["0", "2"]
        assert result.requests[0].param("sysparm_limit") == "2"
        # Static Table API params ride on every request.
        assert result.requests[0].param("sysparm_display_value") == "false"
        assert result.requests[0].param("sysparm_exclude_reference_link") == "true"
        # Checkpoint saved after the first full page (points at the next offset); the short page ends it.
        assert result.saved_states == [ServiceNowResumeConfig(offset=2)]

    def test_resumes_from_saved_offset(self) -> None:
        with mock.patch.object(servicenow_module, "DEFAULT_PAGE_SIZE", 2):
            result = self._run([_result_response([{"sys_id": "5"}])], ServiceNowResumeConfig(offset=4))

        assert [r["sys_id"] for r in result.rows] == ["5"]
        assert result.requests[0].param("sysparm_offset") == "4"

    def test_incremental_query_in_params(self) -> None:
        with mock.patch.object(servicenow_module, "DEFAULT_PAGE_SIZE", 2):
            result = self._run(
                [_result_response([])],
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
                incremental_field="sys_updated_on",
            )

        assert result.requests[0].param("sysparm_query") == "sys_updated_on>=2024-01-01 00:00:00^ORDERBYsys_updated_on"

    @parameterized.expand(
        [
            (SERVICENOW_API_VERSION_V1, "https://acme.service-now.com/api/now/table/incident"),
            (SERVICENOW_API_VERSION_V2, "https://acme.service-now.com/api/now/v2/table/incident"),
        ]
    )
    def test_version_selects_request_url(self, api_version: str, expected_url: str) -> None:
        with mock.patch.object(servicenow_module, "DEFAULT_PAGE_SIZE", 2):
            result = self._run([_result_response([{"sys_id": "1"}])], api_version=api_version)

        assert result.requests[0].url.split("?")[0] == expected_url


class TestServiceNowSourceShape:
    @parameterized.expand(list(SERVICENOW_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        config = ServiceNowSourceConfig(
            instance_url="https://acme.service-now.com",
            auth_method=ServiceNowAuthMethodConfig(selection="api_key", api_key="x"),
        )
        result = SourceDriver(ServiceNowSource(), config).run(
            endpoint, [_result_response([])], api_version=SERVICENOW_API_VERSION_V1
        )

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["sys_id"]
        assert response.partition_keys == ["sys_created_on"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"
