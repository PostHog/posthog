import dataclasses
from collections.abc import Iterator
from typing import Any, Literal, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.notion.settings import (
    NOTION_ENDPOINTS,
    NOTION_PAGE_SIZE,
    NotionEndpointConfig,
)

NOTION_BASE_URL = "https://api.notion.com"
# Pinned API version. 2025-09-03 is the current official SDK default and introduces the
# data sources model: a "database" is a container, and the schema-bearing tables are
# "data sources". For the endpoints we use this only changes the search object filter
# ("database" -> "data_source"); users/blocks/comments are unaffected.
NOTION_VERSION = "2025-09-03"

CHUNK_SIZE = 2000
CHUNK_SIZE_BYTES = 100 * 1024 * 1024

# Bounds for the fan-out streams (blocks/comments). Notion is rate limited to ~3 req/s, so deep
# recursion and unbounded child pagination would make syncs prohibitively slow.
MAX_BLOCK_DEPTH = 2
MAX_CHILD_PAGES_PER_PARENT = 50

MAX_RETRY_WAIT_SECONDS = 30.0
# Notion can ask us to back off for several minutes via Retry-After under sustained load (values
# of 5+ minutes are common). Honor that instruction up to this bound instead of retrying early and
# getting throttled again — retrying inside the penalty window just burns attempts and can extend
# the penalty. Blocking this long is safe: the import activity has a week-long timeout and
# heartbeats on an independent timer, so a waiting request won't trip the heartbeat. The bound is a
# backstop against a pathologically large Retry-After.
MAX_RETRY_AFTER_SECONDS = 600.0


class NotionRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class NotionNotFoundError(Exception):
    """Notion returned 404 for a resource: the page/block was deleted or is no longer shared with
    the integration. In the per-page fan-out streams (blocks/comments) a single page going missing
    is recoverable — skip it and keep syncing the rest rather than crashing the whole sync."""


class NotionBadRequestError(Exception):
    """Notion returned 400 for a per-page resource. Some blocks advertise has_children but cannot be
    expanded via the API (e.g. blocks backed by synced/external content), so Notion rejects the
    children request. Like a 404, this is recoverable in the fan-out streams (blocks/comments): skip
    the offending block/page and keep syncing rather than crashing the whole sync."""


@dataclasses.dataclass
class NotionResumeConfig:
    next_cursor: str


def _get_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _build_session(token: str) -> requests.Session:
    # Disable the tracked session's built-in urllib3 retries so tenacity is the single retry layer;
    # one session is reused across every request of a stream to keep connection pooling/keep-alive.
    return make_tracked_session(headers=_get_headers(token), redact_values=(token,), retry=Retry(total=0))


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


_wait_exponential = wait_exponential_jitter(initial=1, max=MAX_RETRY_WAIT_SECONDS)


