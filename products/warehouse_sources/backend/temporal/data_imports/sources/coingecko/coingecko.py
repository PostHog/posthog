import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from requests import Response
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.sources.coingecko.settings import (
    CHART_WINDOW_DAYS,
    COINGECKO_ENDPOINTS,
    DEFAULT_HISTORY_DAYS,
    EXCHANGE_RATES_ENDPOINT,
    GLOBAL_CHART_DAYS_OPTIONS,
    GLOBAL_MARKET_CAP_CHART_ENDPOINT,
    MARKET_CHART_ENDPOINT,
    MAX_COINS,
    MINIMUM_START_DATE,
    OHLC_ENDPOINT,
    CoinGeckoEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    RESTClient,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.config_setup import (
    create_auth,
    create_response_hooks,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    ResponseAction,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Two distinct hosts: the free Demo plan (and keyless public access) live on api.coingecko.com,
# paid Pro plans on pro-api.coingecko.com. The plan also selects which API-key header to send.
DEMO_BASE_URL = "https://api.coingecko.com/api/v3"
PRO_BASE_URL = "https://pro-api.coingecko.com/api/v3"

PLAN_DEMO = "demo"
PLAN_PRO = "pro"

# /coins/markets allows up to 250 per page; other paginated endpoints accept it too.
PAGE_SIZE = 250
MAX_RETRY_ATTEMPTS = 6
# Per-request (connect, read) ceiling. Left unset, a server that accepts the connection and then
# never answers holds an import worker open for the whole run. The per-coin endpoints issue one
# request per coin per page or per window, so one stalled request blocks every coin behind it.
REQUEST_TIMEOUT_SECONDS = 60

NO_COINS_ERROR = "No coin IDs configured"

# CoinGecko signals rate limiting via a 429 status (retried by the client on status alone) and, on the
# keyless/demo tier, via a 200/4xx body carrying ``{"status":{"error_code":429}}``. The client only
# retries on 429/5xx status, so classify that in-body envelope as retryable by content substring. Both
# whitespace variants are matched so the classification survives a compact- vs spaced-JSON server, the
# same way the old structural ``status.error_code == 429`` check was whitespace-agnostic.
RATE_LIMIT_BODY_MARKERS = ('"error_code":429', '"error_code": 429')

_RATE_LIMIT_RESPONSE_ACTIONS: list[ResponseAction] = [
    {"content": marker, "action": "retry"} for marker in RATE_LIMIT_BODY_MARKERS
]

# Column each of the three parallel series in a market chart response lands in.
_MARKET_CHART_SERIES = {"prices": "price", "market_caps": "market_cap", "total_volumes": "total_volume"}

# The global market cap chart answers with two parallel series already named as we want the columns.
_GLOBAL_CHART_SERIES = {"market_cap": "market_cap", "volume": "volume"}

_OHLC_COLUMNS = ("open", "high", "low", "close")


@dataclasses.dataclass(frozen=True)
class CoinGeckoResumeConfig:
    # Next page to fetch for paginated endpoints. Unused for single-response reference endpoints.
    page: int = 1
    # Index into the configured coin list of the coin the fan-out resumes at. Only the paginated
    # per-coin endpoints checkpoint mid-list; the timeseries endpoints resume whole windows.
    coin_index: int = 0
    # ISO date (YYYY-MM-DD) of the first day the next window should fetch, for the timeseries
    # endpoints. None for the endpoints that fetch no date range.
    next_start: str | None = None


def _base_url(plan: str) -> str:
    return PRO_BASE_URL if plan == PLAN_PRO else DEMO_BASE_URL


def _api_key_header(plan: str) -> str:
    return "x-cg-pro-api-key" if plan == PLAN_PRO else "x-cg-demo-api-key"


def _headers(plan: str, api_key: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if api_key:
        headers[_api_key_header(plan)] = api_key
    return headers


def _client_config(plan: str, api_key: str) -> ClientConfig:
    return {
        "base_url": _base_url(plan),
        # Only non-secret headers here; the API key rides in the framework auth config so its
        # value is redacted from logs and raised error messages.
        "headers": {"Accept": "application/json"},
        "auth": {
            "type": "api_key",
            "api_key": api_key,
            "name": _api_key_header(plan),
            "location": "header",
        },
        "max_retries": MAX_RETRY_ATTEMPTS,
        "request_timeout": REQUEST_TIMEOUT_SECONDS,
    }


def _rest_client(plan: str, api_key: str) -> RESTClient:
    """Client for the per-coin endpoints, whose fan-out over the configured coin list can't be
    expressed declaratively. Read off the same config as the declarative path so the two can't
    drift apart."""
    config = _client_config(plan, api_key)
    return RESTClient(
        base_url=config["base_url"],
        headers=config["headers"],
        auth=create_auth(config["auth"]),
        max_retry_attempts=config["max_retries"],
        request_timeout=config["request_timeout"],
    )


class CoinGeckoPagePaginator(PageNumberPaginator):
    """CoinGecko paginates with ``page``/``per_page``. A short page (fewer than ``per_page`` items) or
    an empty page is the last one — stop without paying an extra empty-page request, since the free
    tier's tight rate limits make sparing that request worthwhile. Resume replays the last full page
    (merge dedupes on the primary key).

    ``max_pages`` caps the page number for endpoints the API refuses to page past (e.g. /insights
    rejects page > 20); the base class stops once the next page would exceed it."""

    def __init__(self, page_size: int, max_pages: Optional[int] = None) -> None:
        super().__init__(base_page=1, page_param="page", maximum_page=max_pages)
        self._page_size = page_size

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._has_next_page and data is not None and len(data) < self._page_size:
            self._has_next_page = False


def _parse_coin_ids(coin_ids: Optional[str]) -> list[str]:
    if not coin_ids:
        return []
    # Split one part further than the cap so the MAX_COINS check downstream can still see that the
    # list overflowed, while a pathological string can never materialize more than that many parts.
    coins: list[str] = []
    seen: set[str] = set()
    for raw in coin_ids.split(",", MAX_COINS + 1)[: MAX_COINS + 1]:
        coin = raw.strip().lower()
        if coin and coin not in seen:
            seen.add(coin)
            coins.append(coin)
    return coins


def _coins_for_fanout(coin_ids: Optional[str], logger: FilteringBoundLogger) -> list[str]:
    coins = _parse_coin_ids(coin_ids)
    if not coins:
        raise ValueError(NO_COINS_ERROR)
    if len(coins) > MAX_COINS:
        logger.warning(f"CoinGecko: more than {MAX_COINS} coin IDs configured, syncing only the first {MAX_COINS}")
        coins = coins[:MAX_COINS]
    return coins


def _coerce_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def default_start_date() -> date:
    return datetime.now(UTC).date() - timedelta(days=DEFAULT_HISTORY_DAYS)


def start_date_error(start_date: Optional[str]) -> Optional[str]:
    """Validation-time check for an unusable `start_date`.

    A value earlier than `MINIMUM_START_DATE` is rejected here (credential validation) so a new
    source can't be configured to run away, and re-checked in `_chart_pages` so a previously stored
    configuration can't either. A value that doesn't parse is rejected too, because the sync falls
    back to the default window and would otherwise sync a different range than the one asked for.
    """
    if not start_date or not start_date.strip():
        return None

    parsed = _coerce_date(start_date)
    if parsed is None:
        return f"Couldn't read '{start_date}' as a date. Use the format YYYY-MM-DD, for example 2025-01-01."
    if parsed < MINIMUM_START_DATE:
        return f"CoinGecko has no data before {MINIMUM_START_DATE.isoformat()}. Enter that date or a later one."
    return None


def _from_millis(value: Any) -> Optional[datetime]:
    """Chart timestamps arrive as UNIX milliseconds. A non-numeric value means the point isn't
    usable as a cursor or a key, so callers drop it rather than writing a column of mixed types."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def _ticker_row(row: dict[str, Any], coin_id: str) -> dict[str, Any]:
    """Pin the queried coin onto the row and lift the exchange id out of the nested ``market``
    object, so every part of the primary key is a flat, always-present column."""
    ticker = dict(row)
    ticker["coin_id"] = coin_id
    market = ticker.get("market")
    ticker["market_identifier"] = market.get("identifier") if isinstance(market, dict) else None
    return ticker


def _single_object_body(page: list[Any], expected: str) -> dict[str, Any]:
    """These endpoints answer with a single object, which the client hands over as a one-item page.
    Anything else is a changed response shape rather than a row."""
    if len(page) == 1 and isinstance(page[0], dict):
        return page[0]
    raise ValueError(f"Required {expected}. The API response shape may have changed.")


def _zip_series(body: dict[str, Any], series: dict[str, str], base: dict[str, Any]) -> list[dict[str, Any]]:
    """Zip parallel ``[timestamp, value]`` series into one row per timestamp, ordered ascending."""
    rows: dict[datetime, dict[str, Any]] = {}
    for key, column in series.items():
        for point in body.get(key) or []:
            if not isinstance(point, list) or len(point) < 2:
                continue
            timestamp = _from_millis(point[0])
            if timestamp is None:
                continue
            rows.setdefault(timestamp, {**base, "timestamp": timestamp})[column] = point[1]
    return [rows[timestamp] for timestamp in sorted(rows)]


def _market_chart_rows(page: list[Any], coin_id: str) -> list[dict[str, Any]]:
    body = _single_object_body(page, "a market chart object carrying price, market cap and volume series")
    return _zip_series(body, _MARKET_CHART_SERIES, {"coin_id": coin_id})


def _global_market_cap_chart_rows(page: list[Any]) -> list[dict[str, Any]]:
    body = _single_object_body(page, "a global market cap chart object carrying market cap and volume series")
    return _zip_series(body, _GLOBAL_CHART_SERIES, {})


def _exchange_rate_rows(page: list[Any]) -> list[dict[str, Any]]:
    """Flatten the ``rates`` object, which is keyed by currency code rather than being a row list,
    into a row per currency with the code as its id."""
    body = _single_object_body(page, "an exchange rates object keyed by currency code")
    return [{"id": code, **rate} for code, rate in body.items() if isinstance(rate, dict)]


def _global_chart_days(should_use_incremental_field: bool, db_incremental_field_last_value: Any) -> str:
    """Pick the smallest `days` window that still covers everything since the watermark.

    The endpoint takes no from/to range, so the window is how far back an incremental run reads.
    The day holding the watermark is re-read rather than skipped: it was still moving when it first
    landed, and merge dedupes the overlap.
    """
    last_value = _coerce_date(db_incremental_field_last_value) if should_use_incremental_field else None
    if last_value is None:
        return "max"

    days_since = (datetime.now(UTC).date() - last_value).days + 1
    for option in GLOBAL_CHART_DAYS_OPTIONS:
        if option != "max" and days_since <= int(option):
            return option
    return "max"


def _ohlc_rows(page: list[Any], coin_id: str) -> list[dict[str, Any]]:
    """Map each ``[timestamp, open, high, low, close]`` candle onto a row.

    ``/coins/{id}/ohlc/range`` answers with a bare array of candles, which is the page itself."""
    rows: list[dict[str, Any]] = []
    for candle in page:
        if not isinstance(candle, list) or len(candle) < 5:
            continue
        timestamp = _from_millis(candle[0])
        if timestamp is None:
            continue
        rows.append({"coin_id": coin_id, "timestamp": timestamp, **dict(zip(_OHLC_COLUMNS, candle[1:5]))})
    return rows


_CHART_ROW_BUILDERS: dict[str, Callable[[list[Any], str], list[dict[str, Any]]]] = {
    MARKET_CHART_ENDPOINT: _market_chart_rows,
    OHLC_ENDPOINT: _ohlc_rows,
}

# Top-level endpoints whose body is a single object rather than a row list, keyed to the builder
# that reshapes it. Membership also routes them away from the declarative top-level path.
_TOP_LEVEL_ROW_BUILDERS: dict[str, Callable[[list[Any]], list[dict[str, Any]]]] = {
    GLOBAL_MARKET_CAP_CHART_ENDPOINT: _global_market_cap_chart_rows,
    EXCHANGE_RATES_ENDPOINT: _exchange_rate_rows,
}


def _ticker_pages(
    client: RESTClient,
    config: CoinGeckoEndpointConfig,
    coins: list[str],
    resumable_source_manager: ResumableSourceManager[CoinGeckoResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    hooks = create_response_hooks(_RATE_LIMIT_RESPONSE_ACTIONS, resource_name=config.name)
    page_size = config.page_size or PAGE_SIZE
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_index = resume.coin_index if resume is not None else 0

    for index in range(start_index, len(coins)):
        coin_id = coins[index]
        initial_paginator_state = {"page": resume.page} if resume is not None and index == start_index else None

        def save_checkpoint(state: Optional[dict[str, Any]], coin_index: int = index) -> None:
            # Persist AFTER a page is yielded so a crash re-yields the last page rather than
            # skipping it. No next page means this coin is done, so the checkpoint moves on.
            if state and state.get("page") is not None:
                resumable_source_manager.save_state(
                    CoinGeckoResumeConfig(page=int(state["page"]), coin_index=coin_index)
                )
            else:
                resumable_source_manager.save_state(CoinGeckoResumeConfig(coin_index=coin_index + 1))

        for page in client.paginate(
            path=config.path.format(coin_id=coin_id),
            # The endpoint takes no per_page parameter, because its page size is fixed at 100,
            # which only feeds the paginator's short-page check.
            params=dict(config.extra_params),
            paginator=CoinGeckoPagePaginator(page_size, config.max_pages),
            data_selector=config.data_selector,
            data_selector_required=True,
            hooks=hooks,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        ):
            yield [_ticker_row(row, coin_id) for row in page]


def _fetch_single_page(
    client: RESTClient,
    path: str,
    params: dict[str, Any],
    data_selector: Optional[str],
    hooks: Optional[dict[str, Any]],
    data_selector_required: bool = False,
) -> list[Any]:
    # One request, so the paginator yields at most one page. Walked with a loop rather than next():
    # a StopIteration escaping into the calling generator surfaces as a RuntimeError.
    for page in client.paginate(
        path=path,
        params=params,
        paginator=SinglePagePaginator(),
        data_selector=data_selector,
        data_selector_required=data_selector_required,
        hooks=hooks,
    ):
        return page
    return []


def _chart_pages(
    client: RESTClient,
    config: CoinGeckoEndpointConfig,
    coins: list[str],
    start_date: Optional[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinGeckoResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    hooks = create_response_hooks(_RATE_LIMIT_RESPONSE_ACTIONS, resource_name=config.name)
    build_rows = _CHART_ROW_BUILDERS[config.name]
    window_days = config.window_days or CHART_WINDOW_DAYS

    # Re-checked here (not just at credential validation) so a configuration stored before this
    # floor existed can't schedule a runaway backfill either.
    base_start = max(_coerce_date(start_date) or default_start_date(), MINIMUM_START_DATE)
    if should_use_incremental_field:
        last_value = _coerce_date(db_incremental_field_last_value)
        if last_value is not None:
            # Start at the last synced day rather than the day after: that day was still moving
            # when it first landed, so re-reading it restates it and merge dedupes the overlap.
            base_start = max(base_start, last_value)

    end_boundary = datetime.now(UTC).date()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = base_start
    if resume is not None:
        resumed_start = _coerce_date(resume.next_start)
        if resumed_start is not None:
            cursor = resumed_start
            logger.debug(f"CoinGecko: resuming {config.name} from {cursor.isoformat()}")

    while cursor <= end_boundary:
        window_end = min(cursor + timedelta(days=window_days - 1), end_boundary)
        params: dict[str, Any] = {**config.extra_params, "from": cursor.isoformat(), "to": window_end.isoformat()}

        # One batch per window, holding every coin's rows for it. The pipeline commits the
        # incremental watermark to the highest timestamp it has seen after each batch, so a batch
        # must never carry one coin past a window another coin has not been fetched for: the next
        # job starts from that watermark and would skip the coin left behind. Whole windows keep
        # the watermark behind every coin, and make `sort_mode="asc"` true batch over batch.
        # A window is one daily point per coin per day, so it stays small enough to hold.
        window_rows: list[dict[str, Any]] = []
        for coin_id in coins:
            page = _fetch_single_page(client, config.path.format(coin_id=coin_id), params, config.data_selector, hooks)
            window_rows.extend(build_rows(page, coin_id))

        if window_rows:
            yield window_rows

        cursor = window_end + timedelta(days=1)
        # Saved AFTER yielding so a crash re-fetches the last window (merge dedupes it) instead of
        # skipping it.
        resumable_source_manager.save_state(CoinGeckoResumeConfig(next_start=cursor.isoformat()))


def _per_coin_source(
    plan: str,
    api_key: str,
    config: CoinGeckoEndpointConfig,
    coin_ids: Optional[str],
    start_date: Optional[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinGeckoResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    client = _rest_client(plan, api_key)

    if config.date_field is None:
        return SourceResponse(
            name=config.name,
            items=lambda: _ticker_pages(
                client=client,
                config=config,
                coins=_coins_for_fanout(coin_ids, logger),
                resumable_source_manager=resumable_source_manager,
            ),
            primary_keys=config.primary_keys,
            # A market-pair snapshot carries no stable created_at to partition on.
            partition_count=None,
            partition_size=None,
        )

    return SourceResponse(
        name=config.name,
        items=lambda: _chart_pages(
            client=client,
            config=config,
            coins=_coins_for_fanout(coin_ids, logger),
            start_date=start_date,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.date_field],
        sort_mode="asc",
    )


def _reshaped_pages(
    client: RESTClient,
    config: CoinGeckoEndpointConfig,
    params: dict[str, Any],
    build_rows: Callable[[list[Any]], list[dict[str, Any]]],
) -> Iterator[list[dict[str, Any]]]:
    hooks = create_response_hooks(_RATE_LIMIT_RESPONSE_ACTIONS, resource_name=config.name)
    page = _fetch_single_page(client, config.path, params, config.data_selector, hooks, data_selector_required=True)
    rows = build_rows(page)
    if rows:
        yield rows


def _reshaped_top_level_source(
    plan: str,
    api_key: str,
    config: CoinGeckoEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    client = _rest_client(plan, api_key)
    build_rows = _TOP_LEVEL_ROW_BUILDERS[config.name]
    params: dict[str, Any] = dict(config.extra_params)

    if config.date_field is None:
        return SourceResponse(
            name=config.name,
            items=lambda: _reshaped_pages(client, config, params, build_rows),
            primary_keys=config.primary_keys,
            # A rate snapshot carries no stable created_at to partition on.
            partition_count=None,
            partition_size=None,
        )

    # The endpoint takes a relative `days` window instead of a from/to range, so an incremental run
    # narrows that window rather than moving a cursor.
    params["days"] = _global_chart_days(should_use_incremental_field, db_incremental_field_last_value)
    return SourceResponse(
        name=config.name,
        items=lambda: _reshaped_pages(client, config, params, build_rows),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.date_field],
        sort_mode="asc",
    )


def _top_level_source(
    plan: str,
    api_key: str,
    config: CoinGeckoEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[CoinGeckoResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    page_size = config.page_size or PAGE_SIZE
    params: dict[str, Any] = dict(config.extra_params)
    if config.paginated:
        params["per_page"] = page_size

    rest_config: RESTAPIConfig = {
        "client": _client_config(plan, api_key),
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Bare-array bodies, or the rows under the endpoint's envelope key. A body that
                    # carries neither means the response shape changed (or an unexpected error
                    # envelope) — fail loud rather than syncing a garbage row.
                    "data_selector": config.data_selector,
                    "data_selector_required": True,
                    "paginator": CoinGeckoPagePaginator(page_size, config.max_pages)
                    if config.paginated
                    else SinglePagePaginator(),
                    # The keyless/demo tier reports rate limiting inside a success-status body; the
                    # client retries on status only, so promote that in-body signal to a retry.
                    "response_actions": _RATE_LIMIT_RESPONSE_ACTIONS,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(CoinGeckoResumeConfig(page=int(state["page"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Snapshot/reference endpoints expose no stable created_at, so there's nothing to partition on.
        partition_count=None,
        partition_size=None,
        column_hints=resource.column_hints,
    )


def coingecko_source(
    plan: str,
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CoinGeckoResumeConfig],
    coin_ids: Optional[str] = None,
    start_date: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = COINGECKO_ENDPOINTS[endpoint]

    if config.name in _TOP_LEVEL_ROW_BUILDERS:
        return _reshaped_top_level_source(
            plan=plan,
            api_key=api_key,
            config=config,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    if config.per_coin:
        return _per_coin_source(
            plan=plan,
            api_key=api_key,
            config=config,
            coin_ids=coin_ids,
            start_date=start_date,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )

    return _top_level_source(
        plan=plan,
        api_key=api_key,
        config=config,
        team_id=team_id,
        job_id=job_id,
        resumable_source_manager=resumable_source_manager,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


def validate_credentials(plan: str, api_key: str) -> bool:
    """Confirm the key is genuine by pinging with the plan's auth header. A valid key returns 200;
    an invalid one returns 401. Transient/network failures also map to False (not validated)."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,) if api_key else ()),
        f"{_base_url(plan)}/ping",
        headers=_headers(plan, api_key),
    )
    return ok
