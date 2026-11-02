import base64
from datetime import UTC, datetime
from typing import Any

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.bamboohr import (
    BAMBOOHR_API_HOST,
    EMPLOYEE_TABLE_HISTORY_START,
    INVALID_SUBDOMAIN_MESSAGE,
    BambooHRResumeConfig,
    _base_url,
    _next_url,
    _page_from_url,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.settings import (
    BAMBOOHR_ENDPOINTS,
    CUSTOM_FIELD_ID,
    CUSTOM_FIELDS_PAGE_SIZE,
    EMPLOYEE_TABLE_EMPLOYEE_ID,
    GOAL_ID,
    LOCATIONS_PAGE_SIZE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bamboohr.source import BambooHRSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bamboohr import (
    BambooHRSourceConfig,
)


def _driver(subdomain: str = "acme") -> SourceDriver:
    return SourceDriver(BambooHRSource(), BambooHRSourceConfig(subdomain=subdomain, api_key="key"))


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
    def test_rows_per_response_shape(
        self, _name: str, endpoint: str, payload: Any, expected: list[dict[str, Any]]
    ) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=payload)])
        assert result.raised is None
        assert result.rows == expected

    def test_missing_data_key_fails_loudly(self) -> None:
        # A 200 body without the envelope key means the response shape changed — fail loud
        # rather than silently syncing zero rows.
        result = _driver().run("time_off_types", [ScriptedResponse(json={"somethingElse": []})])
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)

    def test_non_list_body_for_bare_list_endpoint_fails_loudly(self) -> None:
        # meta/fields returns a bare JSON array; an object body is an unexpected shape change.
        result = _driver().run("meta_fields", [ScriptedResponse(json={"id": "1"})])
        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)

    def test_invalid_subdomain_rejected_before_any_request(self) -> None:
        result = _driver("acme/v1/employees/123?").run("employees", [])
        assert isinstance(result.raised, ValueError)
        assert result.requests == []

    def test_basic_auth_uses_api_key_as_username_and_redacts_it(self) -> None:
        result = _driver().run("employees", [ScriptedResponse(json={"employees": [{"id": "1"}]})])
        assert result.raised is None
        authorization = result.requests[0].headers["authorization"]
        assert base64.b64decode(authorization.removeprefix("Basic ")) == b"key:x"
        # The API key is the Basic auth *username* — it must be the redacted secret.
        assert any("key" in options.get("redact_values", ()) for options in result.session_options)


class TestPagination:
    def test_paginates_and_saves_state_after_each_yield(self) -> None:
        next_url = "https://api.bamboohr.com/api/gateway.php/acme/v1/p2"
        page1 = {"employees": [{"id": "1"}], "_links": {"next": next_url}}
        page2 = {"employees": [{"id": "2"}]}

        result = _driver().run("employees", [ScriptedResponse(json=page1), ScriptedResponse(json=page2)])

        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["1", "2"]
        assert result.urls[1] == next_url
        # Checkpoint saved once (after page 1, pointing at page 2); the last page saves nothing.
        assert result.saved_states == [BambooHRResumeConfig(next_url=next_url)]

    def test_off_host_next_link_is_not_followed(self) -> None:
        page = {"employees": [{"id": "1"}], "_links": {"next": "http://169.254.169.254/latest/meta-data/"}}

        result = _driver().run("employees", [ScriptedResponse(json=page)])

        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["1"]
        assert len(result.requests) == 1
        assert result.saved_states == []

    def test_resumes_from_saved_state(self) -> None:
        resume_url = "https://api.bamboohr.com/api/gateway.php/acme/v1/resume"
        result = _driver().run(
            "employees",
            [ScriptedResponse(json={"employees": [{"id": "9"}]})],
            resume_state=BambooHRResumeConfig(next_url=resume_url),
        )

        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["9"]
        assert result.urls[0] == resume_url

    def test_tampered_resume_state_raises(self) -> None:
        result = _driver().run(
            "employees", [], resume_state=BambooHRResumeConfig(next_url="http://169.254.169.254/latest/meta-data/")
        )
        assert isinstance(result.raised, ValueError)
        assert "unexpected URL" in str(result.raised)
        assert result.requests == []


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
            ("unexpected", 400, None, False),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, _name: str, status_code: int, schema_name: str | None, expected_valid: bool
    ) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            valid, message = validate_credentials("acme", "key", schema_name)
        assert valid is expected_valid
        if not expected_valid:
            assert message is not None
        assert network.requests_log[0].path == "/api/gateway.php/acme/v1/meta/fields"

    def test_invalid_subdomain_rejected_before_request(self) -> None:
        with scripted_network([]) as network:
            valid, message = validate_credentials("acme/v1/employees/123?", "key")
        assert valid is False
        assert message == INVALID_SUBDOMAIN_MESSAGE
        assert network.requests_log == []


