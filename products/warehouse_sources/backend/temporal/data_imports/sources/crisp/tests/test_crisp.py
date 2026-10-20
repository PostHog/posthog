from datetime import UTC, datetime
from typing import Any

import pytest

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    RunStopped,
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.crisp import crisp as crisp_module
from products.warehouse_sources.backend.temporal.data_imports.sources.crisp.crisp import CrispResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.crisp.source import CrispSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.crisp import CrispSourceConfig


def page(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"error": False, "reason": "listed", "data": rows})


@pytest.mark.parametrize(
    ("schema", "path", "key", "params"),
    [
        (
            "conversations",
            "conversations",
            "session_id",
            {"per_page": ("50",), "include_empty": ("1",), "filter_inbox_id": ("all",), "order_date_created": ("1",)},
        ),
        ("people", "people/profiles", "people_id", {"per_page": ("50",)}),
        ("visitors", "visitors/list", "session_id", {}),
        ("helpdesk_locales", "helpdesk/locales", "locale_id", {}),
    ],
)
def test_path_pages_stop_at_short_or_empty_page_and_commit_before_next_request(
    config: CrispSourceConfig, schema: str, path: str, key: str, params: dict[str, tuple[str, ...]]
) -> None:
    first = [{key: str(number), "created_at": 1000} for number in range(50 if "per_page" in params else 1)]
    script = [page(first), page([{key: "last", "created_at": None}])]
    if "per_page" not in params:
        script.append(page([]))
    result = SourceDriver(CrispSource(), config).run(schema, script)
    assert result.raised is None
    assert result.paths == [f"/v1/website/{config.website_id}/{path}/{number}" for number in range(1, len(script) + 1)]
    assert result.queries == [params] * len(script)
    assert [row[key] for row in result.rows] == [row[key] for row in first] + ["last"]
    assert result.rows[0]["created_at"] == datetime.fromtimestamp(1, UTC)
    assert result.rows[-1]["created_at"] is None
    assert result.committed_states == [
        CrispResumeConfig(paginator_state={"page": number}) for number in range(2, len(script) + 1)
    ]


@pytest.mark.parametrize("schema", ["conversations", "people"])
def test_out_of_range_page_completes_without_discarding_rows(config: CrispSourceConfig, schema: str) -> None:
    key = "session_id" if schema == "conversations" else "people_id"
    result = SourceDriver(CrispSource(), config).run(
        schema,
        [
            page([{key: str(number)} for number in range(50)]),
            ScriptedResponse(status=416, json={"error": True, "reason": "invalid_page"}),
        ],
    )
    assert result.raised is None
    assert len(result.rows) == 50
    assert result.paths[-1].endswith("/2")


@pytest.mark.parametrize(
    ("last_value", "filter_date_start"),
    [
        (datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=UTC), "2026-01-02T03:04:05.678Z"),
        (None, None),
    ],
)
def test_incremental_conversations_filter_by_update_date(
    config: CrispSourceConfig, last_value: datetime | None, filter_date_start: str | None
) -> None:
    result = SourceDriver(CrispSource(), config).run(
        "conversations",
        [page([{"session_id": "one", "created_at": 1000, "updated_at": 2000}])],
        incremental_field="updated_at",
        db_incremental_field_last_value=last_value,
    )
    assert result.raised is None
    expected = {
        "per_page": ("50",),
        "include_empty": ("1",),
        "filter_inbox_id": ("all",),
        "order_date_updated": ("1",),
    }
    if filter_date_start is not None:
        expected["filter_date_start"] = (filter_date_start,)
    assert result.queries[0] == expected
    assert result.response is not None and result.response.sort_mode == "desc"
    assert [row["updated_at"] for row in result.rows] == [datetime.fromtimestamp(2, UTC)]


