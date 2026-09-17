import threading
import dataclasses
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any, Optional, cast

from requests import PreparedRequest, Request, Response, Session

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import (
    coerce_datetime_to_utc,
    parse_datetime_value,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.request_pacer import (
    RequestPacer,
    submit_with_context,
)
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

# `POST /v1/usage` documents `ending_before` as at least one day after `starting_on`.
MIN_USAGE_WINDOW = timedelta(days=1)

# How many rows of a usage walk go into one yielded batch, which is one Delta merge.
USAGE_COALESCE_ROWS = 20_000

# `POST /v1/usage` pages per customer and billable metric and takes no page-size parameter, so a
# first sync costs one request per page whatever the account holds, and a large account runs to
# hundreds of thousands of requests. Customers are independent, so walk several at once. The
# endpoint sits in Metronome's default rate tier, 8 requests a second shared with every other table
# on the same account, so take well under it and leave the rest for the account's other syncs.
# Two, not more: the pacer below is what governs throughput, and at the latency this endpoint
# answers in, two workers already saturate it. Each worker holds one customer's rows while it walks
# them, so a third would buy no request rate and cost another customer's worth of memory. More
# workers only pay off if the endpoint slows enough for the workers, rather than the rate, to become
# the limit.
USAGE_CUSTOMER_CONCURRENCY = 2
USAGE_REQUESTS_PER_SECOND = 5.0
# Metronome documents its limit per second and documents no Retry-After, so a throttled pool only
# has to stand down for a second or two, and it has to decide that for itself. The pacer's own
# default is sized for a vendor that sends the header and falls back rarely.
USAGE_RATE_LIMIT_HOLD_SECONDS = 5.0
# Caps a batch when an account's customers are small enough that the row cap never trips.
USAGE_CUSTOMERS_PER_BATCH = 100


@frozen
class MetronomeResumeConfig:
    """Checkpoint for a walk, plus the request window it belongs to.

    A sequential walk stores `next_page`, the cursor of the page it has not fetched yet. A usage walk
    is partitioned by customer, so it stores where the customer list had reached and which customers
    of that page are already written; the rest of the page is re-walked from the start.
    """

    next_page: str | None = None
    # For a windowed endpoint, the `ending_before` cutoff pinned at the walk's start. A resumed
    # attempt replays it instead of recomputing from the clock, so one table never mixes rows
    # aggregated to two different cutoffs. None for endpoints that send no window.
    ending_before: str | None = None
    # The `starting_on` bound of the same request. A bucketed table resolves it against the clock
    # when the schema recorded no range, so it is pinned for the walk for the same reason.
    starting_on: str | None = None
    # Partitioned usage walks. The cursor that fetches the customer page being worked on, and the
    # customers within that page whose rows are already written. Both reset together when a page
    # finishes, so the checkpoint stays the size of one customer page however large the account is.
    parent_cursor: str | None = None
    completed_customers: tuple[str, ...] = ()


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


def _align_to_utc_midnight(value: datetime) -> datetime:
    """Floor a usage window bound to the boundary Metronome requires.

    `POST /v1/usage` documents both bounds as aligned to UTC midnight and answers a 400 when either
    is not, whatever the `window_size`, so an hourly table also asks for whole days.

    Flooring also keeps a bucketed table's rows stable. A period's `start_timestamp` is part of the
    table's primary key, and the bound this run asks from is the watermark shifted back by a
    lookback the user sets in seconds, so it usually lands mid-period. Asking from mid-period
    returns a partial aggregate for a period the table already holds in full, which then upserts as
    a second row instead of replacing the first.
    """
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _usage_window_end(value: datetime) -> datetime:
    """The end bound a usage request asks for.

    Metronome takes a UTC-midnight bound only, so the nearest aligned end that still covers the
    period in progress is the next midnight rather than the last one. Ending at the last one would
    hold every table a full period behind, which is the period a usage table is most asked about.

    Rows for a period still in progress come back partial. The merge key carries the period start,
    so each later run upserts a fresher value over them, and the row settles once the period
    closes. This is the same path a period already takes when Metronome accepts a backdated event
    for it.
    """
    return _align_to_utc_midnight(value) + timedelta(days=1)


def _clamp_window_start(starting_on: str, ending_before: str) -> str:
    """Hold the requested window to the one-day minimum Metronome documents.

    Both bounds floor to UTC midnight, so a table whose watermark already reached the newest
    complete period resolves a start equal to the end. Metronome rejects that window, so ask for
    the last whole day instead. Those rows upsert over ones the table already holds.
    """
    start = parse_datetime_value(starting_on)
    end = parse_datetime_value(ending_before)
    if start is None or end is None or end - start >= MIN_USAGE_WINDOW:
        return starting_on
    return _format_rfc3339(end - MIN_USAGE_WINDOW)


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
    return _format_rfc3339(_align_to_utc_midnight(start))


@frozen
class MetronomeWalkStart:
    """Where one walk of an endpoint begins: the request window, and the cursor to resume from."""

    starting_on: str | None = None
    ending_before: str | None = None
    paginator_state: dict[str, Any] | None = None
    parent_cursor: str | None = None
    completed_customers: tuple[str, ...] = ()


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
    parent_cursor: str | None = None
    completed_customers: tuple[str, ...] = ()

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
            if resume_config.next_page:
                paginator_state = {"cursor": resume_config.next_page}
            parent_cursor = resume_config.parent_cursor
            completed_customers = tuple(resume_config.completed_customers or ())
            ending_before = resume_config.ending_before
            starting_on = resume_config.starting_on

    if config.window_size is not None:
        if ending_before is None:
            ending_before = _format_rfc3339(_usage_window_end(datetime.now(UTC)))
        if starting_on is None:
            # Only a freshly resolved start is clamped. A resumed walk replays the exact window its
            # checkpoint stored, and both bounds come back together or neither does.
            starting_on = _clamp_window_start(
                _resolve_window_start(config, db_incremental_field_last_value, history_start), ending_before
            )

    return MetronomeWalkStart(
        starting_on=starting_on,
        ending_before=ending_before,
        paginator_state=paginator_state,
        parent_cursor=parent_cursor,
        completed_customers=completed_customers,
    )


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
    params: dict[str, Any] = {}
    if config.paginated and config.accepts_page_size:
        params["limit"] = config.page_size
    params.update(config.extra_params)
    return params


def _retry_after_seconds(response: Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        # The header may carry an HTTP date instead. The pacer's own hold covers that.
        return None


class _PacedSession:
    """Fronts a tracked session, taking a pacer slot before every request it sends.

    `RESTClient` drives pagination itself, so pacing at the call site would only space the first
    request of a walk. Sitting in front of `send` puts a slot before every page, and reports a 429
    so the whole pool backs off rather than the one thread that met it.

    `RESTClient` reads `headers` and calls `prepare_request` and `send`, which is what this
    forwards. The wrapped session keeps its tracked adapters, credential redaction and its refusal
    to follow redirects, because every request still goes out through it.
    """

    def __init__(self, session: Session, pacer: RequestPacer) -> None:
        self._session = session
        self._pacer = pacer

    @property
    def headers(self) -> Any:
        return self._session.headers

    def prepare_request(self, request: Request) -> PreparedRequest:
        return self._session.prepare_request(request)

    def send(self, request: PreparedRequest, **kwargs: Any) -> Response:
        self._pacer.wait_turn()
        response = self._session.send(request, **kwargs)
        if response.status_code == 429:
            self._pacer.throttled(_retry_after_seconds(response))
        return response


def _paced_session(api_key: str, pacer: RequestPacer) -> Session:
    session = make_tracked_session(redact_values=(api_key,), capture=False, allow_redirects=False)
    # Not a `Session` subclass: a tracked session is built by a factory, and subclassing it would
    # mean rebuilding the adapters this needs to keep.
    return cast(Session, _PacedSession(session, pacer))


class _PacedClients:
    """One client per worker thread, all sharing one pacer.

    Every thread needs its own `requests.Session`, which is not documented as thread-safe, but the
    budget being protected is the customer's single Metronome account, so the pacer is shared.
    """

    def __init__(self, api_key: str, pacer: RequestPacer) -> None:
        self._api_key = api_key
        self._pacer = pacer
        self._local = threading.local()

    def get(self) -> RESTClient:
        client: Optional[RESTClient] = getattr(self._local, "client", None)
        if client is None:
            config = _rest_api_client_config(self._api_key)
            client = RESTClient(
                base_url=config["base_url"],
                headers=config["headers"],
                auth=create_auth(config["auth"]),
                session=_paced_session(self._api_key, self._pacer),
                allowed_hosts=config["allowed_hosts"],
                allow_redirects=config["allow_redirects"],
                request_timeout=config["request_timeout"],
            )
            self._local.client = client
        return client


def _customer_id(row: dict[str, Any]) -> str:
    """The id that partitions one customer's usage walk.

    A customer that cannot be asked for has to fail the sync. Skipping it would drop that
    customer's usage from the table with no signal, and a usage table that is quietly short is
    worse than one that stops and says why. A missing key raises on its own; a null or empty id
    needs saying, because `str(None)` would otherwise ask Metronome for a customer called "None".
    """
    customer_id = row["id"]
    if customer_id is None or customer_id == "":
        raise ValueError("Metronome returned a customer with no id, so its usage cannot be read")
    return str(customer_id)


class _WalkCancelled(Exception):
    """The consumer went away while this customer was still being walked.

    Raised rather than returning the rows gathered so far, because the checkpoint records whole
    customers: a partial one must never be mistakable for a finished one.
    """


def _usage_rows_for_customer(
    client: RESTClient,
    config: MetronomeEndpointConfig,
    json_body: dict[str, Any],
    customer_id: str,
    cancelled: threading.Event,
) -> list[Any]:
    """Every usage row one customer has in the requested window.

    `_float_usage_value` is applied here because this path builds its own requests rather than going
    through the resource's `data_map`.

    `cancel_futures` only drops walks that never started, so a walk already running checks between
    pages for itself. Otherwise it keeps spending the account's request budget after the consumer
    has gone, and the pool's threads hold up the process on their way out.

    The rows are gathered whole rather than streamed, because the checkpoint records whole
    customers and a partial one must never be mistakable for a finished one. That is bounded rather
    than open ended: one customer holds the periods in the requested window multiplied by the
    account's billable metrics, the window is capped by the source's history setting, and only as
    many of these exist at once as there are workers. Streaming within a customer would need a
    per-customer resume cursor, which is a larger change than the size of this buffer justifies.
    """
    rows: list[Any] = []
    for page in client.paginate(
        config.path,
        method=config.method,
        params=_list_params(config),
        json={**json_body, "customer_ids": [customer_id]},
        data_selector=DATA_SELECTOR,
        data_selector_required=True,
        paginator=_paginator_for(config),
    ):
        rows.extend(_float_usage_value(row) for row in page)
        if cancelled.is_set():
            raise _WalkCancelled(customer_id)
    return rows


def _fill_in_flight(
    submit: Callable[[str], "Future[list[Any]]"],
    todo: deque[str],
    in_flight: deque[tuple[str, "Future[list[Any]]"]],
) -> None:
    """Keep as many walks in flight as there are workers, and no more.

    Submitting a whole customer page at once would leave every finished customer's rows in memory
    behind a slow one, which is how a batch gets past the row cap.
    """
    while todo and len(in_flight) < USAGE_CUSTOMER_CONCURRENCY:
        customer_id = todo.popleft()
        in_flight.append((customer_id, submit(customer_id)))


def _parallel_usage_pages(
    clients: _PacedClients,
    config: MetronomeEndpointConfig,
    json_body: dict[str, Any],
    walk: "MetronomeWalkStart",
    commit_checkpoint: Callable[[Optional[str], tuple[str, ...]], None],
) -> Iterator[list[Any]]:
    """Walk each customer's usage separately, several at a time, and yield whole customers.

    `customer_ids` makes each customer's walk independent, which is the only parallelism this
    endpoint allows: its cursor is one opaque chain per customer and billable metric, so the next
    cursor is unknowable until the previous page returns.

    A batch carries only customers whose walk finished, and its checkpoint is committed after the
    `yield` returns, once the consumer has written the batch. So the recorded set never runs ahead
    of rows that reached Delta, and a resumed attempt re-walks only customers that wrote nothing.
    That is what lets a full refresh resume here without duplicating rows.
    """
    parent = METRONOME_ENDPOINTS["customers"]
    paginator = _paginator_for(parent)
    if walk.parent_cursor:
        paginator.set_resume_state({"cursor": walk.parent_cursor})

    # `RESTClient.paginate` advances a deep copy of the paginator it is given, so the instance here
    # never moves. The cursor has to come back through the resume hook, which fires when the loop
    # asks for the page after the one it just handed over.
    next_page_cursor: Optional[str] = None

    def record_parent_cursor(state: Optional[dict[str, Any]]) -> None:
        nonlocal next_page_cursor
        next_page_cursor = (state or {}).get("cursor")

    page_cursor = walk.parent_cursor
    done_in_page = set(walk.completed_customers)
    pool = ThreadPoolExecutor(max_workers=USAGE_CUSTOMER_CONCURRENCY, thread_name_prefix="metronome-usage")

    cancelled = threading.Event()

    def submit_walk(customer_id: str) -> "Future[list[Any]]":
        return submit_with_context(
            pool, lambda: _usage_rows_for_customer(clients.get(), config, json_body, customer_id, cancelled)
        )

    try:
        for page_index, customer_page in enumerate(
            clients.get().paginate(
                parent.path,
                params=_list_params(parent),
                data_selector=DATA_SELECTOR,
                data_selector_required=True,
                paginator=paginator,
                resume_hook=record_parent_cursor,
            )
        ):
            if page_index:
                # The hook fired while this page was being fetched, so its cursor is only known now.
                page_cursor = next_page_cursor
                done_in_page = set()

            todo = deque(cid for row in customer_page if (cid := _customer_id(row)) not in done_in_page)
            in_flight: deque[tuple[str, Future[list[Any]]]] = deque()
            _fill_in_flight(submit_walk, todo, in_flight)
            batch: list[Any] = []
            batch_customers: list[str] = []
            while in_flight:
                customer_id, future = in_flight.popleft()
                batch.extend(future.result())
                batch_customers.append(customer_id)
                _fill_in_flight(submit_walk, todo, in_flight)
                if len(batch) >= USAGE_COALESCE_ROWS or len(batch_customers) >= USAGE_CUSTOMERS_PER_BATCH:
                    yield batch
                    done_in_page.update(batch_customers)
                    commit_checkpoint(page_cursor, tuple(done_in_page))
                    batch, batch_customers = [], []

            if batch:
                yield batch
                done_in_page.update(batch_customers)
                commit_checkpoint(page_cursor, tuple(done_in_page))
    finally:
        # The consumer may close the generator early. Signal first so a walk already running stops
        # at its next page, then never block on the ones still in flight.
        cancelled.set()
        pool.shutdown(wait=False, cancel_futures=True)


def _float_usage_value(row: dict[str, Any]) -> dict[str, Any]:
    """Give the usage amount a floating point type before the column is inferred from it.

    Metronome returns `value` as a bare JSON number, so an account whose first batch holds whole
    numbers infers an integer column, and the first fractional amount after that no longer fits
    the stored type. That failure is not retryable and turns the schema off.

    A null means no usage matched the period, which is not the same as zero, so it stays null.
    """
    value = row.get("value")
    if isinstance(value, int) and not isinstance(value, bool):
        row["value"] = float(value)
    return row


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
            # `starting_on` at the epoch means "all usage the account has". The caller pins both
            # bounds for the whole walk so a resumed attempt replays the same window, and these
            # fall back only for a one-shot build with no pinned window.
            # The spec's enum accepts three casings, but both vendor SDKs emit upper case only.
            json_body["window_size"] = config.window_size.upper()
            json_body["starting_on"] = window_starting_on if window_starting_on is not None else EPOCH_RFC_3339
            json_body["ending_before"] = (
                window_ending_before
                if window_ending_before is not None
                else _format_rfc3339(_usage_window_end(datetime.now(UTC)))
            )
        endpoint_config["json"] = json_body

    incremental = _incremental_window(config, incremental_field_name or config.default_incremental_field or "")
    if should_use_incremental_field and incremental is not None:
        endpoint_config["incremental"] = cast(IncrementalConfig, incremental)

    # A bucketed usage table syncs incrementally with no framework-injected param: its window lives
    # in the request body, which `_incremental_window` cannot reach. So the write disposition
    # follows the endpoint declaring a cursor field rather than the injected param.
    syncs_incrementally = should_use_incremental_field and bool(config.incremental_fields)

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if syncs_incrementally else "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }
    if config.window_size is not None:
        resource["data_map"] = _float_usage_value
    return resource


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

    # A usage walk pages per customer and billable metric, so one sequential pass is one request
    # per page for the whole account. Partition it by customer and run several walks at once.
    if endpoint_config.window_size is not None:
        usage_resource = cast(
            dict[str, Any],
            get_resource(
                endpoint, should_use_incremental_field, incremental_field, walk.ending_before, walk.starting_on
            ),
        )
        json_body = cast(dict[str, Any], usage_resource["endpoint"]).get("json", {})
        clients = _PacedClients(
            api_key, RequestPacer(USAGE_REQUESTS_PER_SECOND, hold_seconds=USAGE_RATE_LIMIT_HOLD_SECONDS)
        )

        def commit_usage_checkpoint(parent_cursor: Optional[str], completed: tuple[str, ...]) -> None:
            # Nothing to resume to once the customer list is exhausted and its last page is written.
            if resumable_source_manager is None or (parent_cursor is None and not completed):
                return
            resumable_source_manager.save_state(
                MetronomeResumeConfig(
                    ending_before=walk.ending_before,
                    starting_on=walk.starting_on,
                    parent_cursor=parent_cursor,
                    completed_customers=completed,
                )
            )

        return _make_source_response(
            endpoint_config,
            lambda: _parallel_usage_pages(clients, endpoint_config, json_body, walk, commit_usage_checkpoint),
            chunk_size=1,
        )

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

        def persist(state: Optional[dict[str, Any]]) -> None:
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

        resume_hook = persist

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=resume_hook,
        initial_paginator_state=walk.paginator_state,
    )
    # `rest_client` fires the resume hook after the `yield` it belongs to, so the consumer has
    # already taken a yielded item by the time the cursor past it is offered. chunk_size=1 turns
    # that into a durability rule: one yielded item is one flush, so a page reaches Delta before its
    # cursor is checkpointed, and a mid-sync worker shutdown resumes at the page it stopped on
    # rather than past it. The fan-out tables above don't resume, so they keep the default.
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
