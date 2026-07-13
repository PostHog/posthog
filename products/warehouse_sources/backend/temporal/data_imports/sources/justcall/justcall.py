import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.settings import (
    JUSTCALL_ENDPOINTS,
    JustCallEndpointConfig,
)

JUSTCALL_BASE_URL = "https://api.justcall.io/v2.1"
# JustCall caps list pages at 100 items across the v2.1 list endpoints.
PAGE_SIZE = 100
# v2.1 list endpoints are 0-indexed ("page 0 indicates first page").
FIRST_PAGE = 0
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class JustCallRetryableError(Exception):
    pass


@dataclasses.dataclass
class JustCallResumeConfig:
    # Next 0-indexed page to fetch. The cursor filter (`from_datetime`) is recomputed from the
    # unchanged job inputs on resume, so only the page position needs persisting.
    page: int


def _get_headers(api_key: str, api_secret: str) -> dict[str, str]:
    # JustCall v2.1 authenticates with the raw `api_key:api_secret` pair in the Authorization
    # header — no `Basic` prefix and no base64 encoding.
    return {
        "Authorization": f"{api_key}:{api_secret}",
        "Accept": "application/json",
    }


def _make_session(api_key: str, api_secret: str) -> requests.Session:
    # Register the raw credential values (and the combined Authorization header value) for
    # value-based redaction, since the auth scheme puts the secret in a nonstandard raw header
    # value that name-based scrubbers can't recognise. This keeps the credentials masked in
    # request logs and captured HTTP samples on a failed sync.
    return make_tracked_session(
        headers=_get_headers(api_key, api_secret),
        redact_values=(api_key, api_secret, f"{api_key}:{api_secret}"),
    )


def _format_cursor(value: Any) -> Optional[str]:
    """Coerce an incremental cursor value to the `yyyy-mm-dd` form JustCall's `from_datetime` takes.

    The cursor is a `_user_date` field (account-timezone date), persisted as a Date. Datetimes and
    ISO strings are handled defensively; only the date component is kept because `from_datetime`
    accepts a bare date and the watermark is day-granular.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return None
    # Handles "2021-08-25", "2021-08-25 10:30:00", and "2021-08-25T10:30:00" alike.
    return text[:10]


def _build_params(config: JustCallEndpointConfig, page: int, from_value: Optional[str]) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "per_page": PAGE_SIZE, "order": config.order}
    if config.incremental_cursor:
        # `sort=datetime` orders by call/SMS time; combined with `order=asc` the watermark advances
        # monotonically. `from_datetime` is only meaningful on the endpoints that support it.
        params["sort"] = "datetime"
        if from_value is not None:
            params["from_datetime"] = from_value
    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{JUSTCALL_BASE_URL}{path}"
    return f"{JUSTCALL_BASE_URL}{path}?{urlencode(clean_params)}"


def validate_credentials(api_key: str, api_secret: str) -> bool:
    """Confirm the API key/secret pair is valid with one cheap authenticated probe.

    `/phone-numbers` is a tiny account-level list available to any valid JustCall key, so it makes a
    good token check without pulling call/message history.
    """
    try:
        response = _make_session(api_key, api_secret).get(
            _build_url("/phone-numbers", {"page": FIRST_PAGE, "per_page": 1}),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JustCallResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = JUSTCALL_ENDPOINTS[endpoint]
    session = _make_session(api_key, api_secret)

    # Only endpoints with a server-side `from_datetime` filter honor the incremental cursor; the
    # rest are full refresh regardless of what the pipeline passes.
    from_value = (
        _format_cursor(db_incremental_field_last_value)
        if should_use_incremental_field and config.incremental_cursor
        else None
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume_config.page if resume_config is not None else FIRST_PAGE
    if resume_config is not None:
        logger.debug(f"JustCall: resuming {endpoint} from page {page}")

    @retry(
        retry=retry_if_exception_type((JustCallRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        # JustCall rate-limits per API key on both a minutely burst window and an hourly window,
        # returning 429 on breach. Exponential backoff with jitter is sufficient here.
        if response.status_code == 429 or response.status_code >= 500:
            raise JustCallRetryableError(
                f"JustCall API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            # Deliberately not logging the response body: these endpoints return calls, texts, and
            # contacts, so a raw error payload could copy customer PII (or echoed credentials) into
            # logs. Status and endpoint are enough to debug an auth/permission failure.
            logger.error(f"JustCall API error: status={response.status_code}, url={page_url}")
            response.raise_for_status()

        return response.json()

    # Page forward, rebuilding the query each time so `from_datetime`/`sort`/`order` stay attached to
    # every request. This deliberately does not follow the response's `next_page_link`: we can't
    # verify that link preserves the time filter on later pages, and dropping it would re-walk each
    # endpoint's full history every incremental sync. A short page (< PAGE_SIZE) marks the end.
    while True:
        url = _build_url(config.path, _build_params(config, page, from_value))
        data = fetch_page(url)
        items = data.get("data", []) or []

        if items:
            yield items
            # Save the page we just yielded (not the next one) AFTER yielding it, so a crash
            # re-fetches and re-yields this page rather than skipping it — the primary-key merge
            # dedupes the overlap.
            resumable_source_manager.save_state(JustCallResumeConfig(page=page))

        if len(items) < PAGE_SIZE:
            break

        page += 1


def justcall_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JustCallResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = JUSTCALL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            api_secret=api_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.incremental_cursor else None,
        partition_format="week" if config.incremental_cursor else None,
        partition_keys=[config.incremental_cursor] if config.incremental_cursor else None,
    )