@pytest.mark.parametrize(
    ("last_value", "first_window_start"),
    [
        (None, "2000-01-01T00:00:00.000Z"),
        (datetime(2025, 12, 31, 12, 0, 0), "2025-12-31T11:59:59.999Z"),
    ],
)
def test_incremental_messages_read_small_windows_oldest_first_and_stop_after_the_run_budget(
    config: CrispSourceConfig,
    monkeypatch: pytest.MonkeyPatch,
    last_value: datetime | None,
    first_window_start: str,
) -> None:
    monkeypatch.setattr(crisp_module, "WINDOW_PAGE_SIZE", 2)
    monkeypatch.setattr(crisp_module, "CONVERSATIONS_PER_RUN", 3)
    hour_ms = 3_600_000
    first = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    conversations: list[dict[str, Any]] = [
        {"session_id": f"c{number}", "updated_at": first + number * hour_ms} for number in range(4)
    ]

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/messages"):
            if request.param("timestamp_before") is not None:
                return page([])
            return page([{"fingerprint": 1, "timestamp": 1000}])
        low = datetime.fromisoformat(request.param("filter_date_start") or "").timestamp() * 1000
        high = datetime.fromisoformat(request.param("filter_date_end") or "").timestamp() * 1000
        return page([row for row in conversations if low <= row["updated_at"] <= high][:2])

    result = SourceDriver(CrispSource(), config).run(
        "messages",
        respond,
        incremental_field="conversation_updated_at",
        db_incremental_field_last_value=last_value,
    )
    assert result.raised is None
    windows = [request for request in result.requests if request.path.endswith("/conversations/1")]
    assert windows[0].param("filter_date_start") == first_window_start
    assert all(request.param("order_date_created") == "1" for request in windows)
    assert [row["session_id"] for row in result.rows] == ["c0", "c1", "c2"]
    assert not any("/c3/" in path for path in result.paths)
    assert result.rows[0]["conversation_updated_at"] == datetime.fromtimestamp(first / 1000, UTC)
    assert result.response is not None and result.response.sort_mode == "desc"


@pytest.mark.parametrize(
    ("finished", "loaded", "expected"),
    [
        (["c0", "c1"], 2, ["c2", "c3"]),
        (["c0", "c1", "c2"], 3, ["c3"]),
    ],
)
def test_resumed_incremental_messages_keep_the_run_budget_of_earlier_attempts(
    config: CrispSourceConfig,
    monkeypatch: pytest.MonkeyPatch,
    finished: list[str],
    loaded: int,
    expected: list[str],
) -> None:
    monkeypatch.setattr(crisp_module, "WINDOW_PAGE_SIZE", 2)
    monkeypatch.setattr(crisp_module, "CONVERSATIONS_PER_RUN", 3)
    hour_ms = 3_600_000
    first = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    conversations: list[dict[str, Any]] = [
        {"session_id": "c0", "updated_at": first},
        {"session_id": "c1", "updated_at": first + hour_ms},
        {"session_id": "c2", "updated_at": first + 2 * hour_ms},
        {"session_id": "c3", "updated_at": first + 2 * hour_ms},
        {"session_id": "c4", "updated_at": first + 3 * hour_ms},
    ]

    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path.endswith("/messages"):
            if request.param("timestamp_before") is not None:
                return page([])
            return page([{"fingerprint": 1, "timestamp": 1000}])
        low = datetime.fromisoformat(request.param("filter_date_start") or "").timestamp() * 1000
        high = datetime.fromisoformat(request.param("filter_date_end") or "").timestamp() * 1000
        matching = [row for row in conversations if low <= row["updated_at"] <= high]
        number = int(request.path.rsplit("/", 1)[1])
        return page(matching[(number - 1) * 2 : number * 2])

    root = f"website/{config.website_id}/conversation"
    result = SourceDriver(CrispSource(), config).run(
        "messages",
        respond,
        incremental_field="conversation_updated_at",
        resume_state=CrispResumeConfig(
            paginator_state={
                "completed": [f"{root}/{session_id}/messages" for session_id in finished],
                "current": None,
                "child_state": None,
            },
            started_at=datetime(2026, 2, 1, tzinfo=UTC).isoformat(),
            conversations_loaded=loaded,
        ),
    )
    assert result.raised is None
    assert [row["session_id"] for row in result.rows] == expected
    assert not any("/c4/" in path for path in result.paths)


def test_incremental_messages_page_through_a_window_that_no_split_can_shrink(config: CrispSourceConfig) -> None:
    updated_at = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
    conversations: list[dict[str, Any]] = [
        {"session_id": f"c{number}", "updated_at": updated_at} for number in range(51)
    ]
    list_requests = 0

    def respond(request: RecordedRequest) -> ScriptedResponse:
        nonlocal list_requests
        if request.path.endswith("/messages"):
            return page([]) if request.param("timestamp_before") else page([{"fingerprint": 1, "timestamp": 1000}])
        list_requests += 1
        if list_requests > 200:
            raise RuntimeError("the window walk did not terminate")
        low = datetime.fromisoformat(request.param("filter_date_start") or "").timestamp() * 1000
        high = datetime.fromisoformat(request.param("filter_date_end") or "").timestamp() * 1000
        matching = [row for row in conversations if low <= row["updated_at"] <= high]
        number = int(request.path.rsplit("/", 1)[1])
        return page(matching[(number - 1) * 50 : number * 50])

    result = SourceDriver(CrispSource(), config).run("messages", respond, incremental_field="conversation_updated_at")
    assert result.raised is None
    assert sorted(row["session_id"] for row in result.rows) == sorted(row["session_id"] for row in conversations)


