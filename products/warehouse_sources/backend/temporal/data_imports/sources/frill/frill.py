import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.frill.settings import (
    FRILL_ENDPOINTS,
    FrillEndpointConfig,
)

FRILL_BASE_URL = "https://api.frill.co/v1"
# Documented maximum `limit` for list endpoints (default is 20).
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class FrillRetryableError(Exception):
    """Raised on 429/5xx so tenacity retries; never reaches get_non_retryable_errors."""


@dataclasses.dataclass
class FrillResumeConfig:
    # `after` cursor into the endpoint's top-level list. For the comments fan-out this is the
    # cursor into /ideas — comments resume at the last fully processed page of parent ideas.
    after: Optional[str] = None


def _make_session(api_key: str) -> requests.Session:
    # The key rides in the Authorization header; register it for redaction so it can never
    # land in tracked HTTP logs/samples regardless of where the API echoes it.
    # `capture=False`: Frill responses carry arbitrary user-authored feedback — idea/comment
    # bodies and private internal notes — that the generic name-based scrubber can't anonymize,
    # so keep those bodies out of the shared HTTP sample store (still metered and logged).
    return make_tracked_session(
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        redact_values=(api_key,),
        capture=False,
    )


def _handle_response(response: requests.Response, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    """Classify a single Frill response: retryable, terminal failure, or success body."""
    if response.status_code == 429 or response.status_code >= 500:
        raise FrillRetryableError(f"Frill API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Frill API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Frill error bodies look like {"error": true, "message": "..."}; surface any that slip
    # through with a 2xx status so they fail loudly instead of being parsed as an empty page.
    if isinstance(data, dict) and data.get("error"):
        raise requests.HTTPError(f"Frill API error: {data.get('message')} (url: {url})", response=response)

    if not isinstance(data, dict):
        raise requests.HTTPError(f"Frill API returned an unexpected body (url: {url})", response=response)

    return data


@retry(
    retry=retry_if_exception_type((FrillRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    return _handle_response(response, url, logger)


def _next_cursor(data: dict[str, Any], records: list[dict[str, Any]], current_after: Optional[str]) -> Optional[str]:
    """Extract the next `after` cursor, or None when pagination is done.

    Frill's docs describe the pagination object as {total, count, hasNextPage, startCursor,
    endCursor} while the embedded OpenAPI specs show {total, before, after}; handle both
    shapes conservatively. When neither a hasNextPage flag nor a full page indicates more
    results, stop — and never reuse a cursor (guards against an infinite loop on API drift).
    """
    pagination = data.get("pagination")
    if not isinstance(pagination, dict):
        return None

    cursor = pagination.get("endCursor") or pagination.get("after")
    if not isinstance(cursor, str) or not cursor or cursor == current_after:
        return None

    has_next = pagination.get("hasNextPage")
    if has_next is False:
        return None
    if has_next is None and len(records) < PAGE_SIZE:
        return None

    return cursor


def _iter_pages(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
    after: Optional[str] = None,
) -> Iterator[tuple[list[dict[str, Any]], Optional[str]]]:
    """Yield (records, next_after) per page; next_after is None on the terminal page."""
    while True:
        query: dict[str, Any] = {**params, "limit": PAGE_SIZE}
        if after:
            query["after"] = after
        data = _fetch_page(session, url, query, logger)

        raw_records = data.get("data")
        records = (
            [record for record in raw_records if isinstance(record, dict)] if isinstance(raw_records, list) else []
        )

        next_after = _next_cursor(data, records, after) if records else None
        yield records, next_after

        if next_after is None:
            break
        after = next_after


def _comment_rows(
    session: requests.Session,
    config: FrillEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FrillResumeConfig],
    ideas_after: Optional[str],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over ideas: GET /comments requires an `idea_idx`, so comments are fetched per idea.

    The resume cursor tracks the /ideas pagination; it is saved only after every comment of an
    entire ideas page has been yielded, so a crash re-yields that page (merge dedupes on the
    primary key) rather than skipping ideas whose comments were never fetched.
    """
    ideas_url = f"{FRILL_BASE_URL}{FRILL_ENDPOINTS['ideas'].path}"
    comments_url = f"{FRILL_BASE_URL}{config.path}"

    for ideas, next_after in _iter_pages(
        session, ideas_url, dict(FRILL_ENDPOINTS["ideas"].params), logger, after=ideas_after
    ):
        for idea in ideas:
            idea_idx = idea.get("idx")
            if not isinstance(idea_idx, str) or not idea_idx:
                continue
            # Ideas report comment_count/note_count; skip the per-idea request only when both
            # are explicitly zero (fetch when the fields are missing, to stay conservative).
            if idea.get("comment_count") == 0 and idea.get("note_count") == 0:
                continue

            comment_params = {**config.params, "idea_idx": idea_idx}
            for comments, _ in _iter_pages(session, comments_url, comment_params, logger):
                if comments:
                    # Comments only carry the idea's integer `idea_id`, while every other stream
                    # keys on `idx` strings — inject the parent idx so rows join back to ideas.
                    yield [{**comment, "_idea_idx": idea_idx} for comment in comments]

        if next_after is not None:
            resumable_source_manager.save_state(FrillResumeConfig(after=next_after))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FrillResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = FRILL_ENDPOINTS[endpoint]
    session = _make_session(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after = resume.after if resume is not None else None
    if after is not None:
        logger.debug(f"Frill: resuming endpoint={endpoint} from cursor={after}")

    if endpoint == "comments":
        yield from _comment_rows(session, config, logger, resumable_source_manager, after)
        return

    url = f"{FRILL_BASE_URL}{config.path}"
    for records, next_after in _iter_pages(session, url, dict(config.params), logger, after=after):
        if records:
            yield records

        # Persist AFTER yielding — a crash re-yields the last page (the merge dedupes on the
        # primary key) rather than skipping it.
        if next_after is not None:
            resumable_source_manager.save_state(FrillResumeConfig(after=next_after))


def frill_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FrillResumeConfig],
) -> SourceResponse:
    config = FRILL_ENDPOINTS[endpoint]

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


def validate_credentials(api_key: str) -> bool:
    # /statuses is the cheapest probe: every workspace ships with default statuses and the
    # endpoint takes no required params. Reuse the catalog path so it can't drift from sync.
    url = f"{FRILL_BASE_URL}{FRILL_ENDPOINTS['statuses'].path}"
    try:
        response = _make_session(api_key).get(url, params={"limit": 1}, timeout=REQUEST_TIMEOUT_SECONDS)
    except Exception:
        return False

    if not response.ok:
        return False

    try:
        body = response.json()
    except ValueError:
        return False

    return isinstance(body, dict) and not body.get("error")