def _wait_strategy(retry_state: RetryCallState) -> float:
    # Honor Notion's Retry-After on 429s; fall back to exponential backoff otherwise.
    exc = retry_state.outcome.exception() if retry_state.outcome is not None else None
    if isinstance(exc, NotionRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
    return _wait_exponential(retry_state)


@retry(
    # ChunkedEncodingError is a sibling of ConnectionError (both RequestException, not subclasses of
    # each other): Notion can break the connection mid-response, surfacing as a malformed chunk
    # ("Connection broken: InvalidChunkLength"). It is a transient connection failure like the others,
    # so retry it rather than letting it crash the sync.
    retry=retry_if_exception_type(
        (
            NotionRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=_wait_strategy,
    reraise=True,
)
def _request(
    session: requests.Session,
    method: Literal["GET", "POST"],
    path: str,
    logger: FilteringBoundLogger,
    *,
    json_body: Optional[dict[str, Any]] = None,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    url = f"{NOTION_BASE_URL}{path}"
    response = session.request(method, url, json=json_body, params=params, timeout=60)

    if response.status_code == 429:
        retry_after = _parse_retry_after(response.headers.get("Retry-After"))
        raise NotionRetryableError(f"Notion rate limited: url={url}, retry_after={retry_after}", retry_after)

    if response.status_code >= 500:
        raise NotionRetryableError(f"Notion API error (retryable): status={response.status_code}, url={url}")

    # A 404 on a per-page resource (a page's comments or block children) means that page was deleted
    # or unshared between enumeration and fetch. The fan-out streams catch this and skip the page;
    # on the collection endpoints (search/users) it is unexpected and propagates as a sync failure.
    if response.status_code == 404:
        raise NotionNotFoundError(f"Notion resource not found: url={url}")

    # A 400 on a per-page resource (block children) means Notion rejects expanding that specific
    # block even though it advertised has_children. The fan-out streams skip it; on the collection
    # endpoints (search/users) a 400 is a genuine bad request and propagates as a sync failure.
    if response.status_code == 400:
        # Carry Notion's error body so callers can log its `code`/`message` (e.g. `validation_error`),
        # which distinguishes the known has_children quirk from an unexpected 400.
        raise NotionBadRequestError(f"Notion rejected request: url={url}, body={response.text}")

    if not response.ok:
        logger.error(f"Notion API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(token: str) -> tuple[bool, str | None]:
    try:
        session = make_tracked_session(headers=_get_headers(token), redact_values=(token,))
        response = session.get(f"{NOTION_BASE_URL}/v1/users/me", timeout=10)
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Notion integration token"
    if response.status_code == 403:
        return False, "Notion integration token is missing the required capabilities"
    return False, f"Notion API error: HTTP {response.status_code}"


def _search_body(object_filter: str, cursor: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "filter": {"property": "object", "value": object_filter},
        "sort": {"timestamp": "last_edited_time", "direction": "ascending"},
        "page_size": NOTION_PAGE_SIZE,
    }
    if cursor:
        body["start_cursor"] = cursor
    return body


def _search_stream(
    session: requests.Session,
    config: NotionEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
) -> Iterator[Any]:
    assert config.object_filter is not None
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.next_cursor if resume is not None else None

    while True:
        data = _request(session, "POST", "/v1/search", logger, json_body=_search_body(config.object_filter, cursor))
        results = data.get("results", [])
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

        for item in results:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                if has_more and next_cursor:
                    resumable_source_manager.save_state(NotionResumeConfig(next_cursor=next_cursor))

        if not has_more or not next_cursor:
            break
        cursor = next_cursor

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def _users_stream(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
) -> Iterator[Any]:
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.next_cursor if resume is not None else None

    while True:
        params: dict[str, Any] = {"page_size": NOTION_PAGE_SIZE}
        if cursor:
            params["start_cursor"] = cursor

        data = _request(session, "GET", "/v1/users", logger, params=params)
        results = data.get("results", [])
        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

        for item in results:
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                if has_more and next_cursor:
                    resumable_source_manager.save_state(NotionResumeConfig(next_cursor=next_cursor))

        if not has_more or not next_cursor:
            break
        cursor = next_cursor

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def _iter_page_ids(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[str]:
    cursor: str | None = None
    while True:
        data = _request(session, "POST", "/v1/search", logger, json_body=_search_body("page", cursor))
        for item in data.get("results", []):
            # "id" is the primary key driving the blocks/comments fan-out; access it directly so a
            # malformed response missing it surfaces loudly instead of silently dropping the page.
            yield item["id"]
        if not data.get("has_more") or not data.get("next_cursor"):
            break
        cursor = data["next_cursor"]


def _iter_block_children(
    session: requests.Session,
    block_id: str,
    page_id: str,
    logger: FilteringBoundLogger,
    depth: int,
) -> Iterator[dict[str, Any]]:
    cursor: str | None = None
    pages_fetched = 0
    while True:
        params: dict[str, Any] = {"page_size": NOTION_PAGE_SIZE}
        if cursor:
            params["start_cursor"] = cursor

        try:
            data = _request(session, "GET", f"/v1/blocks/{block_id}/children", logger, params=params)
        except NotionNotFoundError:
            logger.warning(
                "Notion: skipping missing or unshared block while fetching children",
                page_id=page_id,
                block_id=block_id,
            )
            return
        except NotionBadRequestError as e:
            logger.warning(
                "Notion: skipping block whose children Notion rejected",
                page_id=page_id,
                block_id=block_id,
                error=str(e),
            )
            return
        for block in data.get("results", []):
            block["_page_id"] = page_id
            yield block
            if block.get("has_children") and depth < MAX_BLOCK_DEPTH:
                yield from _iter_block_children(session, block["id"], page_id, logger, depth + 1)

        pages_fetched += 1
        if not data.get("has_more") or not data.get("next_cursor"):
            break
        if pages_fetched >= MAX_CHILD_PAGES_PER_PARENT:
            logger.warning(
                "Notion: reached block children page cap for parent",
                page_id=page_id,
                block_id=block_id,
                cap=MAX_CHILD_PAGES_PER_PARENT,
            )
            break
        cursor = data["next_cursor"]


def _blocks_stream(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[Any]:
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    for page_id in _iter_page_ids(session, logger):
        for block in _iter_block_children(session, page_id, page_id, logger, 0):
            batcher.batch(block)
            if batcher.should_yield():
                yield batcher.get_table()

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def _comments_stream(session: requests.Session, logger: FilteringBoundLogger) -> Iterator[Any]:
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    for page_id in _iter_page_ids(session, logger):
        cursor: str | None = None
        pages_fetched = 0
        while True:
            params: dict[str, Any] = {"block_id": page_id, "page_size": NOTION_PAGE_SIZE}
            if cursor:
                params["start_cursor"] = cursor

            try:
                data = _request(session, "GET", "/v1/comments", logger, params=params)
            except NotionNotFoundError:
                logger.warning(
                    "Notion: skipping comments for missing or unshared page",
                    page_id=page_id,
                )
                break
            except NotionBadRequestError as e:
                logger.warning(
                    "Notion: skipping comments Notion rejected for page",
                    page_id=page_id,
                    error=str(e),
                )
                break
            for comment in data.get("results", []):
                comment["_page_id"] = page_id
                batcher.batch(comment)
                if batcher.should_yield():
                    yield batcher.get_table()

            pages_fetched += 1
            if not data.get("has_more") or not data.get("next_cursor"):
                break
            if pages_fetched >= MAX_CHILD_PAGES_PER_PARENT:
                logger.warning(
                    "Notion: reached comments page cap for parent",
                    page_id=page_id,
                    cap=MAX_CHILD_PAGES_PER_PARENT,
                )
                break
            cursor = data["next_cursor"]

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def get_rows(
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
) -> Iterator[Any]:
    config = NOTION_ENDPOINTS[endpoint]
    session = _build_session(token)

    if config.stream_type == "search":
        yield from _search_stream(session, config, logger, resumable_source_manager)
    elif config.stream_type == "users":
        yield from _users_stream(session, logger, resumable_source_manager)
    elif config.stream_type == "blocks":
        yield from _blocks_stream(session, logger)
    elif config.stream_type == "comments":
        yield from _comments_stream(session, logger)
    else:
        raise ValueError(f"Unknown Notion stream type: {config.stream_type}")


def notion_source(
    token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
) -> SourceResponse:
    config = NOTION_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            token=token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=["id"],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