class TestEmployeeTableStreams:
    def test_flattens_the_employee_map_onto_rows(self) -> None:
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

        result = _driver().run("employee_job_info", [ScriptedResponse(json=payload)])

        assert result.raised is None
        assert result.paths[0] == "/api/gateway.php/acme/v1/employees/changed/tables/jobInfo"
        # Employees come back in map order, so the rows must be re-sorted onto the cursor before
        # the pipeline checkpoints a watermark against them.
        assert result.rows == [
            {"id": "10", "jobTitle": "Designer", "employeeId": "1", "lastChanged": "2024-01-01T00:00:00+00:00"},
            {"id": "11", "jobTitle": "Lead", "employeeId": "1", "lastChanged": "2024-01-01T00:00:00+00:00"},
            {"id": "20", "employeeId": "2", "jobTitle": "Engineer", "lastChanged": "2024-03-01T00:00:00+00:00"},
        ]

    @parameterized.expand(
        [
            ("missing_employees_key", {"table": "jobInfo"}),
            ("employees_is_a_list", {"employees": [{"id": "1"}]}),
        ]
    )
    def test_unexpected_shape_fails_loudly(self, _name: str, payload: Any) -> None:
        result = _driver().run("employee_job_info", [ScriptedResponse(json=payload)])
        assert isinstance(result.raised, ValueError)
        assert "'employees' object" in str(result.raised)

    @parameterized.expand(
        [
            ("watermark_as_string", "2024-05-06T07:08:09+00:00", "2024-05-06T07:08:09+00:00"),
            ("watermark_as_datetime", datetime(2024, 5, 6, 7, 8, 9, tzinfo=UTC), "2024-05-06T07:08:09+00:00"),
            ("no_watermark_yet", None, EMPLOYEE_TABLE_HISTORY_START.isoformat()),
        ]
    )
    def test_incremental_sync_sends_the_watermark(self, _name: str, watermark: Any, expected: str) -> None:
        result = _driver().run(
            "employee_job_info",
            [ScriptedResponse(json={"employees": {}})],
            incremental_field="lastChanged",
            db_incremental_field_last_value=watermark,
        )

        assert result.raised is None
        assert result.requests[0].param("since") == expected
        assert result.queries[0] == {"since": (expected,)}


