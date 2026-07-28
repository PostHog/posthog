import re
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.simfin.settings import (
    SIMFIN_ENDPOINTS,
    SimFinEndpointConfig,
)

SIMFIN_BASE_URL = "https://backend.simfin.com/api"

REQUEST_TIMEOUT_SECONDS = 60

# The connector issues one outbound request per ticker for every selected table, so an unbounded
# ticker list lets a saved config fan out into arbitrarily many requests per scheduled sync. Cap the
# distinct-ticker count to keep worker time and third-party quota bounded.
MAX_TICKERS = 100

# Company-level fields SimFin wraps around each ticker-scoped compact payload; injected into every
# reshaped row so child rows are self-describing.
_COMPANY_FIELDS = ("id", "name", "ticker", "currency", "isin")


class SimFinAPIError(Exception):
    pass


def _normalize_column_name(name: str) -> str:
    """Turn a SimFin compact column label into a snake_case column name.

    e.g. "Fiscal Year" -> "fiscal_year", "Adjusted Closing Price" -> "adjusted_closing_price".
    """
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def parse_tickers(tickers: str) -> list[str]:
    """Split the user's comma-separated tickers field into a de-duplicated, upper-cased list."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in tickers.split(","):
        ticker = raw.strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            result.append(ticker)
    return result


def validate_tickers(tickers: str) -> tuple[list[str], str | None]:
    """Parse and bound the tickers field. Returns the parsed list plus a user-facing error, if any."""
    parsed = parse_tickers(tickers)
    if not parsed:
        return parsed, "Enter at least one ticker (e.g. AAPL, MSFT)"
    if len(parsed) > MAX_TICKERS:
        return parsed, f"Too many tickers ({len(parsed)}); enter at most {MAX_TICKERS} distinct tickers."
    return parsed, None


def _make_session(api_key: str) -> requests.Session:
    # The key rides in the Authorization header on every request; mask its literal value from logged
    # URLs, headers, and captured samples.
    return make_tracked_session(
        headers={"Authorization": f"api-key {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
    )


def _fetch_json(session: requests.Session, url: str, params: dict[str, Any]) -> Any:
    # The tracked session already retries 429/5xx with backoff, so a non-ok status here is final.
    # The URL carries no secrets (auth is a header), so raise_for_status' message is safe to log.
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _zip_rows(columns: list[Any], data: list[Any], normalize: bool = True) -> Iterator[dict[str, Any]]:
    names = [_normalize_column_name(str(column)) if normalize else str(column) for column in columns]
    for row in data:
        if isinstance(row, list):
            yield dict(zip(names, row))


def _parse_companies(body: Any, ticker: Optional[str]) -> Iterator[dict[str, Any]]:
    # /companies/list returns a flat array of company objects with machine-friendly keys.
    if not isinstance(body, list):
        raise SimFinAPIError("SimFin API error [unexpected_response]: expected a JSON array of companies")
    for company in body:
        if isinstance(company, dict):
            yield company


def _parse_company_details(body: Any, ticker: Optional[str]) -> Iterator[dict[str, Any]]:
    # /companies/general/compact returns a single columnar object: {"columns": [...], "data": [[...]]}.
    # Its column names are already camelCase identifiers matching /companies/list, so keep them as-is.
    if not isinstance(body, dict):
        raise SimFinAPIError("SimFin API error [unexpected_response]: expected a columnar JSON object")
    yield from _zip_rows(body.get("columns") or [], body.get("data") or [], normalize=False)


def _parse_statements(body: Any, ticker: Optional[str]) -> Iterator[dict[str, Any]]:
    # /companies/statements/compact returns one item per company, each wrapping per-statement
    # columnar blocks: [{"id": ..., "ticker": ..., "statements": [{"statement", "columns", "data"}]}].
    if not isinstance(body, list):
        raise SimFinAPIError("SimFin API error [unexpected_response]: expected a JSON array of statement items")
    for item in body:
        if not isinstance(item, dict):
            continue
        company = {field: item.get(field) for field in _COMPANY_FIELDS}
        for statement in item.get("statements") or []:
            if not isinstance(statement, dict):
                continue
            for row in _zip_rows(statement.get("columns") or [], statement.get("data") or []):
                yield {**company, **row}


def _parse_prices(body: Any, ticker: Optional[str]) -> Iterator[dict[str, Any]]:
    # /companies/prices/compact returns one columnar item per company:
    # [{"id": ..., "ticker": ..., "columns": [...], "data": [[...], ...]}].
    if not isinstance(body, list):
        raise SimFinAPIError("SimFin API error [unexpected_response]: expected a JSON array of price items")
    for item in body:
        if not isinstance(item, dict):
            continue
        company = {field: item.get(field) for field in _COMPANY_FIELDS}
        for row in _zip_rows(item.get("columns") or [], item.get("data") or []):
            yield {**company, **row}


# The shares-outstanding endpoints return positional arrays without column headers. Field order is
# undocumented but stable, matching SimFin's official API clients.
_COMMON_SHARES_COLUMNS = ["id", "date", "common_shares_outstanding"]
_WEIGHTED_SHARES_COLUMNS = [
    "id",
    "date",
    "fiscal_year",
    "period",
    "basic_shares_outstanding",
    "diluted_shares_outstanding",
]


def _parse_common_shares(body: Any, ticker: Optional[str]) -> Iterator[dict[str, Any]]:
    if not isinstance(body, list):
        raise SimFinAPIError("SimFin API error [unexpected_response]: expected a JSON array of share rows")
    yield from _zip_rows(_COMMON_SHARES_COLUMNS, body, normalize=False)


def _parse_weighted_shares(body: Any, ticker: Optional[str]) -> Iterator[dict[str, Any]]:
    if not isinstance(body, list):
        raise SimFinAPIError("SimFin API error [unexpected_response]: expected a JSON array of share rows")
    yield from _zip_rows(_WEIGHTED_SHARES_COLUMNS, body, normalize=False)


_PARSERS = {
    "companies": _parse_companies,
    "company_details": _parse_company_details,
    "statements": _parse_statements,
    "prices": _parse_prices,
    "common_shares": _parse_common_shares,
    "weighted_shares": _parse_weighted_shares,
}


def _endpoint_url(config: SimFinEndpointConfig, api_version: str) -> str:
    return f"{SIMFIN_BASE_URL}/{api_version}/{config.path}"


def get_rows(
    api_key: str,
    tickers: list[str],
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = SIMFIN_ENDPOINTS[endpoint]
    parser = _PARSERS[config.kind]
    session = _make_session(api_key)
    url = _endpoint_url(config, api_version)

    if not config.fan_out_tickers:
        rows = list(parser(_fetch_json(session, url, dict(config.params or {})), None))
        if rows:
            yield rows
        return

    # One request per ticker (no pagination); a single ticker's full history is bounded (a few
    # thousand statement rows, ~10k daily price rows), so each response comfortably fits in memory
    # and the pipeline batches downstream. Per-ticker requests also stay within the request shape
    # every SimFin plan tier allows.
    for ticker in tickers:
        params = dict(config.params or {})
        params["ticker"] = ticker
        rows = list(parser(_fetch_json(session, url, params), ticker))
        if rows:
            yield rows
        else:
            # An unknown ticker or a dataset outside the account's plan comes back empty rather than
            # as an error; skip it so the rest of the configured tickers still sync.
            logger.warning(f"SimFin: no rows returned for ticker {ticker} on {endpoint}")


def simfin_source(
    api_key: str,
    tickers: list[str],
    endpoint: str,
    api_version: str,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = SIMFIN_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key, tickers=tickers, endpoint=endpoint, api_version=api_version, logger=logger
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str, api_version: str) -> bool:
    """Confirm the API key is genuine with one cheap probe request.

    Uses the company-details endpoint scoped to a single well-known ticker so the probe stays small;
    an invalid or unconfirmed key returns 401.
    """
    if not api_key.strip():
        return False

    session = _make_session(api_key)
    url = _endpoint_url(SIMFIN_ENDPOINTS["company_details"], api_version)
    try:
        response = session.get(url, params={"ticker": "AAPL"}, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False

    return response.status_code == 200
