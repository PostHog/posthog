from datetime import UTC, datetime

import pytest

from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network
from products.warehouse_sources.sources.shipmail._config import ShipmailSourceConfig
from products.warehouse_sources.sources.shipmail.shipmail import (
    SHIPMAIL_BASE_URL,
    ShipmailResumeConfig,
    _incremental_value,
    get_capabilities,
)
from products.warehouse_sources.sources.shipmail.source import ShipmailSource


def _driver() -> SourceDriver:
    return SourceDriver(ShipmailSource(), ShipmailSourceConfig(api_key="test-key"))


def test_incremental_value_preserves_iso_timestamp() -> None:
    value = datetime(2026, 7, 29, 12, 30, tzinfo=UTC)
    assert _incremental_value(value) == "2026-07-29T12:30:00+00:00"
    assert _incremental_value("2026-07-29T12:30:00Z") == "2026-07-29T12:30:00Z"


@pytest.mark.parametrize("endpoint", ["messages", "newsletters", "members"])
def test_pagination_checkpoints_and_incremental_watermark(endpoint: str) -> None:
    result = _driver().run(
        endpoint,
        [
            ScriptedResponse(
                json={
                    "data": [{"id": "msg_1"}],
                    "pagination": {"next_cursor": "cursor_2", "has_more": True, "limit": 100},
                }
            ),
            ScriptedResponse(
                json={
                    "data": [{"id": "msg_2"}],
                    "pagination": {"next_cursor": None, "has_more": False, "limit": 100},
                }
            ),
        ],
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-07-01T00:00:00Z",
        incremental_field="updated_at",
    )

    assert result.rows == [{"id": "msg_1"}, {"id": "msg_2"}]
    assert result.raised is None
    path = "messages/analytics" if endpoint == "messages" else endpoint
    assert result.paths == [f"/api/v1/{path}"] * 2
    params = {"limit": ("100",)}
    if endpoint == "messages":
        params["updated_after"] = ("2026-07-01T00:00:00Z",)
    assert result.queries == [params, {**params, "cursor": ("cursor_2",)}]
    assert result.saved_states == [ShipmailResumeConfig(cursor="cursor_2")]
    assert result.session_options == [{"redact_values": ("test-key",), "capture": False}]


@pytest.mark.parametrize(
    "endpoint,parent,child_path,parent_key",
    [
        ("threads", "mailboxes", "/threads?mailbox_id={id}", "mailbox_id"),
        ("audience_subscribers", "audiences", "/audiences/{id}/subscribers", "audience_id"),
    ],
)
def test_fanout_paginates_parents_and_children(endpoint: str, parent: str, child_path: str, parent_key: str) -> None:
    result = _driver().run(
        endpoint,
        [
            ScriptedResponse(
                json={"data": [{"id": "parent_1"}, {"id": "empty"}], "pagination": {"next_cursor": "parents_2"}}
            ),
            ScriptedResponse(json={"data": [{"id": "shared"}], "pagination": {"next_cursor": "children_2"}}),
            ScriptedResponse(json={"data": [{"id": "child_2"}], "pagination": {"next_cursor": None}}),
            ScriptedResponse(json={"data": [], "pagination": {"next_cursor": None}}),
            ScriptedResponse(json={"data": [{"id": "parent_2"}], "pagination": {"next_cursor": None}}),
            ScriptedResponse(json={"data": [{"id": "shared"}], "pagination": {"next_cursor": None}}),
        ],
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-07-01T00:00:00Z",
        incremental_field="updated_at",
    )

    assert result.raised is None
    assert result.rows == [
        {"id": "shared", parent_key: "parent_1"},
        {"id": "child_2", parent_key: "parent_1"},
        {"id": "shared", parent_key: "parent_2"},
    ]
    children = [
        child_path.format(id=value).partition("?")[0] for value in ["parent_1", "parent_1", "empty", "parent_2"]
    ]
    assert result.paths == [
        f"/api/v1/{parent}",
        *[f"/api/v1{path}" for path in children[:3]],
        f"/api/v1/{parent}",
        f"/api/v1{children[3]}",
    ]
    expected_queries = [
        {"limit": ("100",)},
        {"limit": ("100",)},
        {"limit": ("100",), "cursor": ("children_2",)},
        {"limit": ("100",)},
        {"limit": ("100",), "cursor": ("parents_2",)},
        {"limit": ("100",)},
    ]
    if endpoint == "threads":
        for index, parent_id in [(1, "parent_1"), (2, "parent_1"), (3, "empty"), (5, "parent_2")]:
            expected_queries[index]["mailbox_id"] = (parent_id,)
    assert result.queries == expected_queries
    assert result.committed_states
    assert any(
        state.fanout_state and state.fanout_state.get("child_state") == {"cursor": "children_2"}
        for state in result.committed_states
    )


