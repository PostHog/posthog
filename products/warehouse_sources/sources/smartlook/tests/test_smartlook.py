from datetime import UTC, datetime
from typing import Literal

import pytest
import time_machine

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver
from products.warehouse_sources.sources.smartlook._config import SmartlookSourceConfig
from products.warehouse_sources.sources.smartlook.smartlook import SmartlookResumeConfig
from products.warehouse_sources.sources.smartlook.source import SmartlookSource


@pytest.mark.parametrize(
    ("table", "path", "method", "sort_field", "region"),
    [
        ("visitors", "/api/v2/visitors/search", "POST", "timeCreate", "eu"),
        ("sessions", "/api/v1/sessions/search", "POST", "timeStart", "us"),
        ("events", "/api/v1/events", "GET", None, "us"),
        ("funnels", "/api/v1/funnels", "GET", None, "eu"),
    ],
)
def test_import_uses_documented_search_body_and_next_links(
    region: Literal["eu", "us"], table: str, path: str, method: str, sort_field: str | None
) -> None:
    driver = SourceDriver(SmartlookSource(), SmartlookSourceConfig(api_token="test-token", region=region))
    next_path = f"{path}?after=next-token&limit=100"
    result = driver.run(
        table,
        [
            ScriptedResponse(
                json={table: [{"id": "first", "identification": {"uid": None}}], "_links": {"nextPage": next_path}}
            ),
            ScriptedResponse(json={table: [{"id": "last"}], "_links": {"nextPage": None}}),
        ],
    )
    assert result.raised is None
    assert [row["id"] for row in result.rows] == ["first", "last"]
    assert result.paths == [path, path]
    assert result.params("after") == [None, "next-token"]
    for request in result.requests:
        assert request.origin == f"https://api.{region}.smartlook.cloud"
        assert request.method == method
        if sort_field:
            assert request.json() == {"filters": [], "sort": {sort_field: "asc"}}
    checkpoint = SmartlookResumeConfig(paginator_state={"next_url": f"https://api.{region}.smartlook.cloud{next_path}"})
    assert result.saved_states == [checkpoint]
    assert result.committed_states == [checkpoint]


def test_resume_starts_at_saved_search_link() -> None:
    driver = SourceDriver(SmartlookSource(), SmartlookSourceConfig(api_token="test-token", region="eu"))
    next_url = "https://api.eu.smartlook.cloud/api/v2/visitors/search?after=saved-token&limit=100"
    result = driver.run(
        "visitors",
        [ScriptedResponse(json={"visitors": [{"id": "last"}], "_links": {}})],
        resume_state=SmartlookResumeConfig(paginator_state={"next_url": next_url}),
    )
    assert result.raised is None
    assert result.urls == [next_url]
    assert result.requests[0].json() == {"filters": [], "sort": {"timeCreate": "asc"}}
    assert result.rows == [{"id": "last"}]


def test_visitor_events_keep_parent_identity_and_resume_child_pages() -> None:
    driver = SourceDriver(SmartlookSource(), SmartlookSourceConfig(api_token="test-token", region="eu"))
    child_next = "/api/v1/visitors/visitor-1/events?after=child-token&limit=100"
    script = [
        ScriptedResponse(json={"visitors": [{"id": "visitor-1"}, {"id": "visitor-2"}], "_links": {}}),
        ScriptedResponse(json={"events": [{"id": "event-1", "value": None}], "_links": {"nextPage": child_next}}),
        ScriptedResponse(json={"events": [{"id": "event-2", "value": {"custom": True}}], "_links": {}}),
        ScriptedResponse(json={"events": [{"id": "event-1"}], "_links": {}}),
    ]
    result = driver.run("visitor_events", script)
    assert result.raised is None
    assert [(row["visitor_id"], row["id"]) for row in result.rows] == [
        ("visitor-1", "event-1"),
        ("visitor-1", "event-2"),
        ("visitor-2", "event-1"),
    ]
    assert result.rows[1]["value"] == {"custom": True}
    assert result.paths == [
        "/api/v2/visitors/search",
        "/api/v1/visitors/visitor-1/events",
        "/api/v1/visitors/visitor-1/events",
        "/api/v1/visitors/visitor-2/events",
    ]
    resumed = driver.run("visitor_events", [script[0], script[2], script[3]], resume_state=result.saved_states[0])
    assert resumed.raised is None
    assert resumed.params("after") == [None, "child-token", None]
    assert [(row["visitor_id"], row["id"]) for row in resumed.rows] == [
        ("visitor-1", "event-2"),
        ("visitor-2", "event-1"),
    ]


def test_missing_rows_fail_instead_of_replacing_table_with_empty_data() -> None:
    driver = SourceDriver(SmartlookSource(), SmartlookSourceConfig(api_token="test-token", region="eu"))
    result = driver.run("visitors", [ScriptedResponse(json={"unexpected": []})])
    assert result.raised is not None
    assert not result.rows


