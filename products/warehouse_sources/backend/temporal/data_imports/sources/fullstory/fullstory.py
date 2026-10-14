import gzip
import json
import time
import tempfile
import itertools
import dataclasses
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote, urlsplit

import requests
from requests import Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.settings import (
    EVENTS_EXPORT_END_LAG,
    EVENTS_EXPORT_WINDOW,
    EVENTS_INITIAL_LOOKBACK,
    EXPORT_BATCH_SIZE,
    EXPORT_POLL_INTERVAL_SECONDS,
    EXPORT_POLL_MAX_ATTEMPTS,
    EXPORT_SEGMENT_ID,
    FULLSTORY_BASE_URL,
    REQUEST_TIMEOUT_SECONDS,
    SEGMENTS_PAGE_SIZE,
)


@dataclasses.dataclass(frozen=True)
class FullStoryResumeConfig:
    # Listings paginate with an opaque next-page token.
    next_page_token: Optional[str] = None
    # Events: the export window in progress, its export operation, and how many of its rows are written.
    # A crash after a write but before its checkpoint commits replays those rows; export rows have no key to dedupe on.
    export_window_start: Optional[str] = None
    export_window_end: Optional[str] = None
    export_operation_id: Optional[str] = None
    export_rows_done: int = 0


class FullStoryExportError(Exception):
    pass


class FullStoryExportFailedError(FullStoryExportError):
    pass


class FullStoryCursorPaginator(JSONResponseCursorPaginator):
    """Body-cursor paginator that also halts on an empty page.

    v2 listings carry the cursor in ``next_page_token`` and take it back as ``page_token``; the v1
    segments listing uses ``nextPaginationToken`` and ``paginationToken``. Beyond the base "no
    cursor => stop", this also stops when a page returns no rows even if a cursor is present, as a
    guard against a cursor that never clears.
    """

    def __init__(self, cursor_path: str = "next_page_token", cursor_param: str = "page_token") -> None:
        super().__init__(cursor_path=cursor_path, cursor_param=cursor_param)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if not data:
            self._has_next_page = False


@dataclasses.dataclass(frozen=True)
class _FanoutEndpoint:
    name: str
    path: str
    incremental_fields: list[Any] = dataclasses.field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = 0


# The sessions listing is per user and unpaginated, so it fans out over identified users.
_FANOUT_ENDPOINTS: dict[str, _FanoutEndpoint] = {
    "users": _FanoutEndpoint(name="users", path="/v2/users"),
    "sessions": _FanoutEndpoint(name="sessions", path="/v2/sessions?uid={uid_param}"),
}
SESSIONS_FANOUT = DependentEndpointConfig(
    parent_name="users",
    resolve_param="uid_param",
    resolve_field="uid_param",
    include_from_parent=["id", "uid"],
    parent_field_renames={"id": "user_id", "uid": "uid"},
    # Only identified users carry the uid the sessions listing is queried by.
    parent_params={"is_identified": "true"},
)


def _auth_header(api_key: str) -> str:
    # Fullstory's scheme is the raw API key after "Basic" (not base64 creds).
    return f"Basic {api_key}"


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": FULLSTORY_BASE_URL,
        # The raw key rides in the Authorization header value; framework auth redacts it from
        # any raised error message. Only non-secret headers would go in client `headers`.
        "auth": {"type": "api_key", "api_key": _auth_header(api_key), "name": "Authorization"},
    }


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is valid with a cheap one-user listing probe."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{FULLSTORY_BASE_URL}/v2/users",
        headers={"Authorization": _auth_header(api_key)},
    )
    return ok


