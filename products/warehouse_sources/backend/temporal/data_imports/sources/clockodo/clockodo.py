import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.settings import (
    CLOCKODO_ENDPOINTS,
    ENTRIES_TIME_SINCE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

# Clockodo's API is hosted at a single fixed host for every account (no per-tenant subdomain).
CLOCKODO_BASE_URL = "https://my.clockodo.com/api"

# Clockodo identifies the calling application via a mandatory header formatted
# "[application name];[email address]". We send our app name plus the connecting user's email.
EXTERNAL_APPLICATION_NAME = "PostHog"

REQUEST_TIMEOUT_SECONDS = 60


class ClockodoRetryableError(Exception):
    pass


@dataclasses.dataclass
class ClockodoResumeConfig:
    # Next 1-indexed page to fetch. Only meaningful for paginated endpoints.
    next_page: int


def _build_headers(api_user: str, api_key: str) -> dict[str, str]:
    return {
        "X-ClockodoApiUser": api_user,
        "X-ClockodoApiKey": api_key,
        "X-Clockodo-External-Application": f"{EXTERNAL_APPLICATION_NAME};{api_user}",
        "Accept": "application/json",
    }


def _format_z(dt: datetime) -> str:
    """ISO 8601 in UTC with a Z suffix, the format the entries endpoint expects."""
    utc_dt = dt.astimezone(UTC)
    return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")


@retry(
    retry=retry_if_exception_type((ClockodoRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (rate limit) and 5xx are transient — back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise ClockodoRetryableError(f"Clockodo API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Clockodo API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _endpoint_params(endpoint: str) -> dict[str, Any]:
    config = CLOCKODO_ENDPOINTS[endpoint]
    params: dict[str, Any] = dict(config.extra_params)
    if endpoint == "entries":
        # Send a wide window so every entry is in range. time_until is pushed a year past now
        # to also capture future-dated planned entries.
        params["time_since"] = ENTRIES_TIME_SINCE
        params["time_until"] = _format_z(datetime.now(UTC) + timedelta(days=365))
    return params


def get_rows(
    api_user: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClockodoResumeConfig],
) -> Iterator[Any]:
    config = CLOCKODO_ENDPOINTS[endpoint]
    headers = _build_headers(api_user, api_key)
    params = _endpoint_params(endpoint)
    url = f"{CLOCKODO_BASE_URL}/{config.path}"
    # One session reused across every page so urllib3 keeps the connection alive.
    # Redact the API key from logged URLs and captured samples — it travels in a custom
    # header the name-based scrubbers don't recognise.
    session = make_tracked_session(redact_values=(api_key,))
    batcher = Batcher(logger=logger, chunk_size=5000, chunk_size_bytes=200 * 1024 * 1024)

    if not config.paginated:
        data = _fetch_page(session, url, headers, params, logger)
        for item in data.get(config.data_key, []):
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
        if batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1

    # Oldest page whose rows aren't yet in a durably-yielded batch. Resume re-fetches from here so a
    # page's tail that hasn't been yielded is never skipped; already-yielded rows merge-dedupe on the
    # primary key. A yield flushes every batched row, so it advances this pointer to the current page.
    resume_page = page

    while True:
        params["page"] = page
        data = _fetch_page(session, url, headers, params, logger)
        items = data.get(config.data_key, [])

        # The paging block tells us the total page count; missing for unpaginated responses.
        paging = data.get("paging") or {}
        count_pages = paging.get("count_pages", page)
        has_more = page < count_pages and bool(items)

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                resume_page = page

        # Save once per page — even when the page produced no yield — so a crash resumes near where it
        # stopped instead of from page 1. We can only advance past pages whose rows are durably yielded,
        # so this points at the oldest still-unflushed page.
        resumable_source_manager.save_state(ClockodoResumeConfig(next_page=resume_page))

        if not has_more:
            break
        page += 1

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def clockodo_source(
    api_user: str,
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ClockodoResumeConfig],
) -> SourceResponse:
    config = CLOCKODO_ENDPOINTS[endpoint]
    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_user=api_user,
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
    )


def validate_credentials(api_user: str, api_key: str) -> bool:
    """Cheap probe to confirm the API user/key pair is genuine."""
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{CLOCKODO_BASE_URL}/v2/users",
            headers=_build_headers(api_user, api_key),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return response.status_code == 200
    except Exception:
        return False
