from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.bamboohr import (
    INVALID_SUBDOMAIN_MESSAGE,
    BambooHRResumeConfig,
    _base_url,
    _build_url,
    _extract_records,
    _next_url,
    bamboohr_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.settings import BAMBOOHR_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.bamboohr"


def _mock_response(status_code: int = 200, payload: Any = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = payload if payload is not None else {}
    response.text = ""
    return response


def _mock_session_returning(*responses: MagicMock) -> MagicMock:
    session = MagicMock()
    session.get.side_effect = list(responses)
    return session


class TestExtractRecords:
    @parameterized.expand(
        [
            (
                "employees_directory",
                "employees",
                {"fields": [{"id": "displayName"}], "employees": [{"id": "1"}, {"id": "2"}]},
                [{"id": "1"}, {"id": "2"}],
            ),
            (
                "top_level_list",
                "meta_fields",
                [{"id": "1", "name": "First Name"}],
                [{"id": "1", "name": "First Name"}],
            ),
            (
                "wrapped_list",
                "time_off_types",
                {"timeOffTypes": [{"id": "1"}]},
                [{"id": "1"}],
            ),
            (
                "dict_keyed_by_id",
                "meta_users",
                {"7": {"id": "7", "employeeId": "1"}, "8": {"id": "8", "employeeId": "2"}},
                [{"id": "7", "employeeId": "1"}, {"id": "8", "employeeId": "2"}],
            ),
            ("non_list_returns_empty", "meta_fields", {"id": "1"}, []),
        ]
    )
    def test_extract_records(self, _name: str, endpoint: str, payload: Any, expected: list[dict[str, Any]]) -> None:
        assert _extract_records(payload, BAMBOOHR_ENDPOINTS[endpoint]) == expected

    def test_missing_data_key_raises(self) -> None:
        # A missing envelope key should fail loudly rather than silently sync zero rows.
        with pytest.raises(KeyError):
            _extract_records({"somethingElse": []}, BAMBOOHR_ENDPOINTS["time_off_types"])


class TestNextUrl:
    @parameterized.expand(
        [
            (
                "underscore_links",
                {"_links": {"next": "https://api.bamboohr.com/api/gateway.php/acme/v1/p2"}},
                "https://api.bamboohr.com/api/gateway.php/acme/v1/p2",
            ),
            (
                "plain_links",
                {"links": {"next": "https://api.bamboohr.com/api/gateway.php/acme/v1/p2"}},
                "https://api.bamboohr.com/api/gateway.php/acme/v1/p2",
            ),
            ("no_links", {"data": []}, None),
            ("null_next", {"_links": {"next": None}}, None),
            ("empty_links_dict", {"_links": {}}, None),
            ("relative_next_ignored", {"_links": {"next": "/v1/employees?page=2"}}, None),
            ("off_host_ignored", {"_links": {"next": "http://169.254.169.254/latest/meta-data/"}}, None),
            ("list_payload", [{"id": "1"}], None),
        ]
    )
    def test_next_url(self, _name: str, payload: Any, expected: str | None) -> None:
        assert _next_url(payload) == expected


class TestValidateSubdomain:
    @parameterized.expand(
        [
            ("simple", "acme"),
            ("with_hyphen", "acme-corp"),
            ("with_digits", "acme123"),
        ]
    )
    def test_valid_subdomains_build_urls(self, _name: str, subdomain: str) -> None:
        assert _base_url(subdomain) == f"https://api.bamboohr.com/api/gateway.php/{subdomain}/v1"

    @parameterized.expand(
        [
            ("path_injection", "acme/v1/employees/123/tables/jobInfo?"),
            ("slash", "acme/admin"),
            ("query", "acme?foo=bar"),
            ("dot_segment", "../internal"),
            ("empty", ""),
            ("whitespace", "acme corp"),
            ("scheme", "http://169.254.169.254"),
        ]
    )
    def test_invalid_subdomains_rejected(self, _name: str, subdomain: str) -> None:
        # An editable, non-secret subdomain must never be able to inject path segments or query params.
        with pytest.raises(ValueError):
            _base_url(subdomain)


class TestBuildUrl:
    def test_employees_directory_has_no_params(self) -> None:
        url = _build_url("acme", BAMBOOHR_ENDPOINTS["employees"])
        assert url == "https://api.bamboohr.com/api/gateway.php/acme/v1/employees/directory"

    def test_time_off_requests_includes_date_window(self) -> None:
        url = _build_url("acme", BAMBOOHR_ENDPOINTS["time_off_requests"])
        assert url.startswith("https://api.bamboohr.com/api/gateway.php/acme/v1/time_off/requests?")
        assert "start=2000-01-01" in url
        assert "end=" in url


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("not_found_subdomain", 404, None, False),
            ("forbidden_at_source_create", 403, None, True),
            ("forbidden_for_schema", 403, "employees", False),
            ("unexpected", 500, None, False),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, _name: str, status_code: int, schema_name: str | None, expected_valid: bool
    ) -> None:
        with patch(f"{MODULE}.make_tracked_session", return_value=_mock_session_returning(_mock_response(status_code))):
            valid, message = validate_credentials("acme", "key", schema_name)
        assert valid is expected_valid
        if not expected_valid:
            assert message is not None

    def test_validate_credentials_connection_error(self) -> None:
        session = MagicMock()
        session.get.side_effect = Exception("boom")
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("acme", "key")
        assert valid is False
        assert message is not None

    def test_invalid_subdomain_rejected_before_request(self) -> None:
        session = MagicMock()
        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("acme/v1/employees/123?", "key")
        assert valid is False
        assert message == INVALID_SUBDOMAIN_MESSAGE
        session.get.assert_not_called()


class TestBambooHRSource:
    @parameterized.expand([(endpoint,) for endpoint in BAMBOOHR_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        response = bamboohr_source("acme", "key", endpoint, MagicMock(), manager)
        assert response.name == endpoint
        assert response.primary_keys == BAMBOOHR_ENDPOINTS[endpoint].primary_keys


class TestGetRows:
    def _run(
        self, manager: MagicMock, *responses: MagicMock, endpoint: str = "employees"
    ) -> list[list[dict[str, Any]]]:
        with patch(f"{MODULE}.make_tracked_session", return_value=_mock_session_returning(*responses)):
            return list(
                get_rows(
                    subdomain="acme",
                    api_key="key",
                    endpoint=endpoint,
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                )
            )

    def test_single_page_yields_once_and_does_not_save_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        payload = {"fields": [], "employees": [{"id": "1"}, {"id": "2"}]}

        batches = self._run(manager, _mock_response(200, payload))

        assert batches == [[{"id": "1"}, {"id": "2"}]]
        manager.save_state.assert_not_called()

    def test_paginates_and_saves_state_after_each_yield(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = False
        page1 = {"employees": [{"id": "1"}], "_links": {"next": "https://api.bamboohr.com/api/gateway.php/acme/v1/p2"}}
        page2 = {"employees": [{"id": "2"}]}

        batches = self._run(manager, _mock_response(200, page1), _mock_response(200, page2))

        assert batches == [[{"id": "1"}], [{"id": "2"}]]
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args[0][0]
        assert isinstance(saved, BambooHRResumeConfig)
        assert saved.next_url == "https://api.bamboohr.com/api/gateway.php/acme/v1/p2"

    def test_resumes_from_saved_state(self) -> None:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = True
        manager.load_state.return_value = BambooHRResumeConfig(
            next_url="https://api.bamboohr.com/api/gateway.php/acme/v1/resume"
        )
        session = _mock_session_returning(_mock_response(200, {"employees": [{"id": "9"}]}))

        with patch(f"{MODULE}.make_tracked_session", return_value=session):
            batches = list(
                get_rows(
                    subdomain="acme",
                    api_key="key",
                    endpoint="employees",
                    logger=MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        assert batches == [[{"id": "9"}]]
        called_url = session.get.call_args[0][0]
        assert called_url == "https://api.bamboohr.com/api/gateway.php/acme/v1/resume"
