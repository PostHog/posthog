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


def test_a_full_refresh_reads_every_chat_state_without_a_date_filter() -> None:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        state = request.param("state")
        if state == "opened" and request.param("cursor") is None:
            return page("userChats", [{"id": "chat-1", "state": "opened"}], next_cursor="c2")
        if state == "opened":
            return page("userChats", [{"id": "chat-2", "state": "opened"}])
        if state == "closed":
            return page("userChats", [{"id": "chat-3", "state": "closed"}])
        return page("userChats", [])

    result = driver().run("user_chats", respond)

    assert result.raised is None
    assert [request.param("state") for request in result.requests] == [
        "opened",
        *USER_CHAT_STATES,
    ]
    assert all(request.param("sortOrder") == "asc" for request in result.requests)
    assert all(request.param("from") is None for request in result.requests)
    assert [row["id"] for row in result.rows] == ["chat-1", "chat-2", "chat-3"]
    assert result.response is not None and result.response.sort_mode == "asc"
    assert result.completed_state is None


def test_an_incremental_sync_reads_each_state_in_windows_of_at_most_30_days() -> None:
    watermark = NOW - timedelta(days=45)

    result = driver().run(
        "user_chats",
        always(page("userChats", [])),
        incremental_field="deskUpdatedAt",
        db_incremental_field_last_value=watermark,
    )

    assert result.raised is None
    windows = sorted({(int(r.param("from") or 0), int(r.param("to") or 0)) for r in result.requests})
    watermark_ms = int(watermark.timestamp() * 1000)
    thirty_days_ms = 30 * 24 * 3600 * 1000
    assert windows == [(watermark_ms, watermark_ms + thirty_days_ms), (watermark_ms + thirty_days_ms, NOW_MS)]
    assert len(result.requests) == 2 * len(USER_CHAT_STATES)
    assert all(request.param("dateTimeFieldName") == "deskUpdatedAt" for request in result.requests)
    # Rows arrive state by state, so the watermark must wait for the end of the run.
    assert result.response is not None and result.response.sort_mode == "desc"


def test_user_chats_resume_at_the_saved_segment_and_cursor() -> None:
    result = driver().run(
        "user_chats",
        always(page("userChats", [])),
        resume_state=ChannelIOResumeConfig(segment=2, cursor="c9", started_at_ms=NOW_MS),
    )

    assert result.raised is None
    assert [request.param("state") for request in result.requests] == list(USER_CHAT_STATES[2:])
    assert result.requests[0].param("cursor") == "c9"
    assert result.requests[1].param("cursor") is None


def message_responder(chats: list[dict[str, Any]]) -> Any:
    def respond(request: RecordedRequest) -> ScriptedResponse:
        if request.path == "/open/user-chats":
            return page("userChats", chats if request.param("state") == "opened" else [])
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

    result = driver().run("messages", message_responder(chats))

    assert result.raised is None
    assert [row["id"] for row in result.rows] == ["chat-1-m1", "chat-1-m2", "chat-2-m1", "chat-2-m2"]
    assert result.rows[0]["userChatDeskUpdatedAt"] == datetime(2024, 3, 29, 3, 28, 35, tzinfo=UTC)
    assert result.rows[2]["userChatDeskUpdatedAt"] == datetime(2024, 3, 29, 3, 28, 37, tzinfo=UTC)
    remaining = [{"id": chat["id"], "deskUpdatedAt": chat["deskUpdatedAt"]} for chat in chats]
    assert result.committed_states[:2] == [
        ChannelIOResumeConfig(pending_chats=remaining, message_cursor="m2", started_at_ms=NOW_MS),
        ChannelIOResumeConfig(pending_chats=remaining[1:], started_at_ms=NOW_MS),
    ]


def test_messages_resume_from_the_saved_chats_without_reading_their_page_again() -> None:
    # The opened page is not requested again: a chat that closed since the last attempt would shift it.
    result = driver().run(
        "messages",
        message_responder([{"id": "chat-1"}, {"id": "chat-2"}]),
        resume_state=ChannelIOResumeConfig(
            pending_chats=[{"id": "chat-2", "deskUpdatedAt": None}], message_cursor="m2", started_at_ms=NOW_MS
        ),
    )

    assert result.raised is None
    assert result.paths[0] == "/open/user-chats/chat-2/messages"
    assert result.requests[0].param("cursor") == "m2"
    assert [request.param("state") for request in result.requests[1:]] == list(USER_CHAT_STATES[1:])
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
        (ScriptedResponse(status=401, json={"type": "unauthenticatedError", "status": 401}), False, "rejected"),
        (ScriptedResponse(status=403, json={"type": "forbiddenError", "status": 403}), False, "permissions"),
        (ScriptedResponse(status=500, json={}), False, "status 500"),
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
