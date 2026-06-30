import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.settings import (
    BLOGGER_ENDPOINTS,
    BloggerEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BLOGGER_BASE_URL = "https://www.googleapis.com/blogger/v3"
# Blogger caps `maxResults` per resource; 100 is comfortably within the limits for posts/comments/pages.
DEFAULT_PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60


class BloggerRetryableError(Exception):
    """Raised for transient Blogger API failures (429 / 5xx) that tenacity should retry."""


@dataclasses.dataclass
class BloggerResumeConfig:
    # Blogger paginates with an opaque `pageToken`; persisting it lets a heartbeat-timed-out sync pick
    # back up at the next page instead of restarting the endpoint.
    page_token: str | None = None


def _format_rfc3339(value: Any) -> str:
    """Format a datetime/date as an RFC 3339 UTC timestamp, which Blogger's date filters require."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def _raise_sanitized_for_status(response: requests.Response) -> None:
    """Mirror `requests.Response.raise_for_status()` but strip the URL's query string before it lands
    in an exception message. Blogger carries the API key in `?key=...`, and these import errors are
    logged and captured by the shared non-retryable error handler — so the raw `raise_for_status()`
    message would leak the key. The sanitized URL keeps the stable `.../blogger/v3` prefix that
    `BloggerSource.get_non_retryable_errors()` matches on, so error classification is unaffected."""
    if response.ok:
        return
    kind = "Client Error" if response.status_code < 500 else "Server Error"
    safe_url = urlsplit(response.url)._replace(query="").geturl()
    raise requests.HTTPError(f"{response.status_code} {kind}: {response.reason} for url: {safe_url}", response=response)


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{BLOGGER_BASE_URL}{path}?{urlencode(params)}"


def _build_params(
    config: BloggerEndpointConfig,
    api_key: str,
    page_token: str | None,
    start_date: str | None,
) -> dict[str, Any]:
    # The Google API key always rides as the `key` query param (Blogger has no header form for it).
    params: dict[str, Any] = {"key": api_key}
    if config.is_single_object:
        return params

    params["maxResults"] = DEFAULT_PAGE_SIZE
    if config.order_by:
        params["orderBy"] = config.order_by
    if start_date:
        params["startDate"] = start_date
    if page_token:
        params["pageToken"] = page_token
    return params


@retry(
    retry=retry_if_exception_type((BloggerRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise BloggerRetryableError(f"Blogger API error (retryable): status={response.status_code}")

    if not response.ok:
        logger.error(f"Blogger API error: status={response.status_code}, body={response.text}")
        _raise_sanitized_for_status(response)

    return response.json()


def validate_credentials(api_key: str, blog_id: str) -> tuple[bool, str | None]:
    """Probe `blogs.get` for the configured blog. This confirms both the API key and that the key can
    read the target blog in a single cheap request."""
    url = _build_url(f"/blogs/{blog_id}", {"key": api_key})
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_headers(), timeout=10)
    except Exception:
        return False, "Could not reach the Blogger API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (400, 401, 403):
        return False, "Your Blogger API key is invalid or does not have access to this blog."
    if response.status_code == 404:
        return False, "No Blogger blog was found for that blog ID."
    return False, f"The Blogger API returned an unexpected error (status {response.status_code})."


def get_rows(
    api_key: str,
    blog_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BloggerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = BLOGGER_ENDPOINTS[endpoint]
    # One session reused across every page so urllib3 keeps the connection alive. The API key is in the
    # query string, so register it for redaction in logged URLs and captured samples.
    session = make_tracked_session(redact_values=(api_key,))
    headers = _headers()

    if config.is_single_object:
        data = _fetch_page(session, _build_url(config.path.format(blog_id=blog_id), {"key": api_key}), headers, logger)
        yield [data]
        return

    # `startDate` is the only server-side filter Blogger offers; map the user's incremental cursor
    # (always `published`) onto it. On first sync there's no last value, so we pull full history.
    start_date: str | None = None
    if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value:
        start_date = _format_rfc3339(db_incremental_field_last_value)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_token = resume.page_token if resume is not None else None

    base_path = config.path.format(blog_id=blog_id)
    while True:
        url = _build_url(base_path, _build_params(config, api_key, page_token, start_date))
        data = _fetch_page(session, url, headers, logger)

        items = data.get("items", [])
        next_token = data.get("nextPageToken")

        if items:
            yield items
            # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last page
            # rather than skipping it — merge dedupes on the primary key.
            if next_token:
                resumable_source_manager.save_state(BloggerResumeConfig(page_token=next_token))

        if not next_token:
            break
        page_token = next_token


def blogger_source(
    api_key: str,
    blog_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BloggerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = BLOGGER_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            blog_id=blog_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        # Blogger only returns list results newest-first (its sort-direction param is unavailable), so
        # incremental endpoints scroll descending. Full-refresh endpoints don't care about order.
        sort_mode="desc" if config.supports_incremental else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
