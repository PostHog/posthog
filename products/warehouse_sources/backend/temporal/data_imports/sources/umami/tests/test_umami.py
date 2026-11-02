from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    route,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.umami import UmamiSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.umami.settings import DAY_MS
from products.warehouse_sources.backend.temporal.data_imports.sources.umami.source import UmamiSource
from products.warehouse_sources.backend.temporal.data_imports.sources.umami.umami import UmamiResumeState

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
