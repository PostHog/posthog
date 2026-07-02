import re
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.settings import (
    ALPHA_VANTAGE_ENDPOINTS,
    AlphaVantageEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"

# The connector issues one outbound request per symbol for every selected table, so an unbounded
# symbol list lets a saved config fan out into arbitrarily many requests/retries per scheduled sync.
# Cap the distinct-symbol count to keep worker time and third-party quota bounded.
MAX_SYMBOLS = 100

# Strips the ordinal prefix Alpha Vantage puts on time-series/quote keys (e.g. "1. open" -> "open",
# "07. latest trading day" -> "latest trading day").
_ORDINAL_PREFIX = re.compile(r"^\d+\.\s*")


class AlphaVantageRetryableError(Exception):
    pass


class AlphaVantageAPIError(Exception):
    pass


def _normalize_key(key: str) -> str:
    """Turn an Alpha Vantage response key into a snake_case column name.

    e.g. "07. latest trading day" -> "latest_trading_day", "1. open" -> "open".
    """
    stripped = _ORDINAL_PREFIX.sub("", key).strip()
    return stripped.replace(" ", "_").lower()


@retry(
    retry=retry_if_exception_type((AlphaVantageRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    # Alpha Vantage's free per-minute throttle resets on a ~60s window, so back off long enough to
    # clear it before the last attempt.
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch(session: requests.Session, params: dict[str, Any], logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise AlphaVantageRetryableError(f"Alpha Vantage API error (retryable): status={response.status_code}")

    if not response.ok:
        # Don't use raise_for_status(): response.url carries the apikey query param, and the raised
        # message is later logged via str(error) outside the tracked session's redaction.
        kind = "Client Error" if response.status_code < 500 else "Server Error"
        safe_url = response.url.split("?", 1)[0]
        raise requests.HTTPError(
            f"{response.status_code} {kind}: {response.reason} for url: {safe_url}", response=response
        )

    body = response.json()
    if not isinstance(body, dict):
        raise AlphaVantageAPIError("Alpha Vantage API error [unexpected_response]: response was not a JSON object")

    # Alpha Vantage signals problems with HTTP 200 and a body-level message rather than a status code:
    #   "Note"        -> per-minute rate limit; transient, so retry with backoff.
    #   "Information"  -> daily quota exhausted, premium-only dataset, or the shared demo key; permanent.
    #   "Error Message"-> missing/invalid apikey or an unrecognized function/symbol; permanent.
    if "Note" in body:
        raise AlphaVantageRetryableError(f"Alpha Vantage API error (retryable) [rate_limit]: {body['Note']}")
    if "Information" in body:
        raise AlphaVantageAPIError(f"Alpha Vantage API error [rate_limit_or_premium]: {body['Information']}")

    return body


def _parse_time_series(body: dict[str, Any], symbol: str) -> Iterator[dict[str, Any]]:
    # The label of the series block varies per function ("Time Series (Daily)", "Weekly Time Series",
    # ...), so pick the first non-metadata block whose value is a dict of date -> OHLCV.
    series = next(
        (value for key, value in body.items() if key != "Meta Data" and isinstance(value, dict)),
        None,
    )
    if series is None:
        return
    for date_str, values in series.items():
        if not isinstance(values, dict):
            continue
        row: dict[str, Any] = {"symbol": symbol, "date": date_str}
        for key, value in values.items():
            row[_normalize_key(key)] = value
        yield row


def _parse_quote(body: dict[str, Any], symbol: str) -> Iterator[dict[str, Any]]:
    quote = body.get("Global Quote")
    if not isinstance(quote, dict) or not quote:
        return
    row: dict[str, Any] = {"symbol": symbol}
    for key, value in quote.items():
        row[_normalize_key(key)] = value
    yield row


def _parse_overview(body: dict[str, Any], symbol: str) -> Iterator[dict[str, Any]]:
    # OVERVIEW is already a flat object; an empty {} means "no fundamentals for this symbol".
    if not any(key for key in body if key != "Meta Data"):
        return
    # Normalize the PascalCase response keys (e.g. "PERatio", "MarketCapitalization") the same way as
    # every other parser, and let the injected snake_case `symbol` override the response's own
    # "Symbol" key so the table has a single primary-key column rather than a Symbol/symbol pair.
    row: dict[str, Any] = {_normalize_key(key): value for key, value in body.items()}
    row["symbol"] = symbol
    yield row


def _parse_reports(body: dict[str, Any], symbol: str) -> Iterator[dict[str, Any]]:
    for report_type, block_key in (("annual", "annualReports"), ("quarterly", "quarterlyReports")):
        reports = body.get(block_key)
        if not isinstance(reports, list):
            continue
        for report in reports:
            if isinstance(report, dict):
                # Access the primary-key field directly so a missing fiscalDateEnding raises instead of
                # silently yielding a row without its key.
                yield {
                    "symbol": symbol,
                    "report_type": report_type,
                    "fiscalDateEnding": report["fiscalDateEnding"],
                    **report,
                }


def _parse_earnings(body: dict[str, Any], symbol: str) -> Iterator[dict[str, Any]]:
    for report_type, block_key in (("annual", "annualEarnings"), ("quarterly", "quarterlyEarnings")):
        reports = body.get(block_key)
        if not isinstance(reports, list):
            continue
        for report in reports:
            if isinstance(report, dict):
                # Access the primary-key field directly so a missing fiscalDateEnding raises instead of
                # silently yielding a row without its key.
                yield {
                    "symbol": symbol,
                    "report_type": report_type,
                    "fiscalDateEnding": report["fiscalDateEnding"],
                    **report,
                }


_PARSERS = {
    "time_series": _parse_time_series,
    "quote": _parse_quote,
    "overview": _parse_overview,
    "reports": _parse_reports,
    "earnings": _parse_earnings,
}


def parse_symbols(symbols: str) -> list[str]:
    """Split the user's comma-separated symbols field into a de-duplicated, upper-cased list."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in symbols.split(","):
        symbol = raw.strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            result.append(symbol)
    return result


def validate_symbols(symbols: str) -> tuple[list[str], str | None]:
    """Parse and bound the symbols field. Returns the parsed list plus a user-facing error, if any.

    Enforces both a lower bound (at least one symbol) and an upper bound (MAX_SYMBOLS distinct
    symbols) so neither an empty config nor an oversized one that fans out into runaway syncs can be
    saved or run.
    """
    parsed = parse_symbols(symbols)
    if not parsed:
        return parsed, "Enter at least one symbol (e.g. IBM, AAPL)"
    if len(parsed) > MAX_SYMBOLS:
        return parsed, f"Too many symbols ({len(parsed)}); enter at most {MAX_SYMBOLS} distinct symbols."
    return parsed, None


def _request_params(config: AlphaVantageEndpointConfig, symbol: str, api_key: str) -> dict[str, Any]:
    params: dict[str, Any] = {"function": config.function, "symbol": symbol, "apikey": api_key}
    # Time-series functions default to the latest 100 points; ask for the full history for a warehouse.
    if config.kind == "time_series":
        params["outputsize"] = "full"
    return params


def get_rows(
    api_key: str,
    symbols: list[str],
    endpoint: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = ALPHA_VANTAGE_ENDPOINTS[endpoint]
    parser = _PARSERS[config.kind]
    # apikey rides as a query param on every request, so mask its value from logged URLs and samples.
    session = make_tracked_session(redact_values=(api_key,))

    # One request per symbol (no pagination); yield each symbol's rows as a list and let the pipeline
    # batch. A symbol's full time series is bounded (~20 years), so it comfortably fits in memory.
    for symbol in symbols:
        # A permanent quota/premium error (AlphaVantageAPIError) or transport failure (HTTPError)
        # affects every symbol equally, so let it propagate and fail the whole sync rather than
        # syncing a partial set of symbols.
        body = _fetch(session, _request_params(config, symbol, api_key), logger)

        if "Error Message" in body:
            # Scoped to one symbol (unknown ticker / unsupported for this function). Skip it so one bad
            # symbol doesn't fail the whole sync; the rest of the configured symbols still sync.
            logger.warning(f"Alpha Vantage: skipping symbol {symbol} for {endpoint}: {body['Error Message']}")
            continue

        rows = list(parser(body, symbol))
        if rows:
            yield rows


def alpha_vantage_source(
    api_key: str,
    symbols: list[str],
    endpoint: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = ALPHA_VANTAGE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, symbols=symbols, endpoint=endpoint, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is usable by issuing one cheap probe request.

    Note: Alpha Vantage does not strictly verify free-tier keys on many endpoints (a syntactically
    valid but unregistered key still returns data), so this mainly confirms the key is present and the
    API is reachable and not returning a missing-key / quota envelope.
    """
    if not api_key.strip():
        return False

    params = {"function": "GLOBAL_QUOTE", "symbol": "IBM", "apikey": api_key}
    try:
        session = make_tracked_session(redact_values=(api_key,))
        response = session.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=10)
    except Exception:
        return False

    if response.status_code != 200:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    if not isinstance(body, dict):
        return False

    # "Error Message" -> missing/invalid apikey; "Information" -> quota exhausted / demo key.
    return "Error Message" not in body and "Information" not in body
