import logging
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from dateutil import parser
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    make_parent_key_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.mux.settings import (
    BREAKDOWN_DIMENSIONS,
    DATA_METRICS,
    MUX_ENDPOINTS,
    MuxEndpointConfig,
)

logger = logging.getLogger(__name__)

MUX_BASE_URL = "https://api.mux.com"
# Endpoint used to confirm a token is genuine when no specific schema is being validated.
DEFAULT_VALIDATION_PATH = "/video/v1/assets"

# On incremental syncs, re-query slightly before the last `view_end` watermark. Mux Data can finish
# processing a view minutes after it ended, so a view can surface with a `view_end` we've already
# passed; the overlap re-fetches that boundary and the merge on `id` dedupes the repeats.
INCREMENTAL_OVERLAP = timedelta(hours=1)


@dataclasses.dataclass(frozen=True)
class MuxResumeConfig:
    # Next offset page to fetch (offset/limit pagination). None for cursor-paginated endpoints.
    page: int | None = None
    # Next `next_cursor` value to fetch (cursor pagination, List Assets only).
    cursor: str | None = None
    # Framework fan-out state (completed child paths plus the in-progress child page) for the
    # metric and dimension fan-out endpoints.
    fan_out: dict[str, Any] | None = None


class MuxPagePaginator(BasePaginator):
    """Page-number pagination that stops on the first short (or empty) page.

    Mux's offset list endpoints return a full ``limit``-sized page while more rows remain, so a page
    shorter than ``limit`` (including an empty one) means the collection is exhausted. The built-in
    ``PageNumberPaginator`` only stops on an *empty* page, which would issue one extra request per
    endpoint — this preserves the short-page termination the hand-rolled source relied on. Resumable
    via the next page number.
    """

    def __init__(
        self, page_size: int, page_param: str = "page", page: int = 1, max_pages: Optional[int] = None
    ) -> None:
        super().__init__()
        self.page_size = page_size
        self.page_param = page_param
        self.page = page
        self.max_pages = max_pages

    def _inject_page(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def init_request(self, request: Request) -> None:
        self._inject_page(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data or len(data) < self.page_size:
            self._has_next_page = False
            return
        if self.max_pages is not None and self.page >= self.max_pages:
            logger.warning("Mux page cap reached; truncating results. url=%s pages=%s", response.url, self.max_pages)
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject_page(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page already points at the next page to fetch (update_state incremented it).
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"MuxPagePaginator(page={self.page})"


def _make_session(access_token_id: str, secret_key: str) -> requests.Session:
    # Mux authenticates with HTTP Basic auth (Access Token ID as username, Secret as password).
    # Redact the secret wherever it might surface in tracked logs/samples.
    session = make_tracked_session(redact_values=(secret_key,))
    session.auth = (access_token_id, secret_key)
    return session


def get_validation_status(access_token_id: str, secret_key: str, path: str) -> int | None:
    """Probe a list endpoint and return the HTTP status code, or None on a transport error."""
    url = f"{MUX_BASE_URL}{path}?{urlencode({'limit': 1})}"
    _ok, status = validate_via_probe(
        lambda: _make_session(access_token_id, secret_key),
        url,
    )
    return status


def _strip_sensitive_fields(item: dict[str, Any], config: MuxEndpointConfig) -> dict[str, Any]:
    """Drop credential-bearing fields before the row is batched into the warehouse.

    Mux list responses embed live-stream ingest keys (`stream_key`) and direct-upload PUT URLs
    (`url`). Persisting them would expose a valid broadcast/upload credential to anyone who can
    query the imported table, crossing from analytics-read to write access in the customer's Mux
    account, so we remove them rather than import them. Live-stream simulcast targets carry their
    own per-destination `stream_key`, so those are stripped too.
    """
    if not config.sensitive_fields:
        return item
    cleaned = {k: v for k, v in item.items() if k not in config.sensitive_fields}
    targets = cleaned.get("simulcast_targets")
    if isinstance(targets, list):
        cleaned["simulcast_targets"] = [
            {k: v for k, v in target.items() if k != "stream_key"} if isinstance(target, dict) else target
            for target in targets
        ]
    return cleaned


def _normalize_row(item: dict[str, Any], config: MuxEndpointConfig) -> dict[str, Any]:
    """Coerce the partition timestamp to an int so datetime partitioning can parse it.

    Mux returns `created_at` as a string-encoded Unix timestamp in seconds (e.g. "1609869152").
    The pipeline's datetime partitioner parses ints via `fromtimestamp` but would misparse the raw
    string, so convert it where it's the partition key.
    """
    if config.partition_key == "created_at":
        created_at = item.get("created_at")
        if isinstance(created_at, str) and created_at.isdigit():
            return {**item, "created_at": int(created_at)}
    return item


def _as_epoch(value: Any) -> int:
    """Coerce a stored incremental watermark to Unix seconds for Mux's `timeframe[]` param.

    The pipeline hands back the DateTime watermark as a `datetime` (or, defensively, an ISO string).
    Naive values are treated as UTC, matching Mux's ISO 8601 UTC `view_end` timestamps.
    """
    dt = value if isinstance(value, datetime) else parser.parse(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


def _timeframe_params(
    config: MuxEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> dict[str, Any]:
    """Build the `timeframe[]=<start>&timeframe[]=<end>` window for a Mux Data endpoint.

    Incremental video-view syncs start just before the last `view_end` watermark; every other case
    (first sync, full refresh, aggregate endpoints) falls back to the default lookback window.
    """
    now = datetime.now(tz=UTC)
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
        start = _as_epoch(db_incremental_field_last_value) - int(INCREMENTAL_OVERLAP.total_seconds())
    else:
        start = int((now - config.lookback).timestamp())
    return {"timeframe[]": [start, int(now.timestamp())]}


def _to_number(value: Any, cast: Callable[[float], float | int]) -> float | int | None:
    # Timeseries points carry numbers as strings or numbers depending on the metric.
    if value is None or value == "":
        return None
    return cast(float(value))


def _dimension_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten `{"basic": [...], "advanced": [...]}` into one row per dimension."""
    rows: dict[str, dict[str, Any]] = {}
    for tier in ("basic", "advanced"):
        for name in data.get(tier) or []:
            rows.setdefault(name, {"name": name, "tier": tier})
    return list(rows.values())


def _dimension_parent_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    # Trace dimensions (e.g. `video_cdn_trace`) hold an array of values per view, and Mux lists their
    # values through `/elements` instead of the plain dimension values endpoint.
    # The name comes from the API response and is bound into the request path, so it is percent-encoded
    # to keep a hostile value from rewriting the URL (and the host the credentials go to).
    return [
        {
            "dimension": row["name"],
            "values_path": quote(row["name"], safe="") + ("/elements" if row["name"].endswith("_trace") else ""),
        }
        for row in _dimension_rows(data)
    ]


def _static_pages(rows: list[dict[str, Any]]) -> Callable[[], Iterator[list[dict[str, Any]]]]:
    def pages() -> Iterator[list[dict[str, Any]]]:
        yield rows

    return pages


def _lift_parent_keys(parent: str, keys: list[str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def lift(row: dict[str, Any]) -> dict[str, Any]:
        lifted = dict(row)
        for key in keys:
            lifted[key] = lifted.pop(make_parent_key_name(parent, key))
        return lifted

    return lift


def _timeseries_rows(body: dict[str, Any]) -> list[dict[str, Any]]:
    """Explode a timeseries response into one row per `[interval, value, views]` point."""
    metric = body[make_parent_key_name("metrics", "metric")]
    meta = body.get("meta") or {}
    return [
        {
            "metric": metric,
            "interval_start": point[0],
            "value": _to_number(point[1], float),
            "views": _to_number(point[2], int) if len(point) > 2 else None,
            "granularity": meta.get("granularity"),
            "aggregation": meta.get("aggregation"),
        }
        for point in body.get("data") or []
    ]


def _fan_out_resource(
    config: MuxEndpointConfig,
    client: ClientConfig,
    params: dict[str, Any],
    paginator: BasePaginator,
    team_id: int,
    job_id: str,
    resume_hook: Callable[[Optional[dict[str, Any]]], None],
    initial_state: Optional[dict[str, Any]],
) -> Resource:
    """Build a Mux Data endpoint keyed by metric or dimension as a framework parent/child fan-out."""
    parent: EndpointResource
    if config.fan_out == "dimensions":
        parent_name = "dimensions"
        resolve_fields, keys = ["values_path"], ["dimension"]
        parent = {
            "name": parent_name,
            "endpoint": {
                "path": MUX_ENDPOINTS["dimensions"].path,
                "paginator": SinglePagePaginator(),
                "data_selector": "data",
            },
            "data_map": _dimension_parent_rows,
        }
    else:
        parent_name = "metrics"
        if config.fan_out == "metric_dimensions":
            keys = ["metric", "dimension"]
            parent_rows = [{"metric": m, "dimension": d} for m in DATA_METRICS for d in BREAKDOWN_DIMENSIONS]
        else:
            keys = ["metric"]
            parent_rows = [{"metric": m} for m in DATA_METRICS]
        resolve_fields = keys
        parent = {
            "name": parent_name,
            "endpoint": {"path": "/data/v1/metrics"},
            "data_iterator": _static_pages(parent_rows),
        }

    child_endpoint: Endpoint = {
        "path": config.path,
        "params": {
            **params,
            **{key: {"type": "resolve", "resource": parent_name, "field": key} for key in resolve_fields},
        },
        "paginator": paginator,
    }
    child: EndpointResource = {"name": config.name, "endpoint": child_endpoint, "include_from_parent": keys}
    if config.fan_out == "metrics":
        # The timeseries body holds `data` as `[interval, value, views]` arrays, so the whole body is
        # selected and exploded into rows after the parent's metric is merged into it.
        child["data_map"] = _timeseries_rows
    else:
        child_endpoint["data_selector"] = "data"
        child["data_map"] = _lift_parent_keys(parent_name, keys)

    resources = rest_api_resources(
        {"client": client, "resources": [parent, child]},
        team_id,
        job_id,
        None,
        resume_hook=resume_hook,
        initial_paginator_state=initial_state,
    )
    return next(r for r in resources if r.name == config.name)


def mux_source(
    access_token_id: str,
    secret_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MuxResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = MUX_ENDPOINTS[endpoint]
    is_incremental = config.supports_incremental and should_use_incremental_field

    paginator: BasePaginator
    if not config.paginated:
        # Aggregate and lookup endpoints return their whole result in one response.
        paginator = SinglePagePaginator()
    elif config.use_cursor:
        # List Assets returns `next_cursor` in the body; a null/absent value ends pagination.
        paginator = JSONResponseCursorPaginator(cursor_path="next_cursor", cursor_param="cursor")
    else:
        paginator = MuxPagePaginator(page_size=config.page_size, max_pages=config.max_pages)

    params: dict[str, Any] = {}
    if config.paginated:
        params["limit"] = config.page_size
    if config.use_timeframe:
        params.update(_timeframe_params(config, should_use_incremental_field, db_incremental_field_last_value))
        if is_incremental:
            # Ask for oldest-first so the pipeline's `sort_mode="asc"` watermark advances monotonically.
            # The server-side `timeframe[]` filter (applied to every page) bounds the sync regardless of
            # order, and the merge on `id` dedupes the overlap re-fetch.
            params["order_direction"] = "asc"
    params.update(config.extra_params)

    def _map_row(item: dict[str, Any]) -> dict[str, Any]:
        # Strip credential-bearing fields, then coerce the partition timestamp — same order as before.
        return _normalize_row(_strip_sensitive_fields(item, config), config)

    client: ClientConfig = {
        "base_url": MUX_BASE_URL,
        # Pin every request to api.mux.com so the Basic credentials never go to another host.
        "allowed_hosts": [],
        # Basic auth via the framework so the secret is redacted from logs and raised errors.
        "auth": {"type": "http_basic", "username": access_token_id, "password": secret_key},
        "paginator": paginator,
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if config.fan_out is not None:
                initial_paginator_state = resume.fan_out
            elif config.use_cursor:
                if resume.cursor is not None:
                    initial_paginator_state = {"cursor": resume.cursor}
            elif resume.page is not None:
                initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if not state:
            return
        if config.fan_out is not None:
            resumable_source_manager.save_state(MuxResumeConfig(fan_out=state))
        elif config.use_cursor:
            cursor = state.get("cursor")
            if cursor is not None:
                resumable_source_manager.save_state(MuxResumeConfig(cursor=cursor))
        else:
            page = state.get("page")
            if page is not None:
                resumable_source_manager.save_state(MuxResumeConfig(page=int(page)))

    resource: Resource
    if config.fan_out is not None:
        resource = _fan_out_resource(
            config, client, params, paginator, team_id, job_id, save_checkpoint, initial_paginator_state
        )
    else:
        rest_config: RESTAPIConfig = {
            "client": client,
            "resources": [
                {
                    "name": endpoint,
                    "endpoint": {
                        "path": config.path,
                        "params": params,
                        "data_selector": "data",
                    },
                    "data_map": _dimension_rows if endpoint == "dimensions" else _map_row,
                }
            ],
        }
        resource = rest_api_resource(
            rest_config,
            team_id,
            job_id,
            # We apply the incremental filter ourselves via `timeframe[]`, so the framework's own
            # incremental-param injection stays off; the pipeline advances the watermark from `view_end`.
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Oldest-first for incremental video views (see `order_direction` above); the default is fine
        # for full-refresh endpoints, where the watermark isn't tracked.
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
