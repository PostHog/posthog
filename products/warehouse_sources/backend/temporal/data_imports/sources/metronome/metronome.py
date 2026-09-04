import dataclasses
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from typing import Any, Literal, Optional, cast

from requests import Request, Response

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
    parse_datetime_value,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import create_auth
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    IncrementalConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.metronome.settings import (
    CURSOR_PARAM,
    CURSOR_PATH,
    DATA_SELECTOR,
    METRONOME_BASE_URL,
    METRONOME_ENDPOINTS,
    USAGE_HISTORY,
    MetronomeEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 30.0

# Metronome accepts RFC 3339 timestamps and returns them in this shape.
RFC_3339_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Lower bound for a first incremental run — earlier than any Metronome account.
EPOCH_RFC_3339 = "1970-01-01T00:00:00Z"


@frozen
class MetronomeResumeConfig:
    """Paginator checkpoint — the `next_page` cursor of the page we have not yet fetched, plus the
    request window that cursor belongs to."""

    next_page: str
    # For a windowed endpoint, the `ending_before` cutoff pinned at the walk's start. A resumed
    # attempt replays it instead of recomputing from the clock, so one table never mixes rows
    # aggregated to two different cutoffs. None for endpoints that send no window.
    ending_before: str | None = None
    # The `starting_on` bound of the same request. A bucketed table resolves it against the clock
    # when the schema recorded no range, so it is pinned for the walk for the same reason.
    starting_on: str | None = None


class MetronomeCursorPaginator(JSONResponseCursorPaginator):
    """Follows Metronome's `next_page` cursor, handling two vendor behaviours.

    `GET /v1/auditLogs` returns a cursor even for an empty page — the docs say it is always
    returned "to support ongoing log retrieval" — so stopping only when the cursor goes null
    never terminates. An empty page means the collection is exhausted on every Metronome list
    endpoint, so stop there too.

    That same endpoint rejects its `starting_on` window when a cursor is also sent, so the
    window only rides the request that has no cursor on it.
    """

    def __init__(self, first_page_only_params: tuple[str, ...] = ()) -> None:
        super().__init__(cursor_path=CURSOR_PATH, cursor_param=CURSOR_PARAM)
        self._first_page_only_params = first_page_only_params

    def _drop_first_page_only_params(self, request: Request) -> None:
        if not request.params:
            return
        for name in self._first_page_only_params:
            request.params.pop(name, None)

    def init_request(self, request: Request) -> None:
        super().init_request(request)
        # A resumed run starts mid-pagination, so its very first request already carries a cursor.
        if self._cursor_value is not None:
            self._drop_first_page_only_params(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if data is not None and len(data) == 0:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        super().update_request(request)
        self._drop_first_page_only_params(request)


def _paginator_for(config: MetronomeEndpointConfig) -> BasePaginator:
    if not config.paginated:
        return SinglePagePaginator()
    first_page_only: tuple[str, ...] = (config.incremental_start_param,) if config.incremental_start_param else ()
    return MetronomeCursorPaginator(first_page_only_params=first_page_only)


def _format_rfc3339(value: Any) -> str:
    normalized_value = coerce_datetime_to_utc(value)
    if normalized_value is None:
        return str(value)
    return normalized_value.strftime(RFC_3339_FORMAT)


def _incremental_window(config: MetronomeEndpointConfig, cursor_path: str) -> IncrementalConfig | None:
    """The request window for an incremental sync, or None when the endpoint has no time filter."""
    if not config.incremental_start_param or not config.incremental_fields:
        return None
    return {
        "cursor_path": cursor_path,
        "start_param": config.incremental_start_param,
        "initial_value": EPOCH_RFC_3339,
        "convert": _format_rfc3339,
    }


def _align_to_window(value: datetime, window_size: Literal["hour", "day"]) -> datetime:
    """Floor a window bound to the boundary Metronome aggregates on.

    A period's `start_timestamp` is part of the table's primary key, and the bound this run asks
    from is the watermark shifted back by a lookback the user sets in seconds, so it usually lands
    mid-period. Asking from mid-period risks a partial aggregate for a period the table already
    holds in full, which then upserts as a second row instead of replacing the first.
    """
    if window_size == "day":
        return value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value.replace(minute=0, second=0, microsecond=0)


def _resolve_window_start(
    config: MetronomeEndpointConfig,
    db_incremental_field_last_value: Any,
    history_start: datetime | None,
) -> str:
    """Where the requested usage window begins.

    The lifetime table asks for everything the account has. A bucketed table starts at the period
    its watermark reached, so each run asks only for what it does not already hold. With no
    watermark it starts where the schema recorded its range on the first sync, and resolves the
    table's own bound against the clock only when no range was recorded.
    """
    window_size = config.window_size
    if window_size != "hour" and window_size != "day":
        return EPOCH_RFC_3339

    start = (
        parse_datetime_value(db_incremental_field_last_value)
        or coerce_datetime_to_utc(history_start)
        or datetime.now(UTC) - USAGE_HISTORY[config.name]
    )
    return _format_rfc3339(_align_to_window(start, window_size))


@frozen
class MetronomeWalkStart:
    """Where one walk of an endpoint begins: the request window, and the cursor to resume from."""

    starting_on: str | None = None
    ending_before: str | None = None
    paginator_state: dict[str, Any] | None = None


def _walk_start(
    config: MetronomeEndpointConfig,
    resumable_source_manager: "Optional[ResumableSourceManager[MetronomeResumeConfig]]",
    db_incremental_field_last_value: Any,
    history_start: datetime | None,
) -> MetronomeWalkStart:
    """Read the resume checkpoint, then fill in whatever it did not carry.

    A windowed endpoint pins its request window for the whole walk, and a resumed attempt has to
    replay the window its checkpoint stored. Recomputing the window each attempt would pair an old
    cursor with a later window and mix two snapshots in one table.
    """
    resume_config: Optional[MetronomeResumeConfig] = None
    if resumable_source_manager is not None and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()

    starting_on: str | None = None
    ending_before: str | None = None
    paginator_state: dict[str, Any] | None = None

    if resume_config is not None and resumable_source_manager is not None:
        # A checkpoint written before the cutoff was stored carries none. Restart the walk rather
        # than replay its stale cursor against a freshly computed window.
        if config.window_size is not None and resume_config.ending_before is None:
            # The pipeline reads the resume key itself after this returns, so skipping the stale
            # cursor here is not enough. A lingering key makes it treat the restarted walk as a
            # resume and append onto the partial `replace` table. Drop the key so the restart is a
            # clean full refresh.
            resumable_source_manager.clear_state()
        else:
            paginator_state = {"cursor": resume_config.next_page}
            ending_before = resume_config.ending_before
            starting_on = resume_config.starting_on

    if config.window_size is not None:
        if ending_before is None:
            ending_before = _format_rfc3339(datetime.now(UTC))
        if starting_on is None:
            starting_on = _resolve_window_start(config, db_incremental_field_last_value, history_start)

    return MetronomeWalkStart(starting_on=starting_on, ending_before=ending_before, paginator_state=paginator_state)


def _rest_api_client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": METRONOME_BASE_URL,
        "auth": {"type": "bearer", "token": api_key},
        "headers": {"Accept": "application/json"},
        # `capture=False`: customer, invoice and contract payloads carry customer names alongside
        # arbitrary `custom_fields` key/values the account sets itself, so the name-based sample
        # scrubbers can't be relied on to redact them. Requests stay metered and logged.
        "session": make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False),
        # Pin every request (and the bearer header) to the Metronome host and refuse to follow a
        # 3xx, so a server-side redirect can never replay the credential off-host.
        "allowed_hosts": [],
        "allow_redirects": False,
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }


def _rest_client(api_key: str) -> RESTClient:
    """The same client the framework builds from `_rest_api_client_config`, for the fan-out that
    can't be expressed declaratively. Read off the config so the two paths can't drift apart."""
    config = _rest_api_client_config(api_key)
    return RESTClient(
        base_url=config["base_url"],
        headers=config["headers"],
        auth=create_auth(config["auth"]),
        session=config["session"],
        allowed_hosts=config["allowed_hosts"],
        allow_redirects=config["allow_redirects"],
        request_timeout=config["request_timeout"],
    )


def _list_params(config: MetronomeEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = {} if not config.paginated else {"limit": config.page_size}
    params.update(config.extra_params)
    return params


def get_resource(
    endpoint: str,
    should_use_incremental_field: bool,
    incremental_field_name: str | None = None,
    window_ending_before: str | None = None,
    window_starting_on: str | None = None,
) -> EndpointResource:
    config = METRONOME_ENDPOINTS[endpoint]
    if config.fanout or config.body_fanout:
        raise ValueError(f"Fan-out endpoint '{endpoint}' must use the fan-out path")
    # Falling back to the epoch here would ask for every period the account has ever had, which is
    # the one thing the bound on these tables exists to prevent.
    if config.window_size in ("hour", "day") and window_starting_on is None:
        raise ValueError(f"Bucketed usage endpoint '{endpoint}' needs a resolved 'starting_on'")

    endpoint_config: Endpoint = {
        "path": config.path,
        "method": config.method,
        "params": _list_params(config),
        "data_selector": DATA_SELECTOR,
        # Every documented list response wraps its rows in `data`, so a body without it means the
        # shape changed — fail loud rather than silently syncing 0 rows.
        "data_selector_required": True,
        "paginator": _paginator_for(config),
    }
    # The POST list endpoints take their filters as a body. Two of them accept no filters at all,
    # and still expect a JSON document rather than an empty request.
    if config.method == "post":
        json_body = dict(config.json_body)
        if config.window_size is not None:
            # `starting_on` at the epoch means "all usage the account has". `ending_before` is the
            # sync time; the caller pins both for the whole walk so a resumed attempt replays the
            # same window, and these fall back only for a one-shot build with no pinned window.
            json_body["window_size"] = config.window_size
            json_body["starting_on"] = window_starting_on if window_starting_on is not None else EPOCH_RFC_3339
            json_body["ending_before"] = (
                window_ending_before if window_ending_before is not None else _format_rfc3339(datetime.now(UTC))
            )
        endpoint_config["json"] = json_body

    incremental = _incremental_window(config, incremental_field_name or config.default_incremental_field or "")
    if should_use_incremental_field and incremental is not None:
        endpoint_config["incremental"] = cast(IncrementalConfig, incremental)

    # A bucketed usage table syncs incrementally with no framework-injected param: its window lives
    # in the request body, which `_incremental_window` cannot reach. So the write disposition
    # follows the endpoint declaring a cursor field rather than the injected param.
    syncs_incrementally = should_use_incremental_field and bool(config.incremental_fields)

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if syncs_incrementally else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def _body_fanout_pages(client: RESTClient, config: MetronomeEndpointConfig) -> Iterator[list[dict[str, Any]]]:
    """Walk the parent list and call the child once per parent row, binding the id into the body."""
    fanout = config.body_fanout
    if fanout is None:
        raise ValueError(f"'{config.name}' has no body fan-out configured")

    parent = METRONOME_ENDPOINTS[fanout.parent_name]

    for parent_page in client.paginate(
        parent.path,
        params=_list_params(parent),
        data_selector=DATA_SELECTOR,
        data_selector_required=True,
        paginator=_paginator_for(parent),
    ):
        for parent_row in parent_page:
            parent_id = parent_row.get(fanout.resolve_field)
            if not parent_id:
                continue
            for page in client.paginate(
                config.path,
                method=config.method,
                json={**config.json_body, fanout.body_param: parent_id},
                data_selector=DATA_SELECTOR,
                data_selector_required=True,
                paginator=_paginator_for(config),
            ):
                if page:
                    yield page


def _make_source_response(
    config: MetronomeEndpointConfig,
    items_fn: Callable[[], Iterable[Any]],
    chunk_size: int | None = None,
) -> SourceResponse:
    # `audit_logs` pins `sort=date_asc`, so the default ascending `sort_mode` matches the order its
    # rows arrive in. The bucketed usage tables declare "desc" instead, because their rows arrive
    # grouped by customer rather than by period. Metronome documents no order for the rest, and
    # none of them checkpoint a watermark.
    return SourceResponse(
        name=config.name,
        items=items_fn,
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
        chunk_size=chunk_size,
    )


def metronome_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: Optional[ResumableSourceManager[MetronomeResumeConfig]] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
    history_start: Optional[datetime] = None,
) -> SourceResponse:
    endpoint_config = METRONOME_ENDPOINTS[endpoint]

    if endpoint_config.body_fanout:
        # One client for the whole fan-out, so every per-customer request reuses its connection
        # pool. Mirrors the framework path, which builds its session at source-build time too.
        client = _rest_client(api_key)
        return _make_source_response(endpoint_config, lambda: _body_fanout_pages(client, endpoint_config))

    if endpoint_config.fanout:
        parent_config = METRONOME_ENDPOINTS[endpoint_config.fanout.parent_name]
        # Dependent resources don't support resume in the rest_source framework, so the manager is
        # intentionally not threaded into this path.
        dependent_resource = cast(
            Iterable[Any],
            build_dependent_resource(
                endpoint_configs=METRONOME_ENDPOINTS,
                child_endpoint=endpoint,
                fanout=dataclasses.replace(endpoint_config.fanout, child_params=dict(endpoint_config.extra_params)),
                client_config=_rest_api_client_config(api_key),
                path_format_values={},
                team_id=team_id,
                job_id=job_id,
                db_incremental_field_last_value=db_incremental_field_last_value,
                should_use_incremental_field=should_use_incremental_field,
                incremental_field=incremental_field,
                parent_endpoint_extra={
                    "paginator": _paginator_for(parent_config),
                    "data_selector": DATA_SELECTOR,
                    "data_selector_required": True,
                },
                child_endpoint_extra={
                    "paginator": _paginator_for(endpoint_config),
                    "data_selector": DATA_SELECTOR,
                    "data_selector_required": True,
                },
            ),
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    walk = _walk_start(endpoint_config, resumable_source_manager, db_incremental_field_last_value, history_start)

    config: RESTAPIConfig = {
        "client": _rest_api_client_config(api_key),
        "resource_defaults": {},
        "resources": [
            get_resource(
                endpoint,
                should_use_incremental_field,
                incremental_field,
                walk.ending_before,
                walk.starting_on,
            )
        ],
    }

    resume_hook: Optional[Callable[[Optional[dict[str, Any]]], None]] = None
    if resumable_source_manager is not None:

        def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
            # Persist only while there is another page to resume to; the Redis TTL cleans up on
            # completion. The pinned window rides along so a resumed attempt replays it.
            if resumable_source_manager is None or not state:
                return
            cursor = state.get("cursor")
            if cursor:
                resumable_source_manager.save_state(
                    MetronomeResumeConfig(
                        next_page=str(cursor),
                        ending_before=walk.ending_before,
                        starting_on=walk.starting_on,
                    )
                )

        resume_hook = save_checkpoint

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=walk.paginator_state,
    )
    # The resume checkpoint advances after every yielded page — rest_client fires the resume hook
    # right after each yield — so each page has to reach Delta before the bookmark moves past it.
    # Each yielded item is already a whole API page, so chunk_size=1 flushes it on its own rather
    # than letting several pages sit in the batcher's buffer; a mid-sync worker shutdown would
    # otherwise resume past the buffered pages and finish the full-refresh table with silent gaps.
    # The fan-out tables above don't resume, so they keep the default and avoid a commit per page.
    return _make_source_response(endpoint_config, lambda: resource, chunk_size=1)


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    valid, status_code = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False),
        f"{METRONOME_BASE_URL}/v1/customers?limit=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        timeout=REQUEST_TIMEOUT_SECONDS,
        allow_redirects=False,
    )
    if valid:
        return True, None
    if status_code is None:
        return False, "Couldn't reach Metronome to validate the API token. Check your connection and try again."
    if status_code in (401, 403):
        # Metronome's auth docs say a token it won't accept comes back as "a 401 or 403", so both
        # codes point at the same fix.
        return (
            False,
            "Metronome rejected the API token. Create a new one in Metronome under "
            "Developer > API tokens and reconnect.",
        )
    return False, f"Metronome API returned an unexpected status code: {status_code}"
