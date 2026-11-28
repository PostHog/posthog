from typing import Any

import pytest
from unittest.mock import patch

from requests.exceptions import HTTPError

from products.warehouse_sources.sources.sdk import SourceCursorManager
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, error_message_matches, route
from products.warehouse_sources.sources.umami._config import UmamiSourceConfig
from products.warehouse_sources.sources.umami.settings import DAY_MS
from products.warehouse_sources.sources.umami.source import UmamiSource
from products.warehouse_sources.sources.umami.umami import UmamiError, UmamiEventCursor, UmamiResumeState

START = 1704067200000


def page(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": rows, "count": len(rows), "page": 1, "pageSize": 100})


def driver(host: str | None = None, **config: Any) -> SourceDriver:
    return SourceDriver(UmamiSource(), UmamiSourceConfig(host=host, **(config or {"api_key": "fake-key"})))


@pytest.mark.parametrize("host", [None, "https://api.umami.is/v1/eu", "https://analytics.example.com"])
def test_catalog_walk_and_page_resume(host: str | None) -> None:
    result = driver(host).run(
        "websites",
        [page([{"id": "site-b"}]), page([{"id": "site-c"}]), page([])],
        resume_state=UmamiResumeState(page=2),
    )
    assert result.raised is None
    assert result.params("page") == ["2", "3", "4"]
    assert result.params("includeTeams") == ["true"] * 3
    assert result.rows == [{"id": "site-b"}, {"id": "site-c"}]
    assert result.committed_states[-2:] == [UmamiResumeState(page=3), UmamiResumeState(page=4)]
    header = "x-umami-api-key" if host is None or "api.umami.is" in host else "authorization"
    assert result.requests[0].headers[header] == ("fake-key" if header == "x-umami-api-key" else "Bearer fake-key")
    if host == "https://analytics.example.com":
        assert result.paths[0] == "/api/websites"
    else:
        assert result.paths[0] == ("/v1/websites" if host is None else "/v1/eu/websites")


@pytest.mark.parametrize("table", ["events", "sessions"])
def test_history_windows_preserve_session_totals_and_milliseconds(table: str) -> None:
    pages = [page([{"id": "first", "websiteId": "wrong"}]), page([{"id": "second"}]), page([])]
    if table == "events":
        pages += [page([{"id": "next-day"}]), page([])]
    result = driver().run(
        table,
        route(
            {
                "/websites": [page([{"id": "site-a"}]), page([{"id": "empty-site"}]), page([])],
                "/site-a/daterange": [
                    ScriptedResponse(json={"startDate": "2024-01-01T00:00:00Z", "endDate": "2024-01-02T00:00:00Z"})
                ],
                f"/site-a/{table}": pages,
                "/empty-site/daterange": [ScriptedResponse(json={"startDate": None, "endDate": None})],
            }
        ),
    )
    assert result.raised is None
    child = [request for request in result.requests if request.path.endswith(f"/{table}")]
    assert [request.param("page") for request in child] == (
        ["1", "2", "3", "1", "2"] if table == "events" else ["1", "2", "3"]
    )
    assert [request.param("startAt") for request in child] == [str(START)] * 3 + (
        [str(START + DAY_MS)] * 2 if table == "events" else []
    )
    assert child[0].param("endAt") == str(START + DAY_MS - 1 if table == "events" else START + DAY_MS)
    assert [row["id"] for row in result.rows] == (
        ["first", "second", "next-day"] if table == "events" else ["first", "second"]
    )
    assert all(row["websiteId"] == "site-a" for row in result.rows)
    assert [state.page for state in result.committed_states if state.website_id == "site-a"][:3] == [1, 2, 3]
    assert result.committed_states[1].start_at == START
    assert result.committed_states[-1].completed_websites == ["site-a", "empty-site"]


def test_resume_keeps_window_ceiling_and_skips_completed_websites() -> None:
    state = UmamiResumeState(
        page=2,
        completed_websites=["site-a"],
        website_id="site-b",
        start_at=START,
        end_at=START + 10,
        stop_at=START + 10,
    )
    result = driver().run(
        "events",
        route(
            {
                "/websites": [page([{"id": "site-a"}, {"id": "site-b"}]), page([])],
                "/site-b/events": [page([{"id": "remaining"}]), page([])],
            }
        ),
        resume_state=state,
    )
    assert result.raised is None
    assert result.rows == [{"id": "remaining", "websiteId": "site-b"}]
    child = result.requests[1]
    assert child.param("page") == "2"
    assert child.param("endAt") == str(START + 10)
    assert not any(request.path.endswith("/daterange") for request in result.requests)
    assert any(state.page == 3 and state.website_id == "site-b" for state in result.committed_states)


@pytest.mark.parametrize("table", ["goals", "funnels"])
def test_saved_definitions_resume_without_requesting_a_date_range(table: str) -> None:
    result = driver().run(
        table,
        route(
            {
                "/websites": [page([{"id": "site-a"}, {"id": "site-b"}, {"id": "site-c"}]), page([])],
                f"/site-b/{table}": [page([{"id": "saved-b", "parameters": "{}"}]), page([])],
                f"/site-c/{table}": [page([{"id": "saved-c"}]), page([])],
            }
        ),
        resume_state=UmamiResumeState(page=2, website_id="site-b", completed_websites=["site-a"]),
    )
    assert result.raised is None
    assert result.rows == [
        {"id": "saved-b", "websiteId": "site-b", "parameters": "{}"},
        {"id": "saved-c", "websiteId": "site-c"},
    ]
    definitions = [request for request in result.requests if request.path.endswith(f"/{table}")]
    assert [request.param("page") for request in definitions] == ["2", "3", "1", "2"]
    assert all(request.param("startAt") is None and request.param("endAt") is None for request in definitions)


def test_event_properties_backfill_new_websites_and_resume_known_websites_inclusively() -> None:
    created_at = "2024-01-01T00:00:00.123Z"
    properties = [
        {"createdAt": created_at, "dataKey": "plan", "stringValue": "basic"},
        {"createdAt": created_at, "dataKey": "amount", "numberValue": 50},
    ]
    known_event = {"eventId": "purchase", "eventProperties": properties}
    historical_event = {"eventId": "signup", "eventProperties": [{"createdAt": "2024-01-01T00:00:00Z"}]}
    cursor = SourceCursorManager(UmamiEventCursor, None, UmamiSource())
    initial = driver().run(
        "event_properties",
        route(
            {
                "/websites": [page([{"id": "site-a"}]), page([])],
                "/site-a/daterange": [ScriptedResponse(json={"startDate": START, "endDate": START + 500})],
                "/site-a/event-data": [page([known_event]), page([])],
            }
        ),
        incremental_field="createdAt",
        source_cursor=cursor,
    )
    assert initial.raised is None
    assert cursor.staged == UmamiEventCursor(watermarks={"site-a": START + 123})

    next_cursor = SourceCursorManager(UmamiEventCursor, cursor.staged, UmamiSource())
    result = driver().run(
        "event_properties",
        route(
            {
                "/websites": [page([{"id": "site-b"}, {"id": "site-a"}]), page([])],
                "/site-b/daterange": [ScriptedResponse(json={"startDate": START - 100, "endDate": START})],
                "/site-b/event-data": [page([historical_event]), page([])],
                "/site-a/daterange": [ScriptedResponse(json={"startDate": START, "endDate": START + 500})],
                "/site-a/event-data": [page([known_event]), page([])],
            }
        ),
        incremental_field="createdAt",
        db_incremental_field_last_value=created_at,
        source_cursor=next_cursor,
    )
    assert result.raised is None
    assert [(row["websiteId"], row["eventId"]) for row in result.rows] == [("site-b", "signup"), ("site-a", "purchase")]
    assert result.rows[1] == {
        "websiteId": "site-a",
        "eventId": "purchase",
        "createdAt": created_at,
        "eventProperties": properties,
    }
    events = [request for request in result.requests if request.path.endswith("/event-data")]
    assert [request.param("startAt") for request in events] == [str(START - 100)] * 2 + [str(START + 123)] * 2
    assert [request.param("endAt") for request in events] == [str(START)] * 2 + [str(START + 500)] * 2
    assert next_cursor.staged == UmamiEventCursor(watermarks={"site-a": START + 123, "site-b": START})


def test_session_properties_resume_within_a_page_and_keep_repeated_keys() -> None:
    created_at = "2024-01-01T00:00:00Z"
    properties = [
        {"dataKey": "plan", "stringValue": "basic"},
        {"dataKey": "plan", "stringValue": "upgraded"},
    ]
    result = driver().run(
        "session_properties",
        route(
            {
                "/websites": [page([{"id": "site-a"}]), page([])],
                "/site-a/sessions": [
                    page([{"id": "finished"}, {"id": "with-properties", "createdAt": created_at}]),
                    page([{"id": "no-properties"}]),
                    page([]),
                ],
                "/with-properties/properties": [ScriptedResponse(json=properties)],
                "/no-properties/properties": [ScriptedResponse(json=[])],
            }
        ),
        resume_state=UmamiResumeState(
            page=2, website_id="site-a", start_at=START, end_at=START + 10, stop_at=START + 10, session_index=1
        ),
    )
    assert result.raised is None
    assert result.rows == [
        {
            "websiteId": "site-a",
            "sessionId": "with-properties",
            "createdAt": created_at,
            "sessionProperties": properties,
        }
    ]
    assert [path for path in result.paths if path.endswith("/properties")] == [
        "/v1/websites/site-a/sessions/with-properties/properties",
        "/v1/websites/site-a/sessions/no-properties/properties",
    ]
    assert any(state.page == 2 and state.session_index == 2 for state in result.committed_states)


@pytest.mark.parametrize("repeats_last_page", [False, True])
@pytest.mark.parametrize("table,path", [("session_properties", "sessions"), ("goals", "goals"), ("funnels", "funnels")])
def test_fan_out_stops_at_the_website_page_limit(table: str, path: str, repeats_last_page: bool) -> None:
    row = {"id": "item-a", "createdAt": "2024-01-01T00:00:00Z"}
    routes = {
        "/websites": [page([{"id": "site-a"}]), page([])],
        f"/site-a/{path}": [page([row]), page([row] if repeats_last_page else [])],
    }
    resume_state = UmamiResumeState(page=2, website_id="site-a")
    if table == "session_properties":
        routes["/item-a/properties"] = [ScriptedResponse(json=[{"dataKey": "plan", "stringValue": "basic"}])]
        resume_state = UmamiResumeState(page=2, website_id="site-a", start_at=START, end_at=START, stop_at=START)

    with patch("products.warehouse_sources.sources.umami.umami.MAX_FAN_OUT_PAGES", 2):
        result = driver("https://analytics.example.com").run(
            table,
            route(routes),
            resume_state=resume_state,
        )

    assert [request.param("page") for request in result.requests if request.path.endswith(f"/{path}")] == ["2", "3"]
    assert len(result.rows) == 1
    if table == "session_properties":
        assert result.paths.count("/api/websites/site-a/sessions/item-a/properties") == 1
    if repeats_last_page:
        assert isinstance(result.raised, UmamiError)
        assert "exceeded the limit of 2 pages per website" in str(result.raised)
    else:
        assert result.raised is None


def test_event_properties_keep_the_page_budget_across_windows_and_retries() -> None:
    next_day = START + DAY_MS
    cursor = SourceCursorManager(UmamiEventCursor, None, UmamiSource())
    with patch("products.warehouse_sources.sources.umami.umami.MAX_FAN_OUT_PAGES", 1):
        interrupted = driver().run(
            "event_properties",
            route(
                {
                    "/websites": [page([{"id": "site-a"}]), page([])],
                    "/site-a/daterange": [ScriptedResponse(json={"startDate": START, "endDate": next_day})],
                    "/site-a/event-data": [
                        page([{"eventId": "first", "eventProperties": [{"createdAt": START}]}]),
                        page([]),
                        ScriptedResponse(status=400, json={}),
                    ],
                }
            ),
            source_cursor=cursor,
        )
        assert isinstance(interrupted.raised, HTTPError)
        assert [row["eventId"] for row in interrupted.rows] == ["first"]

        resumed = driver().run(
            "event_properties",
            route(
                {
                    "/websites": [page([{"id": "site-a"}]), page([])],
                    "/site-a/event-data": [page([{"eventId": "later", "eventProperties": [{"createdAt": next_day}]}])],
                }
            ),
            resume_state=interrupted.final_state,
            source_cursor=cursor,
        )
    assert isinstance(resumed.raised, UmamiError)
    assert resumed.rows == []
    assert cursor.staged is None


@pytest.mark.parametrize("second_status", [200, 401])
def test_expired_login_replays_once_and_keeps_new_token(second_status: int) -> None:
    responses = [
        ScriptedResponse(status=401, json={"error": {"code": "unauthorized"}}),
        page([{"id": "site-a"}])
        if second_status == 200
        else ScriptedResponse(status=401, json={"error": {"code": "unauthorized"}}),
    ]
    if second_status == 200:
        responses.append(page([]))
    result = driver("https://analytics.example.com/api", username="reader", password="fake-password").run(
        "websites",
        route(
            {
                "/auth/login": [
                    ScriptedResponse(json={"token": "fake-old-token"}),
                    ScriptedResponse(json={"token": "fake-new-token"}),
                ],
                "/websites": responses,
            }
        ),
    )
    assert result.paths.count("/api/auth/login") == 2
    assert result.requests[1].headers["authorization"] == "Bearer fake-old-token"
    assert result.requests[3].headers["authorization"] == "Bearer fake-new-token"
    if second_status == 200:
        assert result.raised is None
        assert result.requests[4].headers["authorization"] == "Bearer fake-new-token"
        assert result.rows == [{"id": "site-a"}]
    else:
        assert "401 Client Error" in str(result.raised)
        assert result.rows == []


@pytest.mark.parametrize(
    "login_statuses, retryable",
    [
        ([530, 200], None),
        ([502, 520, 200], None),
        ([530, 530, 530], True),
        ([503, 503, 503], True),
        ([404], False),
        ([501], False),
    ],
)
def test_transient_login_failure_is_retried_then_classified_as_retryable(
    login_statuses: list[int], retryable: bool | None
) -> None:
    logins = [
        ScriptedResponse(json={"token": "fake-token"}) if status == 200 else ScriptedResponse(status=status)
        for status in login_statuses
    ]
    result = driver("https://analytics.example.com/api", username="reader", password="fake-password").run(
        "websites", route({"/auth/login": logins, "/websites": [page([{"id": "site-a"}]), page([])]})
    )
    assert result.paths.count("/api/auth/login") == len(login_statuses)
    if retryable is None:
        assert result.raised is None
        assert result.rows == [{"id": "site-a"}]
    else:
        assert isinstance(result.raised, HTTPError)
        assert error_message_matches(str(result.raised), UmamiSource().get_retryable_errors()) is retryable
        assert result.rows == []


@pytest.mark.parametrize(
    "body, message",
    [
        ({"data": [{"id": "truncated"}], "isCapped": True}, "capped"),
        ({"count": 1}, "data_selector"),
    ],
)
def test_invalid_or_capped_response_cannot_replace_the_table(body: dict[str, Any], message: str) -> None:
    result = driver().run("websites", [ScriptedResponse(json=body)])
    assert message in str(result.raised)
    assert result.rows == []
    assert result.committed_states == []


@pytest.mark.parametrize("dates", [{"startDate": None, "endDate": None}, {"startDate": "2024-01-01", "endDate": None}])
def test_website_without_a_complete_date_range_is_treated_as_empty(dates: dict[str, str | None]) -> None:
    result = driver().run(
        "events",
        route({"/websites": [page([{"id": "site-a"}]), page([])], "/site-a/daterange": [ScriptedResponse(json=dates)]}),
    )
    assert result.raised is None
    assert result.rows == []
    assert not any(request.path.endswith("/events") for request in result.requests)


@pytest.mark.parametrize(
    "dates",
    [
        {},
        {"startDate": "not-a-date", "endDate": "2024-01-01"},
        {"startDate": "2024-01-02", "endDate": "2024-01-01"},
        {"startDate": "0001-01-01", "endDate": "2024-01-01"},
        {"startDate": "2024-01-01", "endDate": "9999-12-31"},
    ],
)
def test_invalid_date_range_fails_before_a_child_request(dates: dict[str, str]) -> None:
    result = driver().run("events", [page([{"id": "site-a"}]), ScriptedResponse(json=dates)])
    assert "date range" in str(result.raised)
    assert result.rows == []
    assert len(result.requests) == 2
