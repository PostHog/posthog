from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hibob import HiBobSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob import validate_credentials
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.settings import ENDPOINTS, HIBOB_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.source import HiBobSource


def _driver() -> SourceDriver:
    return SourceDriver(HiBobSource(), HiBobSourceConfig(service_user_id="service-id", service_user_token="token"))


class TestGetRows:
    def test_auth_error_is_not_retried_and_raises(self) -> None:
        # 401 trips HiBob's WAF on repeat, so it must fail loud without retrying.
        result = _driver().run("tasks", [ScriptedResponse(status=401, json={"error": "unauthorized"})])

        assert isinstance(result.raised, Exception)
        assert result.paths == ["/v1/tasks"]


class TestEmployeeHistoryTables:
    @pytest.mark.parametrize(
        "endpoint, path",
        [
            ("employee_lifecycle", "/v1/bulk/people/lifecycle"),
            ("employee_employment", "/v1/bulk/people/employment"),
            ("employee_salaries", "/v1/bulk/people/salaries"),
            ("employee_deductions", "/v1/bulk/people/deduction"),
            ("employee_entitlements", "/v1/bulk/people/entitlement"),
            ("employee_variable_pay", "/v1/bulk/people/variable"),
            ("employee_dependents", "/v1/bulk/people/dependents"),
            ("employee_right_to_work", "/v1/bulk/people/right-to-work"),
            ("employee_equities", "/v1/bulk/people/equities"),
        ],
    )
    @pytest.mark.parametrize(
        "values_page_1, values_page_2",
        [
            ([{"id": 1, "status": "hired"}, {"id": 2, "status": "employed"}], [{"id": 1, "status": "hired"}]),
            (
                [{"values": [{"id": 1, "status": "hired"}, {"id": 2, "status": "employed"}], "restricted_columns": {}}],
                [{"values": [{"id": 1, "status": "hired"}]}],
            ),
        ],
        ids=["bare_entries", "wrapped_entries"],
    )
    def test_flattens_entries_per_employee_and_follows_query_cursor(
        self,
        endpoint: str,
        path: str,
        values_page_1: list[dict[str, Any]],
        values_page_2: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(
                    json={
                        "results": [{"employeeId": "e1", "values": values_page_1}],
                        "response_metadata": {"next_cursor": "c2"},
                    }
                ),
                ScriptedResponse(
                    json={
                        "results": [{"employeeId": "e2", "values": values_page_2}, {"employeeId": "e3", "values": []}],
                        "response_metadata": {"next_cursor": None},
                    }
                ),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": 1, "status": "hired", "employeeId": "e1"},
            {"id": 2, "status": "employed", "employeeId": "e1"},
            {"id": 1, "status": "hired", "employeeId": "e2"},
        ]
        assert result.response is not None
        assert result.response.primary_keys == ["employeeId", "id"]
        assert [(request.method, request.path) for request in result.requests] == [("GET", path)] * 2
        assert all(request.origin == "https://api.hibob.com" for request in result.requests)
        assert result.queries == [{"limit": ("200",)}, {"limit": ("200",), "cursor": ("c2",)}]

    def test_rejects_repeated_cursor(self) -> None:
        result = _driver().run(
            "employee_lifecycle",
            [
                ScriptedResponse(json={"results": [], "response_metadata": {"next_cursor": "stalled"}}),
                ScriptedResponse(json={"results": [], "response_metadata": {"next_cursor": "stalled"}}),
            ],
        )

        assert isinstance(result.raised, ValueError)
        assert "repeated cursor" in str(result.raised)


