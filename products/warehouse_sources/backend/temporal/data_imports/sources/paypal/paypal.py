from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.paypal.settings import (
    DISPUTE_HISTORY_DAYS,
    PAYPAL_ENDPOINTS,
    PAYPAL_HOSTS,
    TRANSACTION_HISTORY_DAYS,
    TRANSACTION_WINDOW_DAYS,
    PayPalEndpointConfig,
)

TOKEN_PATH = "/v1/oauth2/token"
REQUEST_TIMEOUT_SECONDS = 120
VALIDATE_TIMEOUT_SECONDS = 15
MAX_RETRY_ATTEMPTS = 5

# Bound method handed to the per-pagination-mode walkers: (path, query params) -> decoded body.
RequestFn = Callable[[str, dict[str, Any]], dict[str, Any]]


class PayPalRetryableError(Exception):
    pass


@frozen
class PayPalResumeConfig:
    """Where to pick a partially-walked endpoint back up.

    Only one of the three positions is meaningful per endpoint: `window_start` + `page` for
    Transaction Search, `page` alone for the page-number listings, `next_page_token` for disputes.
    """

    window_start: Optional[str] = None
    page: int = 1
    next_page_token: Optional[str] = None


def _base_url(environment: str) -> str:
    host = PAYPAL_HOSTS.get(environment)
    if host is None:
        raise ValueError(f"Invalid PayPal environment: {environment}")
    return host


def _get_session(client_secret: str) -> requests.Session:
    return make_tracked_session(headers={"Accept": "application/json"}, redact_values=(client_secret,))


def _now() -> datetime:
    return datetime.now(UTC)


def _to_datetime(value: Any) -> Optional[datetime]:
    """Coerce an incremental watermark into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _format_reporting_datetime(value: datetime) -> str:
    """RFC 3339 with a numeric offset — the only shape the reporting APIs accept."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S-0000")


