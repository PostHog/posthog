from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional
from urllib.parse import quote

from requests import PreparedRequest

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.channel_io.settings import (
    CHANNEL_IO_BASE_URL,
    ENDPOINTS,
    MAX_FILTER_RANGE,
    PAGE_LIMIT,
    USER_CHAT_STATES,
    ChannelIOEndpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import schema_for_resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.channelio import (
    ChannelIOSourceConfig,
)

Rows = list[dict[str, Any]]


@frozen
class ChannelIOResumeConfig:
    # List tables and user chats: the next page. Messages: the user chat page after the chats in `pending_chats`.
    segment: int = 0
    cursor: str | None = None
    # Messages: the chats of the current page whose messages are not all written, with the first one's next
    # message page. Kept by id, because a chat that changes state leaves the page and shifts the rest.
    pending_chats: list[dict[str, Any]] | None = None
    message_cursor: str | None = None
    # The end of the incremental windows, pinned so a resumed attempt reads the same segments.
    started_at_ms: int | None = None


@frozen
class UserChatSegment:
    state: str
    from_ms: int | None = None
    to_ms: int | None = None


@frozen
class UserChatPage:
    segment: int
    # The cursor that fetched this page, and the one that fetches the next page of the segment.
    cursor: str | None
    next_cursor: str | None
    chats: Rows


class ChannelIOAuth(AuthConfigBase):
    def __init__(self, access_key: str, access_secret: str) -> None:
        self.access_key = access_key
        self.access_secret = access_secret

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        request.headers["x-access-key"] = self.access_key
        request.headers["x-access-secret"] = self.access_secret
        return request

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.access_secret, self.access_key) if value)


def _headers(api_version: str) -> dict[str, str]:
    return {"Channel-Version": api_version, "Accept": "application/json"}


def client_config(config: ChannelIOSourceConfig, api_version: str) -> ClientConfig:
    return {
        "base_url": CHANNEL_IO_BASE_URL,
        "headers": _headers(api_version),
        "auth": ChannelIOAuth(config.access_key, config.access_secret),
        "allowed_hosts": [],
        "allow_redirects": False,
    }


def make_client(config: ChannelIOSourceConfig, api_version: str) -> RESTClient:
    return RESTClient(
        base_url=CHANNEL_IO_BASE_URL,
        headers=_headers(api_version),
        auth=ChannelIOAuth(config.access_key, config.access_secret),
        allowed_hosts=[],
        allow_redirects=False,
    )


def cursor_paginator() -> JSONResponseCursorPaginator:
    return JSONResponseCursorPaginator(cursor_path="nextCursor", cursor_param="cursor", raise_on_repeated_cursor=True)


