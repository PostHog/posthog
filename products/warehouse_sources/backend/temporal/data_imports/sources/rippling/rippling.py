import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urljoin, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.rippling.settings import RIPPLING_ENDPOINTS

RIPPLING_BASE_URL = "https://rest.ripplingapis.com"
RIPPLING_HOST = urlsplit(RIPPLING_BASE_URL).netloc
# Rippling list pages cap at 100 items.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Rippling's rate limits are not publicly documented — honor 429s with backoff.
MAX_RETRY_ATTEMPTS = 5


class RipplingRetryableError(Exception):
    pass


@dataclasses.dataclass
class RipplingResumeConfig:
    # Rippling cursor pagination returns a `next_link` URL (sometimes relative);
    # we persist it absolutized, so it's all we need to pick back up.
    next_url: str


def _get_session(api_token: str) -> requests.Session:
    return make_tracked_session(headers={"Authorization": f"Bearer {api_token}"}, redact_values=(api_token,))


def _format_filter_timestamp(value: Any) -> str:
    """Format an incremental cursor for Rippling's OData-style filter (e.g. updated_at ge 2024-10-01T00:00:00)."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00")
    return str(value)


def _build_params(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE}

    if should_use_incremental_field and db_incremental_field_last_value is not None:
        cursor_field = incremental_field or "updated_at"
        params["filter"] = f"{cursor_field} ge {_format_filter_timestamp(db_incremental_field_last_value)}"
        # Ascending order on the cursor field so the incremental watermark
        # advances monotonically as pages are consumed (order_by defaults to asc).
        params["order_by"] = cursor_field
    else:
        # Full refresh: a stable creation-time sort prevents page-boundary
        # skips/duplicates if rows change mid-sync.
        params["order_by"] = "created_at"

    return params


def _absolutize_next_url(next_link: str) -> str:
    """Absolutize a pagination link against the Rippling host, rejecting off-domain targets.

    The session carries the user's bearer token in its default headers, so a malicious or
    buggy `next_link` pointing at another host could leak that token. Only https URLs on the
    Rippling API host (or relative paths resolving to it) are allowed."""
    next_url = urljoin(RIPPLING_BASE_URL, next_link)
    parts = urlsplit(next_url)
    if parts.scheme != "https" or parts.netloc != RIPPLING_HOST:
        raise ValueError(f"Rippling pagination link points off-domain: {next_link}")
    return next_url


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{RIPPLING_BASE_URL}{path}"
    return f"{RIPPLING_BASE_URL}{path}?{urlencode(params)}"


def validate_credentials(api_token: str) -> bool:
    """Confirm the API token is valid with a cheap one-company listing probe.

    Scoped tokens may lack individual dataset scopes (403); only 401 means the
    token itself is bad, so 403 is accepted at source-create time."""
    try:
        response = _get_session(api_token).get(
            _build_url("/companies", {"limit": 1}),
            timeout=10,
        )
        return response.status_code != 401
    except Exception:
        return False


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RipplingResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = RIPPLING_ENDPOINTS[endpoint]
    session = _get_session(api_token)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = resume_config.next_url
        logger.debug(f"Rippling: resuming {endpoint} from URL: {url}")
    else:
        url = _build_url(
            config.path,
            _build_params(should_use_incremental_field, db_incremental_field_last_value, incremental_field),
        )

    @retry(
        retry=retry_if_exception_type((RipplingRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise RipplingRetryableError(
                f"Rippling API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Rippling API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)
        items = data.get("results", []) or []

        if items:
            yield items

        next_link = data.get("next_link")
        if not next_link:
            break

        # next_link can be a relative path; absolutize against the API host and
        # reject any off-domain target before reusing the token-bearing session.
        next_url = _absolutize_next_url(next_link)
        # Save state AFTER yielding the page so a crash re-yields the last page
        # (merge dedupes on primary key) rather than skipping it.
        resumable_source_manager.save_state(RipplingResumeConfig(next_url=next_url))
        url = next_url


def rippling_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RipplingResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = RIPPLING_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