class TestTimesheetEntries:
    def test_entries_from_every_window_are_yielded(self) -> None:
        window = BAMBOOHR_ENDPOINTS["timesheet_entries"].chunked_date_window
        assert window is not None
        request_count = -(-(window.history_days + 1) // window.chunk_days)
        responses = [ScriptedResponse(json=[]) for _ in range(request_count)]
        responses[0] = ScriptedResponse(json=[{"id": 1}])
        responses[-1] = ScriptedResponse(json=[{"id": 2}])

        result = _driver().run("timesheet_entries", responses)

        assert result.raised is None
        assert result.rows == [{"id": 1}, {"id": 2}]

    def test_non_list_body_fails_loudly(self) -> None:
        result = _driver().run("timesheet_entries", [ScriptedResponse(json={"error": "nope"})])
        assert isinstance(result.raised, ValueError)
        assert "list response body" in str(result.raised)


class TestEmployeeFanout:
    @parameterized.expand(
        [
            (
                "time_off_policies",
                "employee_time_off_policies",
                {"timeOffPolicyId": "5", "timeOffTypeId": 1},
                {"timeOffPolicyId": "5", "timeOffTypeId": 1, "employeeId": "7"},
            ),
            (
                "time_off_balances",
                "employee_time_off_balances",
                {"timeOffType": "1", "balance": "24.50"},
                {"timeOffType": "1", "balance": "24.50", "employeeId": "7"},
            ),
            (
                "goals",
                "employee_goals",
                {"id": "4", "title": "Ship the thing"},
                {"id": "4", "title": "Ship the thing", "employeeId": "7"},
            ),
        ]
    )
    def test_child_rows_carry_the_parent_employee_id(
        self, _name: str, endpoint: str, child_row: dict[str, Any], expected: dict[str, Any]
    ) -> None:
        payload = {"goals": [child_row]} if endpoint == "employee_goals" else [child_row]
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"employees": [{"id": "7"}]}), ScriptedResponse(json=payload)],
        )

        assert result.raised is None
        assert result.rows == [expected]
        assert result.paths[0] == "/api/gateway.php/acme/v1/employees/directory"


class TestStaticEndpointParams:
    @parameterized.expand(
        [
            # Each of these defaults to a narrowed slice of the collection, so the param is what
            # keeps the synced table complete rather than a silently filtered subset.
            ("job_openings", [], {"statusGroups": "ALL"}),
            ("applicant_statuses", [], {}),
            ("ats_locations", [], {}),
        ]
    )
    def test_list_endpoint_request(self, endpoint: str, payload: Any, expected: dict[str, Any]) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=payload)])
        assert result.raised is None
        assert result.queries[0] == {name: (str(value),) for name, value in expected.items()}


class TestApplicationsPagination:
    @parameterized.expand(
        [
            ("pagination_complete", {"applications": [{"id": 1}], "paginationComplete": True}),
            ("no_next_page_url", {"applications": [{"id": 1}], "paginationComplete": False, "nextPageUrl": None}),
            ("empty_page", {"applications": [], "paginationComplete": False, "nextPageUrl": "?page=2"}),
        ]
    )
    def test_walk_terminates(self, _name: str, payload: Any) -> None:
        result = _driver().run("applications", [ScriptedResponse(json=payload)])
        assert result.raised is None
        assert len(result.requests) == 1

    def test_unreadable_next_link_still_advances(self) -> None:
        # A next link we cannot parse a page out of must not silently truncate the table.
        page1 = {"applications": [{"id": 1}], "paginationComplete": False, "nextPageUrl": "/next"}
        page2 = {"applications": [{"id": 2}], "paginationComplete": True}

        result = _driver().run("applications", [ScriptedResponse(json=page1), ScriptedResponse(json=page2)])

        assert result.raised is None
        assert [r["id"] for r in result.rows] == [1, 2]
        assert result.requests[1].param("page") == "1"

    @parameterized.expand(
        [
            ("absolute", "https://acme.bamboohr.com/api/v1/x?page=3&limit=50", 3),
            ("relative", "/api/v1/x?page=0", 0),
            ("no_page_param", "https://acme.bamboohr.com/api/v1/x?limit=50", None),
            ("non_numeric", "https://acme.bamboohr.com/api/v1/x?page=abc", None),
            ("not_a_string", None, None),
        ]
    )
    def test_page_from_url(self, _name: str, url: Any, expected: int | None) -> None:
        assert _page_from_url(url) == expected


