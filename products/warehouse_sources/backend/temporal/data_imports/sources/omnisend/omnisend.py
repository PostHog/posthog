import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar, Optional

from requests import Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.cursor import SourceCursorManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import APIKeyAuth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.settings import (
    OMNISEND_2026_03_15,
    OMNISEND_ENDPOINTS,
    OMNISEND_V3,
    OmnisendAnalyticsQuery,
    OmnisendWire,
)

OMNISEND_BASE_URL = "https://api.omnisend.com/v3"
OMNISEND_API_BASE_URL = "https://api.omnisend.com/api"

_BASE_URL_BY_VERSION = {
    OMNISEND_V3: OMNISEND_BASE_URL,
    OMNISEND_2026_03_15: OMNISEND_API_BASE_URL,
}

# Raised when a schema is synced on a version that has no list endpoint for it (e.g. a carts
# schema pinned to 2026-03-15, where carts and orders are write-only events).
UNSUPPORTED_ENDPOINT_ERROR = "Omnisend API version has no list endpoint for this table"

# Omnisend allows up to 250 items per page; larger pages mean fewer requests against the
# 400 req/min general rate limit.
PAGE_SIZE = 250

# Omnisend rejects an analytics `dateRange.from` more than 5 years back.
ANALYTICS_HISTORY_DAYS = 5 * 365 - 5
# Daily granularity caps one query at 60 days, and a request at 4 queries spanning under 12 months.
ANALYTICS_WINDOW_DAYS = 56
ANALYTICS_WINDOWS_PER_REQUEST = 4


@dataclasses.dataclass(frozen=True)
class OmnisendResumeConfig:
    # Fully-formed next-page URL from the API's `paging.next`; we follow it verbatim.
    next_url: Optional[str] = None
    # Opaque `paging.cursors.after` token for the cursor-paginated 2026-03-15 endpoints.
    cursor: Optional[str] = None
    # Last segment on the `cursor` page whose row was handed on.
    last_segment_id: Optional[str] = None
    # First day of the next analytics request, as an ISO date.
    window_start: Optional[str] = None


@frozen
class OmnisendAnalyticsCursor:
    """The exclusive end date of the last analytics read that completed."""

    cursor_kind: ClassVar[str] = "omnisend_analytics_read_through"

    read_through: str


@frozen
class _AnalyticsWindow:
    start: date
    end: date


class _OmnisendCursorPaginator(JSONResponseCursorPaginator):
    def __init__(self) -> None:
        super().__init__(cursor_path="paging.cursors.after", cursor_param="after", raise_on_repeated_cursor=True)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        # Omnisend documents `hasMore: false` and a null `after` cursor as equivalent stop signals.
        try:
            has_more = response.json().get("paging", {}).get("hasMore")
        except Exception:
            has_more = None
        if has_more is False:
            self._has_next_page = False


def _base_url(api_version: str) -> str:
    try:
        return _BASE_URL_BY_VERSION[api_version]
    except KeyError:
        raise ValueError(f"Unsupported Omnisend API version: {api_version}")


def _wire(endpoint: str, api_version: str) -> OmnisendWire:
    wire = OMNISEND_ENDPOINTS[endpoint].wires.get(api_version)
    if wire is None:
        raise ValueError(f"{UNSUPPORTED_ENDPOINT_ERROR}: {endpoint} is not available on {api_version}")
    return wire


def _headers(api_version: str) -> dict[str, str]:
    # Auth is supplied via the framework auth config so its value is redacted from logs and raised
    # errors; only non-secret headers are set here.
    headers = {"Accept": "application/json"}
    if api_version != OMNISEND_V3:
        headers["Omnisend-Version"] = api_version
    return headers


@dataclasses.dataclass(frozen=True)
class _AuthHeader:
    name: str
    value: str


def _auth_header(api_key: str, api_version: str) -> _AuthHeader:
    if api_version == OMNISEND_V3:
        return _AuthHeader(name="X-API-KEY", value=api_key)
    return _AuthHeader(name="Authorization", value=f"Omnisend-API-Key {api_key}")


def _client_config(api_key: str, api_version: str, wire: OmnisendWire) -> ClientConfig:
    auth = _auth_header(api_key, api_version)
    paginator: BasePaginator = (
        _OmnisendCursorPaginator()
        if wire.cursor_paginated
        # Omnisend returns a fully-formed next-page URL under `paging.next`; follow it verbatim.
        else JSONResponsePaginator(next_url_path="paging.next")
    )
    return {
        "base_url": _base_url(api_version),
        "headers": _headers(api_version),
        "auth": {"type": "api_key", "api_key": auth.value, "name": auth.name, "location": "header"},
        "paginator": paginator,
        # Pin every request, including `paging.next` links and seeded resume URLs, to the Omnisend
        # host so a tampered link or redirect can't carry the API key elsewhere.
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": (10, 60),
    }


