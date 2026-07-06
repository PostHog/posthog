import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.statuspage.settings import (
    STATUSPAGE_ENDPOINTS,
    StatuspageEndpointConfig,
)

STATUSPAGE_BASE_URL = "https://api.statuspage.io/v1"

# Statuspage rate limits paginated reads to 60 requests/minute on a rolling 60s window and
# returns 420/429 with a Retry-After header when exceeded. We retry those (and transient 5xx)
# with bounded exponential backoff — capped well above the 60s window so a throttle clears.
_MAX_ATTEMPTS = 8
_REQUEST_TIMEOUT_SECONDS = 60


class StatuspageRetryableError(Exception):
    """Raised for rate-limit (420/429) and transient 5xx responses so tenacity retries them."""

    pass


@dataclasses.dataclass
class StatuspageResumeConfig:
    # The page number most recently yielded for the resource currently being read. On resume we
    # re-fetch this page and re-yield it (merge dedupes on the primary key) rather than risk
    # skipping rows that were batched but not yet persisted when the worker stopped.
    page: int
    # For page-scoped (fan-out) endpoints, the id of the status page we were reading children for.
    # None for the top-level /pages listing.
    parent_page_id: Optional[str] = None


def _get_headers(api_key: str) -> dict[str, str]:
    # Despite the "OAuth" prefix this is a static API key, not an OAuth2 bearer token — that's the
    # header format Statuspage's Manage API requires.
    return {
        "Authorization": f"OAuth {api_key}",
        "Content-Type": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    return f"{STATUSPAGE_BASE_URL}{path}?{urlencode(params)}"


def _get_session(api_key: str) -> requests.Session:
    # One session per sync so keep-alive is preserved across pages and retries. `redact_values`
    # masks the key from request telemetry/log samples, and `allow_redirects=False` keeps a
    # credentialed request pinned to the validated Statuspage host (it can't be replayed elsewhere).
    return make_tracked_session(
        headers=_get_headers(api_key),
        redact_values=(api_key,),
        allow_redirects=False,
    )


@retry(
    retry=retry_if_exception_type((StatuspageRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(_MAX_ATTEMPTS),
    wait=wait_exponential_jitter(initial=2, max=60),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> requests.Response:
    response = session.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)

    if response.status_code in (420, 429) or response.status_code >= 500:
        raise StatuspageRetryableError(f"Statuspage API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Statuspage API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response


def _iter_resource(
    session: requests.Session,
    path: str,
    config: StatuspageEndpointConfig,
    logger: FilteringBoundLogger,
    start_page: int = 1,
) -> Iterator[tuple[list[dict[str, Any]], int]]:
    """Yield (rows, page_number) for each non-empty page, incrementing `page` from start_page.

    Statuspage's list endpoints page with a 1-based `page` number plus a per-page size param
    (`per_page` for most resources, `limit` for subscribers), both capped at 100. Termination is
    on an empty array: we deliberately do NOT stop on a short page, because if the API ignores the
    size param and defaults below 100, a short-but-non-empty page is still not the last one.
    """
    page = start_page
    while True:
        params = {config.page_size_param: config.page_size, "page": page}
        response = _fetch_page(session, _build_url(path, params), logger)
        data = response.json()
        if not isinstance(data, list) or not data:
            return
        yield data, page
        page += 1


def _list_page_ids(session: requests.Session, logger: FilteringBoundLogger) -> list[str]:
    """List every status page id the key can see — the parents that page-scoped endpoints fan out over."""
    pages_config = STATUSPAGE_ENDPOINTS["pages"]
    page_ids: list[str] = []
    for rows, _page in _iter_resource(session, pages_config.path, pages_config, logger):
        for row in rows:
            # Direct access: page_id drives the entire child fan-out, so a page without an id is a
            # malformed response we want to surface loudly rather than silently drop its children.
            page_ids.append(row["id"])
    return page_ids


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StatuspageResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = STATUSPAGE_ENDPOINTS[endpoint]
    session = _get_session(api_key)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if not config.page_scoped:
        start_page = resume.page if resume is not None else 1
        if resume is not None:
            logger.debug(f"Statuspage: resuming {endpoint} from page {start_page}")
        for rows, page in _iter_resource(session, config.path, config, logger, start_page=start_page):
            yield rows
            resumable_source_manager.save_state(StatuspageResumeConfig(page=page, parent_page_id=None))
        return

    page_ids = _list_page_ids(session, logger)

    start_index = 0
    resume_start_page = 1
    if resume is not None and resume.parent_page_id is not None and resume.parent_page_id in page_ids:
        start_index = page_ids.index(resume.parent_page_id)
        resume_start_page = resume.page
        logger.debug(
            f"Statuspage: resuming {endpoint} fan-out at page_id={resume.parent_page_id}, page={resume_start_page}"
        )

    for idx in range(start_index, len(page_ids)):
        page_id = page_ids[idx]
        path = config.path.format(page_id=page_id)
        start_page = resume_start_page if idx == start_index else 1
        for rows, page in _iter_resource(session, path, config, logger, start_page=start_page):
            # Inject the parent page id so the composite primary key is unique table-wide — a sync
            # aggregates rows from every page, and the bare resource id is only unique within a page.
            for row in rows:
                row["page_id"] = page_id
            yield rows
            resumable_source_manager.save_state(StatuspageResumeConfig(page=page, parent_page_id=page_id))


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Confirm the API key is genuine with one cheap probe against the pages listing."""
    url = _build_url("/pages", {"per_page": 1, "page": 1})
    try:
        response = _get_session(api_key).get(url, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Statuspage API key. Please check your API key and try again."
    if response.status_code == 403:
        return False, "Your Statuspage API key does not have permission to list pages."

    try:
        message = response.json().get("error", response.text)
    except Exception:
        message = response.text
    return False, message


def statuspage_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[StatuspageResumeConfig],
) -> SourceResponse:
    config = STATUSPAGE_ENDPOINTS[endpoint]

    def items() -> Iterator[list[dict[str, Any]]]:
        return get_rows(api_key, endpoint, logger, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=config.primary_key,
        # Full refresh only — Statuspage exposes no server-side timestamp filter — but rows still
        # arrive in a stable page order, so asc is correct.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
