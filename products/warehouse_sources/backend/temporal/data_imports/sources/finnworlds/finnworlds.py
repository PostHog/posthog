import re
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.finnworlds.settings import (
    FINNWORLDS_ENDPOINTS,
    FinnworldsEndpointConfig,
    ResponseMode,
)

FINNWORLDS_BASE_URL = "https://api.finnworlds.com/api/v1"

# Finnworlds returns HTTP 200 even for an invalid key, signalling the failure only in the JSON body
# (e.g. {"error": "Invalid key"}). These substrings (lower-cased) mark a body-level error that retrying
# can never fix, so the sync fails fast via FinnworldsAuthError instead of treating the ticker as empty.
_AUTH_ERROR_MARKERS = ("invalid key", "forbidden", "unauthorized", "expired", "not authorized")

REQUEST_TIMEOUT_SECONDS = 60

# Every ticker costs one request per enabled ticker-backed table on each sync, so cap the list to bound
# the outbound fan-out (and the credit burn) a single config can trigger. 500 comfortably covers a large
# watchlist like the S&P 500 while rejecting paste-the-whole-exchange configs.
MAX_TICKERS = 500


class FinnworldsRetryableError(Exception):
    """A transient API error (429 / 5xx) worth retrying."""


class FinnworldsAuthError(Exception):
    """A permanent authentication/authorization failure — surfaced via get_non_retryable_errors."""


def parse_tickers(raw: str | None) -> list[str]:
    """Split the user's free-text ticker list into a clean, de-duplicated, upper-cased list.

    Accepts commas, whitespace, and newlines as separators so users can paste a watchlist in any
    common shape. Order is preserved (first occurrence wins) for stable, predictable sync output.

    Raises ``ValueError`` when more than ``MAX_TICKERS`` distinct symbols are supplied so an oversized
    config is rejected before the pipeline starts scheduling a request per ticker per table.
    """
    if not raw:
        return []
    tokens = raw.replace(",", " ").split()
    seen: set[str] = set()
    tickers: list[str] = []
    for token in tokens:
        symbol = token.strip().upper()
        if symbol and symbol not in seen:
            seen.add(symbol)
            tickers.append(symbol)
    if len(tickers) > MAX_TICKERS:
        raise ValueError(f"Too many tickers: at most {MAX_TICKERS} are allowed per source.")
    return tickers


def _build_url(path: str, params: dict[str, str]) -> str:
    return f"{FINNWORLDS_BASE_URL}/{path}?{urlencode(params)}"


# The API key rides in the `key` query param, so it ends up in `response.url`. `raise_for_status()`
# embeds that URL in its message, which would otherwise leak the key into the sync's stored error and logs.
_KEY_RE = re.compile(r"(key=)[^&\s]+", re.IGNORECASE)


def _redact_key(text: str) -> str:
    return _KEY_RE.sub(r"\1REDACTED", text)


