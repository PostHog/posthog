import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.float_app.settings import (
    DELETE_LOG_LIMIT,
    FLOAT_ENDPOINTS,
    PER_PAGE,
    FloatEndpointConfig,
)

FLOAT_BASE_URL = "https://api.float.com/v3"
# Float rejects requests without a User-Agent that identifies the app and a contact email. This is a
# static integration identifier, not user data, so it's hardcoded rather than surfaced as a form field.
USER_AGENT = "PostHog Data Warehouse (hey@posthog.com)"


class FloatRetryableError(Exception):
    pass


@dataclasses.dataclass
class FloatAppResumeConfig:
    # Page-number endpoints resume from `next_page` (1-indexed); Delete Log endpoints resume from the
    # opaque `next_cursor`. Only one is set per endpoint. None means "start from the beginning".
    next_page: int | None = None
    next_cursor: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{FLOAT_BASE_URL}{path}"
    return f"{FLOAT_BASE_URL}{path}?{urlencode(params)}"


def _header_int(headers: Any, name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    """Float list endpoints return a bare JSON array. Guard against a wrapped shape defensively."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


@retry(
    retry=retry_if_exception_type((FloatRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> requests.Response:
    response = session.get(url, headers=headers, timeout=60)

    # Float enforces 200 GET/min (burst 10/sec) and returns 429 with a `ratelimit-reset` header on
    # exceed. Back off and retry rather than failing the sync; transient 5xx are retryable too.
    if response.status_code == 429 or response.status_code >= 500:
        raise FloatRetryableError(f"Float API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Float API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def _get_page_rows(
    session: requests.Session,
    config: FloatEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[FloatAppResumeConfig],
    resume: FloatAppResumeConfig | None,
) -> Iterator[Any]:
    page = resume.next_page if resume is not None and resume.next_page else 1
    if page > 1:
        logger.debug(f"Float: resuming {config.name} from page {page}")

    while True:
        response = _fetch_page(session, _build_url(config.path, {"per-page": PER_PAGE, "page": page}), headers, logger)
        items = _extract_items(response.json())
        if not items:
            break

        # Prefer Float's `X-Pagination-Pages` header; fall back to a full-page heuristic if it's absent.
        total_pages = _header_int(response.headers, "X-Pagination-Pages")
        has_more = page < total_pages if total_pages is not None else len(items) >= PER_PAGE

        for item in items:
            batcher.batch(item)

        # Yield and save state only after the whole page is batched, so the resume pointer never
        # advances past a page whose items are still buffered — a mid-page save could skip the
        # remaining items of the current page on a crash-resume. Save AFTER yielding so a crash
        # re-yields rather than skips (merge dedupes on the primary key).
        if batcher.should_yield():
            yield batcher.get_table()
            if has_more:
                resumable_source_manager.save_state(FloatAppResumeConfig(next_page=page + 1))

        if not has_more:
            break
        page += 1


def _get_cursor_rows(
    session: requests.Session,
    config: FloatEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    resumable_source_manager: ResumableSourceManager[FloatAppResumeConfig],
    resume: FloatAppResumeConfig | None,
) -> Iterator[Any]:
    """Walk the cursor-paginated Delete Log endpoints.

    Termination is defensive: we stop on a missing/blank/repeated `X-Pagination-Next-Cursor`, an explicit
    `X-Pagination-Has-More=false`, or a short page. That guarantees the loop ends even if the delete-log
    pagination header names differ from the documented ones (they can't be verified without a live token).
    """
    cursor = resume.next_cursor if resume is not None else None

    while True:
        params: dict[str, Any] = {"limit": DELETE_LOG_LIMIT}
        if cursor:
            params["cursor"] = cursor
        response = _fetch_page(session, _build_url(config.path, params), headers, logger)
        items = _extract_items(response.json())

        next_cursor = response.headers.get("X-Pagination-Next-Cursor") or None
        has_more_header = response.headers.get("X-Pagination-Has-More")
        has_more_false = has_more_header is not None and str(has_more_header).strip().lower() in ("false", "0", "no")

        page_full = len(items) >= DELETE_LOG_LIMIT
        advances = bool(next_cursor) and next_cursor != cursor
        keep_going = page_full and advances and not has_more_false

        if page_full and not advances:
            logger.warning(
                f"Float: {config.name} returned a full page with no advancing cursor; stopping to avoid a loop"
            )

        for item in items:
            batcher.batch(item)

        # Same page-boundary discipline as the page paginator: only advance the saved cursor after
        # the whole page has been batched, so a crash-resume can't skip the current page's tail.
        if batcher.should_yield():
            yield batcher.get_table()
            if keep_going:
                resumable_source_manager.save_state(FloatAppResumeConfig(next_cursor=next_cursor))

        if not keep_going:
            break
        cursor = next_cursor


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FloatAppResumeConfig],
) -> Iterator[Any]:
    config = FLOAT_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.pagination == "cursor":
        yield from _get_cursor_rows(session, config, headers, logger, batcher, resumable_source_manager, resume)
    else:
        yield from _get_page_rows(session, config, headers, logger, batcher, resumable_source_manager, resume)

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def float_app_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FloatAppResumeConfig],
) -> SourceResponse:
    config = FLOAT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe Float's `/accounts` endpoint to confirm the token is genuine.

    Returns ``(ok, status_code)``. ``status_code`` is ``None`` on a transport error. Float uses a single
    account-owner token with full access, so a 200 means the whole API is reachable.
    """
    url = _build_url("/accounts", {"per-page": 1})
    try:
        response = make_tracked_session().get(url, headers=_headers(api_key), timeout=10)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
