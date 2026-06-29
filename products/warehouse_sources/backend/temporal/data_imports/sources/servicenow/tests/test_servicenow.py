from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow import servicenow as servicenow_module
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.servicenow import (
    ServiceNowAuth,
    ServiceNowResumeConfig,
    _format_datetime,
    build_sysparm_query,
    get_rows,
    normalize_instance_url,
    servicenow_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicenow.settings import SERVICENOW_ENDPOINTS


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

    def raise_for_status(self) -> None:
        if not self.ok:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(f"{self.status_code} Client Error", response=response)


class FakeResumeManager:
    def __init__(self, initial: ServiceNowResumeConfig | None = None):
        self.state = initial
        self.saved: list[ServiceNowResumeConfig] = []

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> ServiceNowResumeConfig | None:
        return self.state

    def save_state(self, data: ServiceNowResumeConfig) -> None:
        self.state = data
        self.saved.append(data)


def _patch_session(get_mock: mock.Mock) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get = get_mock
    return session


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


class TestServiceNowAuth:
    def test_api_key_headers(self) -> None:
        auth = ServiceNowAuth(api_key="abc")
        assert auth.headers()["x-sn-apikey"] == "abc"
        assert auth.basic_auth() is None

    def test_basic_auth(self) -> None:
        auth = ServiceNowAuth(username="admin", password="secret")
        assert "x-sn-apikey" not in auth.headers()
        assert auth.basic_auth() == ("admin", "secret")


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
                "https://acme.service-now.com", ServiceNowAuth(api_key="x"), team_id=1, table=table
            )
        assert valid is expected_valid

    def test_redirect_is_rejected(self) -> None:
        get_mock = mock.Mock(return_value=FakeResponse(status_code=302))
        with mock.patch.object(servicenow_module, "make_tracked_session", return_value=_patch_session(get_mock)):
            valid, error = validate_credentials("https://acme.service-now.com", ServiceNowAuth(api_key="x"), team_id=1)
        assert valid is False
        assert error is not None
        # redirects must not be followed (SSRF guard)
        assert get_mock.call_args.kwargs["allow_redirects"] is False

    def test_invalid_instance_url(self) -> None:
        valid, error = validate_credentials("", ServiceNowAuth(api_key="x"), team_id=1)
        assert valid is False
        assert error is not None

    def test_network_error_is_handled(self) -> None:
        get_mock = mock.Mock(side_effect=requests.ConnectionError("boom"))
        with mock.patch.object(servicenow_module, "make_tracked_session", return_value=_patch_session(get_mock)):
            valid, error = validate_credentials("https://acme.service-now.com", ServiceNowAuth(api_key="x"), team_id=1)
        assert valid is False
        assert error is not None


class TestGetRows:
    def _run(
        self,
        pages: dict[int, list[dict[str, Any]]],
        manager: FakeResumeManager,
        page_size: int = 2,
        **kwargs: Any,
    ) -> tuple[list[list[dict[str, Any]]], list[dict[str, Any]]]:
        captured_params: list[dict[str, Any]] = []

        def fake_get(url: str, params: dict[str, Any], **_: Any) -> FakeResponse:
            captured_params.append(params)
            offset = params["sysparm_offset"]
            return FakeResponse(json_data={"result": pages.get(offset, [])})

        get_mock = mock.Mock(side_effect=fake_get)
        with (
            mock.patch.object(servicenow_module, "DEFAULT_PAGE_SIZE", page_size),
            mock.patch.object(servicenow_module, "make_tracked_session", return_value=_patch_session(get_mock)),
        ):
            batches = list(
                get_rows(
                    base_url="https://acme.service-now.com",
                    table="incident",
                    auth=ServiceNowAuth(api_key="x"),
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,  # type: ignore[arg-type]
                    **kwargs,
                )
            )
        return batches, captured_params

    def test_paginates_until_short_page(self) -> None:
        pages = {
            0: [{"sys_id": "1"}, {"sys_id": "2"}],
            2: [{"sys_id": "3"}],  # short page terminates iteration
        }
        manager = FakeResumeManager()
        batches, params = self._run(pages, manager, page_size=2)

        assert [len(b) for b in batches] == [2, 1]
        # state saved after each yielded batch, pointing at the next offset
        assert [s.offset for s in manager.saved] == [2, 4]
        assert params[0]["sysparm_offset"] == 0
        assert params[1]["sysparm_offset"] == 2

    def test_empty_first_page_yields_nothing(self) -> None:
        manager = FakeResumeManager()
        batches, _ = self._run({0: []}, manager, page_size=2)
        assert batches == []
        assert manager.saved == []

    def test_resumes_from_saved_offset(self) -> None:
        pages = {
            4: [{"sys_id": "5"}],
        }
        manager = FakeResumeManager(initial=ServiceNowResumeConfig(offset=4))
        batches, params = self._run(pages, manager, page_size=2)

        assert [len(b) for b in batches] == [1]
        assert params[0]["sysparm_offset"] == 4

    def test_incremental_query_in_params(self) -> None:
        manager = FakeResumeManager()
        _, params = self._run(
            {0: []},
            manager,
            page_size=2,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="sys_updated_on",
        )
        assert params[0]["sysparm_query"] == "sys_updated_on>=2024-01-01 00:00:00^ORDERBYsys_updated_on"

    def test_full_refresh_query_in_params(self) -> None:
        manager = FakeResumeManager()
        _, params = self._run({0: []}, manager, page_size=2, should_use_incremental_field=False)
        assert params[0]["sysparm_query"] == "ORDERBYsys_created_on"


class TestServiceNowSource:
    @parameterized.expand(list(SERVICENOW_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = servicenow_source(
            instance_url="https://acme.service-now.com",
            auth=ServiceNowAuth(api_key="x"),
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),  # type: ignore[arg-type]
            team_id=1,
        )
        assert response.name == endpoint
        assert response.primary_keys == ["sys_id"]
        assert response.partition_keys == ["sys_created_on"]
        assert response.partition_mode == "datetime"
        assert response.sort_mode == "asc"
