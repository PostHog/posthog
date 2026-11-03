import itertools
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import (
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.zep.settings import (
    ZEP_BASE_URL,
    ZEP_ENDPOINTS,
    ZepEndpointConfig,
)

# Zep's rate limits are plan-based and undocumented, so we lean on retries with backoff and honor
# any Retry-After the API sends on a 429.
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5
# The graph list endpoints return a bare JSON list and send the next page's cursor in this header.
NEXT_CURSOR_HEADER = "Zep-Next-Cursor"


class ZepRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class ZepResumeConfig:
    # Page-based endpoints (users, threads): the next 1-based page to fetch.
    page_number: int | None = None
    # thread_messages fan-out: the thread we were part-way through and the message cursor
    # (offset) to resume it at. `thread_id` is a stable id (not a positional index) so threads
    # added/removed between a crash and the retry can't resume us into the wrong thread.
    thread_id: str | None = None
    cursor: int | None = None
    # Graph fan-out (graph_edges, graph_nodes, graph_episodes): the graph to resume at and the
    # opaque page cursor within it. None for the cursor means the first page of that graph.
    graph_scope: str | None = None
    graph_owner_id: str | None = None
    graph_cursor: str | None = None
    # Set once the last graph's rows are all yielded, so a resume after that reads nothing again.
    graph_finished: bool = False


@frozen
class GraphOwner:
    scope: str  # "user" or "graph"
    owner_id: str


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Api-Key {api_key}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    url = f"{ZEP_BASE_URL}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


_retry_request = retry_with_deadline(
    retry=retry_if_exception_type(
        (
            ZepRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)


@_retry_request
def _fetch_page(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise ZepRetryableError(f"Zep API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Never log the response body: Zep error payloads can echo customer content (users,
        # threads, messages), which must stay inside the access-controlled warehouse tables.
        logger.error(f"Zep API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json()


@_retry_request
def _post_graph_page(
    session: requests.Session, url: str, headers: dict[str, str], body: dict[str, Any], logger: FilteringBoundLogger
) -> tuple[list[dict[str, Any]], str | None] | None:
    """POST one page of a graph list endpoint. Returns the rows and the next cursor, or None on a 404."""
    response = session.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise ZepRetryableError(f"Zep API error (retryable): status={response.status_code}, url={url}")

    if response.status_code == 404:
        return None

    if not response.ok:
        logger.error(f"Zep API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    return response.json() or [], response.headers.get(NEXT_CURSOR_HEADER) or None


def validate_credentials(api_key: str) -> bool:
    # A single cheap probe: 200 means the key is genuine. Any non-200 (401 "unauthorized" for a
    # bad key) means invalid. Never raises; network blips fall through to False.
    url = _build_url("/users-ordered", {"pageSize": 1})
    try:
        # capture=False: the probe returns a user record, which is customer content the
        # name-based sample scrubbers can't strip. Stay metered/logged, just don't sample the body.
        response = make_tracked_session(redact_values=(api_key,), capture=False).get(
            url, headers=_headers(api_key), timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


def _page_based_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZepResumeConfig],
    config: ZepEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Walk a page-numbered endpoint (users, threads), yielding one page of rows at a time."""
    assert config.page_number_param is not None and config.page_size_param is not None

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_number = resume.page_number if resume is not None and resume.page_number else 1

    seen = 0
    while True:
        params: dict[str, Any] = {
            config.page_size_param: config.page_size,
            config.page_number_param: page_number,
        }
        if config.order_by:
            params["order_by"] = config.order_by
            # Ascending (oldest-first) so the order matches SourceResponse.sort_mode="asc".
            params["asc"] = "true"

        data = _fetch_page(session, _build_url(config.path, params), headers, logger)
        items = data.get(config.data_key) or []
        if not items:
            break

        yield items
        seen += len(items)

        total_count = data.get("total_count")
        # A short page or reaching the reported total means the last page has been served.
        if (total_count is not None and seen >= total_count) or len(items) < config.page_size:
            break

        page_number += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; merge
        # dedupes the re-pulled rows on the primary key.
        resumable_source_manager.save_state(ZepResumeConfig(page_number=page_number))


def _iter_thread_ids(session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger) -> Iterator[str]:
    """Lazily page /threads, yielding thread ids one at a time (used to fan out into messages).

    Streaming rather than materialising the whole catalog keeps memory flat no matter how many
    threads a project has, so a large Zep project can't exhaust the sync worker.
    """
    threads_config = ZEP_ENDPOINTS["threads"]
    page_number = 1
    seen = 0
    while True:
        params: dict[str, Any] = {
            "page_size": threads_config.page_size,
            "page_number": page_number,
            "order_by": "created_at",
            "asc": "true",
        }
        data = _fetch_page(session, _build_url("/threads", params), headers, logger)
        items = data.get("threads") or []
        if not items:
            break
        for item in items:
            thread_id = item.get("thread_id")
            if thread_id is not None:
                yield thread_id
        seen += len(items)
        total_count = data.get("total_count")
        if (total_count is not None and seen >= total_count) or len(items) < threads_config.page_size:
            break
        page_number += 1


def _fan_out_message_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZepResumeConfig],
    config: ZepEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every thread, yielding its messages enriched with the parent thread id.

    Messages paginate with an integer `cursor`. The API documents `cursor` only as "Cursor for
    pagination" with no next-cursor field in the response, so we treat it as an offset (advance by
    the number of rows returned) and stop once a short page or the reported total is reached. If Zep
    ever changes cursor semantics this stays safe: merge dedupes on the message `uuid` primary key.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    resume_thread_id = resume.thread_id if resume is not None else None
    resume_cursor: int | None = resume.cursor if resume is not None and resume_thread_id is not None else None

    thread_id_iter = iter(_iter_thread_ids(session, headers, logger))

    if resume_thread_id is not None:
        # Skip forward until the bookmarked thread. Thread order (created_at asc) is stable, so the
        # bookmark's position doesn't move; seeking lazily avoids holding the full id list in memory.
        for thread_id in thread_id_iter:
            if thread_id == resume_thread_id:
                break
        else:
            # The bookmarked thread vanished before the retry (rare). Its messages are gone anyway,
            # so there's nothing to resume; the next full-refresh job re-reads every thread.
            logger.warning(f"Zep: resume thread_id={resume_thread_id} no longer present, ending thread_messages")
            return
        logger.debug(f"Zep: resuming thread_messages from thread_id={resume_thread_id}, cursor={resume_cursor}")
        # Re-inject the matched thread so it's processed below rather than skipped.
        thread_id_iter = itertools.chain([resume_thread_id], thread_id_iter)

    # Keep one id of lookahead so we can bookmark the *next* thread without knowing the total count.
    current = next(thread_id_iter, None)
    cursor = resume_cursor or 0
    while current is not None:
        nxt = next(thread_id_iter, None)
        thread_id = current
        # thread_id is a user-defined string; escape path-significant characters (/, ?, #) so it
        # can't break out of its path segment and hit the wrong URL.
        path = config.path.format(thread_id=quote(thread_id, safe=""))

        seen = 0
        while True:
            params: dict[str, Any] = {"limit": config.page_size}
            if cursor:
                params["cursor"] = cursor

            data = _fetch_page(session, _build_url(path, params), headers, logger)
            items = data.get(config.data_key) or []
            if not items:
                break

            user_id = data.get("user_id")
            rows = [{**item, "thread_id": thread_id, "user_id": user_id} for item in items]
            yield rows

            seen += len(items)
            cursor += len(items)

            total_count = data.get("total_count")
            if (total_count is not None and seen >= total_count) or len(items) < config.page_size:
                break

            # Save mid-thread progress after yielding, so a crash resumes this thread at the cursor.
            resumable_source_manager.save_state(ZepResumeConfig(thread_id=thread_id, cursor=cursor))

        # Advance the bookmark to the next thread so a crash between threads resumes correctly.
        if nxt is not None:
            resumable_source_manager.save_state(ZepResumeConfig(thread_id=nxt, cursor=0))

        current = nxt
        cursor = 0  # only the resumed-into thread uses the saved cursor


def _iter_ids(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger, endpoint: str, id_field: str
) -> Iterator[str]:
    """Lazily page a page-numbered list endpoint (users, graphs), yielding one id at a time."""
    config = ZEP_ENDPOINTS[endpoint]
    assert config.page_number_param is not None and config.page_size_param is not None
    page_number = 1
    seen = 0
    while True:
        params: dict[str, Any] = {
            config.page_size_param: config.page_size,
            config.page_number_param: page_number,
            "order_by": "created_at",
            "asc": "true",
        }
        data = _fetch_page(session, _build_url(config.path, params), headers, logger)
        items = data.get(config.data_key) or []
        if not items:
            break
        for item in items:
            item_id = item.get(id_field)
            if item_id:
                yield item_id
        seen += len(items)
        total_count = data.get("total_count")
        if (total_count is not None and seen >= total_count) or len(items) < config.page_size:
            break
        page_number += 1


def _iter_graph_owners(
    session: requests.Session, headers: dict[str, str], logger: FilteringBoundLogger
) -> Iterator[GraphOwner]:
    """Yield every user graph, then every standalone graph."""
    for user_id in _iter_ids(session, headers, logger, "users", "user_id"):
        yield GraphOwner(scope="user", owner_id=user_id)
    for graph_id in _iter_ids(session, headers, logger, "graphs", "graph_id"):
        yield GraphOwner(scope="graph", owner_id=graph_id)


def _graph_row(item: dict[str, Any], scope: str, owner_id: str) -> dict[str, Any]:
    return {
        **item,
        "graph_scope": scope,
        "graph_owner_id": owner_id,
        "user_id": owner_id if scope == "user" else None,
        "graph_id": owner_id if scope == "graph" else None,
    }


def _fan_out_graph_rows(
    session: requests.Session,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZepResumeConfig],
    config: ZepEndpointConfig,
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every user graph and standalone graph, yielding the graph's edges, nodes or episodes."""
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.graph_finished:
        return

    owners: Iterator[GraphOwner] = iter(_iter_graph_owners(session, headers, logger))
    resume_cursor: str | None = None

    if resume is not None and resume.graph_scope is not None and resume.graph_owner_id is not None:
        target = GraphOwner(scope=resume.graph_scope, owner_id=resume.graph_owner_id)
        for owner in owners:
            if owner == target:
                break
        else:
            logger.warning(f"Zep: resume graph {target} no longer present, ending {config.name}")
            return
        owners = itertools.chain([target], owners)
        resume_cursor = resume.graph_cursor

    def _stage_next_owner(nxt: GraphOwner | None) -> None:
        if nxt is None:
            resumable_source_manager.save_state(ZepResumeConfig(graph_finished=True))
        else:
            resumable_source_manager.save_state(ZepResumeConfig(graph_scope=nxt.scope, graph_owner_id=nxt.owner_id))

    # One owner of lookahead so the bookmark can point at the next graph before its rows exist.
    current = next(owners, None)
    while current is not None:
        nxt = next(owners, None)
        scope, owner_id = current.scope, current.owner_id
        # user_id and graph_id are user-defined strings; escape path-significant characters.
        path = config.path.format(scope=scope, owner_id=quote(owner_id, safe=""))
        cursor, resume_cursor = resume_cursor, None

        while True:
            body: dict[str, Any] = {"limit": config.page_size, "order_by": "created_at", "direction": "asc"}
            if cursor:
                body["cursor"] = cursor

            page = _post_graph_page(session, _build_url(path, {}), headers, body, logger)
            if page is None:
                # The user or graph was deleted after we listed it.
                logger.warning(f"Zep: {config.name} for {scope} {owner_id} returned 404, skipping")
                items: list[dict[str, Any]] = []
                next_cursor = None
            else:
                items, next_cursor = page
                if next_cursor == cursor:
                    # A repeated cursor would loop forever on the same page.
                    next_cursor = None

            if not items:
                _stage_next_owner(nxt)
                resumable_source_manager.safe_point()
                break

            if next_cursor:
                resumable_source_manager.save_state(
                    ZepResumeConfig(graph_scope=scope, graph_owner_id=owner_id, graph_cursor=next_cursor)
                )
            else:
                _stage_next_owner(nxt)

            yield [_graph_row(item, scope, owner_id) for item in items]

            if not next_cursor:
                break
            cursor = next_cursor

        current = nxt


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZepResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ZEP_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    # One session reused across every page (and, for the fan-out, every thread) so urllib3 keeps
    # the connection alive instead of re-handshaking per request. The API key rides in a custom
    # `Authorization: Api-Key ...` header the auto-redactor can't recognise, so mask it explicitly.
    # capture=False: response bodies are users/threads/messages — customer content the name-based
    # sample scrubbers can't strip, so keep it out of HTTP sample capture (still metered/logged).
    session = make_tracked_session(redact_values=(api_key,), capture=False)

    if config.fan_out_over_threads:
        yield from _fan_out_message_rows(session, headers, logger, resumable_source_manager, config)
    elif config.fan_out_over_graphs:
        yield from _fan_out_graph_rows(session, headers, logger, resumable_source_manager, config)
    else:
        yield from _page_based_rows(session, headers, logger, resumable_source_manager, config)


def zep_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZepResumeConfig],
) -> SourceResponse:
    config = ZEP_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        # Rows arrive oldest-first (created_at ascending / message cursor order). The graph fan-out
        # restarts the order for each graph, so it is not one ordered series.
        sort_mode=None if config.fan_out_over_graphs else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


__all__ = ["ZepResumeConfig", "get_rows", "validate_credentials", "zep_source"]
