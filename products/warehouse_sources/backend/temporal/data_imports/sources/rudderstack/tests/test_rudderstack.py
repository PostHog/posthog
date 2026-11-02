from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.rudderstack import (
    RudderStackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rudderstack.rudderstack import (
    RudderStackCatalogLimitError,
    RudderStackResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rudderstack.source import RudderStackSource


@pytest.fixture
def driver() -> SourceDriver:
    return SourceDriver(
        RudderStackSource(),
        RudderStackSourceConfig(
            access_token="test-workspace-token", organization_access_token="test-organization-token"
        ),
    )


@pytest.mark.parametrize(
    ("table", "path", "selector", "page_param", "token"),
    [
        ("sources", "/v2/sources", "sources", "page", "test-workspace-token"),
        ("destinations", "/v2/destinations", "destinations", "page", "test-workspace-token"),
        ("connections", "/v2/connections", "connections", "page", "test-workspace-token"),
        ("retl_connections", "/v2/retl-connections", "data", "page", "test-workspace-token"),
        ("audit_logs", "/v2/audit-logs", "data", "after_cursor", "test-organization-token"),
    ],
)
def test_linked_collections_walk_to_the_end_and_commit_resume_state(
    driver: SourceDriver,
    table: str,
    path: str,
    selector: str,
    page_param: str,
    token: str,
) -> None:
    next_path = f"{path}?{page_param}=next-page"
    result = driver.run(
        table,
        [
            ScriptedResponse(json={selector: [{"id": "row-a"}], "paging": {"next": next_path}}),
            ScriptedResponse(json={selector: [{"id": "row-b"}], "paging": {"next": ""}}),
        ],
    )

    assert result.raised is None
    assert result.rows == [{"id": "row-a"}, {"id": "row-b"}]
    assert result.paths == [path, path]
    assert result.params(page_param) == [None, "next-page"]
    assert all(request.headers["authorization"] == f"Bearer {token}" for request in result.requests)
    assert result.committed_states == [
        RudderStackResumeConfig(paginator_state={"next_url": f"https://api.rudderstack.com{next_path}"})
    ]
    assert all(request.param("created_after") is None for request in result.requests)


@pytest.mark.parametrize("table", ["catalog_events", "catalog_properties", "catalog_categories"])
def test_catalog_uses_response_page_size_and_stops_at_total(driver: SourceDriver, table: str) -> None:
    result = driver.run(
        table,
        [
            ScriptedResponse(json={"data": [{"id": "a"}, {"id": "b"}], "total": 3, "pageSize": 2, "currentPage": 1}),
            ScriptedResponse(json={"data": [{"id": "c"}], "total": 3, "pageSize": 2, "currentPage": 2}),
        ],
    )

    assert result.raised is None
    assert result.rows == [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    assert result.params("page") == ["1", "2"]
    assert result.params("orderBy") == ["createdAt:asc", "createdAt:asc"]
    assert result.committed_states == [RudderStackResumeConfig(paginator_state={"page": 2})]


@pytest.mark.parametrize(
    ("payload", "error_type"),
    [
        ({"data": [{"id": "a"}], "total": 2501, "pageSize": 50}, RudderStackCatalogLimitError),
        ({"data": [{"id": "a"}], "total": 1, "pageSize": 0}, ValueError),
    ],
)
def test_catalog_refuses_incomplete_or_invalid_pagination(
    driver: SourceDriver,
    payload: dict[str, Any],
    error_type: type[Exception],
) -> None:
    result = driver.run("catalog_events", [ScriptedResponse(json=payload)])

    assert isinstance(result.raised, error_type)
    assert result.rows == []
    assert result.committed_states == []


@pytest.mark.parametrize(
    ("table", "selector", "path"),
    [
        ("transformations", "transformations", "/transformations"),
        ("libraries", "libraries", "/libraries"),
        ("tracking_plans", "trackingPlans", "/v2/catalog/tracking-plans"),
    ],
)
def test_unpaginated_collections_preserve_vendor_rows(
    driver: SourceDriver,
    table: str,
    selector: str,
    path: str,
) -> None:
    rows = [{"id": "a", "description": None, "config": {"nested": ["value"]}}, {"id": "b"}]
    result = driver.run(table, [ScriptedResponse(json={selector: rows})])

    assert result.raised is None
    assert result.rows == rows
    assert result.paths == [path]


@pytest.mark.parametrize(
    ("table", "state", "payload", "path", "param", "value"),
    [
        (
            "audit_logs",
            {"next_url": "https://api.rudderstack.com/v2/audit-logs?after_cursor=saved&per_page=100"},
            {"data": [{"id": "last"}], "paging": {}},
            "/v2/audit-logs",
            "after_cursor",
            "saved",
        ),
        (
            "catalog_properties",
            {"page": 2},
            {"data": [{"id": "last"}], "total": 3, "pageSize": 2},
            "/v2/catalog/properties",
            "page",
            "2",
        ),
    ],
)
def test_resume_starts_after_the_last_written_page(
    driver: SourceDriver,
    table: str,
    state: dict[str, Any],
    payload: dict[str, Any],
    path: str,
    param: str,
    value: str,
) -> None:
    result = driver.run(
        table, [ScriptedResponse(json=payload)], resume_state=RudderStackResumeConfig(paginator_state=state)
    )

    assert result.raised is None
    assert result.paths == [path]
    assert result.params(param) == [value]
    assert result.rows == [{"id": "last"}]


def test_sync_history_fans_out_and_preserves_the_connection_for_each_sync(driver: SourceDriver) -> None:
    first_path = "/v2/retl-connections/connection-a/syncs"
    result = driver.run(
        "retl_syncs",
        [
            ScriptedResponse(json={"data": [{"id": "connection-a"}, {"id": "connection-b"}], "paging": {}}),
            ScriptedResponse(
                json={
                    "syncs": [{"id": "shared-id", "metrics": {"total": 2}}],
                    "paging": {"next": f"{first_path}?page=2&per_page=100"},
                }
            ),
            ScriptedResponse(json={"syncs": [{"id": "last-a"}], "paging": {}}),
            ScriptedResponse(json={"syncs": [{"id": "shared-id", "metrics": {"total": 5}}], "paging": {}}),
        ],
    )

    assert result.raised is None
    assert result.rows == [
        {"id": "shared-id", "metrics": {"total": 2}, "connection_id": "connection-a"},
        {"id": "last-a", "connection_id": "connection-a"},
        {"id": "shared-id", "metrics": {"total": 5}, "connection_id": "connection-b"},
    ]
    assert result.paths == ["/v2/retl-connections", first_path, first_path, "/v2/retl-connections/connection-b/syncs"]
    assert result.params("per_page") == [None, "100", "100", "100"]
    assert all(request.param("started_after") is None for request in result.requests)
    assert result.committed_states


def test_sync_history_resume_skips_completed_connections(driver: SourceDriver) -> None:
    result = driver.run(
        "retl_syncs",
        [
            ScriptedResponse(json={"data": [{"id": "connection-a"}, {"id": "connection-b"}], "paging": {}}),
            ScriptedResponse(json={"syncs": [{"id": "remaining"}], "paging": {}}),
        ],
        resume_state=RudderStackResumeConfig(
            paginator_state={
                "completed": ["/v2/retl-connections/connection-a/syncs"],
                "current": None,
                "child_state": None,
            }
        ),
    )

    assert result.raised is None
    assert result.paths == ["/v2/retl-connections", "/v2/retl-connections/connection-b/syncs"]
    assert result.rows == [{"id": "remaining", "connection_id": "connection-b"}]


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_from_transport_match_permanent_error_messages(driver: SourceDriver, status: int) -> None:
    result = driver.run("sources", [ScriptedResponse(status=status, json={"message": "Unauthorized"})])

    assert result.raised is not None
    assert error_message_matches(str(result.raised), RudderStackSource().get_non_retryable_errors())
    assert result.rows == []
