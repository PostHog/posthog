import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.kisi.settings import (
    BASE_URL,
    DEFAULT_PARTITION_KEYS,
    DEFAULT_PRIMARY_KEYS,
    ENDPOINTS,
    EVENT_SET_CURSOR_ERROR,
    EVENT_SET_EXPIRED_ERROR,
    EVENT_SET_FAILED_ERROR,
    EVENT_SET_TIMEOUT_ERROR,
    EVENTS,
    EVENTS_CREATE_INTERVAL_SECONDS,
    EVENTS_INITIAL_LOOKBACK,
    EVENTS_MAX_PAGES_PER_WINDOW,
    EVENTS_POLL_INTERVAL_SECONDS,
    EVENTS_POLL_MAX_ATTEMPTS,
    EVENTS_WINDOW,
    GROUP_LOCKS,
    GROUP_LOCKS_PATH,
    GROUPS,
    MAX_OFFSET,
    OFFSET_ERROR,
    PAGE_SIZE,
    PARTITION_KEYS,
    PRIMARY_KEYS,
    UNPAGINATED_ENDPOINTS,
)

HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}
REQUEST_TIMEOUT = (10, 30)


@frozen
class KisiResumeConfig:
    offset: int = 0
    events_window_start: str | None = None
    events_window_end: str | None = None
    event_set_id: int | None = None
    events_cursor: str | None = None
    events_written: int = 0
    fanout_state: dict[str, Any] | None = None


class KisiEventSetError(Exception):
    pass


class KisiPaginator(OffsetPaginator):
    def __init__(self) -> None:
        super().__init__(limit=PAGE_SIZE, total_path=None)

    def update_state(self, response: Response, data: list[Any] | None = None) -> None:
        super().update_state(response, data)
        # Kisi puts the total inside a range header, rather than a separate count header.
        collection_range = re.fullmatch(r"\d+-\d+/(\d+)", response.headers.get("X-Collection-Range", ""))
        if collection_range and data:
            self._has_next_page = self.offset < int(collection_range[1])
        if self.has_next_page and self.offset > MAX_OFFSET:
            raise ValueError(OFFSET_ERROR)


def kisi_auth(api_key: str) -> APIKeyAuth:
    return APIKeyAuth(api_key=f"KISI-LOGIN {api_key}", name="Authorization", location="header")


