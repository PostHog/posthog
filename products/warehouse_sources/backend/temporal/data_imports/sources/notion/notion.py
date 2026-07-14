import json
import time
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

# Bounds for the fan-out streams (blocks/comments). Notion block trees are finite and acyclic, so
# this cap is not needed for termination — it is a backstop against pathological/cyclic data. It is
# set high enough that all real content (deeply nested toggles, lists, sub-pages) syncs: a low cap
# silently dropped everything below it. When the cap is actually reached we log a warning so the
# truncation is observable rather than silent. Deep recursion is affordable now that the blocks
# stream resumes across retries and paces itself under Notion's rate limit.
MAX_BLOCK_DEPTH = 30
MAX_CHILD_PAGES_PER_PARENT = 50

# Notion enforces an average of ~3 requests/second per integration. Pacing requests to this minimum
# interval keeps us under the cap proactively, avoiding the retry churn that reacting to 429s alone
# produces (each 429 burns an attempt and can extend Notion's penalty window).
NOTION_MAX_REQUESTS_PER_SECOND = 3.0
NOTION_MIN_REQUEST_INTERVAL_SECONDS = 1.0 / NOTION_MAX_REQUESTS_PER_SECOND

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
    """Notion returned 400. Two distinct cases surface as this error, told apart by the parsed
    `code`/`message`:

    - A per-page 400 (block children): some blocks advertise has_children but cannot be expanded via
      the API (e.g. blocks backed by synced/external content). Like a 404, this is recoverable in the
      fan-out streams (blocks/comments): skip the offending block/page and keep syncing.
    - A stale search/users pagination cursor: Notion invalidates the cursor when the result set
      shifts mid-enumeration (our search sorts by last_edited_time ascending, so a page edited during
      the sync moves and the persisted cursor no longer resolves). This is recoverable by restarting
      pagination — see `_is_invalid_cursor_error`."""

    def __init__(self, message: str, *, code: str | None = None, notion_message: str | None = None) -> None:
        super().__init__(message)
        # Notion's error `code` (e.g. "validation_error") and human `message`, parsed from the body so
        # callers can distinguish the has_children quirk from a stale-cursor error.
        self.code = code
        self.notion_message = notion_message


# How many times a search/users pagination may restart from the beginning after Notion invalidates
# its cursor before we give up and end the enumeration gracefully. A stale cursor is rare and
# self-clearing once the edit burst settles, so a few restarts is plenty; the bound stops a workspace
# under continuous edits from re-enumerating forever.
MAX_CURSOR_RESTARTS = 3


def _parse_error_body(body: str) -> tuple[str | None, str | None]:
    """Pull Notion's `code` and `message` out of a JSON error body, tolerating a non-JSON body."""
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return None, None
    if not isinstance(parsed, dict):
        return None, None
    code = parsed.get("code")
    message = parsed.get("message")
    return (code if isinstance(code, str) else None, message if isinstance(message, str) else None)


def _is_invalid_cursor_error(exc: NotionBadRequestError) -> bool:
    # Notion answers a stale pagination cursor with validation_error and a message naming
    # start_cursor. Match on both: the has_children quirk is also a validation_error, so the message
    # is what tells the recoverable-cursor case apart from it.
    return exc.code == "validation_error" and exc.notion_message is not None and "start_cursor" in exc.notion_message


@dataclasses.dataclass
class NotionResumeConfig:
    # Cursor-paginated streams (search, users) persist the next page cursor.
    next_cursor: str | None = None
    # The blocks fan-out persists its queue of pages still to process, head first. The head is the
    # page currently in progress: a retry re-processes it in full (blocks already written are deduped
    # on the primary key at merge) and continues with the rest, instead of restarting from page one.
    remaining_page_ids: list[str] | None = None