class TestSearchEndpoints:
    @pytest.mark.parametrize(
        "endpoint, path, prefix, requested_field",
        [
            ("candidates", "/v1/hiring/candidates/search", "/candidate", "/candidate/modificationDate"),
            ("applications", "/v1/hiring/applications/search", "/application", "/application/modificationDate"),
            ("employers", "/v1/employers/search", "/employer", "/employer/legalName"),
            # The default skill field set leaves proficiency levels out.
            ("skills", "/v1/skills/search", "/skill", "/skill/proficiencyLevels"),
        ],
    )
    def test_posts_body_cursor_and_normalizes_pointer_keys(
        self, endpoint: str, path: str, prefix: str, requested_field: str
    ) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(
                    json={
                        "items": [{f"{prefix}/id": 7, f"{prefix}/status": "active"}],
                        "response_metadata": {"next_cursor": "c2"},
                    }
                ),
                ScriptedResponse(json={"items": [{f"{prefix}/id": 8}], "response_metadata": {"next_cursor": None}}),
            ],
        )

        assert result.raised is None
        assert result.rows == [{"id": 7, "status": "active"}, {"id": 8}]
        assert [(request.method, request.path) for request in result.requests] == [("POST", path)] * 2
        assert all(request.origin == "https://api.hibob.com" for request in result.requests)
        first_body, second_body = (request.json() for request in result.requests)
        assert "cursor" not in first_body
        assert requested_field in first_body["fields"]
        # HiBob rejects a search asking for more than 50 fields.
        assert len(first_body["fields"]) <= 50
        assert second_body["cursor"] == "c2"
        # The next sync must not start from the previous sync's cursor.
        body = HIBOB_ENDPOINTS[endpoint].body
        assert body is not None and "cursor" not in body


class TestNamedLists:
    @pytest.mark.parametrize(
        "payload",
        [
            [
                {"name": "department", "items": [{"id": 1, "value": "Eng", "name": "Eng", "archived": False}]},
                {
                    "name": "site",
                    "items": [
                        {
                            "id": 2,
                            "value": "UK",
                            "name": "UK",
                            "archived": True,
                            "children": [{"id": 3, "value": "London", "name": "London", "archived": False}],
                        }
                    ],
                },
            ],
            {
                "department": {
                    "name": "department",
                    "items": [{"id": 1, "value": "Eng", "name": "Eng", "archived": False, "children": []}],
                },
                "site": {
                    "name": "site",
                    "items": [
                        {
                            "id": 2,
                            "value": "UK",
                            "name": "UK",
                            "archived": True,
                            "children": [{"id": 3, "value": "London", "name": "London", "archived": False}],
                        }
                    ],
                },
            },
        ],
        ids=["documented_array", "keyed_by_list_name"],
    )
    def test_flattens_nested_items_with_list_name_and_parent(self, payload: Any) -> None:
        result = _driver().run("named_lists", [ScriptedResponse(json=payload)])

        assert result.raised is None
        assert result.rows == [
            {"id": 1, "value": "Eng", "name": "Eng", "archived": False, "listName": "department", "parentId": None},
            {"id": 2, "value": "UK", "name": "UK", "archived": True, "listName": "site", "parentId": None},
            {"id": 3, "value": "London", "name": "London", "archived": False, "listName": "site", "parentId": 2},
        ]
        assert result.response is not None
        assert result.response.primary_keys == ["listName", "id"]
        assert result.paths == ["/v1/company/named-lists"]
        assert result.params("includeArchived") == ["true"]

    def test_auth_error_fails_loud(self) -> None:
        result = _driver().run("named_lists", [ScriptedResponse(status=401, json={"error": "unauthorized"})])

        assert isinstance(result.raised, Exception)
        assert result.paths == ["/v1/company/named-lists"]


class TestTimeOffCalendars:
    """The calendars stream fans out over employee ids (POST search)."""

    def test_follows_cursor_until_exhausted(self) -> None:
        result = _driver().run(
            "time_off_calendars",
            [
                ScriptedResponse(json={"employees": [{"id": "e1"}]}),
                ScriptedResponse(
                    json={"items": [{"/employeeCalendar/employeeId": "e1"}], "response_metadata": {"next_cursor": "n"}}
                ),
                ScriptedResponse(
                    json={"items": [{"/employeeCalendar/employeeId": "e2"}], "response_metadata": {"next_cursor": None}}
                ),
            ],
        )

        assert result.raised is None
        assert [row["employeeId"] for row in result.rows] == ["e1", "e2"]
        assert result.paths == [
            "/v1/people/search",
            "/v1/timeoff/calendars/employees/search",
            "/v1/timeoff/calendars/employees/search",
        ]
        assert all(request.method == "POST" for request in result.requests)
        assert result.requests[2].json()["cursor"] == "n"

    def test_auth_error_fails_loud(self) -> None:
        # Repeated 401s trip HiBob's WAF, so the fan-out must raise rather than swallow the failure.
        result = _driver().run("time_off_calendars", [ScriptedResponse(status=401, json={"error": "unauthorized"})])

        assert isinstance(result.raised, Exception)
        assert result.paths == ["/v1/people/search"]


