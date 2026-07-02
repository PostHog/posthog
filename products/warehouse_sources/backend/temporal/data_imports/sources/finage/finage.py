import re
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

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

# Each symbol costs one request per point-in-time sync and one 50k-row fetch per aggregate sync, so the
# list is a fan-out multiplier. Cap it so a member can't save thousands of symbols and blow up every sync.
MAX_SYMBOLS = 100
# US tickers are short and alphanumeric; dots/hyphens cover class shares (e.g. BRK.B, BF-B).
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,11}$")
# Finage's US stock history doesn't meaningfully predate this; a floor rejects typos and unbounded ranges.
MIN_START_DATE = "2000-01-01"


class FinageRetryableError(Exception):
    """Raised for 429 / 5xx so tenacity retries; terminal statuses (401/403/404) are not wrapped."""


class FinageConfigError(ValueError):
    """Raised when the user-supplied symbols / start_date fail validation."""


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


def validate_source_config(symbols: list[str], start_date: str) -> None:
    """Reject oversized symbol lists, malformed tickers, and out-of-range start dates before a sync runs.

    Each symbol fans out into its own Finage request (and, for aggregates, up to a 50k-row fetch), so an
    unbounded symbol list or a start date in the distant past is a resource-exhaustion vector. Raises
    `FinageConfigError` with a user-facing message on the first problem found.
    """
    if not symbols:
        raise FinageConfigError("Enter at least one stock symbol to sync.")
    if len(symbols) > MAX_SYMBOLS:
        raise FinageConfigError(
            f"Too many symbols ({len(symbols)}). Enter at most {MAX_SYMBOLS} comma-separated stock symbols."
        )
    invalid = [s for s in symbols if not SYMBOL_PATTERN.match(s)]
    if invalid:
        preview = ", ".join(invalid[:5])
        raise FinageConfigError(f"Invalid stock symbol(s): {preview}. Use US tickers like AAPL, MSFT, BRK.B.")

    try:
        parsed_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=UTC).date()
    except ValueError:
        raise FinageConfigError(f"Invalid backfill start date '{start_date}'. Use the format YYYY-MM-DD.")
    floor = datetime.strptime(MIN_START_DATE, "%Y-%m-%d").date()
    today = datetime.now(UTC).date()
    if parsed_start < floor:
        raise FinageConfigError(f"Backfill start date must be on or after {MIN_START_DATE}.")
    if parsed_start > today:
        raise FinageConfigError("Backfill start date can't be in the future.")


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

    # 401 (bad/missing key) and 403 (plan doesn't cover this data) are permanent — surface them as an
    # HTTPError so `get_non_retryable_errors` can match and stop the sync. The URL query carries the raw
    # apikey, so strip it: the default `raise_for_status` message embeds the full URL (credential and all)
    # into the exception, which is then written to error logs. Dropping the query keeps the matchable
    # `... for url: https://api.finage.co.uk/<path>` prefix without leaking the key.
    if response.status_code >= 400:
        safe_url = (response.url or "").split("?", 1)[0]
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {safe_url}",
            response=response,
        )

    return response.json()


def validate_credentials(api_key: str) -> int | None:
    """Probe a basic stock endpoint and return the HTTP status code (or None on a transport error).

    `/last/stock/AAPL` needs only a stocks subscription, so it's the cheapest genuine token check.
    """
    try:
        # Redact the key so the probe URL is never persisted raw in tracked logs / sample capture.
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{FINAGE_BASE_URL}/last/stock/AAPL", params={"apikey": api_key}, timeout=10
        )
        return response.status_code
    except Exception:
        return None


def _handle_symbol_http_error(exc: requests.HTTPError, logger: FilteringBoundLogger, what: str) -> None:
    """Re-raise auth/plan failures (401/403) to stop the whole sync; warn-and-skip any other per-symbol error."""
    status = exc.response.status_code if exc.response is not None else None
    if status in (401, 403):
        raise exc
    logger.warning(f"Finage: {what} failed (status={status}), skipping")


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
            _handle_symbol_http_error(exc, logger, f"{config.name} request for {symbol}")
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
            _handle_symbol_http_error(exc, logger, f"aggregates request for {symbol}")
            continue

        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            continue

        if len(results) >= AGG_LIMIT:
            logger.warning(f"Finage: aggregates for {symbol} hit the {AGG_LIMIT}-row limit; older bars truncated")

        response_symbol = data.get("symbol", symbol)
        rows = []
        for bar in results:
            # `t` is the primary/partition key. A missing key raises KeyError; a present-but-unparseable
            # value converts to None, which `datetime` partitioning would silently bucket into the fallback
            # 1970-01 partition. Reject both so corrupt upstream data fails fast instead of misbucketing.
            date = _ms_to_date(bar["t"])
            if date is None:
                raise ValueError(
                    f"Finage aggregates for {response_symbol} returned a bar with an invalid timestamp: {bar['t']!r}"
                )
            rows.append({**bar, "symbol": response_symbol, "date": date})
        yield rows


def get_rows(
    api_key: str,
    endpoint: str,
    symbols: list[str],
    start_date: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = FINAGE_ENDPOINTS[endpoint]
    # One session reused across every symbol so urllib3 keeps the connection alive. Redact the key
    # so the `apikey` query value is never persisted raw in tracked logs / sample capture. Disable the
    # adapter's default retry policy: `_fetch_json` already retries 429/5xx with tenacity, and stacking a
    # second urllib3 retry layer would multiply backoff and let long `Retry-After` waits bypass its cap.
    session = make_tracked_session(redact_values=(api_key,), retry=Retry(total=0))

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