class TestPageLinksPagination:
    @parameterized.expand(
        [
            ("timesheets", "v1/time-tracking/timesheets", {"sort": "startDate asc", "pageSize": 200}, {}),
            ("hour_entries", "v1/time-tracking/hour-entries", {"sort": "date asc", "pageSize": 200}, {}),
            ("clock_entries", "v1/time-tracking/clock-entries", {"sort": "start asc", "pageSize": 200}, {}),
            ("holidays", "v1/holidays", {"orderBy": "startDate asc", "pageSize": 100}, {"next": None}),
            ("custom_fields", "v1/hris/custom-fields", {"pageSize": 1000}, {"next": None}),
            ("archived_custom_fields", "v1/hris/custom-fields/archived", {"pageSize": 1000}, {}),
            (
                "time_tracking_employees",
                "v1/time-tracking/employees",
                {"orderBy": "employeeId asc", "pageSize": 100},
                {},
            ),
            (
                "time_tracking_configurations",
                "v1/time-tracking/configurations",
                {"orderBy": "createdAt asc", "pageSize": 100},
                {},
            ),
            ("time_tracking_kiosks", "v1/time-tracking/kiosks", {"orderBy": "createdAt asc", "pageSize": 100}, {}),
            (
                "time_tracking_time_clocks",
                "v1/time-tracking/time-clocks",
                {"orderBy": "serialNumber asc", "pageSize": 100},
                {},
            ),
        ]
    )
    def test_walks_pages_by_the_next_link(
        self, endpoint: str, path: str, params: dict[str, Any], last_links: dict[str, Any]
    ) -> None:
        page1 = {
            "data": [{"id": 1}],
            "meta": {"page": 1, "pageSize": 1, "totalPages": 2, "totalItems": 2},
            "_links": {"next": {"href": f"https://acme.bamboohr.com/api/{path}?page=2&pageSize=1"}},
        }
        page2 = {
            "data": [{"id": 2}],
            "meta": {"page": 2, "pageSize": 1, "totalPages": 2, "totalItems": 2},
            "_links": last_links,
        }

        result = _driver().run(endpoint, [ScriptedResponse(json=page1), ScriptedResponse(json=page2)])

        assert result.raised is None
        assert [r["id"] for r in result.rows] == [1, 2]
        # The next link points at the company domain, so the walk stays on the gateway and only
        # reuses the link's page number.
        assert result.paths == [f"/api/gateway.php/acme/{path}"] * 2
        assert result.queries[0] == {name: (str(value),) for name, value in params.items()}
        assert result.queries[1] == {name: (str(value),) for name, value in {**params, "page": 2}.items()}


class TestLocationsPagination:
    def test_walks_every_page_of_active_and_archived_locations(self) -> None:
        pages = [
            ScriptedResponse(json={"data": [{"id": "1"}]}),
            ScriptedResponse(json={"data": [{"id": "2"}]}),
            ScriptedResponse(json={"data": []}),
            ScriptedResponse(json={"data": [{"id": "3"}]}),
            ScriptedResponse(json={"data": []}),
        ]

        result = _driver().run("locations", pages)

        # The endpoint answers with active locations only, so an archived location a synced
        # employee still points at reaches the table through the second walk.
        assert result.raised is None
        assert [r["id"] for r in result.rows] == ["1", "2", "3"]
        assert result.paths[0] == "/api/gateway.php/acme/v1/hris/org/locations"
        assert result.params("filter") == [
            "archived eq false",
            "archived eq false",
            "archived eq false",
            "archived eq true",
            "archived eq true",
        ]
        # Each walk pages from zero and stops on its first empty page.
        assert result.params("page") == ["0", "1", "2", "0", "1"]
        assert set(result.params("pageSize")) == {str(LOCATIONS_PAGE_SIZE)}

    def test_missing_data_key_fails_loudly(self) -> None:
        result = _driver().run("locations", [ScriptedResponse(json={"meta": {}})])
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestGoalStreams:
    def test_comments_walk_every_goal_of_every_employee(self) -> None:
        responses = [
            ScriptedResponse(json={"employees": [{"id": "7"}, {"id": "8"}]}),
            ScriptedResponse(json={"goals": [{"id": "4"}, {"id": "5"}]}),
            ScriptedResponse(json={"comments": [{"id": "100", "text": "nice"}]}),
            ScriptedResponse(json={"comments": []}),
            ScriptedResponse(json={"goals": []}),
        ]

        result = _driver().run("employee_goal_comments", responses)

        # A comment row names neither its goal nor its employee, so both have to be stamped on.
        assert result.raised is None
        assert result.rows == [{"id": "100", "text": "nice", "employeeId": "7", GOAL_ID: "4"}]
        assert result.paths == [
            "/api/gateway.php/acme/v1/employees/directory",
            "/api/gateway.php/acme/v1/performance/employees/7/goals",
            "/api/gateway.php/acme/v1/performance/employees/7/goals/4/comments",
            "/api/gateway.php/acme/v1/performance/employees/7/goals/5/comments",
            "/api/gateway.php/acme/v1/performance/employees/8/goals",
        ]

    def test_ids_from_the_api_cannot_extend_the_request_path(self) -> None:
        responses = [
            ScriptedResponse(json={"employees": [{"id": "7/../../meta/users?"}]}),
            ScriptedResponse(json={"goals": []}),
        ]

        result = _driver().run("employee_goal_comments", responses)

        assert result.raised is None
        assert result.paths[1] == ("/api/gateway.php/acme/v1/performance/employees/7%2F..%2F..%2Fmeta%2Fusers%3F/goals")


