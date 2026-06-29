from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.finnhub.settings import (
    FINNHUB_ENDPOINTS,
    FinnhubEndpointConfig,
)

FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
DEFAULT_EXCHANGE = "US"
MARKET_NEWS_CATEGORY = "general"
REQUEST_TIMEOUT_SECONDS = 60


class FinnhubRetryableError(Exception):
    """Raised for 429 / 5xx responses so tenacity backs off and retries."""


def _headers(api_key: str) -> dict[str, str]:
    return {"X-Finnhub-Token": api_key, "Accept": "application/json"}


def _parse_symbols(symbols: str | None) -> list[str]:
    if not symbols:
        return []
    # Accept comma, whitespace, or newline separated tickers; normalize to upper-case and dedupe
    # while preserving order so fan-out is deterministic.
    raw = symbols.replace("\n", ",").replace(" ", ",").split(",")
    seen: set[str] = set()
    out: list[str] = []
    for token in raw:
        ticker = token.strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def _to_date(value: Any) -> date:
    """Coerce a stored incremental cursor (epoch seconds, datetime, date, or ISO string) to a date."""
    if isinstance(value, datetime):
        return value.astimezone(UTC).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC).date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
    raise ValueError(f"Cannot coerce incremental value {value!r} to a date")


@retry(
    retry=retry_if_exception_type((FinnhubRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(6),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch(session: requests.Session, path: str, params: dict[str, Any], logger: FilteringBoundLogger) -> Any:
    response = session.get(f"{FINNHUB_BASE_URL}{path}", params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # Finnhub returns 429 once the per-minute / per-second rate limit is hit; back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise FinnhubRetryableError(f"Finnhub API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Finnhub API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    return response.json()


def _extract_rows(data: Any, config: FinnhubEndpointConfig) -> list[dict[str, Any]]:
    """Normalize a Finnhub response into a list of row dicts per the endpoint's shape."""
    if config.single_object:
        # Snapshot endpoints (quote/profile/metric) return a single object. Finnhub returns an
        # empty object for an unknown symbol, which we skip.
        return [data] if isinstance(data, dict) and data else []
    if config.data_key:
        rows = data.get(config.data_key) if isinstance(data, dict) else None
        return rows or []
    return data if isinstance(data, list) else []


def _window(config: FinnhubEndpointConfig, last_value: Any) -> tuple[str, str]:
    today = datetime.now(UTC).date()
    if last_value is not None:
        start = _to_date(last_value)
    else:
        start = today - timedelta(days=config.lookback_days)
    end = today + timedelta(days=config.forward_days)
    return start.isoformat(), end.isoformat()


def _request_params(
    config: FinnhubEndpointConfig,
    symbol: str | None,
    exchange: str,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if symbol is not None:
        params["symbol"] = symbol
    if config.name == "stock_symbols":
        params["exchange"] = exchange or DEFAULT_EXCHANGE
    if config.name == "market_news":
        params["category"] = MARKET_NEWS_CATEGORY
    if config.name == "basic_financials":
        params["metric"] = "all"
    if config.windowed:
        # Incremental endpoints advance `from` to the saved watermark; windowed full-refresh
        # endpoints (calendars) always sweep the full rolling window.
        last_value = db_incremental_field_last_value if should_use_incremental_field else None
        params["from"], params["to"] = _window(config, last_value)
    return params


def _emit(rows: list[dict[str, Any]], symbol: str | None, config: FinnhubEndpointConfig) -> list[dict[str, Any]]:
    if symbol is not None:
        # Inject the requested ticker: several per-symbol endpoints (quote, company-news) omit it,
        # and it's part of those tables' primary keys.
        for row in rows:
            row["symbol"] = symbol
    if config.name == "company_news":
        # Guarantee ascending order so the declared `sort_mode="asc"` matches the data the
        # incremental watermark is checkpointed against, regardless of the API's response order.
        rows.sort(key=lambda r: r.get("datetime") or 0)
    return rows


def get_rows(
    api_key: str,
    endpoint: str,
    symbols: str | None,
    exchange: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = FINNHUB_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    if config.requires_symbol:
        tickers = _parse_symbols(symbols)
        if not tickers:
            logger.warning(
                f"Finnhub: endpoint '{endpoint}' needs symbols but none are configured; nothing to sync. "
                "Add tickers to the source's Symbols field."
            )
            return
        for ticker in tickers:
            params = _request_params(
                config, ticker, exchange, should_use_incremental_field, db_incremental_field_last_value
            )
            rows = _extract_rows(_fetch(session, config.path, params, logger), config)
            if rows:
                yield _emit(rows, ticker, config)
        return

    params = _request_params(config, None, exchange, should_use_incremental_field, db_incremental_field_last_value)
    rows = _extract_rows(_fetch(session, config.path, params, logger), config)
    if rows:
        yield _emit(rows, None, config)


def finnhub_source(
    api_key: str,
    endpoint: str,
    symbols: str | None,
    exchange: str,
    logger: FilteringBoundLogger,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FINNHUB_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            symbols=symbols,
            exchange=exchange,
            logger=logger,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )


def validate_credentials(api_key: str, schema_name: str | None = None) -> tuple[bool, str | None]:
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        # `/quote` is a cheap, free-tier endpoint — enough to prove the token is genuine.
        response = session.get(f"{FINNHUB_BASE_URL}/quote", params={"symbol": "AAPL"}, timeout=10)
    except Exception:
        return False, "Could not connect to Finnhub to validate the API key"

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Finnhub API key"
    if response.status_code == 403:
        # A genuine token whose plan tier doesn't cover this resource. Accept at source-create
        # (schema_name is None) so users can still connect for the endpoints they do have; only
        # report it as a problem when validating a specific schema.
        if schema_name is None:
            return True, None
        return False, "Your Finnhub plan does not include access to this data"
    return False, f"Finnhub credential check failed (HTTP {response.status_code})"