@time_machine.travel(datetime(2026, 3, 31, 23, 30, tzinfo=UTC), tick=False)
def test_event_visitors_send_the_required_window_and_keep_the_event_id() -> None:
    driver = SourceDriver(SmartlookSource(), SmartlookSourceConfig(api_token="test-token", region="eu"))
    script = [
        ScriptedResponse(json={"events": [{"id": "event-1"}, {"id": "event-2"}], "_links": {}}),
        ScriptedResponse(json={"visitors": [{"id": "visitor-1", "eventMatchedCount": 3, "firstSeen": None}]}),
        ScriptedResponse(json={}),
    ]
    result = driver.run("event_visitors", script)
    assert result.raised is None
    assert [(row["event_id"], row["id"], row["eventMatchedCount"]) for row in result.rows] == [
        ("event-1", "visitor-1", 3)
    ]
    assert result.paths == ["/api/v1/events", "/api/v1/events/event-1/visitors", "/api/v1/events/event-2/visitors"]
    assert result.params("limit") == ["100", None, None]
    assert result.params("dateFrom") == [None, "2026-03-01", "2026-03-01"]
    assert result.params("dateTo") == [None, "2026-03-31", "2026-03-31"]


def _funnels_page(funnels: list[dict], next_page: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={"funnels": funnels, "_links": {"nextPage": next_page}})


def _step_visitors(visitors: list[str]) -> ScriptedResponse:
    return ScriptedResponse(json={"totalVisitorsCount": len(visitors), "visitors": visitors})


@time_machine.travel(datetime(2026, 3, 31, 12, tzinfo=UTC), tick=False)
def test_funnel_step_visitors_walk_every_step_of_every_funnel_page() -> None:
    driver = SourceDriver(SmartlookSource(), SmartlookSourceConfig(api_token="test-token", region="us"))
    script = [
        _funnels_page(
            [
                {"id": "funnel-1", "events": [{"id": "event-a"}, {"id": "event-b"}]},
                {"id": "funnel-empty", "events": []},
            ],
            next_page="/api/v1/funnels?after=next-token&limit=100",
        ),
        _step_visitors(["visitor-1", "visitor-2"]),
        _step_visitors([]),
        _funnels_page([{"id": "funnel-2", "events": [{"id": "event-c"}]}]),
        ScriptedResponse(json={"totalVisitorsCount": 0}),
    ]
    result = driver.run("funnel_step_visitors", script)
    assert result.raised is None
    assert result.rows == [
        {"funnel_id": "funnel-1", "step": 0, "event_id": "event-a", "visitor_id": "visitor-1"},
        {"funnel_id": "funnel-1", "step": 0, "event_id": "event-a", "visitor_id": "visitor-2"},
    ]
    assert result.paths == [
        "/api/v1/funnels",
        "/api/v1/funnels/funnel-1/visitors/drop-off",
        "/api/v1/funnels/funnel-1/visitors/drop-off",
        "/api/v1/funnels",
        "/api/v1/funnels/funnel-2/visitors/drop-off",
    ]
    assert result.params("step") == [None, "0", "1", None, "0"]
    assert result.params("success") == [None, "true", "true", None, "true"]
    assert result.params("dateFrom") == [None, "2026-03-01", "2026-03-01", None, "2026-03-01"]
    assert result.params("dateTo") == [None, "2026-03-31", "2026-03-31", None, "2026-03-31"]
    assert result.saved_states[-1] == SmartlookResumeConfig(
        paginator_state={"completed_funnels": ["funnel-1", "funnel-empty", "funnel-2"]}
    )


def test_funnel_step_visitors_resume_after_the_last_staged_step() -> None:
    driver = SourceDriver(SmartlookSource(), SmartlookSourceConfig(api_token="test-token", region="eu"))
    funnels = _funnels_page(
        [
            {"id": "funnel-done", "events": [{"id": "event-a"}]},
            {"id": "funnel-1", "events": [{"id": "event-a"}, {"id": "event-b"}, {"id": "event-c"}]},
        ]
    )
    result = driver.run(
        "funnel_step_visitors",
        [funnels, _step_visitors(["visitor-3"])],
        resume_state=SmartlookResumeConfig(
            paginator_state={"completed_funnels": ["funnel-done"], "funnel_id": "funnel-1", "next_step": 2}
        ),
    )
    assert result.raised is None
    assert result.params("step") == [None, "2"]
    assert result.rows == [{"funnel_id": "funnel-1", "step": 2, "event_id": "event-c", "visitor_id": "visitor-3"}]


@pytest.mark.parametrize("body", [{"visitors": ["visitor-1"]}, [], {"error": "invalid step"}])
def test_funnel_step_visitors_fail_on_unexpected_step_response(body: object) -> None:
    driver = SourceDriver(SmartlookSource(), SmartlookSourceConfig(api_token="test-token", region="eu"))
    script = [_funnels_page([{"id": "funnel-1", "events": [{"id": "event-a"}]}]), ScriptedResponse(json=body)]
    result = driver.run("funnel_step_visitors", script)
    assert result.raised is not None
    assert not result.rows