def _rest_client(api_key: str, api_version: str) -> RESTClient:
    auth = _auth_header(api_key, api_version)
    return RESTClient(
        base_url=_base_url(api_version),
        headers=_headers(api_version),
        auth=APIKeyAuth(api_key=auth.value, name=auth.name, location="header"),
        paginator=SinglePagePaginator(),
        allowed_hosts=[],
        allow_redirects=False,
        request_timeout=(10, 60),
    )


def _fetch_object(
    client: RESTClient,
    path: str,
    method: str = "get",
    params: Optional[dict[str, Any]] = None,
    json: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    pages = list(client.paginate(path=path, method=method, params=params, json=json, data_selector="$"))
    body = pages[0][0] if pages and pages[0] else None
    if not isinstance(body, dict):
        raise ValueError(f"Omnisend returned an unexpected response from {path}. Expected a JSON object.")
    return body


def _segment_contacts_count(client: RESTClient, segment_id: Any) -> Optional[int]:
    if not segment_id:
        return None
    try:
        statistics = _fetch_object(client, f"/segments/{segment_id}/statistics")
    except HTTPError as e:
        # A segment deleted between the list call and this one.
        if e.response is not None and e.response.status_code == 404:
            return None
        raise
    return statistics.get("contactsCount")


def _iter_segments(
    api_key: str,
    api_version: str,
    wire: OmnisendWire,
    resumable_source_manager: ResumableSourceManager[OmnisendResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume is not None else None
    done_through = resume.last_segment_id if resume is not None else None

    client = _rest_client(api_key, api_version)
    try:
        while True:
            params: dict[str, Any] = {"limit": wire.page_size or PAGE_SIZE, **wire.params}
            if cursor:
                params["after"] = cursor
            page = _fetch_object(client, wire.path, params=params)
            segments = page.get(wire.data_key)
            if not isinstance(segments, list):
                raise ValueError(f"Omnisend response from {wire.path} has no '{wire.data_key}' list")

            start = 0
            # Skip by id, not position: if the checkpointed segment is gone, replay the whole page.
            if done_through is not None:
                ids = [segment.get("segmentID") for segment in segments]
                if done_through in ids:
                    start = ids.index(done_through) + 1
                done_through = None

            for segment in segments[start:]:
                segment_id = segment.get("segmentID")
                row = {**segment, "contactsCount": _segment_contacts_count(client, segment_id)}
                resumable_source_manager.save_state(OmnisendResumeConfig(cursor=cursor, last_segment_id=segment_id))
                yield [row]

            paging = page.get("paging") or {}
            next_cursor = (paging.get("cursors") or {}).get("after")
            if paging.get("hasMore") is False or not next_cursor:
                break
            if next_cursor == cursor:
                raise ValueError("Omnisend segments pagination is not advancing (repeated cursor)")
            cursor = next_cursor
            resumable_source_manager.safe_point()
    finally:
        client.session.close()


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _analytics_start(
    today: date,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    stored_cursor: Optional[OmnisendAnalyticsCursor],
    lookback: timedelta,
) -> date:
    earliest = today - timedelta(days=ANALYTICS_HISTORY_DAYS)
    if not should_use_incremental_field:
        return earliest
    if db_incremental_field_last_value is not None:
        return max(earliest, _as_date(db_incremental_field_last_value))
    # Reads that returned no rows set no watermark, so the stored read-through date bounds the next read.
    if stored_cursor is not None:
        return max(earliest, date.fromisoformat(stored_cursor.read_through) - lookback)
    return earliest


def _analytics_windows(start: date, end: date) -> list[_AnalyticsWindow]:
    windows = []
    window_start = start
    while window_start < end:
        window_end = min(window_start + timedelta(days=ANALYTICS_WINDOW_DAYS), end)
        windows.append(_AnalyticsWindow(start=window_start, end=window_end))
        window_start = window_end
    return windows


def _analytics_body(query: OmnisendAnalyticsQuery, windows: list[_AnalyticsWindow]) -> dict[str, Any]:
    queries = []
    for index, window in enumerate(windows):
        date_range: dict[str, str] = {"from": f"{window.start}T00:00:00Z", "to": f"{window.end}T00:00:00Z"}
        if query.date_range_interval:
            date_range["interval"] = query.date_range_interval
        queries.append(
            {
                "alias": f"window-{index}",
                "metrics": [{"name": metric} for metric in query.metrics],
                "dimensions": [
                    {"name": "timestamp", "granularity": "day"},
                    *({"name": dimension} for dimension in query.dimensions),
                ],
                "dateRange": date_range,
            }
        )
    return {"queries": queries}


def _iter_analytics(
    api_key: str,
    api_version: str,
    wire: OmnisendWire,
    query: OmnisendAnalyticsQuery,
    start: date,
    end: date,
    resumable_source_manager: ResumableSourceManager[OmnisendResumeConfig],
    cursor_manager: Optional[SourceCursorManager[OmnisendAnalyticsCursor]],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start:
        start = max(start, date.fromisoformat(resume.window_start))

    windows = _analytics_windows(start, end)
    client = _rest_client(api_key, api_version)
    try:
        for offset in range(0, len(windows), ANALYTICS_WINDOWS_PER_REQUEST):
            batch = windows[offset : offset + ANALYTICS_WINDOWS_PER_REQUEST]
            response = _fetch_object(client, wire.path, method="post", json=_analytics_body(query, batch))
            results = response.get(wire.data_key)
            if not isinstance(results, list):
                raise ValueError(f"Omnisend response from {wire.path} has no '{wire.data_key}' list")
            rows = [row for result in results for row in (result.get("rows") or [])]

            next_offset = offset + ANALYTICS_WINDOWS_PER_REQUEST
            if next_offset < len(windows):
                resumable_source_manager.save_state(
                    OmnisendResumeConfig(window_start=windows[next_offset].start.isoformat())
                )
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()
        if cursor_manager is not None:
            cursor_manager.stage(OmnisendAnalyticsCursor(read_through=end.isoformat()))
    finally:
        client.session.close()


def validate_credentials(api_key: str, api_version: str) -> tuple[bool, int | None]:
    """Cheap probe to confirm the API key is genuine. Returns (is_valid, status_code)."""
    auth = _auth_header(api_key, api_version)
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{_base_url(api_version)}/contacts?limit=1",
        headers={auth.name: auth.value, **_headers(api_version)},
        allow_redirects=False,
    )


def omnisend_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[OmnisendResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    analytics_cursor_manager: Optional[SourceCursorManager[OmnisendAnalyticsCursor]] = None,
) -> SourceResponse:
    config = OMNISEND_ENDPOINTS[endpoint]
    wire = _wire(endpoint, api_version)
    partition_keys = [config.partition_key] if config.partition_key else None

    if config.analytics is not None:
        query = config.analytics
        today = datetime.now(UTC).date()
        start = _analytics_start(
            today,
            should_use_incremental_field,
            db_incremental_field_last_value,
            analytics_cursor_manager.load() if analytics_cursor_manager is not None else None,
            timedelta(seconds=config.default_incremental_lookback_seconds or 0),
        )
        return SourceResponse(
            name=endpoint,
            # `to` is exclusive, so tomorrow's midnight includes today's completed hours.
            items=lambda: _iter_analytics(
                api_key,
                api_version,
                wire,
                query,
                start,
                today + timedelta(days=1),
                resumable_source_manager,
                analytics_cursor_manager,
            ),
            primary_keys=[wire.primary_key, *query.dimensions],
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="month",
            partition_keys=partition_keys,
        )

    if endpoint == "segments":
        return SourceResponse(
            name=endpoint,
            items=lambda: _iter_segments(api_key, api_version, wire, resumable_source_manager),
            primary_keys=[wire.primary_key],
            partition_count=1,
            partition_size=1,
            partition_mode="datetime",
            partition_format="month",
            partition_keys=partition_keys,
        )

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key, api_version, wire),
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": wire.path,
                    "params": {"limit": wire.page_size or PAGE_SIZE, **wire.params},
                    "data_selector": wire.data_key,
                    # A 200 body missing the envelope key means the response shape changed — fail
                    # loud instead of silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if wire.cursor_paginated and resume.cursor:
                initial_paginator_state = {"cursor": resume.cursor}
            # A next-page URL saved under another version points at that version's base path.
            elif not wire.cursor_paginated and resume.next_url and resume.next_url.startswith(_base_url(api_version)):
                initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if not state:
            return
        if state.get("cursor"):
            resumable_source_manager.save_state(OmnisendResumeConfig(cursor=state["cursor"]))
        elif state.get("next_url"):
            resumable_source_manager.save_state(OmnisendResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Omnisend list endpoint is full refresh
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[wire.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=partition_keys,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
