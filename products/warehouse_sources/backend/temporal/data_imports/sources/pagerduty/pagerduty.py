import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.pagerduty.settings import (
    PAGERDUTY_ENDPOINTS,
    PagerDutyEndpointConfig,
)

PAGERDUTY_BASE_URL = "https://api.pagerduty.com"

# PagerDuty's max page size is 100; the default is 25.
PAGE_SIZE = 100

# PagerDuty rejects requests where `offset + limit` exceeds 10,000 with an HTTP 400.
# Stop paginating before we cross it. Incremental endpoints stay well under this because
# the `since` filter bounds the window; full-refresh endpoints could in theory truncate
# on very large accounts (logged when it happens).
MAX_OFFSET = 10_000

# Retry/throttle settings kept near the top for easy tuning.
RETRY_ATTEMPTS = 5
REQUEST_TIMEOUT_SECONDS = 60


class PagerDutyRetryableError(Exception):
    pass


@dataclasses.dataclass
class PagerDutyResumeConfig:
    offset: int


def _format_incremental_value(value: Any) -> str:
    """Format an incremental field value as an ISO 8601 string for PagerDuty's `since` filter."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Token token={api_token}",
        "Accept": "application/vnd.pagerduty+json;version=2",
        "Content-Type": "application/json",
    }


def _build_params(
    config: PagerDutyEndpointConfig,
    offset: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset}

    if config.supports_since:
        # created_at is immutable, so an ascending sort means new rows append to the end
        # and never shift pages we've already read. We send this on every sync (not just
        # incremental ones) so full refreshes paginate over a stable ordering too.
        params["sort_by"] = "created_at:asc"
        if should_use_incremental_field and db_incremental_field_last_value:
            params["since"] = _format_incremental_value(db_incremental_field_last_value)

    return params


def validate_credentials(api_token: str, endpoint: Optional[str] = None) -> tuple[bool, int, str | None]:
    """Probe PagerDuty with a cheap single-row request.

    Returns ``(ok, status_code, error_message)``. ``status_code`` is 0 on transport failure.
    The caller decides how to treat 403 (valid token, missing scope for the probed endpoint).
    """
    config = PAGERDUTY_ENDPOINTS.get(endpoint) if endpoint else None
    path = config.path if config else "/users"
    url = f"{PAGERDUTY_BASE_URL}{path}?{urlencode({'limit': 1})}"

    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_token), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)

    if response.status_code == 200:
        return True, 200, None
    if response.status_code == 401:
        return False, 401, "Invalid PagerDuty API key"
    if response.status_code == 403:
        return False, 403, "Your PagerDuty API key does not have access to this resource"

    try:
        message = response.json().get("error", {}).get("message", response.text)
    except Exception:
        message = response.text
    return False, response.status_code, message


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PagerDutyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = PAGERDUTY_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.offset if resume_config is not None else 0
    if resume_config is not None:
        logger.debug(f"PagerDuty: resuming {endpoint} from offset {offset}")

    @retry(
        retry=retry_if_exception_type((PagerDutyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_offset: int) -> dict:
        params = _build_params(config, page_offset, should_use_incremental_field, db_incremental_field_last_value)
        url = f"{PAGERDUTY_BASE_URL}{config.path}?{urlencode(params)}"
        response = make_tracked_session().get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise PagerDutyRetryableError(f"PagerDuty API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"PagerDuty API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(offset)

        items = data.get(config.envelope_key, [])
        if not items:
            break

        yield items

        if not data.get("more", False):
            break

        offset += PAGE_SIZE
        if offset + PAGE_SIZE > MAX_OFFSET:
            logger.warning(
                f"PagerDuty: reached max offset {MAX_OFFSET} for endpoint '{endpoint}'; "
                f"stopping pagination (results may be truncated)"
            )
            break

        # Save AFTER yielding so a crash re-fetches the last page; merge dedupes on primary key.
        resumable_source_manager.save_state(PagerDutyResumeConfig(offset=offset))


def pagerduty_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PagerDutyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = PAGERDUTY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        # We always request created_at ascending where a sort is available, and full-refresh
        # endpoints replace wholesale, so ascending is correct everywhere.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
