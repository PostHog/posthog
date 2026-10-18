from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import RESTClient
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import Endpoint
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.kalshi.settings import (
    KALSHI_ENDPOINTS,
    WEATHER_INDEX_CITIES,
    KalshiEndpointConfig,
)

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

CANDLESTICK_PERIOD_MINUTES = 1440
_CANDLESTICK_PERIOD_SECONDS = CANDLESTICK_PERIOD_MINUTES * 60
# The batch candlestick endpoint takes at most 100 tickers and returns at most 10,000 candlesticks
# per request, with no pagination, so a batch that could exceed the cap is split before it is sent.
_MAX_TICKERS_PER_REQUEST = 100
_MAX_CANDLESTICKS_PER_REQUEST = 10_000

# `from=0` reads as unset and falls back to the trailing 24 hours, so a full read starts at 1 ms.
_WEATHER_INDEX_EARLIEST_MS = 1
# Re-read the last hour so a minute published after the previous run's watermark is not skipped.
_WEATHER_INDEX_OVERLAP_MS = 60 * 60 * 1000


@frozen
class KalshiResumeConfig:
    # Opaque pagination cursor from the previous response's `cursor` field.
    cursor: str


def _to_epoch_seconds(value: Any) -> Optional[int]:
    """Kalshi's `min_ts` filter wants the cutoff as integer seconds since epoch."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day, tzinfo=UTC).timestamp())
    if isinstance(value, int | float):
        return int(value)
    try:
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


@frozen
class _CandlestickMarket:
    ticker: str
    start_ts: int
    end_ts: int

    @property
    def expected_candlesticks(self) -> int:
        # One candlestick per period, plus the partial periods at each end of the window.
        return (self.end_ts - self.start_ts) // _CANDLESTICK_PERIOD_SECONDS + 2


def _candlestick_market(market: dict[str, Any], window_start: Optional[int], now: int) -> Optional[_CandlestickMarket]:
    ticker = market.get("ticker")
    opened = _to_epoch_seconds(market.get("open_time"))
    if not ticker or opened is None:
        return None
    start = opened if window_start is None else max(opened, window_start)
    closed = _to_epoch_seconds(market.get("close_time"))
    end = now if closed is None else min(closed, now)
    if start >= end:
        return None
    return _CandlestickMarket(ticker=str(ticker), start_ts=start, end_ts=end)


def _batch_markets(markets: Iterable[_CandlestickMarket]) -> Iterator[list[_CandlestickMarket]]:
    batch: list[_CandlestickMarket] = []
    expected = 0
    for market in markets:
        cost = market.expected_candlesticks
        if batch and (len(batch) >= _MAX_TICKERS_PER_REQUEST or expected + cost > _MAX_CANDLESTICKS_PER_REQUEST):
            yield batch
            batch, expected = [], 0
        batch.append(market)
        expected += cost
    if batch:
        yield batch


def _fetch_candlesticks(client: RESTClient, batch: list[_CandlestickMarket], now: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in client.paginate(
        path="/markets/candlesticks",
        params={
            "market_tickers": ",".join(market.ticker for market in batch),
            "start_ts": min(market.start_ts for market in batch),
            "end_ts": now,
            "period_interval": CANDLESTICK_PERIOD_MINUTES,
        },
        paginator=SinglePagePaginator(),
        data_selector="markets",
        data_selector_required=True,
    ):
        for market in page:
            for candlestick in market.get("candlesticks") or []:
                rows.append({"market_ticker": market.get("market_ticker"), **candlestick})
    return rows


def _candlestick_rows(
    client: RESTClient,
    resumable_source_manager: ResumableSourceManager[KalshiResumeConfig],
    window_start: Optional[int],
    now: int,
) -> Iterator[list[dict[str, Any]]]:
    params: dict[str, Any] = {"limit": 1000, "mve_filter": "exclude"}
    if window_start is not None:
        # A market that closed before the window has no candlesticks in it.
        params["min_close_ts"] = window_start

    page_cursor: Optional[str] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            page_cursor = resume.cursor

    next_cursor: list[Optional[str]] = [None]

    def remember_next_cursor(state: Optional[dict[str, Any]], has_next_page: bool) -> None:
        next_cursor[0] = str(state["cursor"]) if has_next_page and state and state.get("cursor") else None

    for markets in client.paginate(
        path="/markets",
        params=params,
        paginator=JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor"),
        data_selector="markets",
        data_selector_required=True,
        initial_paginator_state={"cursor": page_cursor} if page_cursor else None,
        page_state_hook=remember_next_cursor,
    ):
        # Every row of the earlier market pages is already yielded, so resuming from the cursor that
        # fetched this page loses nothing.
        if page_cursor:
            resumable_source_manager.save_state(KalshiResumeConfig(cursor=page_cursor))
        resumable_source_manager.safe_point()

        candidates = (_candlestick_market(market, window_start, now) for market in markets)
        pending = list(_batch_markets(market for market in candidates if market is not None))
        pending.reverse()
        while pending:
            batch = pending.pop()
            rows = _fetch_candlesticks(client, batch, now)
            if len(rows) >= _MAX_CANDLESTICKS_PER_REQUEST and len(batch) > 1:
                # The response may be truncated at the cap; refetch the batch in halves.
                middle = len(batch) // 2
                pending.extend([batch[middle:], batch[:middle]])
                resumable_source_manager.safe_point()
                continue
            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()

        page_cursor = next_cursor[0]


def _candlestick_source(
    config: KalshiEndpointConfig,
    resumable_source_manager: ResumableSourceManager[KalshiResumeConfig],
    last_value: Optional[Any],
) -> SourceResponse:
    client = RESTClient(base_url=KALSHI_BASE_URL, headers={"Accept": "application/json"})
    last_period_end = _to_epoch_seconds(last_value)
    # Start one period back so the latest, possibly partial, candlestick is fetched again.
    window_start = None if last_period_end is None else last_period_end - _CANDLESTICK_PERIOD_SECONDS
    now = int(datetime.now(UTC).timestamp())

    return SourceResponse(
        name=config.name,
        items=lambda: _candlestick_rows(client, resumable_source_manager, window_start, now),
        primary_keys=config.primary_keys,
        # Rows arrive grouped by market, not by time, so the watermark can only advance once the
        # walk completes.
        sort_mode="desc",
    )


def _weather_index_rows(
    client: RESTClient,
    resumable_source_manager: ResumableSourceManager[KalshiResumeConfig],
    from_ms: int,
    to_ms: int,
) -> Iterator[list[dict[str, Any]]]:
    cities = list(WEATHER_INDEX_CITIES)
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor in cities:
            cities = cities[cities.index(resume.cursor) :]

    for position, city in enumerate(cities):
        rows: list[dict[str, Any]] = []
        for page in client.paginate(
            path=f"/live_data/weather/{city}",
            params={"from": from_ms, "to": to_ms},
            paginator=SinglePagePaginator(),
            data_selector="timeseries",
            data_selector_required=True,
        ):
            rows.extend({"city": city, **point} for point in page)
        if position + 1 < len(cities):
            # The cursor names the next city to read, so a resume skips the cities already yielded.
            resumable_source_manager.save_state(KalshiResumeConfig(cursor=cities[position + 1]))
        if rows:
            yield rows
        else:
            resumable_source_manager.safe_point()


def _weather_index_source(
    config: KalshiEndpointConfig,
    resumable_source_manager: ResumableSourceManager[KalshiResumeConfig],
    last_value: Optional[Any],
) -> SourceResponse:
    client = RESTClient(base_url=KALSHI_BASE_URL, headers={"Accept": "application/json"})
    from_ms = _WEATHER_INDEX_EARLIEST_MS
    if last_value is not None:
        from_ms = max(int(last_value) - _WEATHER_INDEX_OVERLAP_MS, _WEATHER_INDEX_EARLIEST_MS)
    to_ms = int(datetime.now(UTC).timestamp() * 1000)

    return SourceResponse(
        name=config.name,
        items=lambda: _weather_index_rows(client, resumable_source_manager, from_ms, to_ms),
        primary_keys=config.primary_keys,
        # Rows arrive grouped by city, not by time, so the watermark can only advance once the
        # walk completes.
        sort_mode="desc",
    )


def _build_endpoint(config: KalshiEndpointConfig, should_use_incremental_field: bool) -> Endpoint:
    endpoint: Endpoint = {
        "path": config.path,
        "data_selector": config.data_key,
        # A missing wrapper key means the response shape changed; fail loud rather than syncing 0 rows.
        "data_selector_required": True,
    }

    if config.paginated:
        endpoint["params"] = {"limit": config.page_size}
        # Kalshi pages with an opaque `cursor` echoed at the response root, and omits it on the
        # last page. The paginator implements resume state, so a heartbeat timeout picks up mid-walk.
        endpoint["paginator"] = JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor")
    else:
        endpoint["paginator"] = SinglePagePaginator()

    if config.supports_incremental and should_use_incremental_field:
        endpoint["incremental"] = {
            "start_param": "min_ts",
            "cursor_path": "created_time",
            "convert": _to_epoch_seconds,
        }

    return endpoint


def kalshi_source(
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[KalshiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = KALSHI_ENDPOINTS[endpoint]
    last_value = db_incremental_field_last_value if should_use_incremental_field else None

    if config.market_fan_out:
        return _candlestick_source(config, resumable_source_manager, last_value)

    if config.city_fan_out:
        return _weather_index_source(config, resumable_source_manager, last_value)

    # Kalshi's market-data endpoints are public and take no credential, so no `auth` is configured.
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": KALSHI_BASE_URL,
            "headers": {"Accept": "application/json"},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": _build_endpoint(config, should_use_incremental_field),
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save after a page is yielded so a crash re-yields the last page (merge dedupes on the
        # primary key) instead of skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(KalshiResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Trades arrive strictly newest-first and the API offers no ascending option, so the
        # watermark can only advance once the walk completes.
        sort_mode="desc" if config.newest_first else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="day" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials() -> bool:
    # Nothing to authenticate; confirm the public API is reachable and answering so a source is
    # never created against an endpoint that has moved.
    ok, _status = validate_via_probe(
        make_tracked_session,
        f"{KALSHI_BASE_URL}/exchange/status",
        headers={"Accept": "application/json"},
    )
    return ok