class TestWorkLocations:
    def test_fans_out_employer_ids_and_follows_cursor(self) -> None:
        result = _driver().run(
            "work_locations",
            [
                ScriptedResponse(json={"items": [{"/employer/id": "11"}], "response_metadata": {"next_cursor": "e2"}}),
                ScriptedResponse(json={"items": [{"/employer/id": "12"}], "response_metadata": {"next_cursor": None}}),
                ScriptedResponse(
                    json={
                        "items": [
                            {"/workLocation/id": "1", "/workLocation/employerId": "11", "/workLocation/name": "HQ"}
                        ],
                        "response_metadata": {"next_cursor": "w2"},
                    }
                ),
                ScriptedResponse(
                    json={
                        "items": [
                            {"/workLocation/id": "2", "/workLocation/employerId": "11", "/workLocation/name": "Home"}
                        ],
                        "response_metadata": {"next_cursor": None},
                    }
                ),
                ScriptedResponse(json={"items": [], "response_metadata": {"next_cursor": None}}),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "1", "employerId": "11", "name": "HQ"},
            {"id": "2", "employerId": "11", "name": "Home"},
        ]
        assert result.response is not None
        assert result.response.primary_keys == ["employerId", "id"]
        assert result.paths == [
            "/v1/employers/search",
            "/v1/employers/search",
            "/v1/employers/11/work-locations/search",
            "/v1/employers/11/work-locations/search",
            "/v1/employers/12/work-locations/search",
        ]
        assert all(request.method == "POST" for request in result.requests)
        assert result.requests[1].json()["cursor"] == "e2"
        assert "cursor" not in result.requests[2].json()
        assert result.requests[3].json()["cursor"] == "w2"
        assert "cursor" not in result.requests[4].json()
        assert result.requests[2].json()["filters"] == []

    def test_rejects_repeated_cursor(self) -> None:
        stalled = {"items": [{"/employer/id": "11"}], "response_metadata": {"next_cursor": "stalled"}}
        result = _driver().run("work_locations", [ScriptedResponse(json=stalled), ScriptedResponse(json=stalled)])

        assert isinstance(result.raised, ValueError)
        assert "repeated cursor" in str(result.raised)


class TestHiBobSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        if endpoint == "named_lists":
            payload: Any = []
        elif endpoint == "time_off_calendars":
            payload = {"employees": []}
        else:
            payload = {}
        result = _driver().run(endpoint, [ScriptedResponse(json=payload)])

        config = HIBOB_ENDPOINTS[endpoint]
        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == list(config.primary_keys)
        assert result.response.sort_mode == "asc"
        assert result.response.partition_mode is None
        assert result.response.partition_keys is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_error",
        [
            # Service users without category permissions 403 but are valid.
            (403, True, None),
        ],
    )
    def test_validate_credentials_status_mapping(
        self, status_code: int, expected_valid: bool, expected_error: str | None
    ) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            actual = validate_credentials("service-id", "token")

        assert actual == (expected_valid, expected_error)
        assert network.requests_log[0].path == "/v1/tasks"

    def test_validate_credentials_surfaces_transport_errors(self) -> None:
        with scripted_network(always(ConnectionError("boom"))) as network:
            valid, error = validate_credentials("service-id", "token")

        assert valid is False
        assert error is not None and "boom" in error
        assert network.requests_log[0].path == "/v1/tasks"