class _RateLimiter:
    """Proactive throttle keeping requests under Notion's average rate limit.

    Requests within a stream are issued serially by a single generator, so tracking one last-request
    timestamp and sleeping to maintain a minimum interval is enough to pace the whole run.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval = min_interval_seconds
        self._last_request_at: float | None = None

    def wait(self) -> None:
        if self._last_request_at is not None:
            sleep_for = self._min_interval - (time.monotonic() - self._last_request_at)
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._last_request_at = time.monotonic()


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
    throttle: Optional["_RateLimiter"] = None,
) -> dict[str, Any]:
    if throttle is not None:
        throttle.wait()

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

    # A 400 can mean a block that can't be expanded (fan-out streams skip it) or a stale search/users
    # pagination cursor (recovered by restarting). Parse Notion's `code`/`message` onto the error so
    # callers can tell the two apart; keep the raw body in the message for logging.
    if response.status_code == 400:
        code, notion_message = _parse_error_body(response.text)
        raise NotionBadRequestError(
            f"Notion rejected request: url={url}, body={response.text}",
            code=code,
            notion_message=notion_message,
        )

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


def _recover_stale_cursor(exc: NotionBadRequestError, restarts: int, logger: FilteringBoundLogger, stream: str) -> bool:
    """Decide how to handle a 400 raised while paginating search/users.

    Returns True to restart pagination from the beginning (caller resets its cursor to None), or
    False to end the enumeration gracefully — better a partial sync than a crashed one. Re-raises
    when the 400 is not a recoverable stale-cursor error (e.g. a genuine bad request), preserving the
    previous fail-loud behaviour for those.
    """
    if not _is_invalid_cursor_error(exc):
        raise exc
    if restarts >= MAX_CURSOR_RESTARTS:
        logger.warning(
            "Notion: search cursor still invalid after restarts; ending enumeration early",
            stream=stream,
            restarts=restarts,
            error=str(exc),
        )
        return False
    logger.warning(
        "Notion: search pagination cursor invalidated mid-run; restarting from the beginning",
        stream=stream,
        restart=restarts + 1,
        error=str(exc),
    )
    return True


def _search_stream(
    session: requests.Session,
    config: NotionEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
    throttle: Optional["_RateLimiter"] = None,
) -> Iterator[Any]:
    assert config.object_filter is not None
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.next_cursor if resume is not None else None
    restarts = 0

    while True:
        try:
            data = _request(
                session,
                "POST",
                "/v1/search",
                logger,
                json_body=_search_body(config.object_filter, cursor),
                throttle=throttle,
            )
        except NotionBadRequestError as e:
            # A stale cursor (e.g. pages edited mid-sync shifting the last_edited_time ordering) must
            # not crash the whole sync; restart pagination or end it gracefully. Duplicates re-emitted
            # by a restart are deduped on the "id" primary key at merge.
            if _recover_stale_cursor(e, restarts, logger, config.name):
                restarts += 1
                cursor = None
                continue
            break
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
    throttle: Optional["_RateLimiter"] = None,
) -> Iterator[Any]:
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.next_cursor if resume is not None else None
    restarts = 0

    while True:
        params: dict[str, Any] = {"page_size": NOTION_PAGE_SIZE}
        if cursor:
            params["start_cursor"] = cursor

        try:
            data = _request(session, "GET", "/v1/users", logger, params=params, throttle=throttle)
        except NotionBadRequestError as e:
            # A stale cursor must restart pagination or end it gracefully rather than crash the sync;
            # re-emitted duplicates are deduped on the "id" primary key at merge.
            if _recover_stale_cursor(e, restarts, logger, "users"):
                restarts += 1
                cursor = None
                continue
            break
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


def _iter_page_ids(
    session: requests.Session, logger: FilteringBoundLogger, throttle: Optional["_RateLimiter"] = None
) -> Iterator[str]:
    cursor: str | None = None
    restarts = 0
    # Track yielded ids so a restart (after a stale cursor) re-enumerates without re-driving the
    # blocks/comments fan-out over pages already emitted. The blocks stream materializes this into a
    # list up front anyway, so holding the id set here is no extra memory concern.
    seen: set[str] = set()
    while True:
        try:
            data = _request(
                session, "POST", "/v1/search", logger, json_body=_search_body("page", cursor), throttle=throttle
            )
        except NotionBadRequestError as e:
            # A stale search cursor must not crash the comments/blocks sync (the reported bug). Restart
            # enumeration from the beginning, or end it gracefully once restarts are exhausted.
            if _recover_stale_cursor(e, restarts, logger, "pages"):
                restarts += 1
                cursor = None
                continue
            break
        for item in data.get("results", []):
            # "id" is the primary key driving the blocks/comments fan-out; access it directly so a
            # malformed response missing it surfaces loudly instead of silently dropping the page.
            page_id = item["id"]
            if page_id in seen:
                continue
            seen.add(page_id)
            yield page_id
        if not data.get("has_more") or not data.get("next_cursor"):
            break
        cursor = data["next_cursor"]


def _iter_block_children(
    session: requests.Session,
    block_id: str,
    page_id: str,
    logger: FilteringBoundLogger,
    depth: int,
    throttle: Optional["_RateLimiter"] = None,
) -> Iterator[dict[str, Any]]:
    cursor: str | None = None
    pages_fetched = 0
    while True:
        params: dict[str, Any] = {"page_size": NOTION_PAGE_SIZE}
        if cursor:
            params["start_cursor"] = cursor

        try:
            data = _request(session, "GET", f"/v1/blocks/{block_id}/children", logger, params=params, throttle=throttle)
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
            if block.get("has_children"):
                if depth < MAX_BLOCK_DEPTH:
                    yield from _iter_block_children(session, block["id"], page_id, logger, depth + 1, throttle)
                else:
                    # Truncation at the depth backstop must be observable, not silent: without this the
                    # sync reports success while quietly leaving every block below this one behind.
                    logger.warning(
                        "Notion: block nesting exceeds max depth; deeper blocks were not synced",
                        page_id=page_id,
                        block_id=block["id"],
                        max_depth=MAX_BLOCK_DEPTH,
                    )

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


def _blocks_stream(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[NotionResumeConfig],
    throttle: Optional["_RateLimiter"] = None,
) -> Iterator[Any]:
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.remaining_page_ids is not None:
        # Resume the fan-out from the persisted queue rather than re-enumerating every page.
        page_ids = list(resume.remaining_page_ids)
        logger.debug(f"Notion: resuming blocks fan-out with {len(page_ids)} page(s) remaining")
    else:
        # Materialize the full set of page IDs up front so the fan-out position can be persisted as a
        # shrinking queue (a crash during this initial enumeration restarts it, like other sources).
        page_ids = list(_iter_page_ids(session, logger, throttle))

    while page_ids:
        page_id = page_ids[0]
        remaining = page_ids[1:]
        for block in _iter_block_children(session, page_id, page_id, logger, 0, throttle):
            batcher.batch(block)
            if batcher.should_yield():
                yield batcher.get_table()
                # Keep the in-progress page at the head: yielding flushes every buffered block from
                # already-finished pages, so only this page and the untouched rest can still be lost
                # on a crash. A retry re-fetches this page's blocks (deduped on merge), losing nothing.
                resumable_source_manager.save_state(NotionResumeConfig(remaining_page_ids=[page_id, *remaining]))
        page_ids = remaining

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def _comments_stream(
    session: requests.Session, logger: FilteringBoundLogger, throttle: Optional["_RateLimiter"] = None
) -> Iterator[Any]:
    batcher = Batcher(logger=logger, chunk_size=CHUNK_SIZE, chunk_size_bytes=CHUNK_SIZE_BYTES)

    for page_id in _iter_page_ids(session, logger, throttle):
        cursor: str | None = None
        pages_fetched = 0
        while True:
            params: dict[str, Any] = {"block_id": page_id, "page_size": NOTION_PAGE_SIZE}
            if cursor:
                params["start_cursor"] = cursor

            try:
                data = _request(session, "GET", "/v1/comments", logger, params=params, throttle=throttle)
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
    throttle = _RateLimiter(NOTION_MIN_REQUEST_INTERVAL_SECONDS)

    if config.stream_type == "search":
        yield from _search_stream(session, config, logger, resumable_source_manager, throttle)
    elif config.stream_type == "users":
        yield from _users_stream(session, logger, resumable_source_manager, throttle)
    elif config.stream_type == "blocks":
        yield from _blocks_stream(session, logger, resumable_source_manager, throttle)
    elif config.stream_type == "comments":
        yield from _comments_stream(session, logger, throttle)
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
