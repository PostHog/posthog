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
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.settings import (
    ROARK_ENDPOINTS,
    RoarkEndpointConfig,
)

ROARK_BASE_URL = "https://api.roark.ai/v1"


class RoarkRetryableError(Exception):
    pass


@dataclasses.dataclass
class RoarkResumeConfig:
    # Cursor (`after`) that fetched the page currently being processed. `None` means "start at the
    # first page". Saved so a crash mid-page resumes by re-fetching that same page; merge dedupes the
    # rows already written on the primary key.
    after: str | None = None
    # Offset that fetched the page currently being processed, for the offset-paginated endpoints.
    offset: int | None = None


@dataclasses.dataclass
class _Page:
    items: list[dict[str, Any]]
    # State to persist if a batch is yielded while processing this page, so a resume re-fetches it.
    resume_state: RoarkResumeConfig


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    url = f"{ROARK_BASE_URL}{path}"
    if params:
        return f"{url}?{urlencode(params)}"
    return url


@retry(
    retry=retry_if_exception_type(
        (
            RoarkRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    # Roark documents 429s but publishes no numeric limits, so back off on 429 and transient 5xx.
    if response.status_code == 429 or response.status_code >= 500:
        raise RoarkRetryableError(f"Roark API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Roark API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(api_key: str) -> bool:
    # `/agent` is a cheap authenticated list endpoint; a 200 confirms the bearer token is genuine.
    url = _build_url("/agent", {"limit": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _base_params(config: RoarkEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.max_page_size > 0:
        params["limit"] = config.max_page_size
    if config.sort_by:
        params["sortBy"] = config.sort_by
    if config.sort_direction:
        params["sortDirection"] = config.sort_direction
    return params


def _iter_pages(
    session: requests.Session,
    headers: dict[str, str],
    config: RoarkEndpointConfig,
    logger: FilteringBoundLogger,
    resume: RoarkResumeConfig | None,
) -> Iterator[_Page]:
    base = _base_params(config)

    if config.pagination == "none":
        # Unpaginated endpoints (e.g. metric_definition) may reply with either a `{"data": [...]}`
        # envelope or a bare top-level list; treat both as the row set rather than dropping the latter.
        raw: Any = _fetch_page(session, _build_url(config.path, base), headers, logger)
        items = raw if isinstance(raw, list) else (raw.get("data", []) or [])
        yield _Page(items=items, resume_state=RoarkResumeConfig())
        return

    if config.pagination == "cursor":
        after: str | None = resume.after if resume else None
        while True:
            params = {**base, "after": after} if after else base
            data = _fetch_page(session, _build_url(config.path, params), headers, logger)
            yield _Page(items=data.get("data", []) or [], resume_state=RoarkResumeConfig(after=after))

            pagination = data.get("pagination", {}) or {}
            next_cursor = pagination.get("nextCursor")
            if not pagination.get("hasMore") or not next_cursor:
                break
            after = next_cursor
        return

    # offset pagination
    offset: int = resume.offset if resume and resume.offset else 0
    while True:
        params = {**base, "offset": offset}
        data = _fetch_page(session, _build_url(config.path, params), headers, logger)
        items = data.get("data", []) or []
        yield _Page(items=items, resume_state=RoarkResumeConfig(offset=offset))

        pagination = data.get("pagination", {}) or {}
        if not pagination.get("hasMore") or not items:
            break
        # Advance by the rows actually returned, never the requested page size: Roark may cap a page
        # below max_page_size, and jumping by the requested size would skip the rows in the gap.
        offset += len(items)


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RoarkResumeConfig],
) -> Iterator[Any]:
    config = ROARK_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        logger.debug(f"Roark: resuming {endpoint} from after={resume.after}, offset={resume.offset}")

    for page in _iter_pages(session, headers, config, logger, resume):
        for item in page.items:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding, recording the token that fetched THIS page so a crash re-fetches
                # it rather than skipping the batched-but-not-yet-yielded tail; merge dedupes on the
                # primary key.
                resumable_source_manager.save_state(page.resume_state)

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def roark_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RoarkResumeConfig],
) -> SourceResponse:
    config = ROARK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