def test_resumed_incremental_messages_defer_conversations_updated_after_the_run_started(
    config: CrispSourceConfig,
) -> None:
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    after_start = int(started_at.timestamp() * 1000) + 1000
    root = f"website/{config.website_id}/conversation"
    result = SourceDriver(CrispSource(), config).run(
        "messages",
        [
            page(
                [
                    {"session_id": "finished", "updated_at": after_start},
                    {"session_id": "changed", "updated_at": after_start},
                    {"session_id": "unchanged", "updated_at": after_start - 86_400_000},
                ]
            ),
            page([{"fingerprint": 2, "timestamp": 1000}]),
            page([]),
        ],
        incremental_field="conversation_updated_at",
        db_incremental_field_last_value=datetime(2025, 12, 1),
        resume_state=CrispResumeConfig(
            paginator_state={"completed": [f"{root}/finished/messages"], "current": None, "child_state": None},
            started_at=started_at.isoformat(),
        ),
    )
    assert result.raised is None
    assert [row["session_id"] for row in result.rows] == ["unchanged"]
    assert not any("/changed/" in path for path in result.paths)
    assert all(state.started_at == started_at.isoformat() for state in result.saved_states)


def test_path_resume_uses_saved_page_after_interruption(config: CrispSourceConfig) -> None:
    driver = SourceDriver(CrispSource(), config)
    stopped = driver.run("visitors", [page([{"session_id": "one"}]), RunStopped("handoff")])
    assert isinstance(stopped.raised, RunStopped)
    assert stopped.saved_states == stopped.committed_states == [CrispResumeConfig(paginator_state={"page": 2})]
    resumed = driver.run(
        "visitors", [page([{"session_id": "two"}]), page([])], resume_state=stopped.committed_states[-1]
    )
    assert resumed.raised is None
    assert resumed.paths[0].endswith("/visitors/list/2")
    assert [row["session_id"] for row in resumed.rows] == ["two"]


def test_messages_page_backwards_for_each_conversation(config: CrispSourceConfig) -> None:
    result = SourceDriver(CrispSource(), config).run(
        "messages",
        [
            page([{"session_id": "session-one"}, {"session_id": "session-two"}]),
            page(
                [
                    {"fingerprint": 2, "timestamp": 1000, "content": "Example"},
                    {
                        "fingerprint": 3,
                        "timestamp": 2000,
                        "content": {"type": "file", "url": "https://example.com/file"},
                    },
                ]
            ),
            page([{"fingerprint": 1, "timestamp": 500, "content": None}]),
            page([]),
            page([{"fingerprint": 1, "timestamp": 3000}]),
            page([]),
        ],
    )
    assert result.raised is None
    root = f"/v1/website/{config.website_id}"
    assert result.paths == [
        f"{root}/conversations/1",
        *[f"{root}/conversation/session-one/messages"] * 3,
        *[f"{root}/conversation/session-two/messages"] * 2,
    ]
    assert result.params("timestamp_before") == [None, None, "1000", "500", None, "3000"]
    assert [row["session_id"] for row in result.rows] == ["session-one"] * 3 + ["session-two"]
    assert [row["fingerprint"] for row in result.rows] == [2, 3, 1, 1]
    assert result.rows[1]["content"] == {"type": "file", "url": "https://example.com/file"}
    assert result.rows[2]["content"] is None
    assert result.rows[2]["timestamp"] == datetime.fromtimestamp(0.5, UTC)
    assert result.committed_states[0].paginator_state == {
        "completed": [],
        "current": f"website/{config.website_id}/conversation/session-one/messages",
        "child_state": {"timestamp_before": 1000},
    }


def test_message_resume_skips_finished_conversations_and_restores_timestamp(config: CrispSourceConfig) -> None:
    first_path = f"website/{config.website_id}/conversation/one/messages"
    second_path = f"website/{config.website_id}/conversation/two/messages"
    result = SourceDriver(CrispSource(), config).run(
        "messages",
        [
            page([{"session_id": "one"}, {"session_id": "two"}]),
            page([{"fingerprint": 1, "timestamp": 500}]),
            page([]),
        ],
        resume_state=CrispResumeConfig(
            paginator_state={
                "completed": [first_path],
                "current": second_path,
                "child_state": {"timestamp_before": 1000},
            }
        ),
    )
    assert result.raised is None
    assert result.params("timestamp_before") == [None, "1000", "500"]
    assert [row["session_id"] for row in result.rows] == ["two"]
    assert all("/conversation/one/" not in path for path in result.paths)


