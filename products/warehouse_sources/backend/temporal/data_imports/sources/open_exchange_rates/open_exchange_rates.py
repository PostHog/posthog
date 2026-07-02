import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.open_exchange_rates.settings import (
    OPEN_EXCHANGE_RATES_ENDPOINTS,
)

BASE_URL = "https://openexchangerates.org/api"
DEFAULT_BASE_CURRENCY = "USD"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 6

# `historical` is walked one request per day, so a first-sync backfill with no configured start date
# stays deliberately small to avoid burning a free-tier monthly request quota (1000/month) in one run.
DEFAULT_LOOKBACK_DAYS = 30


class OpenExchangeRatesRetryableError(Exception):
    """Raised for transient upstream failures (5xx) that are worth retrying."""

    pass


@dataclasses.dataclass
class OpenExchangeRatesResumeConfig:
    # ISO date (YYYY-MM-DD) of the next `historical` day to fetch. Lets a multi-day backfill resume
    # mid-sync after a heartbeat timeout instead of restarting from the first day. Unused for the
    # single-response currencies/latest/usage endpoints.
    next_date: str | None = None


def _build_url(path: str, params: dict[str, Any] | None = None) -> str:
    if params:
        return f"{BASE_URL}/{path}?{urlencode(params)}"
    return f"{BASE_URL}/{path}"


def _auth_headers(app_id: str) -> dict[str, str]:
    # Send the App ID as a header rather than the `app_id` query param, so the credential never
    # appears in a request URL, log line, or raised error message.
    return {"Authorization": f"Token {app_id}"}


def _request(session: requests.Session, path: str, params: dict[str, Any], logger: FilteringBoundLogger) -> Any:
    url = _build_url(path, params)
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # Open Exchange Rates uses real HTTP status codes. Only 5xx is transient — a 429 here means
    # `not_allowed` (the plan doesn't permit this feature/base), which is permanent, so it falls
    # through to the raise below and is surfaced via `get_non_retryable_errors()`.
    if response.status_code >= 500:
        raise OpenExchangeRatesRetryableError(f"Open Exchange Rates error (retryable): status={response.status_code}")

    if not response.ok:
        description = _error_description(response)
        logger.error(f"Open Exchange Rates error: status={response.status_code}, body={response.text}, url={url}")
        # The App ID rides in the Authorization header, not the URL, so the URL is safe to include —
        # it lets `get_non_retryable_errors()` match on the stable host prefix.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {url}{description}",
            response=response,
        )

    return response.json()


def _error_description(response: requests.Response) -> str:
    # Open Exchange Rates error bodies look like {"error": true, "status", "message", "description"}.
    # Append the human-readable description to the raised error when present, but never fail if the
    # body isn't the expected JSON.
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict) and body.get("description"):
        return f" — {body['description']}"
    return ""