@retry(
    retry=retry_if_exception_type((FinnworldsRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise FinnworldsRetryableError(f"Finnworlds API error (retryable): status={response.status_code}")

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        # Re-raise with the `key` redacted so the credential never reaches stored errors / logs, keeping the
        # `... for url: https://api.finnworlds.com` prefix intact for `get_non_retryable_errors()`.
        raise requests.HTTPError(_redact_key(str(exc)), response=exc.response) from None

    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    return payload


def _payload_error(payload: dict[str, Any]) -> str | None:
    """Return the body-level error message, if any. Finnworlds reports failures in the body at 200."""
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        return error
    status = payload.get("status")
    if isinstance(status, dict):
        code = status.get("code")
        if code is not None and str(code) != "200":
            message = status.get("message") or status.get("details") or f"status {code}"
            return str(message)
    return None


def _raise_if_auth_error(error_message: str) -> None:
    lowered = error_message.lower()
    if any(marker in lowered for marker in _AUTH_ERROR_MARKERS):
        raise FinnworldsAuthError(f"Finnworlds authentication failed: {error_message}")


def _extract_rows(payload: dict[str, Any], config: FinnworldsEndpointConfig) -> list[dict[str, Any]]:
    result = payload.get("result", {})
    result = result if isinstance(result, dict) else {}

    rows: Any
    if config.response_mode == ResponseMode.OUTPUT_ARRAY:
        output = result.get("output", {})
        rows = output.get(config.data_key, []) if isinstance(output, dict) and config.data_key else []
    elif config.response_mode == ResponseMode.OUTPUT_OBJECT:
        output = result.get("output", {})
        rows = [output] if isinstance(output, dict) and output else []
    elif config.response_mode == ResponseMode.OUTPUT_BARE:
        output = result.get("output", [])
        rows = output if isinstance(output, list) else []
    elif config.response_mode == ResponseMode.RESULT_KEY:
        rows = result.get(config.data_key, []) if config.data_key else []
    else:  # TOP_LEVEL
        rows = payload.get(config.data_key, []) if config.data_key else []

    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _normalize_row(
    row: dict[str, Any], config: FinnworldsEndpointConfig, ticker: str | None, period: str | None
) -> dict[str, Any]:
    """Flatten configured nested objects and inject the identifiers the primary key relies on."""
    for nested_key in config.flatten_keys:
        nested = row.pop(nested_key, None)
        if isinstance(nested, dict):
            # Injected ticker/period below take precedence, so merge the nested object first.
            row = {**nested, **row}
    if config.requires_ticker and ticker is not None:
        row["ticker"] = ticker
    if config.include_period:
        row["period"] = period or "annual"
    return row


def _fetch_endpoint_rows(
    session: requests.Session,
    config: FinnworldsEndpointConfig,
    api_key: str,
    ticker: str | None,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    params: dict[str, str] = {"key": api_key}
    if ticker is not None:
        params["ticker"] = ticker
    url = _build_url(config.path, params)

    payload = _fetch(session, url, logger)

    error_message = _payload_error(payload)
    if error_message is not None:
        _raise_if_auth_error(error_message)
        # A non-auth error usually means "no data for this identifier" or a tier-gated endpoint; skip
        # the identifier rather than failing the whole sync.
        logger.warning(
            f"Finnworlds {config.name}: skipping ticker={ticker} due to API error: {error_message}",
        )
        return []

    period = None
    if config.include_period:
        result_dict = payload.get("result", {})
        basics = result_dict.get("basics", {}) if isinstance(result_dict, dict) else {}
        period = basics.get("period") if isinstance(basics, dict) else None
        if period is None:
            # The primary key for fundamentals is (ticker, period, date); without a real period every row
            # falls back to "annual", which would silently merge quarterly rows. Surface it when it happens.
            logger.warning(
                f"Finnworlds {config.name}: no period in response for ticker={ticker}; "
                "defaulting to 'annual' (quarterly rows may collide on the primary key)",
            )

    rows = _extract_rows(payload, config)
    return [_normalize_row(row, config, ticker, period) for row in rows]


def get_rows(
    api_key: str,
    endpoint: str,
    tickers: list[str],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    config = FINNWORLDS_ENDPOINTS[endpoint]
    # One session reused across every request so urllib3 keeps the connection alive. The API key
    # rides in the query string, so redact it from logged URLs and captured samples.
    session = make_tracked_session(redact_values=(api_key,))

    if not config.requires_ticker:
        rows = _fetch_endpoint_rows(session, config, api_key, None, logger)
        if rows:
            yield rows
        return

    for ticker in tickers:
        rows = _fetch_endpoint_rows(session, config, api_key, ticker, logger)
        if rows:
            # Yield one batch per ticker; the pipeline buffers and re-batches across tickers.
            yield rows


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a cheap ticker-keyed endpoint. The key is valid when the body carries no error.

    Returns (is_valid, error_message). A transient network failure during setup is reported distinctly
    from a bad key so a brief connectivity blip isn't mistaken for an invalid credential — the sync path
    retries the same transient errors via tenacity.
    """
    url = _build_url("information", {"key": api_key, "ticker": "AAPL"})
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(url, timeout=10)
    except (requests.ConnectionError, requests.Timeout) as exc:
        return False, f"Could not reach the Finnworlds API: {type(exc).__name__}. Please try again."
    except Exception:
        # Any other unexpected failure stays fail-closed as a bad key rather than crashing setup.
        return False, "Invalid Finnworlds API key"

    if not response.ok:
        return False, "Invalid Finnworlds API key"
    try:
        payload = response.json()
    except ValueError:
        return False, "Invalid Finnworlds API key"

    if not isinstance(payload, dict):
        return False, "Invalid Finnworlds API key"
    if _payload_error(payload) is not None:
        return False, "Invalid Finnworlds API key"
    return True, None


def finnworlds_source(
    api_key: str,
    endpoint: str,
    tickers: list[str],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    config = FINNWORLDS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_key=api_key, endpoint=endpoint, tickers=tickers, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