def _format_dispute_datetime(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _mint_token(session: requests.Session, base_url: str, client_id: str, client_secret: str) -> str:
    """Exchange the app credentials for a bearer token (client_credentials grant)."""
    response = session.post(
        f"{base_url}{TOKEN_PATH}",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def _next_page_token(links: Any) -> Optional[str]:
    """Pull `next_page_token` off the HATEOAS `rel="next"` link, if there is one."""
    if not isinstance(links, list):
        return None
    for link in links:
        if not isinstance(link, dict) or link.get("rel") != "next":
            continue
        href = link.get("href")
        if not isinstance(href, str):
            continue
        tokens = parse_qs(urlparse(href).query).get("next_page_token")
        if tokens:
            return tokens[0]
    return None


def _flatten_transaction(row: dict[str, Any]) -> dict[str, Any]:
    """Hoist the fields the pipeline keys on out of the nested `transaction_info` object."""
    info = row.get("transaction_info") or {}
    return {
        **row,
        "transaction_id": info.get("transaction_id"),
        "transaction_initiation_date": info.get("transaction_initiation_date"),
        "transaction_updated_date": info.get("transaction_updated_date"),
    }


@frozen
class DateWindow:
    start: datetime
    end: datetime


def _date_windows(start: datetime, end: datetime, window_days: int) -> list[DateWindow]:
    windows: list[DateWindow] = []
    cursor = start
    step = timedelta(days=window_days)
    while cursor < end:
        window_end = min(cursor + step, end)
        windows.append(DateWindow(start=cursor, end=window_end))
        cursor = window_end
    return windows


def _has_more_pages(items: list[Any], total_pages: Any, page: int, page_size: int) -> bool:
    """Whether a page-numbered listing has another page after `page`.

    `total_required=true` makes PayPal return `total_pages`; when a response omits it we fall
    back to "a full page probably isn't the last one" rather than silently truncating the table.
    """
    if not items:
        return False
    if isinstance(total_pages, int):
        return page < total_pages
    return len(items) >= page_size


def _transaction_start(db_incremental_field_last_value: Any, now: datetime) -> datetime:
    """First instant to search from, clamped to the three years PayPal keeps searchable."""
    earliest = now - timedelta(days=TRANSACTION_HISTORY_DAYS)
    watermark = _to_datetime(db_incremental_field_last_value)
    if watermark is None:
        # Floored to midnight so a full-refresh run produces the same window boundaries as the
        # attempt it is resuming, which is what makes the saved `window_start` match.
        return earliest.replace(hour=0, minute=0, second=0, microsecond=0)
    return max(watermark, earliest)


def _dispute_start(db_incremental_field_last_value: Any, now: datetime) -> Optional[datetime]:
    """Instant to filter disputes from, or None for a full refresh.

    PayPal rejects an `update_time_after` older than 180 days with a non-retryable 400, so an
    incremental watermark is clamped forward to that floor. PayPal cannot serve disputes outside it.
    """
    watermark = _to_datetime(db_incremental_field_last_value)
    if watermark is None:
        return None
    earliest = now - timedelta(days=DISPUTE_HISTORY_DAYS)
    return max(watermark, earliest)


def validate_credentials(environment: str, client_id: str, client_secret: str) -> tuple[bool, str | None]:
    """Mint a token — that alone proves the app credentials and environment line up."""
    try:
        base_url = _base_url(environment)
    except ValueError as e:
        return False, str(e)

    session = _get_session(client_secret)
    try:
        response = session.post(
            f"{base_url}{TOKEN_PATH}",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
            timeout=VALIDATE_TIMEOUT_SECONDS,
        )
    except Exception:
        return False, "Could not reach PayPal. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (400, 401):
        return False, "PayPal rejected these credentials. Check the client ID, secret, and environment."
    return False, f"PayPal returned an unexpected status ({response.status_code}) while authenticating."


def _probe_params(config: PayPalEndpointConfig, now: datetime) -> dict[str, Any]:
    """Smallest valid request per endpoint, used only to observe a 200/403 for the permission probe."""
    if config.pagination == "date_window":
        return {
            "start_date": _format_reporting_datetime(now - timedelta(days=1)),
            "end_date": _format_reporting_datetime(now),
            "fields": "all",
            "page_size": 1,
            "page": 1,
        }
    if config.pagination == "single":
        return {"currency_code": "ALL"}
    if config.pagination == "page_token":
        return {"page_size": 1}
    return {"page": 1, "page_size": 1}


def check_endpoint_permissions(
    environment: str, client_id: str, client_secret: str, endpoints: list[str]
) -> dict[str, str | None]:
    """Report which endpoints the app cannot read: ``{name: None}`` reachable, ``{name: reason}`` denied.

    A fresh PayPal REST app enables no features, so setup could otherwise turn on tables that 403 on
    every sync. Only a real 403 counts as a missing feature; a throttle, 5xx, or network blip stays
    reachable so a transient failure never blocks source creation or the schema picker.
    """
    try:
        base_url = _base_url(environment)
    except ValueError:
        return dict.fromkeys(endpoints)

    session = _get_session(client_secret)
    try:
        token = _mint_token(session, base_url, client_id, client_secret)
    except Exception:
        return dict.fromkeys(endpoints)

    now = _now()
    results: dict[str, str | None] = {}
    for name in endpoints:
        config = PAYPAL_ENDPOINTS.get(name)
        if config is None or config.required_feature is None:
            results[name] = None
            continue
        try:
            response = session.get(
                f"{base_url}{config.path}",
                params=_probe_params(config, now),
                headers={"Authorization": f"Bearer {token}"},
                timeout=VALIDATE_TIMEOUT_SECONDS,
            )
        except Exception:
            results[name] = None
            continue
        results[name] = (
            f"Your PayPal app cannot access this table. Enable {config.required_feature} on the app "
            "in the PayPal developer dashboard."
            if response.status_code == 403
            else None
        )
    return results


def get_rows(
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PayPalResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = PAYPAL_ENDPOINTS[endpoint]
    base_url = _base_url(environment)
    session = _get_session(client_secret)
    token = _mint_token(session, base_url, client_id, client_secret)

    @retry(
        retry=retry_if_exception_type((PayPalRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=2, max=120),
        reraise=True,
    )
    def request(path: str, params: dict[str, Any]) -> dict[str, Any]:
        nonlocal token
        url = f"{base_url}{path}"

        def _do() -> requests.Response:
            return session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )

        response = _do()
        # Access tokens last ~9h; re-mint once if a long sync outlives one.
        if response.status_code == 401:
            token = _mint_token(session, base_url, client_id, client_secret)
            response = _do()

        if response.status_code == 429 or response.status_code >= 500:
            raise PayPalRetryableError(f"PayPal API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"PayPal API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        body = response.json()
        return body if isinstance(body, dict) else {}

    watermark = db_incremental_field_last_value if should_use_incremental_field else None
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.pagination == "single":
        yield from _single_rows(config, request)
    elif config.pagination == "date_window":
        yield from _transaction_rows(config, request, resumable_source_manager, resume, watermark, logger)
    elif config.pagination == "page_token":
        yield from _page_token_rows(config, request, resumable_source_manager, resume, watermark)
    else:
        yield from _page_number_rows(config, request, resumable_source_manager, resume)


def _single_rows(
    config: PayPalEndpointConfig,
    request: RequestFn,
) -> Iterator[list[dict[str, Any]]]:
    data = request(config.path, {"currency_code": "ALL"})
    # The balances payload carries the account and snapshot time alongside the per-currency
    # rows; fold them in so each row is self-describing.
    items = [
        {**item, "account_id": data.get("account_id"), "as_of_time": data.get("as_of_time")}
        for item in (data.get(config.data_selector) or [])
    ]
    if items:
        yield items


def _transaction_rows(
    config: PayPalEndpointConfig,
    request: RequestFn,
    resumable_source_manager: ResumableSourceManager[PayPalResumeConfig],
    resume: Optional[PayPalResumeConfig],
    watermark: Any,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    now = _now()
    windows = _date_windows(_transaction_start(watermark, now), now, TRANSACTION_WINDOW_DAYS)

    start_index = 0
    start_page = 1
    if resume is not None and resume.window_start is not None:
        for index, window in enumerate(windows):
            if window.start.isoformat() == resume.window_start:
                start_index = index
                start_page = max(resume.page, 1)
                logger.debug(f"PayPal: resuming transactions from {resume.window_start} page {start_page}")
                break

    for index in range(start_index, len(windows)):
        window = windows[index]
        page = start_page if index == start_index else 1

        while True:
            data = request(
                config.path,
                {
                    "start_date": _format_reporting_datetime(window.start),
                    "end_date": _format_reporting_datetime(window.end),
                    "fields": "all",
                    "page_size": config.page_size,
                    "page": page,
                },
            )
            items = [_flatten_transaction(row) for row in (data.get(config.data_selector) or [])]
            if items:
                yield items

            if not _has_more_pages(items, data.get("total_pages"), page, config.page_size):
                break

            page += 1
            # Saved after yielding so a crash re-yields the last page (merge dedupes on the
            # primary key) rather than skipping it.
            resumable_source_manager.save_state(PayPalResumeConfig(window_start=window.start.isoformat(), page=page))

        if index + 1 < len(windows):
            resumable_source_manager.save_state(
                PayPalResumeConfig(window_start=windows[index + 1].start.isoformat(), page=1)
            )


def _page_number_rows(
    config: PayPalEndpointConfig,
    request: RequestFn,
    resumable_source_manager: ResumableSourceManager[PayPalResumeConfig],
    resume: Optional[PayPalResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    page = max(resume.page, 1) if resume is not None else 1

    while True:
        data = request(
            config.path,
            {"page": page, "page_size": config.page_size, "total_required": "true"},
        )
        items = list(data.get(config.data_selector) or [])
        if items:
            yield items

        if not _has_more_pages(items, data.get("total_pages"), page, config.page_size):
            break

        page += 1
        resumable_source_manager.save_state(PayPalResumeConfig(page=page))


def _page_token_rows(
    config: PayPalEndpointConfig,
    request: RequestFn,
    resumable_source_manager: ResumableSourceManager[PayPalResumeConfig],
    resume: Optional[PayPalResumeConfig],
    watermark: Any,
) -> Iterator[list[dict[str, Any]]]:
    params: dict[str, Any] = {"page_size": config.page_size}
    update_time_after = _dispute_start(watermark, _now())
    if update_time_after is not None:
        # Filter on update time, not creation time, so a dispute whose status changed since the
        # last run is re-fetched and the merge on dispute_id refreshes the row.
        params["update_time_after"] = _format_dispute_datetime(update_time_after)

    token = resume.next_page_token if resume is not None else None

    while True:
        page_params = {**params, "next_page_token": token} if token is not None else dict(params)

        data = request(config.path, page_params)
        items = list(data.get(config.data_selector) or [])
        if items:
            yield items

        token = _next_page_token(data.get("links"))
        if not items or token is None:
            break

        resumable_source_manager.save_state(PayPalResumeConfig(next_page_token=token))


def paypal_source(
    environment: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PayPalResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PAYPAL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            environment=environment,
            client_id=client_id,
            client_secret=client_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_key,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )
