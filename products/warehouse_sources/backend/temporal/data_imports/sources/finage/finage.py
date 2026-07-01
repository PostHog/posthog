from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.finage.settings import (
    FINAGE_ENDPOINTS,
    FinageEndpointConfig,
)

FINAGE_BASE_URL = "https://api.finage.co.uk"

# Daily OHLCV bars are the canonical historical-price grain. Finer intervals (minute/hour) explode row
# counts and are better served by the WebSocket feed, so the aggregate window is fixed to daily here.
AGG_MULTIPLIER = 1
AGG_TIMESPAN = "day"
# Finage caps `limit` at 50000. A symbol can't accumulate that many daily bars (~200 years), so one
# request per symbol covers the whole window without pagination.
AGG_LIMIT = 50000
DEFAULT_START_DATE = "2020-01-01"

REQUEST_TIMEOUT_SECONDS = 60


class FinageRetryableError(Exception):
    """Raised for 429 / 5xx so tenacity retries; terminal statuses (401/403/404) are not wrapped."""


def parse_symbols(symbols: str) -> list[str]:
    """Split the user's comma-separated symbol field into a clean, de-duplicated, upper-cased list."""
    seen: set[str] = set()
    parsed: list[str] = []
    for raw in symbols.split(","):
        symbol = raw.strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            parsed.append(symbol)
    return parsed


def _ms_to_date(timestamp_ms: Any) -> str | None:
    """Convert a Finage millisecond epoch timestamp to an ISO date string for partitioning."""
    if timestamp_ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp_ms) / 1000, tz=UTC).date().isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


@retry(
    retry=retry_if_exception_type((FinageRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_json(
    session: requests.Session,
    path: str,
    api_key: str,
    logger: FilteringBoundLogger,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    request_params: dict[str, Any] = {"apikey": api_key, **(params or {})}
    url = f"{FINAGE_BASE_URL}{path}"
    response = session.get(url, params=request_params, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise FinageRetryableError(f"Finage API error (retryable): status={response.status_code}, path={path}")

    # 401 (bad/missing key) and 403 (plan doesn't cover this data) are permanent — surface them via
    # raise_for_status so `get_non_retryable_errors` can match and stop the sync.
    response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> int | None:
    """Probe a basic stock endpoint and return the HTTP status code (or None on a transport error).

    `/last/stock/AAPL` needs only a stocks subscription, so it's the cheapest genuine token check.
    """
    try:
        response = make_tracked_session().get(
            f"{FINAGE_BASE_URL}/last/stock/AAPL", params={"apikey": api_key}, timeout=10
        )
        return response.status_code
    except Exception:
        return None


def _iter_point_in_time_rows(
    session: requests.Session,
    api_key: str,
    symbols: list[str],
    config: FinageEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Yield the single current quote/trade object per symbol.

    A per-symbol error (unknown ticker, no data) is logged and skipped so one bad symbol doesn't fail
    the whole sync; auth/plan failures (401/403) propagate from `_fetch_json` and stop it.
    """
    for symbol in symbols:
        path = config.path.format(symbol=symbol)
        try:
            data = _fetch_json(session, path, api_key, logger)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (401, 403):
                raise
            logger.warning(f"Finage: {config.name} request failed for {symbol} (status={status}), skipping")
            continue

        if not isinstance(data, dict) or not data or data.get("error"):
            logger.warning(f"Finage: {config.name} returned no data for {symbol}, skipping")
            continue

        # The endpoint already returns `symbol`, but pin it from our request so the key is never empty.
        data.setdefault("symbol", symbol)
        yield [data]


def _iter_aggregate_rows(
    session: requests.Session,
    api_key: str,
    symbols: list[str],
    config: FinageEndpointConfig,
    start_date: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Yield historical OHLCV bars for each symbol over [start_date, today].

    Full refresh: the whole window is re-fetched every sync and de-duplicated on `[symbol, t]` at
    merge time. `sort=asc` matches `SourceResponse.sort_mode`.
    """
    to_date = _today()
    for symbol in symbols:
        path = config.path.format(
            symbol=symbol,
            multiplier=AGG_MULTIPLIER,
            timespan=AGG_TIMESPAN,
            from_date=start_date,
            to_date=to_date,
        )
        try:
            data = _fetch_json(session, path, api_key, logger, params={"limit": AGG_LIMIT, "sort": "asc"})
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (401, 403):
                raise
            logger.warning(f"Finage: aggregates request failed for {symbol} (status={status}), skipping")
            continue

        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            continue

        if len(results) >= AGG_LIMIT:
            logger.warning(f"Finage: aggregates for {symbol} hit the {AGG_LIMIT}-row limit; older bars truncated")

        response_symbol = data.get("symbol", symbol)
        rows = [{**bar, "symbol": response_symbol, "date": _ms_to_date(bar.get("t"))} for bar in results]
        yield rows


def get_rows(
    api_key: str,
    endpoint: str,
    symbols: list[str],
    start_date: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = FINAGE_ENDPOINTS[endpoint]
    # One session reused across every symbol so urllib3 keeps the connection alive.
    session = make_tracked_session()

    if config.is_aggregate:
        yield from _iter_aggregate_rows(session, api_key, symbols, config, start_date, logger)
    else:
        yield from _iter_point_in_time_rows(session, api_key, symbols, config, logger)


def finage_source(
    api_key: str,
    endpoint: str,
    symbols: list[str],
    start_date: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = FINAGE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            symbols=symbols,
            start_date=start_date,
            logger=logger,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
