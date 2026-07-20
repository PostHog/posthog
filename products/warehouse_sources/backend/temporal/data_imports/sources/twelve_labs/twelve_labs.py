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
from products.warehouse_sources.backend.temporal.data_imports.sources.twelve_labs.settings import (
    TWELVE_LABS_ENDPOINTS,
    TwelveLabsEndpointConfig,
)

TWELVE_LABS_BASE_URL = "https://api.twelvelabs.io/v1.3"

# Max page size the API allows; larger values are rejected.
PAGE_LIMIT = 50

REQUEST_TIMEOUT_SECONDS = 60


class TwelveLabsRetryableError(Exception):
    pass


@dataclasses.dataclass
class TwelveLabsResumeConfig:
    # Next page number to request (1-based). None means "start at page 1".
    next_page: int | None = None
    # The index currently being processed by the videos fan-out. A stable index-id bookmark (not a
    # positional slice) so indexes added/removed between a crash and the retry can't resume us into
    # the wrong index. None for the standard (non-fan-out) endpoints.
    index_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "Accept": "application/json"}


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor as an RFC 3339 timestamp with a Z suffix."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return str(value)


def _build_params(
    config: TwelveLabsEndpointConfig,
    page: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build query params for a single page request.

    Page-number pagination means the `created_at` / `updated_at` filter can be applied on every
    page (unlike cursor APIs that only window the first page), so incremental syncs stay bounded
    without any client-side watermark termination.
    """
    params: dict[str, Any] = {"page": page, "page_limit": PAGE_LIMIT}

    # `sort_by` defaults to the endpoint's advertised cursor field but always honors the user's
    # selection. Ascending sort makes the pipeline watermark advance correctly (sort_mode="asc").
    filter_field = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)

    if should_use_incremental_field and filter_field:
        params["sort_by"] = filter_field
        params["sort_option"] = "asc"
        if db_incremental_field_last_value:
            # `created_at` / `updated_at` filter at-or-after the given value; the boundary row is
            # re-fetched each sync and merge dedupes it on the primary key.
            params[filter_field] = _format_incremental_value(db_incremental_field_last_value)
    else:
        # Full refresh: sort ascending on the stable creation field so page boundaries don't skip
        # or duplicate rows if the library grows mid-sync.
        params["sort_by"] = config.partition_key or "created_at"
        params["sort_option"] = "asc"

    return params


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{TWELVE_LABS_BASE_URL}{path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type(
        (
            TwelveLabsRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (per-category rate limit) and transient 5xx are retryable; the API exposes X-RateLimit-*
    # headers but exponential jitter backoff is enough to stay under the window.
    if response.status_code == 429 or response.status_code >= 500:
        raise TwelveLabsRetryableError(f"Twelve Labs API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Twelve Labs API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe /indexes to confirm the API key is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error so the caller
    can tell a rejected key (401/403) apart from a transient outage (429/5xx/network) and avoid
    reporting a valid key as invalid during a rate-limit or downtime window.
    """
    url = _build_url("/indexes", {"page": 1, "page_limit": 1})
    try:
        # Redact the key from tracked telemetry and refuse redirects so a 30x can never replay the
        # `x-api-key` header to another origin.
        session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
        response = session.get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code


def _iter_index_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> Iterator[str]:
    """Page through /indexes and yield each index id, for the videos fan-out."""
    page = 1
    while True:
        data = _fetch_page(session, _build_url("/indexes", {"page": page, "page_limit": PAGE_LIMIT}), headers, logger)
        for item in data.get("data", []):
            yield item["_id"]

        page_info = data.get("page_info", {})
        total_page = page_info.get("total_page", page)
        if page >= total_page:
            break
        page += 1


def _iter_pages(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    path: str,
    base_params: dict[str, Any],
    start_page: int,
) -> Iterator[tuple[list[dict[str, Any]], int | None]]:
    """Yield ``(rows, next_page)`` for each page, following page_info.total_page.

    ``next_page`` is None on the final page so the caller knows not to persist resume state past
    the end of the list.
    """
    page = start_page
    while True:
        params = {**base_params, "page": page}
        data = _fetch_page(session, _build_url(path, params), headers, logger)

        rows = data.get("data", [])
        page_info = data.get("page_info", {})
        total_page = page_info.get("total_page", page)
        next_page = page + 1 if page < total_page else None

        yield rows, next_page

        if next_page is None:
            break
        page = next_page


def _get_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TwelveLabsResumeConfig],
    config: TwelveLabsEndpointConfig,
    base_params: dict[str, Any],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every index, yielding that index's videos with the parent ``index_id`` injected.

    The [index_id, _id] primary key keeps rows unique table-wide, so videos from different indexes
    never collide and merge dedupes cleanly.
    """
    index_ids = list(_iter_index_ids(session, headers, logger))

    # Resolve the saved index-id bookmark to the slice still to process. If the bookmarked index no
    # longer exists (deleted between runs), start over from the first index — full refresh replaces
    # on the primary key anyway.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = index_ids
    resume_page = 1
    if resume is not None and resume.index_id is not None and resume.index_id in index_ids:
        remaining = index_ids[index_ids.index(resume.index_id) :]
        resume_page = resume.next_page or 1
        logger.debug(f"Twelve Labs: resuming videos from index_id={resume.index_id}, page={resume_page}")

    for position, index_id in enumerate(remaining):
        path = config.path.format(index_id=index_id)
        start_page = resume_page if position == 0 else 1

        for rows, next_page in _iter_pages(session, headers, logger, path, base_params, start_page):
            yield [{**row, "index_id": index_id} for row in rows]

            # Save AFTER yielding so a crash re-yields the last page rather than skipping it.
            if next_page is not None:
                resumable_source_manager.save_state(TwelveLabsResumeConfig(next_page=next_page, index_id=index_id))

        # Advance the bookmark to the next index so a crash between indexes resumes correctly.
        if position + 1 < len(remaining):
            resumable_source_manager.save_state(TwelveLabsResumeConfig(next_page=1, index_id=remaining[position + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TwelveLabsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = TWELVE_LABS_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page (and, for fan-out, every index) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. The key is redacted from tracked
    # telemetry and redirects are refused so a 30x can't replay `x-api-key` to another origin.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)

    base_params = _build_params(
        config, 1, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )
    base_params.pop("page", None)

    if config.fan_out_over_indexes:
        yield from _get_fan_out_rows(session, headers, logger, resumable_source_manager, config, base_params)
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    start_page = resume.next_page if resume is not None and resume.next_page else 1

    for rows, next_page in _iter_pages(session, headers, logger, config.path, base_params, start_page):
        yield rows

        if next_page is not None:
            resumable_source_manager.save_state(TwelveLabsResumeConfig(next_page=next_page))


def twelve_labs_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[TwelveLabsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = TWELVE_LABS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        # Every list endpoint is requested with sort_option=asc, so rows arrive oldest-first and the
        # pipeline can checkpoint the incremental watermark after each batch.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