def validate_credentials(app_id: str) -> bool:
    """Confirm the App ID is genuine with the cheapest authenticated call (/usage.json). It requires
    a valid App ID (an invalid one returns 401) but is free and does not count toward the request
    quota. A valid App ID returns 200."""
    try:
        session = make_tracked_session(headers=_auth_headers(app_id), redact_values=(app_id,) if app_id else ())
        response = session.get(_build_url("usage.json"), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _iter_currencies(data: dict[str, Any]) -> list[dict[str, Any]]:
    # currencies.json is a flat {code: name} map.
    return [{"code": code, "name": name} for code, name in data.items()]


def _iter_rates(data: dict[str, Any], value_date: str) -> list[dict[str, Any]]:
    # base is part of the composite primary key — fail fast rather than write None rows. latest.json
    # and historical/{date}.json share this {base, timestamp, rates: {currency: rate}} shape.
    base = data["base"]
    timestamp = data.get("timestamp")
    rates = data.get("rates") or {}
    return [
        {"base": base, "currency": currency, "rate": rate, "date": value_date, "timestamp": timestamp}
        for currency, rate in rates.items()
    ]


def _iter_usage(data: dict[str, Any]) -> list[dict[str, Any]]:
    # usage.json wraps the account details under `data`; flatten the plan + usage blocks into one row.
    payload = data.get("data") or {}
    plan = payload.get("plan") or {}
    usage = payload.get("usage") or {}
    # app_id is the primary key — index it directly so a response missing it fails loudly rather than
    # silently writing zero rows (matches `_iter_rates` reading `data["base"]`).
    return [
        {
            "app_id": payload["app_id"],
            "status": payload.get("status"),
            "plan_name": plan.get("name"),
            "plan_quota": plan.get("quota"),
            "plan_update_frequency": plan.get("update_frequency"),
            "requests": usage.get("requests"),
            "requests_quota": usage.get("requests_quota"),
            "requests_remaining": usage.get("requests_remaining"),
            "days_elapsed": usage.get("days_elapsed"),
            "days_remaining": usage.get("days_remaining"),
            "daily_average": usage.get("daily_average"),
        }
    ]


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


def _date_from_timestamp(timestamp: Any) -> Optional[date]:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(int(timestamp), tz=UTC).date()
    except (ValueError, OverflowError, OSError, TypeError):
        return None


def _date_range(start: date, end: date) -> list[date]:
    if start > end:
        return []
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _resolve_historical_start(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    configured_start_date: str | None,
    today: date,
) -> date:
    if should_use_incremental_field:
        watermark = _to_date(db_incremental_field_last_value)
        if watermark is not None:
            # Re-pull the watermark day; merge dedupes on the composite primary key.
            return watermark

    configured = _to_date(configured_start_date)
    if configured is not None:
        return configured

    return today - timedelta(days=DEFAULT_LOOKBACK_DAYS)


def get_rows(
    app_id: str,
    endpoint: str,
    base_currency: str,
    start_date: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenExchangeRatesResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    session = make_tracked_session(headers=_auth_headers(app_id), redact_values=(app_id,) if app_id else ())
    base = base_currency or DEFAULT_BASE_CURRENCY

    @retry(
        retry=retry_if_exception_type(
            (OpenExchangeRatesRetryableError, requests.ReadTimeout, requests.ConnectionError)
        ),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=120),
        reraise=True,
    )
    def fetch(path: str, params: dict[str, Any]) -> Any:
        return _request(session, path, params, logger)

    if endpoint == "currencies":
        rows = _iter_currencies(fetch("currencies.json", {}))
        if rows:
            yield rows
        return

    if endpoint == "usage":
        rows = _iter_usage(fetch("usage.json", {}))
        if rows:
            yield rows
        return

    if endpoint == "latest":
        data = fetch("latest.json", {"base": base})
        value_date = _date_from_timestamp(data.get("timestamp")) or datetime.now(tz=UTC).date()
        rows = _iter_rates(data, value_date.isoformat())
        if rows:
            yield rows
        return

    if endpoint == "historical":
        today = datetime.now(tz=UTC).date()
        # Only walk finalized past days (up to yesterday). Today's snapshot lives in `latest`.
        end = today - timedelta(days=1)
        start = _resolve_historical_start(
            should_use_incremental_field, db_incremental_field_last_value, start_date, today
        )
        days = _date_range(start, end)

        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        if resume is not None and resume.next_date:
            days = [day for day in days if day.isoformat() >= resume.next_date]
            logger.debug(f"Open Exchange Rates: resuming historical from {resume.next_date}")

        for index, value_date in enumerate(days):
            data = fetch(f"historical/{value_date.isoformat()}.json", {"base": base})
            rows = _iter_rates(data, value_date.isoformat())
            if rows:
                yield rows

            # Save AFTER yielding so a crash re-yields the last day rather than skipping it (merge
            # dedupes on the composite primary key).
            if index + 1 < len(days):
                resumable_source_manager.save_state(
                    OpenExchangeRatesResumeConfig(next_date=days[index + 1].isoformat())
                )
        return

    raise ValueError(f"Unknown Open Exchange Rates endpoint: {endpoint}")


def open_exchange_rates_source(
    app_id: str,
    endpoint: str,
    base_currency: str,
    start_date: str | None,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[OpenExchangeRatesResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = OPEN_EXCHANGE_RATES_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            app_id=app_id,
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
