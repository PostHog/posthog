import json
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

import pytest
from unittest import mock

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.bamboohr import (
    BAMBOOHR_API_HOST,
    EMPLOYEE_TABLE_HISTORY_START,
    INVALID_SUBDOMAIN_MESSAGE,
    BambooHRBasicAuth,
    BambooHRResumeConfig,
    _base_url,
    _next_url,
    bamboohr_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.settings import (
    BAMBOOHR_ENDPOINTS,
    EMPLOYEE_TABLE_EMPLOYEE_ID,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.bamboohr"
# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
FANOUT_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout"


def _response(payload: Any, status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(payload).encode()
    return resp


def _make_manager(resume_state: BambooHRResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session and snapshot each request (url/params/auth) AT PREPARE TIME.

    ``request.params`` is a single dict mutated in place across pages, so inspecting it after the
    run shows only the final state — snapshot a copy when each request is prepared instead.
    """
    session.headers = {}
    request_snapshots: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        request_snapshots.append({"url": request.url, "params": dict(request.params or {}), "auth": request.auth})
        prepared = mock.MagicMock()
        # The client re-checks the host of the prepared URL before sending, so it must be real.
        prepared.url = request.url
        return prepared

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return request_snapshots


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


def _run(
    endpoint: str,
    responses: list[Response],
    MockSession: mock.MagicMock,
    manager: mock.MagicMock | None = None,
    subdomain: str = "acme",
    rows_from_pages: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], mock.MagicMock]:
    session = MockSession.return_value
    requests_made = _wire(session, responses)
    manager = manager if manager is not None else _make_manager()
    response = bamboohr_source(subdomain, "key", endpoint, team_id=1, job_id="j", resumable_source_manager=manager)
    # Fan-out resources yield rows; every other resource yields pages of rows.
    rows = _rows(response) if rows_from_pages else list(cast(Any, response.items()))
    return rows, requests_made, manager


class TestRows:
    @parameterized.expand(
        [
            (
                "employees_directory_envelope",
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
            (
                "dict_with_single_entry",
                "meta_users",
                {"7": {"id": "7", "employeeId": "1"}},
                [{"id": "7", "employeeId": "1"}],
            ),
            ("empty_dict_yields_no_rows", "meta_users", {}, []),
            ("empty_wrapped_list_yields_no_rows", "time_off_types", {"timeOffTypes": []}, []),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rows_per_response_shape(
        self, _name: str, endpoint: str, payload: Any, expected: list[dict[str, Any]], MockSession
    ) -> None:
        rows, _requests, _manager = _run(endpoint, [_response(payload)], MockSession)
        assert rows == expected

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_missing_data_key_fails_loudly(self, MockSession) -> None:
        # A 200 body without the envelope key means the response shape changed — fail loud
        # rather than silently syncing zero rows.
        with pytest.raises(ValueError, match="matched nothing"):
            _run("time_off_types", [_response({"somethingElse": []})], MockSession)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_for_bare_list_endpoint_fails_loudly(self, MockSession) -> None:
        # meta/fields returns a bare JSON array; an object body is an unexpected shape change.
        with pytest.raises(ValueError, match="list response body"):
            _run("meta_fields", [_response({"id": "1"})], MockSession)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_employees_url_and_no_params(self, MockSession) -> None:
        _rows_, requests_made, _manager = _run("employees", [_response({"employees": [{"id": "1"}]})], MockSession)
        assert requests_made[0]["url"] == "https://api.bamboohr.com/api/gateway.php/acme/v1/employees/directory"
        assert requests_made[0]["params"] == {}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_time_off_requests_sends_date_window(self, MockSession) -> None:
        _rows_, requests_made, _manager = _run("time_off_requests", [_response([{"id": "1"}])], MockSession)
        assert requests_made[0]["url"] == "https://api.bamboohr.com/api/gateway.php/acme/v1/time_off/requests"
        assert requests_made[0]["params"]["start"] == "2000-01-01"
        # End of the window is now + 730 days, formatted as a date.
        assert len(requests_made[0]["params"]["end"]) == 10

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_invalid_subdomain_rejected_before_any_request(self, MockSession) -> None:
        session = MockSession.return_value
        with pytest.raises(ValueError):
            bamboohr_source(
                "acme/v1/employees/123?",
                "key",
                "employees",
                team_id=1,
                job_id="j",
                resumable_source_manager=_make_manager(),
            )
        session.send.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_basic_auth_uses_api_key_as_username_and_redacts_it(self, MockSession) -> None:
        _rows_, requests_made, _manager = _run("employees", [_response({"employees": [{"id": "1"}]})], MockSession)
        auth = requests_made[0]["auth"]
        assert isinstance(auth, BambooHRBasicAuth)
        assert auth.username == "key"
        assert auth.password == "x"
        # The API key is the Basic auth *username* — it must be the redacted secret.
        assert auth.secret_values() == ("key",)
        assert "key" in (MockSession.call_args.kwargs.get("redact_values") or ())


class TestPagination:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_paginates_and_saves_state_after_each_yield(self, MockSession) -> None:
        next_url = "https://api.bamboohr.com/api/gateway.php/acme/v1/p2"
        page1 = {"employees": [{"id": "1"}], "_links": {"next": next_url}}
        page2 = {"employees": [{"id": "2"}]}

        rows, requests_made, manager = _run("employees", [_response(page1), _response(page2)], MockSession)

        assert [r["id"] for r in rows] == ["1", "2"]
        assert requests_made[1]["url"] == next_url
        # Checkpoint saved once (after page 1, pointing at page 2); the last page saves nothing.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0] == BambooHRResumeConfig(next_url=next_url)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_single_page_makes_one_request_and_no_checkpoint(self, MockSession) -> None:
        rows, requests_made, manager = _run("employees", [_response({"employees": [{"id": "1"}]})], MockSession)

        assert [r["id"] for r in rows] == ["1"]
        assert len(requests_made) == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_off_host_next_link_is_not_followed(self, MockSession) -> None:
        page = {"employees": [{"id": "1"}], "_links": {"next": "http://169.254.169.254/latest/meta-data/"}}

        rows, requests_made, manager = _run("employees", [_response(page)], MockSession)

        assert [r["id"] for r in rows] == ["1"]
        assert len(requests_made) == 1
        manager.save_state.assert_not_called()

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_resumes_from_saved_state(self, MockSession) -> None:
        resume_url = "https://api.bamboohr.com/api/gateway.php/acme/v1/resume"
        manager = _make_manager(BambooHRResumeConfig(next_url=resume_url))

        rows, requests_made, _manager = _run(
            "employees", [_response({"employees": [{"id": "9"}]})], MockSession, manager=manager
        )

        assert [r["id"] for r in rows] == ["9"]
        assert requests_made[0]["url"] == resume_url

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_tampered_resume_state_raises(self, MockSession) -> None:
        manager = _make_manager(BambooHRResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"))

        with pytest.raises(ValueError, match="unexpected URL"):
            bamboohr_source("acme", "key", "employees", team_id=1, job_id="j", resumable_source_manager=manager)


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
        assert _base_url(subdomain) == f"{BAMBOOHR_API_HOST}/{subdomain}"

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
        session = mock.MagicMock()
        session.get.return_value = mock.MagicMock(status_code=status_code)
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("acme", "key", schema_name)
        assert valid is expected_valid
        if not expected_valid:
            assert message is not None

    def test_validate_credentials_connection_error(self) -> None:
        session = mock.MagicMock()
        session.get.side_effect = Exception("boom")
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("acme", "key")
        assert valid is False
        assert message is not None

    def test_invalid_subdomain_rejected_before_request(self) -> None:
        session = mock.MagicMock()
        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            valid, message = validate_credentials("acme/v1/employees/123?", "key")
        assert valid is False
        assert message == INVALID_SUBDOMAIN_MESSAGE
        session.get.assert_not_called()


class TestEmployeeTableStreams:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flattens_the_employee_map_onto_rows(self, MockSession) -> None:
        payload = {
            "table": "jobInfo",
            "employees": {
                "2": {
                    "lastChanged": "2024-03-01T00:00:00+00:00",
                    # The row carries a stale employeeId; the map key is what the API grouped by.
                    "rows": [{"id": "20", "employeeId": "999", "jobTitle": "Engineer"}],
                },
                "1": {
                    "lastChanged": "2024-01-01T00:00:00+00:00",
                    "rows": [{"id": "10", "jobTitle": "Designer"}, {"id": "11", "jobTitle": "Lead"}],
                },
            },
        }

        rows, requests_made, _manager = _run("employee_job_info", [_response(payload)], MockSession)

        assert requests_made[0]["url"] == (
            "https://api.bamboohr.com/api/gateway.php/acme/v1/employees/changed/tables/jobInfo"
        )
        # Employees come back in map order, so the rows must be re-sorted onto the cursor before
        # the pipeline checkpoints a watermark against them.
        assert rows == [
            {"id": "10", "jobTitle": "Designer", "employeeId": "1", "lastChanged": "2024-01-01T00:00:00+00:00"},
            {"id": "11", "jobTitle": "Lead", "employeeId": "1", "lastChanged": "2024-01-01T00:00:00+00:00"},
            {"id": "20", "employeeId": "2", "jobTitle": "Engineer", "lastChanged": "2024-03-01T00:00:00+00:00"},
        ]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rows_without_a_last_changed_sort_first(self, MockSession) -> None:
        payload = {
            "employees": {
                "1": {"lastChanged": "2024-01-01T00:00:00+00:00", "rows": [{"id": "10"}]},
                "2": {"rows": [{"id": "20"}]},
            }
        }

        rows, _requests, _manager = _run("employee_compensation", [_response(payload)], MockSession)

        assert [row["id"] for row in rows] == ["20", "10"]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_empty_response_yields_no_rows(self, MockSession) -> None:
        rows, _requests, _manager = _run(
            "employee_employment_status", [_response({"table": "employmentStatus", "employees": {}})], MockSession
        )
        assert rows == []

    @parameterized.expand(
        [
            ("missing_employees_key", {"table": "jobInfo"}),
            ("employees_is_a_list", {"employees": [{"id": "1"}]}),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_unexpected_shape_fails_loudly(self, _name: str, payload: Any, MockSession) -> None:
        with pytest.raises(ValueError, match="'employees' object"):
            _run("employee_job_info", [_response(payload)], MockSession)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_full_refresh_asks_for_the_whole_history(self, MockSession) -> None:
        _rows_, requests_made, _manager = _run("employee_job_info", [_response({"employees": {}})], MockSession)
        assert requests_made[0]["params"] == {"since": EMPLOYEE_TABLE_HISTORY_START.isoformat()}

    @parameterized.expand(
        [
            ("watermark_as_string", "2024-05-06T07:08:09+00:00", "2024-05-06T07:08:09+00:00"),
            ("watermark_as_datetime", datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC), "2024-05-06T07:08:09+00:00"),
            ("no_watermark_yet", None, EMPLOYEE_TABLE_HISTORY_START.isoformat()),
        ]
    )
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_incremental_sync_sends_the_watermark(self, _name: str, watermark: Any, expected: str, MockSession) -> None:
        session = MockSession.return_value
        requests_made = _wire(session, [_response({"employees": {}})])

        response = bamboohr_source(
            "acme",
            "key",
            "employee_job_info",
            team_id=1,
            job_id="j",
            resumable_source_manager=_make_manager(),
            should_use_incremental_field=True,
            db_incremental_field_last_value=watermark,
        )
        _rows(response)

        assert requests_made[0]["params"] == {"since": expected}


class TestTimesheetEntries:
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_walks_the_year_in_contiguous_windows(self, MockSession) -> None:
        window = BAMBOOHR_ENDPOINTS["timesheet_entries"].chunked_date_window
        assert window is not None
        expected_requests = -(-(window.history_days + 1) // window.chunk_days)

        _rows_, requests_made, _manager = _run(
            "timesheet_entries", [_response([]) for _ in range(expected_requests)], MockSession
        )

        assert len(requests_made) == expected_requests
        windows = [
            (date.fromisoformat(r["params"]["start"]), date.fromisoformat(r["params"]["end"])) for r in requests_made
        ]
        today = datetime.now(UTC).date()
        # The whole supported range is covered exactly once: no gap and no overlap between slices,
        # and nothing reaching past the API's 365-day limit.
        assert windows[0][0] == today - timedelta(days=window.history_days)
        assert windows[-1][1] == today
        for (_start, end), (next_start, _next_end) in zip(windows, windows[1:]):
            assert next_start == end + timedelta(days=1)

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_entries_from_every_window_are_yielded(self, MockSession) -> None:
        window = BAMBOOHR_ENDPOINTS["timesheet_entries"].chunked_date_window
        assert window is not None
        request_count = -(-(window.history_days + 1) // window.chunk_days)
        responses = [_response([]) for _ in range(request_count)]
        responses[0] = _response([{"id": 1}])
        responses[-1] = _response([{"id": 2}])

        rows, _requests, _manager = _run("timesheet_entries", responses, MockSession)

        assert rows == [{"id": 1}, {"id": 2}]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_non_list_body_fails_loudly(self, MockSession) -> None:
        with pytest.raises(ValueError, match="list response body"):
            _run("timesheet_entries", [_response({"error": "nope"})], MockSession)


class _FakeDltResource:
    """Stand-in for the DltResource the fan-out helper returns.

    ``process_parent_data_item`` injects parent fields as ``_<parent_resource>_<field>``, which is
    what the rename mapper under test reads.
    """

    def __init__(self, name: str, rows: list[dict[str, Any]]) -> None:
        self.name = name
        self._rows = rows

    def add_map(self, mapper: Any) -> "_FakeDltResource":
        self._rows = [mapper(dict(row)) for row in self._rows]
        return self

    def __iter__(self) -> Any:
        return iter(self._rows)


class TestEmployeeFanout:
    @parameterized.expand(
        [
            (
                "time_off_policies",
                "employee_time_off_policies",
                {"timeOffPolicyId": "5", "timeOffTypeId": 1, "_employees_id": "7"},
                {"timeOffPolicyId": "5", "timeOffTypeId": 1, "employeeId": "7"},
            ),
            (
                "time_off_balances",
                "employee_time_off_balances",
                {"timeOffType": "1", "balance": "24.50", "_employees_id": "7"},
                {"timeOffType": "1", "balance": "24.50", "employeeId": "7"},
            ),
        ]
    )
    @mock.patch(f"{FANOUT_MODULE}.rest_api_resources")
    def test_child_rows_carry_the_parent_employee_id(
        self, _name: str, endpoint: str, child_row: dict[str, Any], expected: dict[str, Any], mock_resources
    ) -> None:
        mock_resources.return_value = [
            _FakeDltResource("employees", [{"id": "7"}]),
            _FakeDltResource(endpoint, [child_row]),
        ]

        response = bamboohr_source(
            "acme", "key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )

        assert list(cast(Any, response.items())) == [expected]

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_child_requests_resolve_the_versioned_employee_path(self, MockSession) -> None:
        directory = _response({"employees": [{"id": "7"}, {"id": "8"}]})
        policies = [_response([{"timeOffPolicyId": "5"}]), _response([])]

        _rows_, requests_made, _manager = _run(
            "employee_time_off_policies", [directory, *policies], MockSession, rows_from_pages=False
        )

        assert [r["url"] for r in requests_made] == [
            "https://api.bamboohr.com/api/gateway.php/acme/v1/employees/directory",
            "https://api.bamboohr.com/api/gateway.php/acme/v1_1/employees/7/time_off/policies",
            "https://api.bamboohr.com/api/gateway.php/acme/v1_1/employees/8/time_off/policies",
        ]


class TestEndpointCatalog:
    @parameterized.expand(
        [(name,) for name, config in BAMBOOHR_ENDPOINTS.items() if config.fanout or config.employee_table]
    )
    def test_employee_scoped_endpoints_key_on_the_employee(self, endpoint: str) -> None:
        # These ids are only unique within one employee, so a key without the employee collides
        # across the directory and every later merge multi-matches the duplicates.
        assert EMPLOYEE_TABLE_EMPLOYEE_ID in BAMBOOHR_ENDPOINTS[endpoint].primary_keys


class TestBambooHRSource:
    @parameterized.expand([(endpoint,) for endpoint in BAMBOOHR_ENDPOINTS])
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_source_response_shape(self, endpoint: str, MockSession) -> None:
        _wire(MockSession.return_value, [])
        response = bamboohr_source(
            "acme", "key", endpoint, team_id=1, job_id="j", resumable_source_manager=_make_manager()
        )
        assert response.name == endpoint
        assert response.primary_keys == BAMBOOHR_ENDPOINTS[endpoint].primary_keys
