import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow import servicenow as servicenow_module
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.servicenow import (
    SERVICENOW_API_VERSION_V1,
    SERVICENOW_API_VERSION_V2,
    ServiceNowAuth,
    ServiceNowResumeConfig,
    _format_datetime,
    _table_api_url,
    build_sysparm_query,
    normalize_instance_url,
    servicenow_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.settings import SERVICENOW_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = ""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {"result": []}
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        return self._json


def _patch_session(get_mock: mock.Mock) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get = get_mock
    return session


def _result_response(rows: list[dict[str, Any]]) -> Response:
    resp = Response()
    resp.status_code = 200
    resp._content = json.dumps({"result": rows}).encode()
    return resp


def _make_manager(resume_state: ServiceNowResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> tuple[list[dict[str, Any]], list[str]]:
    """Snapshot each request's params and URL AT SEND TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the run
    shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    param_snapshots: list[dict[str, Any]] = []
    url_snapshots: list[str] = []

    def _prepare(request: Any) -> mock.MagicMock:
        param_snapshots.append(dict(request.params or {}))
        url_snapshots.append(request.url)
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return param_snapshots, url_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


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

    def test_aware_non_utc_is_converted(self) -> None:
        from datetime import timedelta, timezone

        aware = datetime(2024, 3, 4, 5, 0, 0, tzinfo=timezone(timedelta(hours=3)))
        assert _format_datetime(aware) == "2024-03-04 02:00:00"


class TestBuildSysparmQuery:
    def test_incremental_query(self) -> None:
        query = build_sysparm_query("sys_updated_on", "2024-01-01 00:00:00", "sys_updated_on")
        assert query == "sys_updated_on>=2024-01-01 00:00:00^ORDERBYsys_updated_on"

    def test_full_refresh_query_orders_only(self) -> None:
        query = build_sysparm_query(None, None, "sys_created_on")
        assert query == "ORDERBYsys_created_on"

    def test_no_value_drops_filter(self) -> None:
        query = build_sysparm_query("sys_updated_on", None, "sys_updated_on")
        assert query == "ORDERBYsys_updated_on"


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
    def test_api_key_headers(self) -> None:
        auth = ServiceNowAuth(api_key="abc")
        assert auth.headers()["x-sn-apikey"] == "abc"
        assert auth.basic_auth() is None

    def test_basic_auth(self) -> None:
        auth = ServiceNowAuth(username="admin", password="secret")
        assert "x-sn-apikey" not in auth.headers()
        assert auth.basic_auth() == ("admin", "secret")

    def test_api_key_auth_config(self) -> None:
        config = ServiceNowAuth(api_key="abc").to_auth_config()
        assert config == {"type": "api_key", "api_key": "abc", "name": "x-sn-apikey", "location": "header"}

    def test_basic_auth_config(self) -> None:
        config = ServiceNowAuth(username="admin", password="secret").to_auth_config()
        assert config == {"type": "http_basic", "username": "admin", "password": "secret"}


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_no_table_accepted", 403, None, True),
            ("not_found", 404, None, False),
            ("forbidden_with_table_rejected", 403, "incident", False),
            ("ok_with_table", 200, "incident", True),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, table: str | None, expected_valid: bool) -> None:
        get_mock = mock.Mock(return_value=FakeResponse(status_code=status))
        with mock.patch.object(servicenow_module, "make_tracked_session", return_value=_patch_session(get_mock)):
            valid, _ = validate_credentials(
                "https://acme.service-now.com",
                ServiceNowAuth(api_key="x"),
                team_id=1,
                table=table,
                api_version=SERVICENOW_API_VERSION_V1,
            )
        assert valid is expected_valid

    def test_redirect_is_rejected(self) -> None:
        get_mock = mock.Mock(return_value=FakeResponse(status_code=302))
        with mock.patch.object(servicenow_module, "make_tracked_session", return_value=_patch_session(get_mock)):
            valid, error = validate_credentials(
                "https://acme.service-now.com",
                ServiceNowAuth(api_key="x"),
                team_id=1,
                api_version=SERVICENOW_API_VERSION_V1,
            )
        assert valid is False
        assert error is not None
        # redirects must not be followed (SSRF guard)
        assert get_mock.call_args.kwargs["allow_redirects"] is False

    def test_invalid_instance_url(self) -> None:
        valid, error = validate_credentials(
            "", ServiceNowAuth(api_key="x"), team_id=1, api_version=SERVICENOW_API_VERSION_V1
        )
        assert valid is False
        assert error is not None

    def test_network_error_is_handled(self) -> None:
        get_mock = mock.Mock(side_effect=requests.ConnectionError("boom"))
        with mock.patch.object(servicenow_module, "make_tracked_session", return_value=_patch_session(get_mock)):
            valid, error = validate_credentials(
                "https://acme.service-now.com",
                ServiceNowAuth(api_key="x"),
                team_id=1,
                api_version=SERVICENOW_API_VERSION_V1,
            )
        assert valid is False
        assert error is not None


class TestServiceNowSourcePagination:
    def _source(self, manager: mock.MagicMock, **kwargs: Any):
        return servicenow_source(
            instance_url="https://acme.service-now.com",
            auth=ServiceNowAuth(api_key="x"),
            endpoint="incidents",
            resumable_source_manager=manager,
            team_id=1,
            job_id="job-1",
            **kwargs,
        )

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_until_short_page(self, MockSession) -> None:
        session = MockSession.return_value
        # limit=2: a full page continues, the short page terminates iteration.
        params, _ = _wire(
            session, [_result_response([{"sys_id": "1"}, {"sys_id": "2"}]), _result_response([{"sys_id": "3"}])]
        )

        with mock.patch.object(servicenow_module, "DEFAULT_PAGE_SIZE", 2):
            manager = _make_manager()
            rows = _rows(self._source(manager))

        assert [r["sys_id"] for r in rows] == ["1", "2", "3"]
        assert params[0]["sysparm_offset"] == 0
        assert params[0]["sysparm_limit"] == 2
        assert params[1]["sysparm_offset"] == 2
        # Static Table API params ride on every request.
        assert params[0]["sysparm_display_value"] == "false"
        assert params[0]["sysparm_exclude_reference_link"] == "true"
        # Checkpoint saved after the first full page (points at the next offset); the short page ends it.
        manager.save_state.assert_called_once_with(ServiceNowResumeConfig(offset=2))

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_first_page_yields_nothing(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(session, [_result_response([])])

        with mock.patch.object(servicenow_module, "DEFAULT_PAGE_SIZE", 2):
            manager = _make_manager()
            rows = _rows(self._source(manager))

        assert rows == []
        assert session.send.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_offset(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_result_response([{"sys_id": "5"}])])

        with mock.patch.object(servicenow_module, "DEFAULT_PAGE_SIZE", 2):
            manager = _make_manager(ServiceNowResumeConfig(offset=4))
            rows = _rows(self._source(manager))

        assert [r["sys_id"] for r in rows] == ["5"]
        assert params[0]["sysparm_offset"] == 4

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_query_in_params(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_result_response([])])

        with mock.patch.object(servicenow_module, "DEFAULT_PAGE_SIZE", 2):
            _rows(
                self._source(
                    _make_manager(),
                    should_use_incremental_field=True,
                    db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
                    incremental_field="sys_updated_on",
                )
            )

        assert params[0]["sysparm_query"] == "sys_updated_on>=2024-01-01 00:00:00^ORDERBYsys_updated_on"

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_query_in_params(self, MockSession) -> None:
        session = MockSession.return_value
        params, _ = _wire(session, [_result_response([])])

        with mock.patch.object(servicenow_module, "DEFAULT_PAGE_SIZE", 2):
            _rows(self._source(_make_manager(), should_use_incremental_field=False))

        assert params[0]["sysparm_query"] == "ORDERBYsys_created_on"

    @parameterized.expand(
        [
            (SERVICENOW_API_VERSION_V1, "https://acme.service-now.com/api/now/table/incident"),
            (SERVICENOW_API_VERSION_V2, "https://acme.service-now.com/api/now/v2/table/incident"),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_version_selects_request_url(self, api_version: str, expected_url: str, MockSession) -> None:
        session = MockSession.return_value
        _, urls = _wire(session, [_result_response([{"sys_id": "1"}])])

        with mock.patch.object(servicenow_module, "DEFAULT_PAGE_SIZE", 2):
            _rows(self._source(_make_manager(), api_version=api_version))

        assert urls[0] == expected_url


class TestServiceNowSourceShape:
    @parameterized.expand(list(SERVICENOW_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = servicenow_source(
            instance_url="https://acme.service-now.com",
            auth=ServiceNowAuth(api_key="x"),
            endpoint=endpoint,
            resumable_source_manager=_make_manager(),
            team_id=1,
            job_id="job-1",
        )
        assert response.name == endpoint
        assert response.primary_keys == ["sys_id"]
        assert response.partition_keys == ["sys_created_on"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"
