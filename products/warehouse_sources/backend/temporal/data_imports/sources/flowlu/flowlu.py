import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.flowlu.settings import FLOWLU_ENDPOINTS

REQUEST_TIMEOUT_SECONDS = 60
# Flowlu pages are 1-indexed. List endpoints return ~50 records per page by default; a per-page
# size param isn't reliably documented, so we only advance `page` and stop on the first empty page.
BASE_PAGE = 1
# Cheap list endpoint used to confirm an API key is genuine. Tasks are part of Flowlu's core
# module set, so the endpoint exists on every account regardless of which apps are enabled.
DEFAULT_PROBE_PATH = "/task/tasks/list"


class FlowluRetryableError(Exception):
    pass


@dataclasses.dataclass
class FlowluResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = BASE_PAGE


def base_url(subdomain: str) -> str:
    """Per-account hostname: every Flowlu portal lives on its own subdomain."""
    return f"https://{subdomain}.flowlu.com/api/v1/module"


@retry(
    retry=retry_if_exception_type((FlowluRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    api_key: str,
    subdomain: str,
    path: str,
    page: int,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    # Flowlu authenticates via the `api_key` query parameter (not a header); the tracked session
    # redacts it from logged URLs via `redact_values`.
    params: dict[str, str | int] = {"api_key": api_key, "page": page}
    response = session.get(
        f"{base_url(subdomain)}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise FlowluRetryableError(f"Flowlu API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Flowlu API error: status={response.status_code}, body={response.text[:500]}, path={path}")
        # Raise manually instead of `raise_for_status()`: that embeds `response.url`, which carries the
        # `api_key` query param, and this message reaches sync error logs viewable by users who can't see
        # secret fields. Keep the "<status> Client Error: <reason> for url" shape that
        # `get_non_retryable_errors()` matches on, but point it at the query-string-free URL.
        kind = "Client Error" if response.status_code < 500 else "Server Error"
        raise requests.HTTPError(
            f"{response.status_code} {kind}: {response.reason} for url: {base_url(subdomain)}{path}",
            response=response,
        )

    data = response.json()
    # Every list endpoint wraps its payload as `{"response": {"items": [...], "total": ..., ...}}`;
    # anything else means a malformed response, so fail loudly rather than silently advancing the
    # cursor past lost rows.
    if not isinstance(data, dict) or not isinstance(data.get("response"), dict):
        raise FlowluRetryableError(f"Flowlu returned an unexpected payload for {path}: {type(data).__name__}")

    items = data["response"].get("items")
    if not isinstance(items, list):
        raise FlowluRetryableError(f"Flowlu response for {path} is missing the 'items' list")

    return items


def get_rows(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FlowluResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = FLOWLU_ENDPOINTS[endpoint]
    # `redact_values` masks the API key in logged URLs and captured samples. `allow_redirects=False`
    # stops a 30x from replaying the credentialed `api_key` query param off-host (defense-in-depth;
    # Smokescreen already blocks internal hosts).
    session = make_tracked_session(
        headers={"Accept": "application/json"}, redact_values=(api_key,), allow_redirects=False
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else BASE_PAGE
    if resume and resume.next_page > BASE_PAGE:
        logger.debug(f"Flowlu: resuming {endpoint} from page {page}")

    while True:
        items = _fetch_page(session, api_key, subdomain, config.path, page, logger)

        # An empty `items` page is the end-of-collection signal (page-number pagination with no
        # authoritative `has_more` flag).
        if not items:
            break

        yield items

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(FlowluResumeConfig(next_page=page))


def flowlu_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FlowluResumeConfig],
) -> SourceResponse:
    config = FLOWLU_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            subdomain=subdomain,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_key: str, subdomain: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(
        headers={"Accept": "application/json"}, redact_values=(api_key,), allow_redirects=False
    )
    try:
        params: dict[str, str | int] = {"api_key": api_key, "page": BASE_PAGE}
        response = session.get(
            f"{base_url(subdomain)}{path}",
            params=params,
            timeout=15,
        )
    except Exception:
        # Don't surface the exception text: `requests` transport errors can embed the prepared URL,
        # which carries the `api_key` query param, and this message can reach editors who can't view secrets.
        return 0, "Could not connect to Flowlu"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Flowlu returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str, subdomain: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key, subdomain)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Flowlu API key"
    return False, message or "Could not validate Flowlu credentials"
