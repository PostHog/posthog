import json
from typing import Any

import pytest
from unittest import mock

from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob import (
    hibob_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.settings import ENDPOINTS, HIBOB_ENDPOINTS

# RESTClient builds its session via make_tracked_session in the rest_client module.
CLIENT_SESSION_PATCH = "products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client.make_tracked_session"
# validate_credentials builds its own tracked session in the hibob module.
HIBOB_SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob.make_tracked_session"
)


def _response(body: Any, status: int = 200) -> Response:
    resp = Response()
    resp.status_code = status
    resp._content = json.dumps(body).encode()
    resp.url = "https://api.hibob.com/probe"
    return resp


def _wire(session: mock.MagicMock, responses: list[Response]) -> list[dict[str, Any]]:
    """Wire a mock session, snapshotting each request (method/url/json/auth) AT SEND TIME."""
    session.headers = {}
    captured: list[dict[str, Any]] = []

    def _prepare(request: Any) -> mock.MagicMock:
        captured.append(
            {
                "method": request.method,
                "url": request.url,
                "params": dict(request.params or {}),
                "json": dict(request.json) if request.json is not None else None,
                "auth": request.auth,
            }
        )
        return mock.MagicMock()

    session.prepare_request.side_effect = _prepare
    session.send.side_effect = responses
    return captured


def _rows(source_response) -> list[dict[str, Any]]:
    return [row for page in source_response.items() for row in page]


class TestGetRows:
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_auth_error_is_not_retried_and_raises(self, MockSession, _sleep) -> None:
        session = MockSession.return_value
        # 401 trips HiBob's WAF on repeat, so it must fail loud without retrying.
        _wire(session, [_response({"error": "unauthorized"}, status=401)])

        with pytest.raises(Exception):
            _rows(hibob_source("service-id", "token", "tasks", team_id=1, job_id="j"))

        assert session.send.call_count == 1


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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_flattens_entries_per_employee_and_follows_query_cursor(
        self, MockSession, endpoint, path, values_page_1, values_page_2
    ) -> None:
        session = MockSession.return_value
        captured = _wire(
            session,
            [
                _response(
                    {
                        "results": [{"employeeId": "e1", "values": values_page_1}],
                        "response_metadata": {"next_cursor": "c2"},
                    }
                ),
                _response(
                    {
                        "results": [{"employeeId": "e2", "values": values_page_2}, {"employeeId": "e3", "values": []}],
                        "response_metadata": {"next_cursor": None},
                    }
                ),
            ],
        )

        response = hibob_source("service-id", "token", endpoint, team_id=1, job_id="j")
        rows = _rows(response)

        assert rows == [
            {"id": 1, "status": "hired", "employeeId": "e1"},
            {"id": 2, "status": "employed", "employeeId": "e1"},
            {"id": 1, "status": "hired", "employeeId": "e2"},
        ]
        assert response.primary_keys == ["employeeId", "id"]
        assert [(c["method"], c["url"]) for c in captured] == [("GET", f"https://api.hibob.com{path}")] * 2
        assert captured[0]["params"] == {"limit": 200}
        assert captured[1]["params"] == {"limit": 200, "cursor": "c2"}

    @mock.patch(CLIENT_SESSION_PATCH)
    def test_rejects_repeated_cursor(self, MockSession) -> None:
        session = MockSession.return_value
        _wire(
            session,
            [
                _response({"results": [], "response_metadata": {"next_cursor": "stalled"}}),
                _response({"results": [], "response_metadata": {"next_cursor": "stalled"}}),
            ],
        )

        with pytest.raises(ValueError, match="repeated cursor"):
            _rows(hibob_source("service-id", "token", "employee_lifecycle", team_id=1, job_id="j"))


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
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_posts_body_cursor_and_normalizes_pointer_keys(
        self, MockSession, endpoint, path, prefix, requested_field
    ) -> None:
        session = MockSession.return_value
        captured = _wire(
            session,
            [
                _response(
                    {
                        "items": [{f"{prefix}/id": 7, f"{prefix}/status": "active"}],
                        "response_metadata": {"next_cursor": "c2"},
                    }
                ),
                _response({"items": [{f"{prefix}/id": 8}], "response_metadata": {"next_cursor": None}}),
            ],
        )

        rows = _rows(hibob_source("service-id", "token", endpoint, team_id=1, job_id="j"))

        assert rows == [{"id": 7, "status": "active"}, {"id": 8}]
        assert [(c["method"], c["url"]) for c in captured] == [("POST", f"https://api.hibob.com{path}")] * 2
        assert "cursor" not in captured[0]["json"]
        assert requested_field in captured[0]["json"]["fields"]
        # HiBob rejects a search asking for more than 50 fields.
        assert len(captured[0]["json"]["fields"]) <= 50
        assert captured[1]["json"]["cursor"] == "c2"
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
    @mock.patch(HIBOB_SESSION_PATCH)
    def test_flattens_nested_items_with_list_name_and_parent(self, mock_make_session, payload) -> None:
        session = mock_make_session.return_value
        session.get.return_value = _response(payload)

        response = hibob_source("service-id", "token", "named_lists", team_id=1, job_id="j")
        rows = _rows(response)

        assert rows == [
            {"id": 1, "value": "Eng", "name": "Eng", "archived": False, "listName": "department", "parentId": None},
            {"id": 2, "value": "UK", "name": "UK", "archived": True, "listName": "site", "parentId": None},
            {"id": 3, "value": "London", "name": "London", "archived": False, "listName": "site", "parentId": 2},
        ]
        assert response.primary_keys == ["listName", "id"]
        assert session.get.call_args.args[0] == "https://api.hibob.com/v1/company/named-lists"
        assert session.get.call_args.kwargs["params"] == {"includeArchived": "true"}

    @mock.patch(HIBOB_SESSION_PATCH)
    def test_auth_error_fails_loud(self, mock_make_session) -> None:
        mock_make_session.return_value.get.return_value = _response({"error": "unauthorized"}, status=401)

        with pytest.raises(Exception):
            _rows(hibob_source("service-id", "token", "named_lists", team_id=1, job_id="j"))


