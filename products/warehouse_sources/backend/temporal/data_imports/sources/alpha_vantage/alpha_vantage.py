import io
import re
import csv
import json
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.alpha_vantage.settings import (
    ALPHA_VANTAGE_ENDPOINTS,
    AlphaVantageEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.datetime_utils import parse_datetime_value
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"

# The connector issues one outbound request per symbol for every selected table, so an unbounded
# symbol list lets a saved config fan out into arbitrarily many requests/retries per scheduled sync.
# Cap the distinct-symbol count to keep worker time and third-party quota bounded.
MAX_SYMBOLS = 100

# Strips the ordinal prefix Alpha Vantage puts on time-series/quote keys (e.g. "1. open" -> "open",
# "07. latest trading day" -> "latest trading day").
_ORDINAL_PREFIX = re.compile(r"^\d+\.\s*")

# LISTING_STATUS covers the whole market in one call per state. Both states are synced: the table's
# value is asset-lifecycle and survivorship research, which needs the delisted side too.
LISTING_STATES = ("active", "delisted")

# The CSV functions return tens of thousands of rows in one body, so yield in chunks.
CSV_CHUNK_SIZE = 5000

# The widest horizon the function offers, for the same single request as the 3-month default.
EARNINGS_CALENDAR_HORIZON = "12month"

# NEWS_SENTIMENT has no cursor pagination; `limit` caps one response at 1000 articles. The page cap
# bounds the time-window walk in `_news_rows` over a symbol with a very deep archive.
NEWS_PAGE_LIMIT = 1000
NEWS_MAX_PAGES = 20

# `time_from` takes YYYYMMDDTHHMM, one granularity coarser than `time_published`.
_NEWS_MINUTE_LENGTH = len("YYYYMMDDTHHMM")

_CSV_ENVELOPE_KEYS = ("Information", "Error Message", "Note")

# Alpha Vantage writes an absent value as one of these placeholder strings rather than JSON null or an
# empty CSV cell (e.g. `delistingDate=null` on an active listing, `payment_date=None` on an old
# dividend), which would otherwise land in the warehouse as literal text in a date column.
_NULL_PLACEHOLDERS = frozenset({"none", "null", ""})


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


def _nullable(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() in _NULL_PLACEHOLDERS:
        return None
    return value


def _raise_for_status(response: requests.Response) -> None:
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


def _raise_for_envelope(body: dict[str, Any]) -> None:
    """Alpha Vantage signals problems with HTTP 200 and a body-level message rather than a status code.

    "Note"        -> per-minute rate limit; transient, so the caller retries with backoff.
    "Information" -> daily quota exhausted, premium-only dataset, or the shared demo key; permanent.

    "Error Message" (missing/invalid apikey, unrecognized function/symbol) is left to the caller,
    because for per-symbol functions it is scoped to the one symbol rather than the whole sync.
    """
    if "Note" in body:
        raise AlphaVantageRetryableError(f"Alpha Vantage API error (retryable) [rate_limit]: {body['Note']}")
    if "Information" in body:
        raise AlphaVantageAPIError(f"Alpha Vantage API error [rate_limit_or_premium]: {body['Information']}")


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
    _raise_for_status(response)

    body = response.json()
    if not isinstance(body, dict):
        raise AlphaVantageAPIError("Alpha Vantage API error [unexpected_response]: response was not a JSON object")

    _raise_for_envelope(body)
    return body


def _raise_for_csv_envelope(csv_text: str) -> None:
    """Detect a JSON error envelope that leaked into a CSV body one character per column.

    A refused CSV function answers with the normal header and then the envelope's key spread across
    the columns ("I,n,f,o,r,m,a" for "Information"), rather than with a JSON body. Only the key
    survives the vendor's truncation to the header's column count, so the check is a prefix match
    against the keys `_raise_for_envelope` handles, with the same split between the transient
    throttle and the permanent quota/premium refusal.
    """
    lines = csv_text.splitlines()
    if len(lines) < 2:
        return

    joined = lines[1].replace(",", "").strip()
    if not joined:
        return

    if "Note".startswith(joined):
        raise AlphaVantageRetryableError(f"Alpha Vantage API error (retryable) [rate_limit]: {joined}")
    if any(key.startswith(joined) for key in _CSV_ENVELOPE_KEYS):
        raise AlphaVantageAPIError(f"Alpha Vantage API error [rate_limit_or_premium]: {joined}")


@retry(
    retry=retry_if_exception_type((AlphaVantageRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_csv(session: requests.Session, params: dict[str, Any]) -> str | None:
    """Fetch a CSV-only function. Returns None when Alpha Vantage answered with JSON instead of a CSV body.

    LISTING_STATUS has no `datatype` param and always replies with CSV, but it still reports errors as
    a JSON envelope, so branch on the payload rather than on what was requested.
    """
    response = session.get(ALPHA_VANTAGE_BASE_URL, params=params, timeout=120)
    _raise_for_status(response)

    text = response.text
    if not text.lstrip().startswith("{"):
        _raise_for_csv_envelope(text)
        return text

    _raise_for_envelope(json.loads(text))
    return None


def _csv_row_chunks(csv_text: str) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        # DictReader parks any surplus cells under a None key, which has no column to land in.
        batch.append({key: _nullable(value) for key, value in row.items() if key is not None})
        if len(batch) >= CSV_CHUNK_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


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


def _parse_corporate_action(body: dict[str, Any], symbol: str) -> Iterator[dict[str, Any]]:
    # DIVIDENDS and SPLITS both answer with {"symbol": ..., "data": [{...}, ...]}.
    data = body.get("data")
    if not isinstance(data, list):
        return
    for entry in data:
        if not isinstance(entry, dict):
            continue
        row: dict[str, Any] = {key: _nullable(value) for key, value in entry.items()}
        # The entries are not symbol-tagged, so the requested symbol is the only source for the column.
        row["symbol"] = symbol
        yield row


def _parse_news(body: dict[str, Any], symbol: str) -> Iterator[dict[str, Any]]:
    feed = body.get("feed")
    if not isinstance(feed, list):
        return
    for article in feed:
        if not isinstance(article, dict):
            continue
        # `topics` and `ticker_sentiment` stay nested: the pipeline writes nested values as JSON
        # strings, which keeps the column type stable across syncs where an article carries none.
        yield {
            "symbol": symbol,
            "url": article["url"],
            **article,
        }


def _parse_insider(body: dict[str, Any], symbol: str) -> Iterator[dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, list):
        return
    for entry in data:
        if not isinstance(entry, dict):
            continue
        yield {
            **{key: _nullable(value) for key, value in entry.items()},
            "transaction_date": entry["transaction_date"],
            # The response tags each row with `ticker`; `symbol` is the column every other table in
            # this source joins on, so it is injected here too.
            "symbol": symbol,
        }


def _parse_institutional(body: dict[str, Any], symbol: str) -> Iterator[dict[str, Any]]:
    holdings = body.get("holdings")
    if not isinstance(holdings, list):
        return
    # One function means one table, so the symbol-level ownership totals ride on every holder row.
    totals = {key: _nullable(value) for key, value in body.items() if key not in ("holdings", "symbol")}
    for holding in holdings:
        if not isinstance(holding, dict):
            continue
        yield {
            **totals,
            **{key: _nullable(value) for key, value in holding.items()},
            "holder_name": holding["holder_name"],
            "symbol": symbol,
        }


def _listing_status_rows(
    session: requests.Session, api_key: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    for state in LISTING_STATES:
        params = {"function": "LISTING_STATUS", "state": state, "apikey": api_key}
        listing = _fetch_csv(session, params)
        if listing is None:
            # A key that is not entitled to a state gets an empty JSON object instead of a CSV body.
            # Skip it so the other state still syncs.
            logger.warning(f"Alpha Vantage: no listing returned for state={state}")
            continue

        yield from _csv_row_chunks(listing)


def _earnings_calendar_rows(
    session: requests.Session, api_key: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    params = {"function": "EARNINGS_CALENDAR", "horizon": EARNINGS_CALENDAR_HORIZON, "apikey": api_key}
    calendar = _fetch_csv(session, params)
    if calendar is None:
        logger.warning("Alpha Vantage: no earnings calendar returned")
        return

    yield from _csv_row_chunks(calendar)


def _news_rows(
    session: requests.Session,
    api_key: str,
    symbol: str,
    time_from: str | None,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    # Each page resumes from the minute the previous one ended on, so that minute's articles come back
    # twice. Track what this symbol already yielded so one batch sequence never carries a row twice.
    seen_urls: set[str] = set()

    for _ in range(NEWS_MAX_PAGES):
        params: dict[str, Any] = {
            "function": "NEWS_SENTIMENT",
            "tickers": symbol,
            "limit": NEWS_PAGE_LIMIT,
            # Oldest first, so the watermark advances monotonically and a full page can be resumed.
            "sort": "EARLIEST",
            "apikey": api_key,
        }
        if time_from:
            params["time_from"] = time_from

        body = _fetch(session, params, logger)
        if "Error Message" in body:
            # Scoped to this ticker, so the rest of the symbols still sync.
            logger.warning(f"Alpha Vantage: skipping symbol {symbol} for news_sentiment: {body['Error Message']}")
            return

        articles = list(_parse_news(body, symbol))
        rows = [article for article in articles if article["url"] not in seen_urls]
        seen_urls.update(article["url"] for article in rows)
        if rows:
            yield rows

        if len(articles) < NEWS_PAGE_LIMIT:
            return

        next_time_from = max((str(article.get("time_published") or "") for article in articles), default="")[
            :_NEWS_MINUTE_LENGTH
        ]
        if len(next_time_from) < _NEWS_MINUTE_LENGTH or next_time_from == time_from:
            # Nothing to advance to, so another request would repeat the page forever.
            logger.warning(f"Alpha Vantage: stopping news_sentiment walk for {symbol}; cursor did not advance")
            return
        time_from = next_time_from

    logger.warning(f"Alpha Vantage: hit the {NEWS_MAX_PAGES}-page cap for news_sentiment on {symbol}")


_PARSERS = {
    "time_series": _parse_time_series,
    "quote": _parse_quote,
    "overview": _parse_overview,
    "reports": _parse_reports,
    "earnings": _parse_earnings,
    "corporate_action": _parse_corporate_action,
    "insider": _parse_insider,
    "institutional": _parse_institutional,
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


def _request_params(
    config: AlphaVantageEndpointConfig,
    symbol: str,
    api_key: str,
    db_incremental_field_last_value: Any = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"function": config.function, "symbol": symbol, "apikey": api_key}
    # Time-series functions default to the latest 100 points; ask for the full history for a warehouse.
    if config.kind == "time_series":
        params["outputsize"] = "full"

    if config.kind == "insider":
        # INSIDER_TRANSACTIONS filters server-side on a whole-day `from` bound, so an incremental run
        # re-reads only the watermark day onwards; merge dedupes that day's overlap.
        since = parse_datetime_value(db_incremental_field_last_value)
        if since is not None:
            params["from"] = since.strftime("%Y-%m-%d")

    return params


def _news_time_from(db_incremental_field_last_value: Any) -> str | None:
    """Format an incremental watermark as the minute-granular value `time_from` accepts."""
    watermark = parse_datetime_value(db_incremental_field_last_value)
    if watermark is None:
        return None
    return watermark.strftime("%Y%m%dT%H%M")


def get_rows(
    api_key: str,
    symbols: list[str],
    endpoint: str,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = ALPHA_VANTAGE_ENDPOINTS[endpoint]
    # apikey rides as a query param on every request, so mask its value from logged URLs and samples.
    session = make_tracked_session(redact_values=(api_key,))

    if config.kind == "listing":
        # The whole market listing arrives in one call per state, so the configured symbols don't apply.
        yield from _listing_status_rows(session, api_key, logger)
        return

    if config.kind == "calendar":
        # The whole market's schedule arrives in one call, so the configured symbols don't apply either.
        yield from _earnings_calendar_rows(session, api_key, logger)
        return

    if config.kind == "news":
        time_from = _news_time_from(db_incremental_field_last_value)
        for symbol in symbols:
            yield from _news_rows(session, api_key, symbol, time_from, logger)
        return

    parser = _PARSERS[config.kind]

    # One request per symbol (no pagination); yield each symbol's rows as a list and let the pipeline
    # batch. A symbol's full time series is bounded (~20 years), so it comfortably fits in memory.
    for symbol in symbols:
        # A permanent quota/premium error (AlphaVantageAPIError) or transport failure (HTTPError)
        # affects every symbol equally, so let it propagate and fail the whole sync rather than
        # syncing a partial set of symbols.
        body = _fetch(session, _request_params(config, symbol, api_key, db_incremental_field_last_value), logger)

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
    db_incremental_field_last_value: Any = None,
) -> SourceResponse:
    config = ALPHA_VANTAGE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            symbols=symbols,
            endpoint=endpoint,
            logger=logger,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
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
