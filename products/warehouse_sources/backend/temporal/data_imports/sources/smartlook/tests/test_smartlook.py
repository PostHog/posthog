from typing import Literal

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartlook import (
    SmartlookSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlook.smartlook import SmartlookResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.smartlook.source import SmartlookSource


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