def _to_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def to_datetime(value: Any) -> Any:
    """Channel.io timestamps arrive as epoch milliseconds or RFC 3339 strings, depending on the API version."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value / 1000, tz=UTC)
    if isinstance(value, str):
        return parse_datetime_value(value) or value
    return value


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    for key, value in row.items():
        if key.endswith("At") and value is not None:
            row[key] = to_datetime(value)
    return row


def list_resource(
    config: ChannelIOSourceConfig,
    endpoint: ChannelIOEndpoint,
    inputs: SourceInputs,
    manager: ResumableSourceManager[ChannelIOResumeConfig],
    api_version: str,
) -> Any:
    rest_config: RESTAPIConfig = {
        "client": client_config(config, api_version),
        "resources": [
            {
                "name": endpoint.name,
                "table_name": endpoint.name,
                "write_disposition": "replace",
                "endpoint": {
                    "path": endpoint.path,
                    "params": {"limit": PAGE_LIMIT},
                    "paginator": cursor_paginator(),
                    "data_selector": endpoint.data_key,
                    "data_selector_required": True,
                },
                "table_format": "delta",
            }
        ],
    }
    resume = manager.load_state() if manager.can_resume() else None

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            manager.save_state(ChannelIOResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        inputs.team_id,
        inputs.job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state={"cursor": resume.cursor} if resume is not None and resume.cursor else None,
    )
    resource.add_map(normalize_row)
    return resource


def user_chat_segments(watermark: datetime | None, started_at_ms: int) -> list[UserChatSegment]:
    """Each state, or each state in each window of at most 30 days from the watermark to the run start."""
    if watermark is None:
        return [UserChatSegment(state=state) for state in USER_CHAT_STATES]
    window_ms = int(MAX_FILTER_RANGE.total_seconds() * 1000)
    segments: list[UserChatSegment] = []
    low = _to_ms(watermark)
    while low < started_at_ms:
        high = min(low + window_ms, started_at_ms)
        segments.extend(UserChatSegment(state=state, from_ms=low, to_ms=high) for state in USER_CHAT_STATES)
        low = high
    return segments


def user_chat_pages(
    client: RESTClient, segments: list[UserChatSegment], start_segment: int, start_cursor: str | None
) -> Iterator[UserChatPage]:
    for index in range(start_segment, len(segments)):
        segment = segments[index]
        params: dict[str, Any] = {"state": segment.state, "sortOrder": "asc", "limit": PAGE_LIMIT}
        if segment.from_ms is not None:
            params.update({"dateTimeFieldName": "deskUpdatedAt", "from": segment.from_ms, "to": segment.to_ms})
        cursor = start_cursor if index == start_segment else None
        next_page: dict[str, str | None] = {}

        def remember_next(
            state: Optional[dict[str, Any]], _has_next: bool, box: dict[str, str | None] = next_page
        ) -> None:
            box["cursor"] = str(state["cursor"]) if state and state.get("cursor") else None

        for chats in client.paginate(
            path=ENDPOINTS["user_chats"].path,
            params=params,
            paginator=cursor_paginator(),
            data_selector="userChats",
            data_selector_required=True,
            initial_paginator_state={"cursor": cursor} if cursor else None,
            page_state_hook=remember_next,
        ):
            next_cursor = next_page.get("cursor")
            yield UserChatPage(segment=index, cursor=cursor, next_cursor=next_cursor, chats=chats)
            cursor = next_cursor


def _after_page(page: UserChatPage, started_at_ms: int) -> ChannelIOResumeConfig:
    if page.next_cursor:
        return ChannelIOResumeConfig(segment=page.segment, cursor=page.next_cursor, started_at_ms=started_at_ms)
    return ChannelIOResumeConfig(segment=page.segment + 1, started_at_ms=started_at_ms)


def user_chat_rows(
    client: RESTClient,
    segments: list[UserChatSegment],
    resume: ChannelIOResumeConfig | None,
    manager: ResumableSourceManager[ChannelIOResumeConfig],
    started_at_ms: int,
) -> Iterator[Rows]:
    start_segment = resume.segment if resume is not None else 0
    start_cursor = resume.cursor if resume is not None else None
    for page in user_chat_pages(client, segments, start_segment, start_cursor):
        manager.save_state(_after_page(page, started_at_ms))
        if page.chats:
            yield [normalize_row(chat) for chat in page.chats]
        else:
            manager.safe_point()


def _message_pages_to_read(
    client: RESTClient, segments: list[UserChatSegment], resume: ChannelIOResumeConfig | None
) -> Iterator[UserChatPage]:
    if resume is None:
        yield from user_chat_pages(client, segments, 0, None)
        return
    if resume.pending_chats is not None:
        yield UserChatPage(segment=resume.segment, cursor=None, next_cursor=resume.cursor, chats=resume.pending_chats)
        if resume.cursor is None:
            yield from user_chat_pages(client, segments, resume.segment + 1, None)
            return
    yield from user_chat_pages(client, segments, resume.segment, resume.cursor)


def message_rows(
    client: RESTClient,
    segments: list[UserChatSegment],
    resume: ChannelIOResumeConfig | None,
    manager: ResumableSourceManager[ChannelIOResumeConfig],
    started_at_ms: int,
) -> Iterator[Rows]:
    """Every message of every user chat the segments list, one chat at a time.

    A chat deleted after it was listed answers 404, which skips it rather than failing the sync.
    """
    skip_missing_chat = create_response_hooks([{"status_code": 404, "action": "ignore"}], resource_name="messages")
    first_message_cursor = resume.message_cursor if resume is not None else None

    for page in _message_pages_to_read(client, segments, resume):
        chats = [
            {"id": chat["id"], "deskUpdatedAt": chat.get("deskUpdatedAt") or chat.get("updatedAt")}
            for chat in page.chats
            if chat.get("id")
        ]

        def checkpoint(index: int, message_cursor: str | None, page: UserChatPage = page, chats: Rows = chats) -> None:
            manager.save_state(
                ChannelIOResumeConfig(
                    segment=page.segment,
                    cursor=page.next_cursor,
                    pending_chats=chats[index:],
                    message_cursor=message_cursor,
                    started_at_ms=started_at_ms,
                )
            )

        # Staged before this page's rows, so an empty page or a page of deleted chats still moves the cursor on.
        checkpoint(0, first_message_cursor)
        for index, chat in enumerate(chats):
            # Every chat before this one is written, including a deleted chat that answered 404 and yielded nothing.
            if index:
                checkpoint(index, None)
            manager.safe_point()
            chat_desk_updated_at = to_datetime(chat["deskUpdatedAt"])
            message_cursor = first_message_cursor if index == 0 else None
            next_page: dict[str, str | None] = {}

            def remember_next(
                state: Optional[dict[str, Any]], _has_next: bool, box: dict[str, str | None] = next_page
            ) -> None:
                box["cursor"] = str(state["cursor"]) if state and state.get("cursor") else None

            for messages in client.paginate(
                path=f"/open/user-chats/{quote(str(chat['id']), safe='')}/messages",
                params={"sortOrder": "asc", "limit": PAGE_LIMIT},
                paginator=cursor_paginator(),
                data_selector="messages",
                data_selector_required=True,
                hooks=skip_missing_chat,
                initial_paginator_state={"cursor": message_cursor} if message_cursor else None,
                page_state_hook=remember_next,
            ):
                next_message_cursor = next_page.get("cursor")
                if next_message_cursor:
                    checkpoint(index, next_message_cursor)
                else:
                    checkpoint(index + 1, None)
                if messages:
                    yield [
                        {**normalize_row(message), "userChatDeskUpdatedAt": chat_desk_updated_at}
                        for message in messages
                    ]
                else:
                    manager.safe_point()
        first_message_cursor = None
        manager.safe_point()


def channel_io_source(
    config: ChannelIOSourceConfig,
    inputs: SourceInputs,
    manager: ResumableSourceManager[ChannelIOResumeConfig],
    api_version: str,
) -> SourceResponse:
    endpoint = schema_for_resource(ENDPOINTS, inputs.schema_name)
    partitioning: dict[str, Any] = (
        {"partition_mode": "datetime", "partition_format": "month", "partition_keys": [endpoint.partition_key]}
        if endpoint.partition_key
        else {}
    )

    if endpoint.kind == "list":
        resource = list_resource(config, endpoint, inputs, manager, api_version)
        return SourceResponse(
            name=endpoint.name,
            items=lambda: resource,
            primary_keys=list(endpoint.primary_keys),
            on_complete=manager.clear_state,
            **partitioning,
        )

    resume = manager.load_state() if manager.can_resume() else None
    started_at_ms = (
        resume.started_at_ms if resume is not None and resume.started_at_ms is not None else _to_ms(datetime.now(UTC))
    )
    watermark = (
        parse_datetime_value(inputs.db_incremental_field_last_value) if inputs.should_use_incremental_field else None
    )
    segments = user_chat_segments(watermark, started_at_ms)
    client = make_client(config, api_version)
    read = user_chat_rows if endpoint.kind == "user_chats" else message_rows

    return SourceResponse(
        name=endpoint.name,
        items=lambda: read(client, segments, resume, manager, started_at_ms),
        primary_keys=list(endpoint.primary_keys),
        # Chats come back state by state, so rows are not in watermark order across a run. "desc" holds the
        # watermark until the run ends.
        sort_mode="desc" if inputs.should_use_incremental_field else "asc",
        on_complete=manager.clear_state,
        **partitioning,
    )


def validate_credentials(config: ChannelIOSourceConfig, api_version: str) -> tuple[bool, str | None]:
    auth = ChannelIOAuth(config.access_key, config.access_secret)
    session = make_tracked_session(redact_values=auth.secret_values(), allow_redirects=False)
    try:
        response = session.get(
            f"{CHANNEL_IO_BASE_URL}/open/channel", headers=_headers(api_version), auth=auth, timeout=30
        )
    except Exception:
        return False, "Could not reach the Channel.io API. Try again in a few minutes."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Channel.io rejected the access key and secret. Create a new credential and try again."
    if response.status_code == 403:
        return False, "This Channel.io credential can't read the channel. Check its permissions and try again."
    return False, f"Channel.io returned status {response.status_code} when checking these credentials."
