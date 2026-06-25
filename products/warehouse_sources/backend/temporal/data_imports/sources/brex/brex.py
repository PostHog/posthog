import time
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.brex.settings import (
    BREX_ENDPOINTS,
    BrexEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BREX_BASE_URL = "https://api.brex.com"
# Expenses caps `limit` at 100; other endpoints don't document a max, so 100 is used uniformly.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 60

CASH_ACCOUNTS_PATH = "/v2/accounts/cash"
# Injected into cash transaction rows so rows from different cash accounts stay distinguishable.
CASH_ACCOUNT_ID_KEY = "account_id"


class BrexRetryableError(Exception):
    pass


@dataclasses.dataclass
class BrexResumeConfig:
    # `next_cursor` of the last fully-yielded page for the endpoint (or current cash account).
    cursor: Optional[str] = None
    # Cash account currently being paged; None for top-level endpoints.
    account_id: Optional[str] = None
    # Cash accounts already fully synced in this run.
    completed_account_ids: list[str] = dataclasses.field(default_factory=list)


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _to_rfc3339(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value to the RFC 3339 date-time format Brex's
    `*_start` filters expect. Watermarks arrive as datetimes, dates, or ISO strings
    depending on the endpoint's incremental field type."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return f"{value.isoformat()}T00:00:00Z"
    if isinstance(value, str):
        # Date-only strings (e.g. a posted_at_date watermark) need a time component.
        if len(value) == 10:
            return f"{value}T00:00:00Z"
        return value
    return None


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{BREX_BASE_URL}{path}"
    return f"{BREX_BASE_URL}{path}?{urlencode(clean_params)}"


def _build_params(
    config: BrexEndpointConfig,
    cursor: Optional[str],
    incremental_value: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if cursor is not None:
        params["cursor"] = cursor
    # Brex docs don't state whether the cursor re-encodes the original filters, so the
    # timestamp filter is re-sent on every page to be safe.
    if config.incremental_param is not None and incremental_value is not None:
        params[config.incremental_param] = incremental_value
    return params


def validate_credentials(api_key: str) -> bool:
    """Confirm the API user token is genuine. /v2/users/me is a cheap authenticated probe.

    A 403 means the token is valid but wasn't granted the Team scope — users may
    legitimately scope tokens to only the endpoints they want to sync, so it's accepted.
    """
    try:
        response = make_tracked_session().get(
            f"{BREX_BASE_URL}/v2/users/me",
            headers=_get_headers(api_key),
            timeout=10,
        )
        return response.status_code in (200, 403)
    except Exception:
        return False


PageFetcher = Callable[[str], dict[str, Any]]


def _make_page_fetcher(api_key: str, logger: FilteringBoundLogger) -> PageFetcher:
    headers = _get_headers(api_key)

    @retry(
        retry=retry_if_exception_type((BrexRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # Brex rate-limits at 1,000 requests per 60s. Honor Retry-After when present,
        # otherwise tenacity's exponential backoff covers it.
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                try:
                    time.sleep(min(int(retry_after), MAX_RETRY_AFTER_SECONDS))
                except ValueError:
                    pass
            raise BrexRetryableError(f"Brex API rate limited: status=429, url={page_url}")

        if response.status_code >= 500:
            raise BrexRetryableError(f"Brex API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Brex API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    return fetch_page


def _list_cash_account_ids(fetch_page: PageFetcher, logger: FilteringBoundLogger) -> list[str]:
    account_ids: list[str] = []
    cursor: Optional[str] = None

    while True:
        url = _build_url(CASH_ACCOUNTS_PATH, {"limit": PAGE_SIZE, "cursor": cursor})
        data = fetch_page(url)
        items = data.get("items", []) or []
        account_ids.extend(item["id"] for item in items)

        cursor = data.get("next_cursor")
        if not cursor:
            break

    logger.debug(f"Brex: found {len(account_ids)} cash accounts")
    return account_ids


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BrexResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = BREX_ENDPOINTS[endpoint]
    fetch_page = _make_page_fetcher(api_key, logger)

    incremental_value = _to_rfc3339(db_incremental_field_last_value) if should_use_incremental_field else None

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        logger.debug(
            f"Brex: resuming {endpoint}. cursor={resume_config.cursor}, account_id={resume_config.account_id}, "
            f"completed_account_ids={resume_config.completed_account_ids}"
        )

    if config.fan_out_cash_accounts:
        yield from _get_fan_out_rows(
            config, fetch_page, logger, resumable_source_manager, resume_config, incremental_value
        )
        return

    cursor = resume_config.cursor if resume_config is not None else None

    while True:
        url = _build_url(config.path, _build_params(config, cursor, incremental_value))
        data = fetch_page(url)
        items = data.get("items", []) or []

        if items:
            yield items

        cursor = data.get("next_cursor")
        if not cursor:
            break

        # Save after yielding so a crash re-yields the last batch (merge dedupes on
        # primary key) rather than skipping it.
        resumable_source_manager.save_state(BrexResumeConfig(cursor=cursor))


def _get_fan_out_rows(
    config: BrexEndpointConfig,
    fetch_page: PageFetcher,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BrexResumeConfig],
    resume_config: Optional[BrexResumeConfig],
    incremental_value: Optional[str],
) -> Iterator[list[dict[str, Any]]]:
    account_ids = _list_cash_account_ids(fetch_page, logger)

    completed_account_ids = list(resume_config.completed_account_ids) if resume_config is not None else []
    completed_set = set(completed_account_ids)

    for account_id in account_ids:
        if account_id in completed_set:
            continue

        cursor = resume_config.cursor if resume_config is not None and resume_config.account_id == account_id else None
        path = config.path.format(account_id=account_id)

        while True:
            url = _build_url(path, _build_params(config, cursor, incremental_value))
            data = fetch_page(url)
            items = data.get("items", []) or []

            if items:
                yield [{**item, CASH_ACCOUNT_ID_KEY: account_id} for item in items]

            cursor = data.get("next_cursor")
            if not cursor:
                break

            resumable_source_manager.save_state(
                BrexResumeConfig(
                    cursor=cursor,
                    account_id=account_id,
                    completed_account_ids=list(completed_account_ids),
                )
            )

        completed_account_ids.append(account_id)
        completed_set.add(account_id)
        resumable_source_manager.save_state(BrexResumeConfig(completed_account_ids=list(completed_account_ids)))


def brex_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BrexResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BREX_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Brex doesn't expose a sort param and doesn't document list ordering. "desc" makes the
        # pipeline commit the incremental watermark only after a fully successful run, which is
        # the safe choice when ascending order can't be requested.
        sort_mode="desc" if config.incremental_fields else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
