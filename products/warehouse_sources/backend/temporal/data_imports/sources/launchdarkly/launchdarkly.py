import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.launchdarkly.settings import (
    LAUNCHDARKLY_ENDPOINTS,
    LaunchDarklyEndpointConfig,
)

API_HOST = "https://app.launchdarkly.com"
BASE_URL = f"{API_HOST}/api/v2"

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5
MAX_RETRY_WAIT_SECONDS = 60


class LaunchDarklyRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclasses.dataclass
class LaunchDarklyResumeConfig:
    # Full URL of the next page to fetch ("" once a resource is exhausted).
    next_url: str = ""
    # For fan-out endpoints, the project currently being paginated ("" for top-level
    # endpoints or before the first project starts).
    project_key: str = ""


def _get_headers(access_token: str) -> dict[str, str]:
    # LaunchDarkly expects the raw access token in the Authorization header, with no
    # "Bearer" prefix (see https://apidocs.launchdarkly.com/#section/Overview/Authentication).
    return {
        "Authorization": access_token,
        "Accept": "application/json",
    }


def _initial_url(path: str, page_size: int) -> str:
    return f"{BASE_URL}{path}?{urlencode({'limit': page_size})}"


def _resolve_url(href: str) -> str:
    # LaunchDarkly returns relative hrefs (e.g. "/api/v2/projects?limit=20&offset=20").
    if href.startswith("http"):
        return href
    return f"{API_HOST}{href}"


def _next_url_from(data: dict[str, Any]) -> str | None:
    links = data.get("_links") or {}
    next_link = links.get("next") or {}
    href = next_link.get("href")
    return _resolve_url(href) if href else None


def _wait_strategy(retry_state: Any) -> float:
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, LaunchDarklyRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_WAIT_SECONDS)
    return min(2.0**retry_state.attempt_number, MAX_RETRY_WAIT_SECONDS)


@retry(
    retry=retry_if_exception_type((LaunchDarklyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=_wait_strategy,
    reraise=True,
)
def _fetch_page(url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict[str, Any]:
    response = make_tracked_session().get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429:
        retry_after_header = response.headers.get("Retry-After")
        try:
            # Retry-After is normally integer seconds, but tolerate fractional values too.
            retry_after = float(retry_after_header) if retry_after_header else None
        except ValueError:
            # A non-numeric value (e.g. an HTTP-date) falls back to exponential backoff.
            retry_after = None
        logger.warning(f"LaunchDarkly rate limited (429), retrying. retry_after={retry_after_header}, url={url}")
        raise LaunchDarklyRetryableError(f"LaunchDarkly rate limited: url={url}", retry_after=retry_after)

    if response.status_code >= 500:
        raise LaunchDarklyRetryableError(f"LaunchDarkly server error: status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"LaunchDarkly API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def validate_credentials(access_token: str, path: str = "/caller-identity") -> int | None:
    """Probe an endpoint and return the HTTP status code (or None on transport failure)."""
    try:
        response = make_tracked_session().get(f"{BASE_URL}{path}", headers=_get_headers(access_token), timeout=10)
        return response.status_code
    except Exception:
        return None


def _fetch_project_keys(headers: dict[str, str], logger: FilteringBoundLogger) -> list[str]:
    keys: list[str] = []
    url: str | None = _initial_url("/projects", LAUNCHDARKLY_ENDPOINTS["projects"].page_size)
    while url:
        data = _fetch_page(url, headers, logger)
        # `key` is the identifier every fan-out URL is built from; fail fast rather than
        # silently dropping a project (and all its environments/flags/metrics) if it's absent.
        for item in data.get("items", []):
            keys.append(item["key"])
        url = _next_url_from(data)
    return keys


def _paginate_resource(
    start_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LaunchDarklyResumeConfig],
    project_key: str,
) -> Iterator[list[dict[str, Any]]]:
    url: str | None = start_url
    while url:
        data = _fetch_page(url, headers, logger)
        items = data.get("items", [])

        if project_key:
            for item in items:
                item["_project_key"] = project_key

        if items:
            yield items

        next_url = _next_url_from(data)
        # Save state AFTER yielding so a heartbeat-timeout crash re-fetches from the next
        # page rather than re-emitting the page we just yielded (merge dedupes regardless).
        resumable_source_manager.save_state(LaunchDarklyResumeConfig(next_url=next_url or "", project_key=project_key))
        url = next_url


def _get_fanout_rows(
    config: LaunchDarklyEndpointConfig,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LaunchDarklyResumeConfig],
    resume: LaunchDarklyResumeConfig | None,
) -> Iterator[list[dict[str, Any]]]:
    project_keys = _fetch_project_keys(headers, logger)
    if not project_keys:
        logger.warning(f"LaunchDarkly: no projects found, nothing to sync for endpoint={config.name}")
        return

    start_idx = 0
    resume_url: str | None = None
    if resume is not None and resume.project_key and resume.project_key in project_keys:
        idx = project_keys.index(resume.project_key)
        if resume.next_url:
            # Mid-project: pick up at the saved page within that project.
            start_idx = idx
            resume_url = resume.next_url
        else:
            # The saved project finished (empty next_url marker); start at the next one.
            start_idx = idx + 1

    for i in range(start_idx, len(project_keys)):
        project_key = project_keys[i]
        if i == start_idx and resume_url:
            start_url = resume_url
        else:
            start_url = _initial_url(config.path.format(project_key=project_key), config.page_size)
        yield from _paginate_resource(start_url, headers, logger, resumable_source_manager, project_key)


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LaunchDarklyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = LAUNCHDARKLY_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if config.requires_project:
        yield from _get_fanout_rows(config, headers, logger, resumable_source_manager, resume)
        return

    if resume is not None and resume.next_url:
        logger.debug(f"LaunchDarkly: resuming endpoint={endpoint} from url={resume.next_url}")
        start_url = resume.next_url
    else:
        start_url = _initial_url(config.path, config.page_size)

    yield from _paginate_resource(start_url, headers, logger, resumable_source_manager, project_key="")


def launchdarkly_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LaunchDarklyResumeConfig],
) -> SourceResponse:
    config = LAUNCHDARKLY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_key,
        # LaunchDarkly timestamps are epoch-millisecond integers and the datetime
        # partitioner expects epoch-seconds, so partitioning is intentionally left off to
        # avoid mis-bucketing rows far into the future.
        partition_mode=None,
        partition_keys=None,
    )
