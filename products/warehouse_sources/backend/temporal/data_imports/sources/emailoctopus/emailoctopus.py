import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.emailoctopus.settings import (
    CONTACT_STATUSES,
    EMAILOCTOPUS_ENDPOINTS,
    EmailOctopusEndpointConfig,
)

EMAILOCTOPUS_BASE_URL = "https://api.emailoctopus.com"
# The v2 API caps a page at 100 results.
PAGE_SIZE = 100


class EmailOctopusRetryableError(Exception):
    pass


@dataclasses.dataclass
class EmailOctopusResumeConfig:
    # Full next-page URL returned by the API (`paging.next.url`). Followed verbatim so the original
    # query string — including any incremental time filter — is preserved across a resume. None means
    # "start this (list, status) pair at its first page".
    next_url: str | None = None
    # Fan-out bookmark: the list and contact status currently being paged. Stable identifiers (not a
    # positional index) so lists added/removed between a crash and the retry can't resume into the
    # wrong slice. None for the non-fan-out (lists/campaigns) endpoints.
    list_id: str | None = None
    status: str | None = None
    # The incremental filter frozen at the original run's start. Reused on resume so a watermark that
    # advanced mid-sync isn't re-applied to lists we haven't reached yet (which would skip their rows).
    incremental_field: str | None = None
    filter_value: str | None = None


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value for EmailOctopus's ISO 8601 filters (e.g. 2024-01-19T12:14:28Z)."""
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _next_url(data: dict[str, Any]) -> str | None:
    """Extract `paging.next.url` from a v2 list response, or None when there are no more pages."""
    paging = data.get("paging") or {}
    nxt = paging.get("next") or {}
    return nxt.get("url")


def validate_credentials(api_key: str) -> bool:
    url = f"{EMAILOCTOPUS_BASE_URL}/lists?{urlencode({'limit': 1})}"
    try:
        session = make_tracked_session(redact_values=(api_key,))
        response = session.get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((EmailOctopusRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    params: dict[str, Any] | None = None,
) -> dict:
    response = session.get(url, headers=headers, params=params, timeout=60)

    # 429s carry an X-RateLimit-Retry-After header; the token bucket refills quickly (10/s), so an
    # exponential backoff retry recovers without parsing the header.
    if response.status_code == 429 or response.status_code >= 500:
        raise EmailOctopusRetryableError(
            f"EmailOctopus API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        # A 404 is expected when a list is deleted mid-fan-out; the caller handles it.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"EmailOctopus API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_list_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> Iterator[str]:
    """Page through /lists and yield each list's id, following the cursor links."""
    url = f"{EMAILOCTOPUS_BASE_URL}/lists"
    params: dict[str, Any] | None = {"limit": PAGE_SIZE}
    while True:
        data = _fetch_page(session, url, headers, logger, params)
        for item in data.get("data", []):
            yield item["id"]

        next_url = _next_url(data)
        if not next_url:
            break
        # Follow the full next-page URL verbatim; it already encodes the cursor and page size.
        url = next_url
        params = None


def _build_contact_params(status: str, incremental_field: str | None, filter_value: str | None) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, "status": status}
    if incremental_field and filter_value:
        # Server-side incremental filter, e.g. last_updated_at.gte=2024-01-19T12:14:28Z.
        params[f"{incremental_field}.gte"] = filter_value
    return params


def _get_top_level_rows(
    session: requests.Session,
    config: EmailOctopusEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[EmailOctopusResumeConfig],
) -> Iterator[Any]:
    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        params: dict[str, Any] | None = None
        logger.debug(f"EmailOctopus: resuming {config.name} from URL: {url}")
    else:
        url = f"{EMAILOCTOPUS_BASE_URL}{config.path}"
        params = {"limit": PAGE_SIZE}

    while True:
        data = _fetch_page(session, url, headers, logger, params)
        items = data.get("data", [])
        next_url = _next_url(data)

        for item in items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding (and only while more pages remain) so a crash re-yields the last
                # page rather than skipping it — merge dedupes on the primary key.
                if next_url:
                    manager.save_state(EmailOctopusResumeConfig(next_url=next_url))

        if not next_url:
            break
        url = next_url
        params = None


def _get_contact_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[EmailOctopusResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> Iterator[Any]:
    """Fan out over every list and contact status, yielding each contact with its `list_id` attached.

    Contacts are nested under lists and the API returns only one status at a time, so we walk every
    (list, status) pair. The [list_id, id] primary key keeps a single row per contact across statuses.
    """
    list_ids = list(_iter_list_ids(session, headers, logger))
    pairs = [(list_id, status) for list_id in list_ids for status in CONTACT_STATUSES]

    resume = manager.load_state() if manager.can_resume() else None
    if resume is not None:
        # Reuse the filter frozen at the original run's start. The incremental watermark can advance
        # mid-sync; recomputing it here would over-filter lists we haven't reached yet.
        filter_field = resume.incremental_field
        filter_value = resume.filter_value
    else:
        filter_field = incremental_field if should_use_incremental_field else None
        filter_value = (
            _format_incremental_value(db_incremental_field_last_value)
            if should_use_incremental_field and db_incremental_field_last_value and incremental_field
            else None
        )

    # Resolve the saved (list_id, status) bookmark to the remaining slice. If the bookmarked list no
    # longer exists, start over from the first pair — merge dedupes the re-pulled rows.
    start = 0
    resume_url: str | None = None
    if resume is not None and resume.list_id is not None and resume.status is not None:
        try:
            start = pairs.index((resume.list_id, resume.status))
            resume_url = resume.next_url
            logger.debug(f"EmailOctopus: resuming contacts from list_id={resume.list_id}, status={resume.status}")
        except ValueError:
            start = 0
    remaining = pairs[start:]

    for index, (list_id, status) in enumerate(remaining):
        if index == 0 and resume_url:
            url = resume_url
            params: dict[str, Any] | None = None
        else:
            url = f"{EMAILOCTOPUS_BASE_URL}/lists/{list_id}/contacts"
            params = _build_contact_params(status, filter_field, filter_value)

        try:
            while True:
                data = _fetch_page(session, url, headers, logger, params)
                items = data.get("data", [])
                next_url = _next_url(data)

                for item in items:
                    item["list_id"] = list_id
                    batcher.batch(item)
                    if batcher.should_yield():
                        yield batcher.get_table()
                        if next_url:
                            manager.save_state(
                                EmailOctopusResumeConfig(
                                    next_url=next_url,
                                    list_id=list_id,
                                    status=status,
                                    incremental_field=filter_field,
                                    filter_value=filter_value,
                                )
                            )

                if not next_url:
                    break
                url = next_url
                params = None
        except requests.HTTPError as exc:
            # A list deleted between enumeration and this fetch 404s. Skip it rather than failing the
            # whole sync — the membership is genuinely gone. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"EmailOctopus: list {list_id} not found while fetching contacts, skipping")
            else:
                raise

        # Flush residual batcher items before advancing the bookmark so a crash between pairs can't
        # silently drop rows that are buffered (below a full chunk) but not yet yielded — on resume we
        # start at the next pair and would never re-fetch them.
        if batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()

        # Advance the bookmark to the next pair so a crash between pairs resumes correctly; its first
        # page is built fresh (next_url=None) when the loop reaches it.
        if index + 1 < len(remaining):
            next_list_id, next_status = remaining[index + 1]
            manager.save_state(
                EmailOctopusResumeConfig(
                    next_url=None,
                    list_id=next_list_id,
                    status=next_status,
                    incremental_field=filter_field,
                    filter_value=filter_value,
                )
            )


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EmailOctopusResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = EMAILOCTOPUS_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page (and, for fan-out, every list) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. Redact the API key so it can't leak
    # into logged URLs or sampled requests via the Bearer auth header.
    session = make_tracked_session(redact_values=(api_key,))

    if config.fan_out_over_lists:
        yield from _get_contact_rows(
            session,
            headers,
            logger,
            batcher,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
            incremental_field,
        )
    else:
        yield from _get_top_level_rows(session, config, headers, logger, batcher, resumable_source_manager)

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def emailoctopus_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EmailOctopusResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = EMAILOCTOPUS_ENDPOINTS[endpoint]

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
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # The v2 contacts endpoint paginates with an opaque cursor and does not document an ascending
        # sort guarantee. "asc" is the safe default: the incremental fields are monotonic wall-clock
        # timestamps, and the resumable cursor (not the watermark) drives mid-sync continuation.
        sort_mode="asc",
    )
