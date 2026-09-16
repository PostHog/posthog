import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, Optional

from requests import Response
from requests.exceptions import HTTPError

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.bunny.settings import (
    BUNNY_ENDPOINTS,
    DATE_FROM_PARAM,
    LOG_DATE_FROM_PARAM,
    LOG_DATE_TO_PARAM,
    LOG_EXCLUDED_FIELDS,
    LOG_RETENTION,
    LOG_WINDOW_MARGIN,
    BunnyEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import create_auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    OffsetPaginator,
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

BUNNY_BASE_URL = "https://api.bunny.net"
# The Stream API answers on its own host and authenticates per video library rather than per
# account, so it needs its own client even though it is the same vendor.
BUNNY_STREAM_BASE_URL = "https://video.bunnycdn.com"
# The CDN Logging API is a third host. It takes the same account API key as the Core API.
BUNNY_LOG_BASE_URL = "https://logging.bunnycdn.com"
# The list endpoints accept perPage 5..1000; 1000 minimises round trips for the typically small
# zone/library tables.
PER_PAGE = 1000
# Cheap endpoint used to confirm an account API key is genuine. The AccessKey is account-wide, so
# one probe validates access to every Core API list endpoint.
DEFAULT_PROBE_PATH = "/pullzone"
# The statistics endpoints take an ISO-8601 UTC instant for their `dateFrom` bound.
DATE_FROM_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# The per-library Stream keys `/videolibrary` carries, best first: read-only is all the Stream
# endpoints we call need.
STREAM_KEY_FIELDS = ("ReadOnlyApiKey", "ApiKey")


@dataclasses.dataclass
class BunnyResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `Id`.
    next_page: int = 1


@frozen
class BunnyEndpointCall:
    """One request an endpoint has to make: the client that carries the right credential for it,
    the resolved path, and the parent columns stamped onto each row it returns."""

    client: RESTClient
    path: str
    injected: dict[str, Any]


class BunnyHasMoreItemsPaginator(PageNumberPaginator):
    """Page-number paginator that stops on bunny.net's explicit ``HasMoreItems`` flag.

    The built-in stop conditions don't fit: bunny.net reports total ITEMS (not pages) and an
    empty ``Items`` page with ``HasMoreItems: true`` must not end the sync, while a final page
    can be full — so neither ``total_path`` nor ``stop_after_empty_page`` matches the API's
    own termination signal.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self.page += 1
        try:
            body = response.json()
        except Exception:
            body = None
        self._has_next_page = isinstance(body, dict) and bool(body.get("HasMoreItems", False))


class BunnyLogHasMorePaginator(OffsetPaginator):
    """Offset paginator that stops on the Logging API's explicit ``pagination.hasMore`` flag.

    The built-in stop conditions don't fit: the response reports no grand total, and the API
    applies some of its filters after fetching a page, so a short page does not mean the last
    one. The flag is the API's own termination signal.
    """

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        self.offset += self.limit
        try:
            body = response.json()
        except Exception:
            body = None
        pagination = body.get("pagination") if isinstance(body, dict) else None
        self._has_next_page = isinstance(pagination, dict) and bool(pagination.get("hasMore", False))


def _paginator_for(config: BunnyEndpointConfig) -> BasePaginator:
    if config.charts is not None:
        return SinglePagePaginator()
    if config.logging_api:
        return BunnyLogHasMorePaginator(limit=PER_PAGE)
    if config.stream_api:
        # The Stream list envelope reports total ITEMS and carries no "more items" flag, so the
        # walk ends on the first empty page instead.
        return PageNumberPaginator(base_page=1)
    # Always request page>=1 so the Core API returns the paginated envelope
    # ({Items, CurrentPage, TotalItems, HasMoreItems}); page=0 would return a bare array.
    return BunnyHasMoreItemsPaginator(base_page=1)


def _client_config(access_key: str, base_url: str = BUNNY_BASE_URL) -> ClientConfig:
    return {
        "base_url": base_url,
        # The AccessKey travels via the framework auth config so its value is redacted from
        # logged URLs and captured samples; only the non-secret Accept header is set here.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": access_key, "name": "AccessKey", "location": "header"},
    }


def _rest_client(access_key: str, base_url: str = BUNNY_BASE_URL) -> RESTClient:
    """The same client the framework builds from ``_client_config``, for the fan-out that can't
    be expressed declaratively. Read off the config so the two paths can't drift apart."""
    config = _client_config(access_key, base_url)
    return RESTClient(
        base_url=config["base_url"],
        headers=config["headers"],
        auth=create_auth(config["auth"]),
    )


def _request_params(
    config: BunnyEndpointConfig, date_from: Optional[str] = None, date_to: Optional[str] = None
) -> dict[str, Any]:
    if config.charts is not None:
        return {**config.params, DATE_FROM_PARAM: date_from}
    if config.logging_api:
        # The paginator carries this endpoint's page size, alongside its offset. `to` is fixed
        # once per sync (see `_log_date_to`) rather than left to the API's own default of "now",
        # so the window a run walks cannot grow while it walks it.
        return {**config.params, LOG_DATE_FROM_PARAM: date_from, LOG_DATE_TO_PARAM: date_to}
    return {config.page_size_param: PER_PAGE, **config.params}


def _date_from(db_incremental_field_last_value: Any) -> Optional[str]:
    """The ``dateFrom`` bound an incremental run asks from, or None to take the vendor default.

    bunny.net returns the last 30 days when no bound is sent, so a first run seeds 30 days and
    each later run asks only from the newest point the table already holds. That point's own
    bucket comes back again and upserts on the primary key, which is what settles an interval
    that was still in progress when it was first read.
    """
    value = parse_datetime_value(db_incremental_field_last_value)
    if value is None:
        return None
    return value.strftime(DATE_FROM_FORMAT)


def _log_date_from(db_incremental_field_last_value: Any) -> str:
    """The ``from`` bound a log query asks from. Always set, unlike ``dateFrom``.

    The Logging API returns only the last 24 hours when no window is sent, which would drop
    entries whenever a sync runs less often than daily, so a first run asks from the retention
    edge instead. A later run asks from the newest entry the table already holds, clamped to
    that same edge because the API rejects a window starting before it. The overlap that the
    clamp and the open window end re-read upserts on the request id.
    """
    retention_edge = datetime.now(UTC) - LOG_RETENTION + LOG_WINDOW_MARGIN
    watermark = parse_datetime_value(db_incremental_field_last_value)
    date_from = retention_edge if watermark is None else max(watermark, retention_edge)
    return date_from.strftime(DATE_FROM_FORMAT)


def _log_date_to() -> str:
    """The ``to`` bound a log query asks up to, captured once when the sync starts.

    The Logging API defaults ``to`` to the moment it handles each request. Sending that default
    on every page would let the window grow for as long as the walk takes, and a busy zone's
    ``pagination.hasMore`` could then stay true indefinitely. Fixing the bound once caps the
    window's size at the number of entries it held when the sync began.
    """
    return datetime.now(UTC).strftime(DATE_FROM_FORMAT)


def _stream_access_key(library: dict[str, Any]) -> Optional[str]:
    """The Stream key for one video library, or None when the row carries neither.

    video.bunnycdn.com authenticates against the library's own key, so the account key that
    listed the libraries cannot reach it.
    """
    for field_name in STREAM_KEY_FIELDS:
        value = library.get(field_name)
        if isinstance(value, str) and value:
            return value
    return None


def _iter_parent_rows(client: RESTClient, parent: BunnyEndpointConfig) -> Iterator[dict[str, Any]]:
    for page in client.paginate(
        parent.path,
        params=_request_params(parent),
        data_selector=parent.items_selector,
        data_selector_required=True,
        paginator=_paginator_for(parent),
    ):
        yield from page


def _endpoint_calls(access_key: str, config: BunnyEndpointConfig) -> Iterator[BunnyEndpointCall]:
    """Every call this endpoint has to make.

    One call for a top-level endpoint, one per parent row for a fan-out child — which on the
    Stream API also means a client holding that library's own key. A library with no usable key
    is skipped rather than failing the whole table.
    """
    core_client = _rest_client(access_key)
    if config.parent is None:
        yield BunnyEndpointCall(client=core_client, path=config.path, injected={})
        return

    child_client = _rest_client(access_key, BUNNY_LOG_BASE_URL) if config.logging_api else core_client
    for parent_row in _iter_parent_rows(core_client, BUNNY_ENDPOINTS[config.parent.endpoint]):
        parent_id = parent_row.get(config.parent.id_field)
        if parent_id is None:
            continue
        injected = {config.parent.id_column: parent_id}
        path = config.path.format(id=parent_id)
        if not config.stream_api:
            yield BunnyEndpointCall(client=child_client, path=path, injected=injected)
            continue
        stream_key = _stream_access_key(parent_row)
        if stream_key is not None:
            client = _rest_client(stream_key, BUNNY_STREAM_BASE_URL)
            yield BunnyEndpointCall(client=client, path=path, injected=injected)


def _chart_rows(
    body: Any, charts: dict[str, str], timestamp_column: str, injected: dict[str, Any]
) -> list[dict[str, Any]]:
    """Pivot a statistics body — one ``{timestamp: value}`` map per chart — into one row per
    timestamp, sorted oldest first.

    Every row carries every chart column so a batch converts to a single Arrow schema even when
    the charts cover different ranges.
    """
    rows: dict[datetime, dict[str, Any]] = {}
    for chart_name, column in charts.items():
        points = body.get(chart_name) if isinstance(body, dict) else None
        if not isinstance(points, dict):
            continue
        for raw_timestamp, value in points.items():
            timestamp = parse_datetime_value(raw_timestamp)
            if timestamp is None:
                continue
            row = rows.setdefault(
                timestamp,
                {**injected, timestamp_column: timestamp, **dict.fromkeys(charts.values())},
            )
            row[column] = value
    return [rows[timestamp] for timestamp in sorted(rows)]


def _chart_pages(
    access_key: str, config: BunnyEndpointConfig, timestamp_column: str, date_from: Optional[str]
) -> Iterator[list[dict[str, Any]]]:
    charts = config.charts or {}
    for call in _endpoint_calls(access_key, config):
        params = _request_params(config, date_from)
        for page in call.client.paginate(call.path, params=params, paginator=_paginator_for(config)):
            for body in page:
                rows = _chart_rows(body, charts, timestamp_column, call.injected)
                if rows:
                    yield rows


def _fanout_list_pages(access_key: str, config: BunnyEndpointConfig) -> Iterator[list[dict[str, Any]]]:
    for call in _endpoint_calls(access_key, config):
        for page in call.client.paginate(
            call.path,
            params=_request_params(config),
            data_selector=config.items_selector,
            data_selector_required=True,
            paginator=_paginator_for(config),
        ):
            if page:
                yield [{**call.injected, **row} for row in page]


def _log_pages(
    access_key: str, config: BunnyEndpointConfig, db_incremental_field_last_value: Any, date_to: str
) -> Iterator[list[dict[str, Any]]]:
    """Walk the CDN access logs of every pull zone that has logging turned on."""
    for call in _endpoint_calls(access_key, config):
        # Recomputed per zone rather than once for the whole walk: a fan-out across many zones
        # can take longer than `LOG_WINDOW_MARGIN` allows, and the API rejects a `from` that has
        # since aged past the retention window it was computed against. `to` stays fixed (see
        # `_log_date_to`) since only the window START can expire this way.
        date_from = _log_date_from(db_incremental_field_last_value)
        params = _request_params(config, date_from, date_to)
        try:
            for page in call.client.paginate(
                call.path,
                params=params,
                data_selector=config.items_selector,
                data_selector_required=True,
                paginator=_paginator_for(config),
            ):
                if page:
                    yield [
                        {**call.injected, **{k: v for k, v in row.items() if k not in LOG_EXCLUDED_FIELDS}}
                        for row in page
                    ]
        except HTTPError as error:
            # The Logging API answers 404 for a pull zone with logging turned off. That is a
            # normal per-zone setting, not a failure of the table, so skip the zone.
            if error.response is None or error.response.status_code != 404:
                raise


def _resume_page(manager: ResumableSourceManager[BunnyResumeConfig]) -> Optional[dict[str, Any]]:
    """The paginator state a retried attempt picks up from, or None to start at the first page."""
    if not manager.can_resume():
        return None
    resume = manager.load_state()
    return None if resume is None else {"page": resume.next_page}


def _save_checkpoint(manager: ResumableSourceManager[BunnyResumeConfig], state: Optional[dict[str, Any]]) -> None:
    # Persist only while more pages remain; saved AFTER a page is yielded so a crash re-fetches
    # from the next page (already-yielded pages are persisted) and merge dedupes the re-pulled
    # page on the primary key.
    if state and state.get("page") is not None:
        manager.save_state(BunnyResumeConfig(next_page=int(state["page"])))


def _source_response(
    config: BunnyEndpointConfig,
    items: Callable[[], Iterable[Any]],
    column_hints: Optional[dict[str, Any]] = None,
) -> SourceResponse:
    return SourceResponse(
        name=config.name,
        items=items,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
        column_hints=column_hints,
    )


def bunny_source(
    access_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BunnyResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BUNNY_ENDPOINTS[endpoint]

    # Only the top-level list endpoints checkpoint: their page number is the whole cursor. A
    # fan-out walk would need the parent's position too, which page-number state cannot carry,
    # so those tables restart from the first parent instead.
    if config.charts is not None:
        if config.timestamp_column is None:
            raise ValueError(f"Statistics endpoint '{endpoint}' needs a timestamp column")
        timestamp_column = config.timestamp_column
        date_from = _date_from(db_incremental_field_last_value)
        return _source_response(config, lambda: _chart_pages(access_key, config, timestamp_column, date_from))

    if config.logging_api:
        date_to = _log_date_to()
        return _source_response(
            config, lambda: _log_pages(access_key, config, db_incremental_field_last_value, date_to)
        )

    if config.parent is not None:
        return _source_response(config, lambda: _fanout_list_pages(access_key, config))

    rest_config: RESTAPIConfig = {
        "client": {**_client_config(access_key), "paginator": _paginator_for(config)},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": _request_params(config),
                    "data_selector": config.items_selector,
                    # `Items` is always present in the paginated envelope; missing it means a
                    # malformed response, so fail loudly rather than silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # the list endpoints are full refresh — no incremental cursor
        resume_hook=lambda state: _save_checkpoint(resumable_source_manager, state),
        initial_paginator_state=_resume_page(resumable_source_manager),
    )

    return _source_response(config, lambda: resource, column_hints=resource.column_hints)


def check_access(access_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[bool, Optional[int]]:
    """Probe a single list endpoint to validate the account API key.

    Returns ``(ok, status)``: ``status`` is the HTTP status of the probe (401/403 means an auth
    failure — bunny.net returns clean HTTP status codes, so no body sniffing is needed) or
    ``None`` when the probe couldn't connect at all.
    """
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(access_key,)),
        f"{BUNNY_BASE_URL}{path}?page=1&perPage=5",
        headers={"AccessKey": access_key, "Accept": "application/json"},
    )
