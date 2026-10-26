from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import time_machine

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.channel_io.channel_io import (
    ChannelIOResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.channel_io.settings import USER_CHAT_STATES
from products.warehouse_sources.backend.temporal.data_imports.sources.channel_io.source import ChannelIOSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.channelio import (
    ChannelIOSourceConfig,
)

CONFIG = ChannelIOSourceConfig(access_key="example-access-key", access_secret="example-access-secret")
NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
NOW_MS = int(NOW.timestamp() * 1000)


@pytest.fixture(autouse=True)
def frozen_clock() -> Iterator[None]:
    with time_machine.travel(NOW, tick=False):
        yield


def driver() -> SourceDriver:
    return SourceDriver(ChannelIOSource(), CONFIG)


def page(key: str, rows: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    return ScriptedResponse(json={key: rows, "nextCursor": next_cursor, "hasNext": next_cursor is not None})


def test_list_tables_walk_cursor_pages_with_the_pinned_version_and_credentials() -> None:
    result = driver().run(
        "managers",
        [
            page("managers", [{"id": "1", "createdAt": 1711616252000}], next_cursor="c2"),
            page("managers", [{"id": "2", "createdAt": "2024-03-28 08:57:32+00:00"}]),
        ],
    )

    assert result.raised is None
    assert result.params("cursor") == [None, "c2"]
    assert result.params("limit") == ["500", "500"]
    headers = result.requests[0].headers
    assert headers["channel-version"] == "2026-06-01"
    assert headers["x-access-key"] == "example-access-key"
    assert headers["x-access-secret"] == "example-access-secret"
    assert [row["createdAt"] for row in result.rows] == [
        datetime(2024, 3, 28, 8, 57, 32, tzinfo=UTC),
        datetime(2024, 3, 28, 8, 57, 32, tzinfo=UTC),
    ]
    assert result.committed_states[0] == ChannelIOResumeConfig(cursor="c2")


def test_list_tables_resume_from_the_saved_cursor() -> None:
    result = driver().run(
        "chat_tags", [page("chatTags", [{"id": "t3"}])], resume_state=ChannelIOResumeConfig(cursor="c3")
    )

    assert result.raised is None
    assert result.params("cursor") == ["c3"]


CHANNEL_CREATED = NOW - timedelta(days=45)
CHANNEL_CREATED_MS = int(CHANNEL_CREATED.timestamp() * 1000)
THIRTY_DAYS_MS = 30 * 24 * 3600 * 1000
WINDOWS = [
    (CHANNEL_CREATED_MS, CHANNEL_CREATED_MS + THIRTY_DAYS_MS),
    (CHANNEL_CREATED_MS + THIRTY_DAYS_MS, NOW_MS),
]


# Resume belongs to incremental runs. A watermark at the channel's creation keeps the same windows.
INCREMENTAL: dict[str, Any] = {
    "incremental_field": "deskUpdatedAt",
    "db_incremental_field_last_value": CHANNEL_CREATED,
}


def pinned_state(**fields: Any) -> ChannelIOResumeConfig:
    return ChannelIOResumeConfig(window_start_ms=CHANNEL_CREATED_MS, started_at_ms=NOW_MS, **fields)


def channel_response() -> ScriptedResponse:
    return ScriptedResponse(json={"channel": {"id": "1", "createdAt": CHANNEL_CREATED.isoformat()}})


@pytest.mark.parametrize("incremental", [False, True])
def test_chats_are_read_per_state_in_30_day_windows_that_end_at_the_run_start(incremental: bool) -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/open/channel":
            return channel_response()
        state, window_start = request.param("state"), int(request.param("from") or 0)
        if state == "opened" and window_start == CHANNEL_CREATED_MS and request.param("cursor") is None:
            return page("userChats", [{"id": "chat-1"}], next_cursor="c2")
        if state == "opened" and window_start == CHANNEL_CREATED_MS:
            return page("userChats", [{"id": "chat-2"}])
        if state == "closed" and window_start != CHANNEL_CREATED_MS:
            return page("userChats", [{"id": "chat-3"}])
        return page("userChats", [])

    inputs: dict[str, Any] = (
        {"incremental_field": "deskUpdatedAt", "db_incremental_field_last_value": CHANNEL_CREATED}
        if incremental
        else {}
    )
    result = driver().run("user_chats", respond, **inputs)

    assert result.raised is None
    # Without a watermark the first read starts at the channel's creation, never unbounded.
    assert (result.paths[0] == "/open/channel") is not incremental
    chat_requests = [request for request in result.requests if request.path == "/open/user-chats"]
    assert sorted({(int(r.param("from") or 0), int(r.param("to") or 0)) for r in chat_requests}) == WINDOWS
    assert len(chat_requests) == 2 * len(USER_CHAT_STATES) + 1
    assert all(r.param("dateTimeFieldName") == "deskUpdatedAt" for r in chat_requests)
    assert [row["id"] for row in result.rows] == ["chat-1", "chat-2", "chat-3"]
    # Rows arrive state by state, so an incremental watermark must wait for the end of the run.
    assert result.response is not None and result.response.sort_mode == ("desc" if incremental else "asc")
    assert result.completed_state is None


def test_user_chats_resume_at_the_saved_segment_and_cursor_without_reading_the_channel_again() -> None:
    result = driver().run(
        "user_chats",
        always(page("userChats", [])),
        resume_state=pinned_state(segment=2, cursor="c9"),
        **INCREMENTAL,
    )

    assert result.raised is None
    assert "/open/channel" not in result.paths
    assert [request.param("state") for request in result.requests] == [
        *USER_CHAT_STATES[2:],
        *USER_CHAT_STATES,
    ]
    assert result.requests[0].param("cursor") == "c9"
    assert result.requests[1].param("cursor") is None


def message_responder(chats: list[dict[str, Any]]) -> Any:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/open/channel":
            return channel_response()
        if request.path == "/open/user-chats":
            first_window = int(request.param("from") or 0) == CHANNEL_CREATED_MS
            return page("userChats", chats if request.param("state") == "opened" and first_window else [])
        chat_id = request.path.split("/")[3]
        if chat_id == "gone":
            return ScriptedResponse(status=404, json={"type": "notFoundError", "status": 404, "errors": []})
        if request.param("cursor") is None:
            return page("messages", [{"id": f"{chat_id}-m1", "chatId": chat_id}], next_cursor="m2")
        return page("messages", [{"id": f"{chat_id}-m2", "chatId": chat_id}])

    return respond


def test_messages_fan_out_per_chat_carry_the_chat_activity_time_and_skip_a_deleted_chat() -> None:
    chats: list[dict[str, Any]] = [
        {"id": "chat-1", "deskUpdatedAt": 1711682915000},
        {"id": "gone", "deskUpdatedAt": 1711682916000},
        {"id": "chat-2", "deskUpdatedAt": "2024-03-29 03:28:37+00:00"},
    ]

    result = driver().run("messages", message_responder(chats), **INCREMENTAL)

    assert result.raised is None
    assert [row["id"] for row in result.rows] == ["chat-1-m1", "chat-1-m2", "chat-2-m1", "chat-2-m2"]
    assert result.rows[0]["userChatDeskUpdatedAt"] == datetime(2024, 3, 29, 3, 28, 35, tzinfo=UTC)
    assert result.rows[2]["userChatDeskUpdatedAt"] == datetime(2024, 3, 29, 3, 28, 37, tzinfo=UTC)
    remaining = [{"id": chat["id"], "deskUpdatedAt": chat["deskUpdatedAt"]} for chat in chats]
    assert result.committed_states[:4] == [
        pinned_state(pending_chats=remaining),
        pinned_state(pending_chats=remaining, message_cursor="m2"),
        pinned_state(pending_chats=remaining[1:]),
        # The deleted chat yields no rows, and the run still commits past it before the next chat.
        pinned_state(pending_chats=remaining[2:]),
    ]


def test_incremental_messages_read_the_whole_history_of_each_listed_chat() -> None:
    # A chat seen for the first time can hold messages older than the watermark.
    result = driver().run(
        "messages",
        message_responder([{"id": "chat-1"}]),
        incremental_field="userChatDeskUpdatedAt",
        db_incremental_field_last_value=CHANNEL_CREATED,
    )

    assert result.raised is None
    message_requests = [request for request in result.requests if request.path.endswith("/messages")]
    assert [request.param("from") for request in message_requests] == [None, None]
    assert [row["id"] for row in result.rows] == ["chat-1-m1", "chat-1-m2"]


def test_a_full_refresh_reads_the_last_window_up_to_each_request_and_keeps_one_copy_per_chat() -> None:
    with time_machine.travel(NOW, tick=False) as clock:

        def respond(request: RecordedRequest) -> ScriptedResponse:
            if request.path == "/open/channel":
                clock.shift(timedelta(minutes=5))
                return channel_response()
            first_window = int(request.param("from") or 0) == CHANNEL_CREATED_MS
            if request.param("state") == "opened" and first_window:
                return page("userChats", [{"id": "chat-1"}])
            if request.param("state") == "closed" and not first_window:
                # chat-1 closed after the run started, so it is listed a second time.
                return page("userChats", [{"id": "chat-1"}, {"id": "chat-2"}])
            return page("userChats", [])

        result = driver().run("user_chats", respond)

    assert result.raised is None
    assert [row["id"] for row in result.rows] == ["chat-1", "chat-2"]
    last_window = [r for r in result.requests if int(r.param("from") or 0) == WINDOWS[1][0]]
    assert {int(r.param("to") or 0) for r in last_window} == {NOW_MS + 5 * 60 * 1000}
    # The dedupe lives in memory, so a retried full refresh starts over instead of resuming.
    assert result.response is not None and result.response.supports_resume is False
    assert result.saved_states == []


def test_messages_resume_from_the_saved_chats_without_reading_their_page_again() -> None:
    # The opened page is not requested again: a chat that closed since the last attempt would shift it.
    result = driver().run(
        "messages",
        message_responder([{"id": "chat-1"}, {"id": "chat-2"}]),
        resume_state=pinned_state(pending_chats=[{"id": "chat-2", "deskUpdatedAt": None}], message_cursor="m2"),
        **INCREMENTAL,
    )

    assert result.raised is None
    assert result.paths[0] == "/open/user-chats/chat-2/messages"
    assert result.requests[0].param("cursor") == "m2"
    assert "/open/channel" not in result.paths
    assert [request.param("state") for request in result.requests[1:]] == [
        *USER_CHAT_STATES[1:],
        *USER_CHAT_STATES,
    ]
    assert [row["id"] for row in result.rows] == ["chat-2-m2"]


def test_a_body_without_the_row_key_fails_instead_of_syncing_nothing() -> None:
    result = driver().run("groups", [ScriptedResponse(json={"nextCursor": None, "hasNext": False})])

    assert isinstance(result.raised, ValueError)
    assert result.rows == []


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_fail_the_sync_without_retrying(status: int) -> None:
    body = {"type": "unauthenticatedError", "status": status, "errors": [{"message": "Invalid credentials"}]}

    result = driver().run("bots", [ScriptedResponse(status=status, json=body)])

    assert isinstance(result.raised, HTTPError)
    assert "api.channel.io" in str(result.raised)
    assert len(result.requests) == 1


@pytest.mark.parametrize(
    ("answer", "valid", "message_part"),
    [
        (ScriptedResponse(json={"channel": {"id": "1"}}), True, None),
    ],
)
def test_validate_credentials_maps_the_probe_status(
    answer: ScriptedResponse, valid: bool, message_part: str | None
) -> None:
    with scripted_network(always(answer)) as network:
        result_valid, message = validate_credentials(CONFIG, "2026-06-01")

    assert result_valid is valid
    assert (message is None) if message_part is None else (message is not None and message_part in message)
    assert network.requests_log[0].path == "/open/channel"
    assert network.requests_log[0].headers["channel-version"] == "2026-06-01"