class TestCustomFieldListValues:
    def test_values_carry_their_field_and_non_list_fields_are_skipped(self) -> None:
        responses = [
            ScriptedResponse(json={"data": [{"id": "4001"}, {"id": "4002"}], "_links": {}}),
            ScriptedResponse(
                json={"id": "4001", "type": "list", "values": [{"id": "1", "display": "Red", "count": 3}]}
            ),
            ScriptedResponse(status=422, json={"title": "Invalid custom field ID."}),
        ]

        result = _driver().run("custom_field_list_values", responses)

        # Value ids repeat across fields, so the field id has to be on every row.
        assert result.raised is None
        assert result.rows == [{"id": "1", "display": "Red", "count": 3, CUSTOM_FIELD_ID: "4001"}]
        assert result.paths == [
            "/api/gateway.php/acme/v1/hris/custom-fields",
            "/api/gateway.php/acme/v1/hris/custom-fields/4001/list-values",
            "/api/gateway.php/acme/v1/hris/custom-fields/4002/list-values",
        ]
        assert result.queries[0] == {"pageSize": (str(CUSTOM_FIELDS_PAGE_SIZE),)}

    def test_field_ids_from_the_api_cannot_extend_the_request_path(self) -> None:
        responses = [
            ScriptedResponse(json={"data": [{"id": "../../other?x="}], "_links": {}}),
            ScriptedResponse(json={"id": "x", "values": [{"id": "1"}]}),
        ]

        result = _driver().run("custom_field_list_values", responses)

        assert result.raised is None
        assert result.paths[1] == "/api/gateway.php/acme/v1/hris/custom-fields/..%2F..%2Fother%3Fx%3D/list-values"
        assert result.rows == [{"id": "1", CUSTOM_FIELD_ID: "../../other?x="}]


class TestEndpointCatalog:
    @parameterized.expand(
        [
            (name,)
            for name, config in BAMBOOHR_ENDPOINTS.items()
            if config.employee_table
            or config.custom_iterator == "goal_comments"
            or (config.fanout is not None and config.fanout.parent_name == "employees")
        ]
    )
    def test_employee_scoped_endpoints_key_on_the_employee(self, endpoint: str) -> None:
        # These ids are only unique within one employee, so a key without the employee collides
        # across the directory and every later merge multi-matches the duplicates.
        assert EMPLOYEE_TABLE_EMPLOYEE_ID in BAMBOOHR_ENDPOINTS[endpoint].primary_keys


class TestBambooHRSource:
    @parameterized.expand([(endpoint,) for endpoint in BAMBOOHR_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [])
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == BAMBOOHR_ENDPOINTS[endpoint].primary_keys
