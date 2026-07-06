import dataclasses
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.exchange_rates_api.settings import (
    EXCHANGE_RATES_API_ENDPOINTS,
)

BASE_URL = "https://api.exchangeratesapi.io/v1"
DEFAULT_BASE_CURRENCY = "EUR"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 6

# The /timeseries endpoint rejects ranges longer than 365 days, so multi-year backfills are chunked
# into windows of at most this many distinct days (inclusive).
MAX_RANGE_DAYS = 365
# On the first sync of an incremental timeseries (no watermark) and when no start date is configured,
# pull this far back — one full window.
DEFAULT_LOOKBACK_DAYS = 365


class ExchangeRatesApiError(Exception):
    """Raised when the API returns a functional error (HTTP 200 with success=false)."""

    pass


class ExchangeRatesApiRetryableError(Exception):
    pass


@dataclasses.dataclass
class ExchangeRatesApiResumeConfig:
    # ISO date (YYYY-MM-DD) of the next timeseries window's start. Lets a chunked multi-year backfill
    # resume mid-sync after a heartbeat timeout instead of restarting from the first window. Unused
    # for the single-response symbols/latest endpoints.
    next_start_date: str | None = None


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{BASE_URL}/{path}?{urlencode(params)}"


def _scrub_url(url: str | None) -> str:
    # The access_key rides in the query string, so strip the query before the URL reaches any error
    # message or log line — otherwise a non-2xx response would leak the credential into job errors.
    # The base host stays intact so `get_non_retryable_errors()` can still match on it.
    if not url:
        return BASE_URL
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _raise_on_functional_error(data: Any, url: str) -> None:
    """apilayer returns HTTP 200 with ``{"success": false, "error": {...}}`` for functional errors
    (e.g. an invalid date, or a base currency the plan doesn't allow). Surface those as failures
    instead of silently yielding nothing."""
    if isinstance(data, dict) and data.get("success") is False:
        error = data.get("error") or {}
        code = error.get("code") or error.get("type") or "unknown_error"
        message = error.get("message") or error.get("info") or "Unknown error"
        raise ExchangeRatesApiError(f"Exchange Rates API error ({code}): {message} url={_scrub_url(url)}")


def _request(session: requests.Session, path: str, params: dict[str, Any], logger: FilteringBoundLogger) -> Any:
    url = _build_url(path, params)
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise ExchangeRatesApiRetryableError(
            f"Exchange Rates API error (retryable): status={response.status_code}, url={_scrub_url(url)}"
        )

    if not response.ok:
        logger.error(
            f"Exchange Rates API error: status={response.status_code}, body={response.text}, url={_scrub_url(url)}"
        )
        # Raise with the access_key scrubbed from the URL rather than calling raise_for_status(), whose
        # message embeds the full credential-bearing URL.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {_scrub_url(response.url)}",
            response=response,
        )

    data = response.json()
    _raise_on_functional_error(data, url)
    return data


def validate_credentials(access_key: str) -> bool:
    """Confirm the key is genuine with the cheapest call (/symbols). A valid key returns 200; an
    invalid or missing one returns 401."""
    try:
        session = make_tracked_session(redact_values=(access_key,) if access_key else ())
        response = session.get(_build_url("symbols", {"access_key": access_key}), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _iter_symbols(data: dict[str, Any]) -> list[dict[str, Any]]:
    symbols = data.get("symbols") or {}
    return [{"code": code, "name": name} for code, name in symbols.items()]


def _iter_latest(data: dict[str, Any]) -> list[dict[str, Any]]:
    # base and date are part of the composite primary key — fail fast rather than write None rows.
    base = data["base"]
    value_date = data["date"]
    timestamp = data.get("timestamp")
    rates = data.get("rates") or {}
    return [
        {"base": base, "currency": currency, "rate": rate, "date": value_date, "timestamp": timestamp}
        for currency, rate in rates.items()
    ]


def _iter_timeseries(data: dict[str, Any]) -> list[dict[str, Any]]:
    # base is part of the composite primary key — fail fast rather than write None rows.
    base = data["base"]
    rates_by_date = data.get("rates") or {}
    rows: list[dict[str, Any]] = []
    # Sort by date so rows arrive in ascending order, matching sort_mode="asc" and keeping the
    # incremental watermark monotonic.
    for value_date in sorted(rates_by_date):
        for currency, rate in rates_by_date[value_date].items():
            rows.append({"base": base, "currency": currency, "rate": rate, "date": value_date})
    return rows


def _to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        # Tolerate both bare dates and full ISO datetimes (the watermark may be stored either way).
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _date_windows(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=max_days - 1), end)
        windows.append((current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def _resolve_timeseries_start(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    configured_start_date: str | None,
) -> date:
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            # Re-pull the watermark day; merge dedupes on the composite primary key.
            return watermark

    configured = _to_date(configured_start_date)
    if configured is not None:
        return configured

    return datetime.now().date() - timedelta(days=DEFAULT_LOOKBACK_DAYS)


def get_rows(
    access_key: str,
    endpoint: str,
    base_currency: str,
    start_date: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ExchangeRatesApiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(redact_values=(access_key,) if access_key else ())
    base = base_currency or DEFAULT_BASE_CURRENCY
    common_params: dict[str, Any] = {"access_key": access_key}

    @retry(
        retry=retry_if_exception_type((ExchangeRatesApiRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=120),
        reraise=True,
    )
    def fetch(path: str, params: dict[str, Any]) -> Any:
        return _request(session, path, params, logger)

    if endpoint == "symbols":
        rows = _iter_symbols(fetch("symbols", common_params))
        if rows:
            yield rows
        return

    if endpoint == "latest":
        rows = _iter_latest(fetch("latest", {**common_params, "base": base}))
        if rows:
            yield rows
        return

    if endpoint == "timeseries":
        end = datetime.now().date()
        start = _resolve_timeseries_start(should_use_incremental_field, db_incremental_field_last_value, start_date)
        windows = _date_windows(start, end, MAX_RANGE_DAYS)

        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        if resume is not None and resume.next_start_date:
            windows = [w for w in windows if w[0].isoformat() >= resume.next_start_date]
            logger.debug(f"Exchange Rates API: resuming timeseries from {resume.next_start_date}")

        for index, (window_start, window_end) in enumerate(windows):
            data = fetch(
                "timeseries",
                {
                    **common_params,
                    "base": base,
                    "start_date": window_start.isoformat(),
                    "end_date": window_end.isoformat(),
                },
            )
            rows = _iter_timeseries(data)
            if rows:
                yield rows

            # Save AFTER yielding so a crash re-yields the last window rather than skipping it (merge
            # dedupes on the composite primary key).
            if index + 1 < len(windows):
                resumable_source_manager.save_state(
                    ExchangeRatesApiResumeConfig(next_start_date=windows[index + 1][0].isoformat())
                )
        return

    raise ValueError(f"Unknown Exchange Rates API endpoint: {endpoint}")


def exchange_rates_api_source(
    access_key: str,
    endpoint: str,
    base_currency: str,
    start_date: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ExchangeRatesApiResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = EXCHANGE_RATES_API_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_key=access_key,
            endpoint=endpoint,
            base_currency=base_currency,
            start_date=start_date,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_keys=config.partition_keys,
        partition_mode=config.partition_mode,
        partition_format=config.partition_format,
        sort_mode="asc",
    )