def _listing_resource(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FullStoryResumeConfig],
) -> Iterable[Any]:
    if endpoint == "segments":
        path = "/segments/v1"
        params: dict[str, Any] = {"limit": SEGMENTS_PAGE_SIZE}
        data_selector = "segments"
        paginator = FullStoryCursorPaginator(cursor_path="nextPaginationToken", cursor_param="paginationToken")
    else:
        path = f"/v2/{endpoint}"
        params = {}
        data_selector = "results"
        paginator = FullStoryCursorPaginator()

    rest_config: RESTAPIConfig = {
        "client": {**_client_config(api_key), "paginator": paginator},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": path,
                    "params": params,
                    # A missing list key is treated as an empty page, not an error.
                    "data_selector": data_selector,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.next_page_token:
            initial_paginator_state = {"cursor": resume.next_page_token}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(FullStoryResumeConfig(next_page_token=state["cursor"]))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _add_uid_param(row: dict[str, Any]) -> dict[str, Any]:
    # The fan-out binds the uid into the path with str.format, which applies no escaping.
    row["uid_param"] = quote(str(row.get("uid") or ""), safe="")
    row.setdefault("uid", None)
    return row


def _sessions_resource(api_key: str, team_id: int, job_id: str) -> Iterable[Any]:
    # Not resumable: fan-out resume state lists every completed parent, which grows with the user count.
    return build_dependent_resource(
        endpoint_configs=_FANOUT_ENDPOINTS,
        child_endpoint="sessions",
        fanout=SESSIONS_FANOUT,
        client_config=_client_config(api_key),
        path_format_values={},
        team_id=team_id,
        job_id=job_id,
        db_incremental_field_last_value=None,
        parent_endpoint_extra={"data_selector": "results", "paginator": FullStoryCursorPaginator()},
        child_endpoint_extra={"data_selector": "results", "paginator": "single_page"},
        parent_data_map=_add_uid_param,
        page_size_param=None,
    )


def _create_event_export(session: requests.Session, start: datetime, end: datetime) -> str:
    time_range = {"start": _format_timestamp(start), "end": _format_timestamp(end)}
    response = session.post(
        f"{FULLSTORY_BASE_URL}/segments/v1/exports",
        json={
            "segmentId": EXPORT_SEGMENT_ID,
            "type": "TYPE_EVENT",
            "format": "FORMAT_NDJSON",
            "timeRange": time_range,
            # The "everyone" segment defaults to the last 30 days; override it so only the window applies.
            "segmentTimeRange": time_range,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    operation_id = response.json().get("operationId")
    if not operation_id:
        raise FullStoryExportError("Fullstory segment export returned no operationId")
    return operation_id


def _wait_for_export(session: requests.Session, operation_id: str) -> str:
    state = None
    for _attempt in range(EXPORT_POLL_MAX_ATTEMPTS):
        response = session.get(
            f"{FULLSTORY_BASE_URL}/operations/v1/{quote(operation_id, safe='')}",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        operation = response.json()
        state = operation.get("state")
        if state == "COMPLETED":
            export_id = (operation.get("results") or {}).get("searchExportId")
            if not export_id:
                raise FullStoryExportError(f"Fullstory export operation {operation_id} completed without an export id")
            return export_id
        if state == "FAILED":
            raise FullStoryExportFailedError(
                f"Fullstory export operation {operation_id} failed: {operation.get('errorDetails')}"
            )
        time.sleep(EXPORT_POLL_INTERVAL_SECONDS)
    raise FullStoryExportError(f"Fullstory export operation {operation_id} still {state} after polling budget")


def _iter_export_rows(session: requests.Session, export_id: str) -> Iterator[dict[str, Any]]:
    response = session.get(
        f"{FULLSTORY_BASE_URL}/search/v1/exports/{quote(export_id, safe='')}/results",
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    location = response.json()["location"]
    if urlsplit(location).scheme.lower() != "https":
        raise FullStoryExportError("Fullstory export download location is not HTTPS")

    # The location is a pre-signed URL on a storage host, so it must not carry the API key.
    download_session = make_tracked_session(redact_values=(location,))
    with tempfile.TemporaryFile() as file:
        with download_session.get(location, stream=True, timeout=REQUEST_TIMEOUT_SECONDS) as download:
            download.raise_for_status()
            for chunk in download.iter_content(chunk_size=1024 * 1024):
                file.write(chunk)

        file.seek(0)
        is_gzip = file.read(2) == b"\x1f\x8b"
        file.seek(0)
        lines: Iterable[bytes] = gzip.GzipFile(fileobj=file) if is_gzip else file
        for line in lines:
            line = line.strip()
            if line:
                yield json.loads(line)


@frozen
class _ExportWindow:
    start: datetime
    end: datetime


def _export_windows(start: datetime, end: datetime) -> Iterator[_ExportWindow]:
    window_start = start
    while window_start < end:
        window_end = min(window_start + EVENTS_EXPORT_WINDOW, end)
        yield _ExportWindow(start=window_start, end=window_end)
        window_start = window_end


def _export_checkpoint(
    window_start: datetime, window_end: datetime, operation_id: str, rows_done: int
) -> FullStoryResumeConfig:
    return FullStoryResumeConfig(
        export_window_start=_format_timestamp(window_start),
        export_window_end=_format_timestamp(window_end),
        export_operation_id=operation_id,
        export_rows_done=rows_done,
    )


def _start_event_export(
    session: requests.Session,
    resumable_source_manager: ResumableSourceManager[FullStoryResumeConfig],
    window_start: datetime,
    window_end: datetime,
    commit: bool,
) -> str:
    operation_id = _create_event_export(session, window_start, window_end)
    checkpoint = _export_checkpoint(window_start, window_end, operation_id, 0)
    if commit:
        with resumable_source_manager.committing():
            resumable_source_manager.save_state(checkpoint)
    else:
        # Staged only: committing now would move the cursor past rows not yet written.
        resumable_source_manager.save_state(checkpoint)
        # The source holds no rows here. Without the safe point, an export that fails after this
        # loses the operation id, and each retry starts a new export.
        resumable_source_manager.safe_point()
    return operation_id


def get_events(
    api_key: str,
    resumable_source_manager: ResumableSourceManager[FullStoryResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(headers={"Authorization": _auth_header(api_key)}, redact_values=(api_key,))
    end = datetime.now(UTC) - EVENTS_EXPORT_END_LAG

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resumed_start = parse_datetime_value(resume.export_window_start) if resume else None
    resumed_end = parse_datetime_value(resume.export_window_end) if resume else None

    pending_operation_id: Optional[str] = None
    pending_rows_done = 0
    windows: Iterator[_ExportWindow]
    if resume is not None and resumed_start is not None and resumed_end is not None:
        # Finish the interrupted window exactly as it was exported before moving on.
        windows = itertools.chain(
            [_ExportWindow(start=resumed_start, end=resumed_end)], _export_windows(resumed_end, end)
        )
        pending_operation_id = resume.export_operation_id
        pending_rows_done = resume.export_rows_done
    else:
        watermark = parse_datetime_value(db_incremental_field_last_value)
        # The export's time range includes its start, so step past the last synced event.
        start = watermark + timedelta(milliseconds=1) if watermark is not None else end - EVENTS_INITIAL_LOOKBACK
        windows = _export_windows(start, end)

    yielded_any = False
    for window in windows:
        window_start, window_end = window.start, window.end
        operation_id, rows_done = pending_operation_id, pending_rows_done
        pending_operation_id, pending_rows_done = None, 0

        if operation_id is None:
            operation_id = _start_event_export(
                session, resumable_source_manager, window_start, window_end, commit=not yielded_any
            )
            export_id = _wait_for_export(session, operation_id)
        else:
            try:
                export_id = _wait_for_export(session, operation_id)
            except FullStoryExportFailedError:
                # A saved operation that failed would fail every retry, so export the window again.
                operation_id = _start_event_export(
                    session, resumable_source_manager, window_start, window_end, commit=not yielded_any
                )
                rows_done = 0
                export_id = _wait_for_export(session, operation_id)

        batch: list[dict[str, Any]] = []
        written = rows_done
        for index, row in enumerate(_iter_export_rows(session, export_id)):
            if index < rows_done:
                continue
            batch.append(row)
            if len(batch) >= EXPORT_BATCH_SIZE:
                written += len(batch)
                resumable_source_manager.save_state(_export_checkpoint(window_start, window_end, operation_id, written))
                yield batch
                yielded_any = True
                batch = []
        if batch:
            written += len(batch)
            resumable_source_manager.save_state(_export_checkpoint(window_start, window_end, operation_id, written))
            yield batch
            yielded_any = True


def fullstory_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[FullStoryResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    if endpoint == "events":
        return SourceResponse(
            name=endpoint,
            items=lambda: get_events(api_key, resumable_source_manager, db_incremental_field_last_value),
            primary_keys=None,
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="day",
            partition_keys=["EventStart"],
            # Rows inside an export file are unordered, so only commit the watermark once the sync completes.
            sort_mode="desc",
        )

    if endpoint == "sessions":
        resource = _sessions_resource(api_key, team_id, job_id)
        return SourceResponse(
            name=endpoint,
            items=lambda: resource,
            # Session ids are "<user_id>:<session_id>", unique across the account.
            primary_keys=["id"],
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_keys=["created_time"],
            sort_mode="asc",
        )

    listing = _listing_resource(api_key, endpoint, team_id, job_id, resumable_source_manager)
    return SourceResponse(
        name=endpoint,
        items=lambda: listing,
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        sort_mode="asc",
    )