def validate_credentials(api_key: str) -> None:
    with make_tracked_session() as session:
        response = session.get(
            f"{BASE_URL}/user",
            auth=kisi_auth(api_key),
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("Kisi returned an unexpected response. Try again later.")


def kisi_source(
    api_key: str,
    inputs: SourceInputs,
    resumable_source_manager: ResumableSourceManager[KisiResumeConfig],
) -> SourceResponse:
    if inputs.schema_name not in ENDPOINTS:
        raise ValueError(f"Unsupported Kisi table: {inputs.schema_name}")

    primary_keys = PRIMARY_KEYS.get(inputs.schema_name, DEFAULT_PRIMARY_KEYS)
    partition_keys = PARTITION_KEYS.get(inputs.schema_name, DEFAULT_PARTITION_KEYS)
    partitioning: dict[str, Any] = (
        {"partition_keys": partition_keys, "partition_mode": "datetime", "partition_format": "month"}
        if partition_keys
        else {}
    )

    if inputs.schema_name == EVENTS:
        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: get_events(api_key, inputs, resumable_source_manager),
            primary_keys=primary_keys,
            # Windows run oldest first, but Kisi does not document the order of events inside an event set.
            sort_mode=None,
            **partitioning,
        )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    is_fanout = inputs.schema_name == GROUP_LOCKS

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is None:
            return
        if is_fanout:
            resumable_source_manager.save_state(KisiResumeConfig(fanout_state=state))
        else:
            resumable_source_manager.save_state(KisiResumeConfig(offset=int(state["offset"])))

    initial_paginator_state: dict[str, Any] | None = None
    if resume is not None:
        initial_paginator_state = resume.fanout_state if is_fanout else {"offset": resume.offset}

    resources: list[str | EndpointResource] = (
        [
            {
                "name": GROUPS,
                "endpoint": {"path": GROUPS, "data_selector": "$"},
                "write_disposition": "replace",
            },
            {
                "name": GROUP_LOCKS,
                "endpoint": {
                    "path": GROUP_LOCKS_PATH,
                    "params": {"group_id": {"type": "resolve", "resource": GROUPS, "field": "id"}},
                    "data_selector": "$",
                    # A path with a query string otherwise gets the single page paginator.
                    "paginator": KisiPaginator(),
                    # A group deleted after the groups page was read answers 404.
                    "response_actions": [{"status_code": 404, "action": "ignore"}],
                },
                "write_disposition": "replace",
            },
        ]
        if is_fanout
        else [
            {
                "name": inputs.schema_name,
                "endpoint": {"path": inputs.schema_name, "data_selector": "$"},
                "write_disposition": "replace",
            }
        ]
    )
    config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": kisi_auth(api_key),
            "headers": HEADERS,
            "paginator": SinglePagePaginator() if inputs.schema_name in UNPAGINATED_ENDPOINTS else KisiPaginator(),
            "request_timeout": REQUEST_TIMEOUT,
            "allow_redirects": False,
        },
        "resources": resources,
    }
    resource = next(
        item
        for item in rest_api_resources(
            config,
            inputs.team_id,
            inputs.job_id,
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        if item.name == inputs.schema_name
    )
    return SourceResponse(
        name=inputs.schema_name,
        items=lambda: resource,
        primary_keys=primary_keys,
        sort_mode=None,
        **partitioning,
    )


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _create_event_set(session: Any, auth: APIKeyAuth, start: datetime, end: datetime) -> dict[str, Any]:
    response = session.post(
        f"{BASE_URL}/event_sets",
        json={"event_set": {"interval": f"{_format_timestamp(start)}/{_format_timestamp(end)}"}},
        auth=auth,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False,
    )
    response.raise_for_status()
    return response.json()


def _fetch_event_set(
    session: Any, auth: APIKeyAuth, event_set_id: int, cursor: str | None = None
) -> dict[str, Any] | None:
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if cursor:
        params["cursor"] = cursor
    response = session.get(
        f"{BASE_URL}/event_sets/{event_set_id}",
        params=params,
        auth=auth,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False,
    )
    # Kisi keeps an event set for about 24 hours, so a set saved by an earlier attempt can be gone.
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def get_events(
    api_key: str,
    inputs: SourceInputs,
    manager: ResumableSourceManager[KisiResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    auth = kisi_auth(api_key)
    now = datetime.now(UTC)

    resume = manager.load_state() if manager.can_resume() else None
    resumed_start = parse_datetime_value(resume.events_window_start) if resume else None
    resumed_end = parse_datetime_value(resume.events_window_end) if resume else None
    event_set_id: int | None = None
    cursor: str | None = None
    # Events of the current window that earlier attempts already handed to the pipeline.
    written = 0
    if resume is not None and resumed_start is not None:
        window_start = resumed_start
        event_set_id, cursor, written = resume.event_set_id, resume.events_cursor, resume.events_written
        # A window that has a set or written rows keeps its interval. A window with neither runs up to now.
        keeps_interval = event_set_id is not None or written > 0
        window_end = resumed_end if keeps_interval and resumed_end is not None else now
    else:
        watermark = (
            parse_datetime_value(inputs.db_incremental_field_last_value)
            if inputs.should_use_incremental_field
            else None
        )
        window_start = watermark or now - EVENTS_INITIAL_LOOKBACK
        window_end = now
    window_end = min(window_end, window_start + EVENTS_WINDOW)

    def stage(start: datetime, end: datetime, set_id: int | None, next_cursor: str | None, rows: int) -> None:
        manager.save_state(
            KisiResumeConfig(
                events_window_start=_format_timestamp(start),
                events_window_end=_format_timestamp(end),
                event_set_id=set_id,
                events_cursor=next_cursor,
                events_written=rows,
            )
        )

    created_any = False
    with make_tracked_session(redact_values=(api_key,)) as session:
        while window_start < window_end:
            event_set = _fetch_event_set(session, auth, event_set_id, cursor) if event_set_id is not None else None
            if event_set is None:
                if created_any:
                    interruptible_wait(EVENTS_CREATE_INTERVAL_SECONDS, safe_point=manager.safe_point)
                event_set = _create_event_set(session, auth, window_start, window_end)
                created_any = True
                cursor = None
                stage(window_start, window_end, int(event_set["id"]), None, written)
                manager.safe_point()
            set_id = int(event_set["id"])

            for _attempt in range(EVENTS_POLL_MAX_ATTEMPTS):
                if event_set.get("status") != "in_progress":
                    break
                interruptible_wait(EVENTS_POLL_INTERVAL_SECONDS, safe_point=manager.safe_point)
                polled = _fetch_event_set(session, auth, set_id)
                if polled is None:
                    raise KisiEventSetError(EVENT_SET_EXPIRED_ERROR)
                event_set = polled
                manager.safe_point()
            if event_set.get("status") != "finished":
                # A failed set fails on every fetch, so the next attempt builds the window again.
                stage(window_start, window_end, None, None, written)
                manager.safe_point()
                raise KisiEventSetError(
                    EVENT_SET_FAILED_ERROR if event_set.get("status") == "failed" else EVENT_SET_TIMEOUT_ERROR
                )

            # A set read from its start replays rows an earlier set of this window already wrote. Kisi builds
            # a set for a past interval from the same stored events, so the first `written` rows are skipped.
            position = written if cursor else 0
            next_window_start = window_end
            next_window_end = min(next_window_start + EVENTS_WINDOW, now)
            seen_cursors: set[str] = set()
            while True:
                page = event_set.get("events") or []
                fresh = page[max(0, written - position) :]
                position += len(page)
                written += len(fresh)
                next_cursor = event_set.get("cursor")
                if not next_cursor:
                    stage(next_window_start, next_window_end, None, None, 0)
                elif position >= written:
                    stage(window_start, window_end, set_id, next_cursor, written)
                if fresh:
                    yield fresh
                else:
                    manager.safe_point()
                if not next_cursor:
                    break
                if next_cursor in seen_cursors or len(seen_cursors) >= EVENTS_MAX_PAGES_PER_WINDOW:
                    raise KisiEventSetError(EVENT_SET_CURSOR_ERROR)
                seen_cursors.add(next_cursor)
                next_page = _fetch_event_set(session, auth, set_id, next_cursor)
                if next_page is None:
                    # The staged cursor still names this set, so the next attempt builds the window again.
                    manager.safe_point()
                    raise KisiEventSetError(EVENT_SET_EXPIRED_ERROR)
                event_set = next_page

            window_start, window_end = next_window_start, next_window_end
            event_set_id, cursor, written = None, None, 0
