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
from products.warehouse_sources.backend.temporal.data_imports.sources.beamer.settings import (
    BEAMER_ENDPOINTS,
    BeamerEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

BEAMER_BASE_URL = "https://api.getbeamer.com/v0"
REQUEST_TIMEOUT = 60
# Beamer's `page` query param is documented as paginating alongside `maxResults` but the docs don't
# state whether it's 0- or 1-based. We could not curl-verify against the live API without a paid key,
# so we assume the common convention (page 1 = first page). If a real key shows it's 0-based, change
# this constant — pagination termination ("a short page ends the loop") is index-independent.
FIRST_PAGE = 1


class BeamerRetryableError(Exception):
    pass


@dataclasses.dataclass
class BeamerResumeConfig:
    # Next page to fetch (1-based, see FIRST_PAGE).
    page: int = FIRST_PAGE
    # Fan-out bookmark: id of the parent currently being processed. A stable parent-id bookmark (not a
    # positional index) so parents added/removed between a crash and the retry can't resume us into the
    # wrong parent. None for the top-level (non-fan-out) endpoints.
    parent_id: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {"Beamer-Api-Key": api_key, "Accept": "application/json"}


def _format_datetime(value: Any) -> str:
    """Format an incremental cursor value as the ISO-8601 `...Z` string Beamer's `dateFrom` expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _build_url(path: str, params: dict[str, Any]) -> str:
    query = {key: value for key, value in params.items() if value is not None}
    base = f"{BEAMER_BASE_URL}{path}"
    return f"{base}?{urlencode(query)}" if query else base


@retry(
    retry=retry_if_exception_type((BeamerRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

    # 429 (rate limit) and 5xx are transient — back off and retry. Beamer allows 30 req/sec on paid
    # plans plus a monthly quota, both of which surface as 429.
    if response.status_code == 429 or response.status_code >= 500:
        raise BeamerRetryableError(f"Beamer API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 happens when a parent is deleted mid fan-out; the caller handles it. Everything else is
        # a hard error (e.g. 401/403 bad-or-unscoped key) raised for `get_non_retryable_errors`.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Beamer API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    # Beamer list endpoints return a bare JSON array.
    return response.json()


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # A bad key 401s; a valid-but-unscoped key 403s (the 'Read posts' permission is optional). Both
    # mean the key is genuine, so only a 401 fails source-create — per-endpoint scope is surfaced
    # separately at sync time via `get_non_retryable_errors`. Transport failures and unexpected
    # statuses are inconclusive: reporting them as an invalid key would push users to needlessly
    # rotate a working credential (and re-enter it into a possibly-degraded environment), so they
    # get a generic retry message instead. `redact_values` masks the key from any captured sample.
    url = _build_url("/posts", {"maxResults": 1})
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(api_key), timeout=10)
    except requests.RequestException:
        return False, "Could not reach Beamer to validate the API key. Please try again."
    if response.status_code in (200, 403):
        return True, None
    if response.status_code == 401:
        return False, "Invalid Beamer API key"
    return False, f"Beamer could not validate the API key right now (status {response.status_code}). Please try again."


def _iter_parent_ids(
    session: requests.Session,
    parent_config: BeamerEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Iterator[str]:
    """Page through a parent collection (posts / feature requests) yielding each row's id."""
    page = FIRST_PAGE
    while True:
        url = _build_url(parent_config.path, {"maxResults": parent_config.max_results, "page": page})
        items = _fetch_page(session, url, headers, logger)
        if not items:
            break
        for item in items:
            # `id` is the required primary key on every parent row; direct access so a missing
            # field fails loudly rather than silently dropping the parent's children.
            yield str(item["id"])
        if len(items) < parent_config.max_results:
            break
        page += 1


def _iter_top_level_rows(
    session: requests.Session,
    config: BeamerEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[BeamerResumeConfig],
    base_params: dict[str, Any],
    start_page: int,
) -> Iterator[Any]:
    page = start_page
    while True:
        url = _build_url(config.path, {**base_params, "page": page})
        items = _fetch_page(session, url, headers, logger)
        if not items:
            break

        has_more = len(items) >= config.max_results
        last_index = len(items) - 1
        for index, item in enumerate(items):
            batcher.batch(item)
            if batcher.should_yield():
                yield batcher.get_table()
                # The batcher just flushed everything buffered up to this item, so checkpoint here.
                # Advance to the next page only on the page's last item; a mid-page flush (the bytes
                # cap firing before the count cap) leaves this page's tail un-batched, so resume from
                # this same page and let merge dedupe the rows already flushed. Saving page+1 mid-page
                # would skip those trailing items on a crash.
                resume_page = page + 1 if index == last_index and has_more else page
                manager.save_state(BeamerResumeConfig(page=resume_page))

        if not has_more:
            break
        page += 1


def _iter_fan_out_rows(
    session: requests.Session,
    config: BeamerEndpointConfig,
    parent_config: BeamerEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    batcher: Batcher,
    manager: ResumableSourceManager[BeamerResumeConfig],
) -> Iterator[Any]:
    assert config.parent_key is not None  # set on every fan-out endpoint in settings.py
    parent_ids = list(_iter_parent_ids(session, parent_config, headers, logger))

    # Resolve the saved parent-id bookmark to the slice of parents still to process. If the bookmarked
    # parent no longer exists (deleted between runs), start over — merge dedupes the re-pulled rows.
    resume = manager.load_state() if manager.can_resume() else None
    remaining = parent_ids
    resume_page = FIRST_PAGE
    if resume is not None and resume.parent_id is not None and resume.parent_id in parent_ids:
        remaining = parent_ids[parent_ids.index(resume.parent_id) :]
        resume_page = resume.page
        logger.debug(f"Beamer: resuming {config.name} from parent_id={resume.parent_id}, page={resume_page}")

    for index, parent_id in enumerate(remaining):
        page = resume_page if index == 0 else FIRST_PAGE
        child_path = config.path.replace("{parent_id}", parent_id)
        try:
            while True:
                url = _build_url(child_path, {"maxResults": config.max_results, "page": page})
                items = _fetch_page(session, url, headers, logger)
                if not items:
                    break

                has_more = len(items) >= config.max_results
                last_index = len(items) - 1
                for item_index, item in enumerate(items):
                    batcher.batch({**item, config.parent_key: parent_id})
                    if batcher.should_yield():
                        yield batcher.get_table()
                        # Same checkpoint rule as the top-level path: only advance the page on the
                        # page's last item, otherwise resume from this page (merge dedupes).
                        checkpoint_page = page + 1 if item_index == last_index and has_more else page
                        manager.save_state(BeamerResumeConfig(page=checkpoint_page, parent_id=parent_id))

                if not has_more:
                    break
                page += 1
        except requests.HTTPError as exc:
            # A parent deleted between enumeration and this fetch 404s. Skip it rather than failing the
            # whole sync — the children are genuinely gone. Any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Beamer: {parent_config.name} {parent_id} not found while fetching {config.name}")
            else:
                raise

        # Advance the bookmark to the next parent so a crash between parents resumes correctly — but
        # only when the batcher holds no unflushed rows. If this parent's tail is still buffered,
        # advancing past it would skip those rows on resume; we leave the last on-yield checkpoint in
        # place instead (a crash re-fetches from there and merge dedupes).
        if index + 1 < len(remaining) and not batcher.should_yield(include_incomplete_chunk=True):
            manager.save_state(BeamerResumeConfig(page=FIRST_PAGE, parent_id=remaining[index + 1]))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BeamerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = BEAMER_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page (and, for fan-out, every parent) so urllib3 keeps the
    # connection alive instead of re-handshaking per request. `redact_values` masks the API key
    # (sent in the `Beamer-Api-Key` header) from any captured HTTP samples or logged requests.
    session = make_tracked_session(redact_values=(api_key,))

    if config.parent is not None:
        parent_config = BEAMER_ENDPOINTS[config.parent]
        yield from _iter_fan_out_rows(
            session, config, parent_config, headers, logger, batcher, resumable_source_manager
        )
    else:
        base_params: dict[str, Any] = {"maxResults": config.max_results}
        if config.supports_incremental and should_use_incremental_field and db_incremental_field_last_value is not None:
            base_params["dateFrom"] = _format_datetime(db_incremental_field_last_value)

        resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
        start_page = resume.page if resume is not None and resume.parent_id is None else FIRST_PAGE
        yield from _iter_top_level_rows(
            session, config, headers, logger, batcher, resumable_source_manager, base_params, start_page
        )

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def beamer_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BeamerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = BEAMER_ENDPOINTS[endpoint]

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
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Beamer doesn't document a sort param on these collections and we couldn't verify the default
        # order against the live API. For incremental endpoints we bound the low end with `dateFrom` and
        # use "desc" semantics so the watermark is only persisted at the end of a successful sync — a
        # mid-sync crash re-fetches from the unchanged watermark instead of skipping rows. Full-refresh
        # endpoints ignore sort_mode.
        sort_mode="desc" if config.supports_incremental else "asc",
    )