@pytest.mark.parametrize("second_timestamp", [1000, 2000])
def test_messages_fail_when_timestamp_filter_does_not_advance(config: CrispSourceConfig, second_timestamp: int) -> None:
    result = SourceDriver(CrispSource(), config).run(
        "messages",
        [
            page([{"session_id": "one"}]),
            page([{"fingerprint": 1, "timestamp": 1000}]),
            page([{"fingerprint": 2, "timestamp": second_timestamp}]),
        ],
    )
    assert isinstance(result.raised, ValueError)
    assert "did not advance" in str(result.raised)
    assert len(result.rows) == 1
    assert result.committed_states[-1].paginator_state["child_state"] == {"timestamp_before": 1000}


@pytest.mark.parametrize(
    ("schema", "parent_path", "parent", "child_path", "child", "parent_field"),
    [
        (
            "people_events",
            "people/profiles",
            {"people_id": "profile/one"},
            "people/events/profile%2Fone/list",
            {"text": "Example event", "timestamp": 1000, "data": {"count": 2}},
            "people_id",
        ),
        (
            "helpdesk_articles",
            "helpdesk/locales",
            {"locale_id": "locale-one", "locale": "en"},
            "helpdesk/page/list/en/articles",
            {"entity_id": "article-one", "title": "Example article", "url": "https://example.com/help"},
            "locale",
        ),
    ],
)
def test_child_path_pagination_keeps_parent_fields(
    config: CrispSourceConfig,
    schema: str,
    parent_path: str,
    parent: dict[str, Any],
    child_path: str,
    child: dict[str, Any],
    parent_field: str,
) -> None:
    script = [page([parent]), page([child]), page([])]
    if schema == "helpdesk_articles":
        script.append(page([]))
    result = SourceDriver(CrispSource(), config).run(schema, script)
    assert result.raised is None
    root = f"/v1/website/{config.website_id}"
    paths = [
        f"{root}/{parent_path}/1",
        f"{root}/{child_path}/1",
        f"{root}/{child_path}/2",
    ]
    if schema == "helpdesk_articles":
        paths.append(f"{root}/{parent_path}/2")
    assert result.paths == paths
    assert result.rows[0][parent_field] == parent[parent_field]
    assert not any(key.startswith("_path") or key.startswith(f"_{parent_path}") for key in result.rows[0])
    assert result.queries[1:3] == [{}, {}]


def test_deleted_parent_does_not_drop_other_messages(config: CrispSourceConfig) -> None:
    result = SourceDriver(CrispSource(), config).run(
        "messages",
        [
            page([{"session_id": "deleted"}, {"session_id": "active"}]),
            ScriptedResponse(status=404, json={"error": True, "reason": "not_found"}),
            page([{"fingerprint": 1, "timestamp": 1000}]),
            page([]),
        ],
    )
    assert result.raised is None
    assert [row["session_id"] for row in result.rows] == ["active"]


def test_operators_exclude_invitation_credentials_and_flatten_details(config: CrispSourceConfig) -> None:
    result = SourceDriver(CrispSource(), config).run(
        "operators",
        [
            page(
                [
                    {
                        "type": "invite",
                        "details": {"email": "invited@example.com", "identifier": "fake-invite", "key": "fake-key"},
                    },
                    {
                        "type": "operator",
                        "details": {
                            "user_id": "operator-one",
                            "email": "operator@example.com",
                            "availability": "online",
                        },
                    },
                    {"type": "sandbox", "details": {"user_id": "developer-one", "email": "developer@example.com"}},
                ]
            )
        ],
    )
    assert result.raised is None
    assert result.paths == [f"/v1/website/{config.website_id}/operators/list"]
    assert result.rows == [
        {"type": "operator", "user_id": "operator-one", "email": "operator@example.com", "availability": "online"},
        {"type": "sandbox", "user_id": "developer-one", "email": "developer@example.com"},
    ]


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_fail_extraction(config: CrispSourceConfig, status: int) -> None:
    result = SourceDriver(CrispSource(), config).run(
        "people", [ScriptedResponse(status=status, json={"error": True, "reason": "unauthorized"})]
    )
    assert isinstance(result.raised, HTTPError)
    assert len(result.requests) == 1
    assert result.rows == []


@pytest.mark.parametrize(
    "body",
    [{"error": True, "reason": "failure", "data": []}, {"error": False, "reason": "listed", "unexpected": []}, {}],
)
def test_bad_envelopes_cannot_complete_as_empty_tables(config: CrispSourceConfig, body: dict[str, Any]) -> None:
    result = SourceDriver(CrispSource(), config).run("conversations", [ScriptedResponse(json=body)])
    assert result.raised is not None
    assert result.rows == []
    assert result.committed_states == []