@pytest.mark.parametrize(
    "endpoint,parent,child_path,parent_key",
    [
        ("threads", "mailboxes", "/threads?mailbox_id={id}", "mailbox_id"),
        ("audience_subscribers", "audiences", "/audiences/{id}/subscribers", "audience_id"),
    ],
)
def test_fanout_resumes_parent_and_child_cursors(endpoint: str, parent: str, child_path: str, parent_key: str) -> None:
    result = _driver().run(
        endpoint,
        [
            ScriptedResponse(json={"data": [{"id": "done"}, {"id": "current"}], "pagination": {"next_cursor": None}}),
            ScriptedResponse(json={"data": [{"id": "remaining"}], "pagination": {"next_cursor": None}}),
        ],
        resume_state=ShipmailResumeConfig(
            fanout_state={
                "parent": {"cursor": "parents_2"},
                "completed": [child_path.format(id="done")],
                "current": child_path.format(id="current"),
                "child_state": {"cursor": "children_2"},
            }
        ),
    )

    assert result.raised is None
    assert result.rows == [{"id": "remaining", parent_key: "current"}]
    assert result.paths == [f"/api/v1/{parent}", f"/api/v1{child_path.format(id='current').partition('?')[0]}"]
    child_query = {"limit": ("100",), "cursor": ("children_2",)}
    if endpoint == "threads":
        child_query["mailbox_id"] = ("current",)
    assert result.queries == [{"limit": ("100",), "cursor": ("parents_2",)}, child_query]


def test_resumes_from_saved_cursor() -> None:
    result = _driver().run(
        "mailboxes",
        [
            ScriptedResponse(
                json={
                    "data": [{"id": "mbx_2"}],
                    "pagination": {"next_cursor": None, "has_more": False, "limit": 100},
                }
            )
        ],
        resume_state=ShipmailResumeConfig(cursor="cursor_2"),
    )

    assert result.rows == [{"id": "mbx_2"}]
    assert result.queries[0] == {"limit": ("100",), "cursor": ("cursor_2",)}


def test_full_refresh_endpoint_does_not_send_incremental_watermark() -> None:
    result = _driver().run(
        "domains",
        [
            ScriptedResponse(
                json={
                    "data": [{"id": "domain_1"}],
                    "pagination": {"next_cursor": None, "has_more": False, "limit": 100},
                }
            )
        ],
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-07-01T00:00:00Z",
        incremental_field="updated_at",
    )

    assert result.queries[0] == {"limit": ("100",)}


def test_missing_data_key_raises() -> None:
    result = _driver().run("messages", [ScriptedResponse(json={"pagination": {"next_cursor": None}})])

    assert isinstance(result.raised, ValueError)
    assert "matched nothing" in str(result.raised)


def test_get_capabilities_returns_status_and_scopes() -> None:
    with scripted_network([ScriptedResponse(json={"scopes": ["messages:read", "domains:read"]})]) as network:
        assert get_capabilities("secret-key") == (200, {"messages:read", "domains:read"})

    assert len(network.requests_log) == 1
    request = network.requests_log[0]
    assert request.url == f"{SHIPMAIL_BASE_URL}/capabilities"
    assert request.headers["authorization"] == "Bearer secret-key"
    assert request.headers["accept"] == "application/json"
    assert request.read_timeout == 10
    assert network.session_options == [{"redact_values": ("secret-key",), "capture": False}]


def test_get_capabilities_handles_invalid_credentials() -> None:
    with scripted_network([ScriptedResponse(status=401, json={"error": "unauthorized"})]):
        assert get_capabilities("bad-key") == (401, set())
