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
    SinglePagePaginator,
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
    # The range the run reads, pinned so a resumed attempt reads the same segments.
    window_start_ms: int | None = None
    started_at_ms: int | None = None


@frozen
class TimeRange:
    from_ms: int
    to_ms: int


@frozen
class UserChatSegment:
    state: str
    time_range: TimeRange
    # A full refresh reads the last window up to the time of each request, so a chat active during the run
    # is not left out of the replaced table.
    open_ended: bool = False


@frozen
class UserChatPage:
    segment: int
    # The cursor that fetches the next page of the segment.
    next_cursor: str | None
    chats: Rows


@frozen
class CursorPage:
    rows: Rows
    next_cursor: str | None


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
    settings = client_config(config, api_version)
    return RESTClient(
        base_url=settings["base_url"],
        headers=settings["headers"],
        auth=ChannelIOAuth(config.access_key, config.access_secret),
        allowed_hosts=settings["allowed_hosts"],
        allow_redirects=settings["allow_redirects"],
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


def time_ranges(start_ms: int, end_ms: int) -> list[TimeRange]:
    """Consecutive ranges of at most 30 days, the most `from` and `to` may span, covering [start, end)."""
    window_ms = int(MAX_FILTER_RANGE.total_seconds() * 1000)
    ranges: list[TimeRange] = []
    low = start_ms
    while low < end_ms:
        high = min(low + window_ms, end_ms)
        ranges.append(TimeRange(from_ms=low, to_ms=high))
        low = high
    return ranges


def run_range(client: RESTClient, watermark: datetime | None, resume: ChannelIOResumeConfig | None) -> TimeRange:
    """From the watermark, or from the channel's creation, to the start of the run.

    Every chat read is bounded by the run start. A chat that changes state during the run moves its
    `deskUpdatedAt` past that bound, so the run reads it at most once, and the next run picks up the change.
    """
    if resume is not None and resume.window_start_ms is not None and resume.started_at_ms is not None:
        return TimeRange(from_ms=resume.window_start_ms, to_ms=resume.started_at_ms)
    started_at_ms = _to_ms(datetime.now(UTC))
    if watermark is not None:
        return TimeRange(from_ms=_to_ms(watermark), to_ms=started_at_ms)
    channel = next(
        iter(
            client.paginate(
                path="/open/channel",
                paginator=SinglePagePaginator(),
                data_selector="channel",
                data_selector_required=True,
            )
        )
    )
    created_at = to_datetime(channel[0].get("createdAt")) if channel else None
    if not isinstance(created_at, datetime):
        raise ValueError("Channel.io returned a channel without a creation time")
    return TimeRange(from_ms=_to_ms(created_at), to_ms=started_at_ms)


def paginate_with_cursor(
    client: RESTClient,
    path: str,
    params: dict[str, Any],
    data_selector: str,
    start_cursor: str | None,
    hooks: Any = None,
) -> Iterator[CursorPage]:
    next_page: dict[str, str | None] = {}

    def remember_next(state: Optional[dict[str, Any]], _has_next: bool) -> None:
        next_page["cursor"] = str(state["cursor"]) if state and state.get("cursor") else None

    for rows in client.paginate(
        path=path,
        params=params,
        paginator=cursor_paginator(),
        data_selector=data_selector,
        data_selector_required=True,
        hooks=hooks,
        initial_paginator_state={"cursor": start_cursor} if start_cursor else None,
        page_state_hook=remember_next,
    ):
        yield CursorPage(rows=rows, next_cursor=next_page.get("cursor"))


def user_chat_pages(
    client: RESTClient, segments: list[UserChatSegment], start_segment: int, start_cursor: str | None
) -> Iterator[UserChatPage]:
    for index in range(start_segment, len(segments)):
        segment = segments[index]
        to_ms = segment.time_range.to_ms
        if segment.open_ended:
            window_ms = int(MAX_FILTER_RANGE.total_seconds() * 1000)
            to_ms = max(to_ms, min(_to_ms(datetime.now(UTC)), segment.time_range.from_ms + window_ms))
        params: dict[str, Any] = {
            "state": segment.state,
            "sortOrder": "asc",
            "limit": PAGE_LIMIT,
            "dateTimeFieldName": "deskUpdatedAt",
            "from": segment.time_range.from_ms,
            "to": to_ms,
        }
        for page in paginate_with_cursor(
            client,
            ENDPOINTS["user_chats"].path,
            params,
            "userChats",
            start_cursor if index == start_segment else None,
        ):
            yield UserChatPage(segment=index, next_cursor=page.next_cursor, chats=page.rows)


def user_chat_segments(run: TimeRange, open_ended: bool) -> list[UserChatSegment]:
    ranges = time_ranges(run.from_ms, run.to_ms)
    return [
        UserChatSegment(state=state, time_range=time_range, open_ended=open_ended and index == len(ranges) - 1)
        for index, time_range in enumerate(ranges)
        for state in USER_CHAT_STATES
    ]


def first_reads(chats: Rows, seen: set[str] | None) -> Rows:
    """Drop chats this attempt already read. Only an open-ended full refresh can list a chat twice."""
    if seen is None:
        return chats
    fresh = [chat for chat in chats if chat.get("id") not in seen]
    seen.update(str(chat["id"]) for chat in fresh if chat.get("id"))
    return fresh


def _after_page(page: UserChatPage, run: TimeRange) -> ChannelIOResumeConfig:
    if page.next_cursor:
        return ChannelIOResumeConfig(
            segment=page.segment, cursor=page.next_cursor, window_start_ms=run.from_ms, started_at_ms=run.to_ms
        )
    return ChannelIOResumeConfig(segment=page.segment + 1, window_start_ms=run.from_ms, started_at_ms=run.to_ms)


def user_chat_rows(
    client: RESTClient,
    watermark: datetime | None,
    resume: ChannelIOResumeConfig | None,
    manager: ResumableSourceManager[ChannelIOResumeConfig],
    full_refresh: bool,
) -> Iterator[Rows]:
    run = run_range(client, watermark, resume)
    start_segment = resume.segment if resume is not None else 0
    start_cursor = resume.cursor if resume is not None else None
    seen: set[str] | None = set() if full_refresh else None
    for page in user_chat_pages(client, user_chat_segments(run, full_refresh), start_segment, start_cursor):
        if not full_refresh:
            manager.save_state(_after_page(page, run))
        chats = first_reads(page.chats, seen)
        if chats:
            yield [normalize_row(chat) for chat in chats]
        else:
            manager.safe_point()


def _message_pages_to_read(
    client: RESTClient, segments: list[UserChatSegment], resume: ChannelIOResumeConfig | None
) -> Iterator[UserChatPage]:
    if resume is None:
        yield from user_chat_pages(client, segments, 0, None)
        return
    if resume.pending_chats is not None:
        yield UserChatPage(segment=resume.segment, next_cursor=resume.cursor, chats=resume.pending_chats)
        if resume.cursor is None:
            yield from user_chat_pages(client, segments, resume.segment + 1, None)
            return
    yield from user_chat_pages(client, segments, resume.segment, resume.cursor)


def message_rows(
    client: RESTClient,
    watermark: datetime | None,
    resume: ChannelIOResumeConfig | None,
    manager: ResumableSourceManager[ChannelIOResumeConfig],
    full_refresh: bool,
) -> Iterator[Rows]:
    """Every message of every user chat the run lists, one chat at a time.

    Each chat's whole history is read: a chat seen for the first time may hold messages older than the
    watermark. A chat deleted after it was listed answers 404 and is skipped.
    """
    skip_missing_chat = create_response_hooks([{"status_code": 404, "action": "ignore"}], resource_name="messages")
    run = run_range(client, watermark, resume)
    seen: set[str] | None = set() if full_refresh else None
    first_cursor = resume.message_cursor if resume is not None else None

    for page in _message_pages_to_read(client, user_chat_segments(run, full_refresh), resume):
        chats = [
            {"id": chat["id"], "deskUpdatedAt": chat.get("deskUpdatedAt") or chat.get("updatedAt")}
            for chat in first_reads(page.chats, seen)
            if chat.get("id")
        ]

        def checkpoint(index: int, cursor: str | None, page: UserChatPage = page, chats: Rows = chats) -> None:
            if full_refresh:
                return
            manager.save_state(
                ChannelIOResumeConfig(
                    segment=page.segment,
                    cursor=page.next_cursor,
                    pending_chats=chats[index:],
                    message_cursor=cursor,
                    window_start_ms=run.from_ms,
                    started_at_ms=run.to_ms,
                )
            )

        # Staged before this page's rows, so an empty page or a page of deleted chats still moves the cursor on.
        checkpoint(0, first_cursor)
        for index, chat in enumerate(chats):
            # Every chat before this one is written, including a deleted chat that answered 404 and yielded nothing.
            if index:
                checkpoint(index, None)
            manager.safe_point()
            chat_desk_updated_at = to_datetime(chat["deskUpdatedAt"])
            for message_page in paginate_with_cursor(
                client,
                f"/open/user-chats/{quote(str(chat['id']), safe='')}/messages",
                {"sortOrder": "asc", "limit": PAGE_LIMIT},
                "messages",
                first_cursor if index == 0 else None,
                hooks=skip_missing_chat,
            ):
                if message_page.next_cursor:
                    checkpoint(index, message_page.next_cursor)
                else:
                    checkpoint(index + 1, None)
                if message_page.rows:
                    yield [
                        {**normalize_row(message), "userChatDeskUpdatedAt": chat_desk_updated_at}
                        for message in message_page.rows
                    ]
                else:
                    manager.safe_point()
        first_cursor = None
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

    # A full refresh does not resume: a retry starts over and its first batch overwrites the table, so rows of an
    # earlier attempt cannot be written twice. Its chat dedupe only needs to span one attempt.
    full_refresh = not inputs.should_use_incremental_field
    resume = manager.load_state() if not full_refresh and manager.can_resume() else None
    watermark = (
        parse_datetime_value(inputs.db_incremental_field_last_value) if inputs.should_use_incremental_field else None
    )
    client = make_client(config, api_version)
    read = user_chat_rows if endpoint.kind == "user_chats" else message_rows

    return SourceResponse(
        name=endpoint.name,
        items=lambda: read(client, watermark, resume, manager, full_refresh),
        primary_keys=list(endpoint.primary_keys),
        # Chats come back state by state, so rows are not in watermark order across a run. "desc" holds the
        # watermark until the run ends.
        sort_mode="asc" if full_refresh else "desc",
        supports_resume=not full_refresh,
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