class TestTimeOffCalendars:
    """The calendars stream fans out over employee ids (POST search), so it hand-rolls its own
    session.post calls rather than riding the shared rest_client."""

    def _people_then_calendars(self, session, calendar_pages: list[Response], employees=None):
        employees = employees if employees is not None else [{"id": "e1"}, {"id": "e2"}]
        session.post.side_effect = [_response({"employees": employees}), *calendar_pages]

    @mock.patch(HIBOB_SESSION_PATCH)
    def test_follows_cursor_until_exhausted(self, mock_make_session):
        session = mock_make_session.return_value
        self._people_then_calendars(
            session,
            [
                _response(
                    {"items": [{"/employeeCalendar/employeeId": "e1"}], "response_metadata": {"next_cursor": "n"}}
                ),
                _response(
                    {"items": [{"/employeeCalendar/employeeId": "e2"}], "response_metadata": {"next_cursor": None}}
                ),
            ],
            employees=[{"id": "e1"}],
        )

        rows = _rows(hibob_source("service-id", "token", "time_off_calendars", team_id=1, job_id="j"))

        assert [row["employeeId"] for row in rows] == ["e1", "e2"]
        assert session.post.call_count == 3  # people/search + two cursor pages
        assert session.post.call_args_list[2].kwargs["json"]["cursor"] == "n"

    @mock.patch(HIBOB_SESSION_PATCH)
    def test_auth_error_fails_loud(self, mock_make_session):
        session = mock_make_session.return_value
        # Repeated 401s trip HiBob's WAF, so the fan-out must raise rather than swallow the failure.
        session.post.side_effect = [_response({"error": "unauthorized"}, status=401)]

        with pytest.raises(Exception):
            _rows(hibob_source("service-id", "token", "time_off_calendars", team_id=1, job_id="j"))


class TestWorkLocations:
    @mock.patch(HIBOB_SESSION_PATCH)
    def test_fans_out_employer_ids_and_follows_cursor(self, mock_make_session):
        session = mock_make_session.return_value
        session.post.side_effect = [
            _response({"items": [{"/employer/id": "11"}], "response_metadata": {"next_cursor": "e2"}}),
            _response({"items": [{"/employer/id": "12"}], "response_metadata": {"next_cursor": None}}),
            _response(
                {
                    "items": [{"/workLocation/id": "1", "/workLocation/employerId": "11", "/workLocation/name": "HQ"}],
                    "response_metadata": {"next_cursor": "w2"},
                }
            ),
            _response(
                {
                    "items": [
                        {"/workLocation/id": "2", "/workLocation/employerId": "11", "/workLocation/name": "Home"}
                    ],
                    "response_metadata": {"next_cursor": None},
                }
            ),
            _response({"items": [], "response_metadata": {"next_cursor": None}}),
        ]

        response = hibob_source("service-id", "token", "work_locations", team_id=1, job_id="j")
        rows = _rows(response)

        assert rows == [
            {"id": "1", "employerId": "11", "name": "HQ"},
            {"id": "2", "employerId": "11", "name": "Home"},
        ]
        assert response.primary_keys == ["employerId", "id"]
        calls = session.post.call_args_list
        assert [call.args[0] for call in calls] == [
            "https://api.hibob.com/v1/employers/search",
            "https://api.hibob.com/v1/employers/search",
            "https://api.hibob.com/v1/employers/11/work-locations/search",
            "https://api.hibob.com/v1/employers/11/work-locations/search",
            "https://api.hibob.com/v1/employers/12/work-locations/search",
        ]
        assert calls[1].kwargs["json"]["cursor"] == "e2"
        assert "cursor" not in calls[2].kwargs["json"]
        assert calls[3].kwargs["json"]["cursor"] == "w2"
        assert "cursor" not in calls[4].kwargs["json"]
        assert calls[2].kwargs["json"]["filters"] == []

    @mock.patch(HIBOB_SESSION_PATCH)
    def test_rejects_repeated_cursor(self, mock_make_session):
        session = mock_make_session.return_value
        stalled = {"items": [{"/employer/id": "11"}], "response_metadata": {"next_cursor": "stalled"}}
        session.post.side_effect = [_response(stalled), _response(stalled)]

        with pytest.raises(ValueError, match="repeated cursor"):
            _rows(hibob_source("service-id", "token", "work_locations", team_id=1, job_id="j"))


class TestHiBobSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    @mock.patch(CLIENT_SESSION_PATCH)
    def test_response_metadata_per_endpoint(self, MockSession, endpoint) -> None:
        config = HIBOB_ENDPOINTS[endpoint]
        response = hibob_source("service-id", "token", endpoint, team_id=1, job_id="j")

        assert response.name == endpoint
        assert response.primary_keys == list(config.primary_keys)
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_error",
        [
            (200, True, None),
            # Service users without category permissions 403 but are valid.
            (403, True, None),
            (401, False, "Invalid HiBob Service User credentials"),
        ],
    )
    @mock.patch(HIBOB_SESSION_PATCH)
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected_valid, expected_error):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("service-id", "token") == (expected_valid, expected_error)

    @mock.patch(HIBOB_SESSION_PATCH)
    def test_validate_credentials_surfaces_transport_errors(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("service-id", "token") == (False, "boom")
