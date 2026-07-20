import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.secoda.settings import SECODA_ENDPOINTS

# US cloud host. EU (eapi.secoda.co), APAC (aapi.secoda.co) and self-hosted domains are not yet
# selectable — see the region caveat in the source docs.
SECODA_BASE_URL = "https://api.secoda.co"
REQUEST_TIMEOUT_SECONDS = 60
# Cheap list endpoint used to confirm an API key is genuine. The key inherits its creator's
# workspace permissions, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/api/v1/user"


class SecodaRetryableError(Exception):
    pass


@dataclasses.dataclass
class SecodaResumeConfig:
    # Full URL of the next page to fetch, taken verbatim from the API's ``links.next``. Secoda uses
    # DRF-style cursor pagination, so a crashed full-refresh sync resumes from the page after the
    # last one yielded; merge dedupes the re-pulled page on ``id``.
    next_url: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def _extract_next_url(data: dict[str, Any]) -> Optional[str]:
    # DRF pagination nests the follow link under ``links.next``; a couple of Secoda endpoints put it
    # at the top level, so we accept either. ``next`` is a full URL (or null on the last page).
    links = data.get("links")
    if isinstance(links, dict) and links.get("next"):
        return links["next"]
    top_level = data.get("next")
    return top_level if isinstance(top_level, str) and top_level else None


@retry(
    retry=retry_if_exception_type((SecodaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], Optional[str]]:
    # ``url`` is already absolute — either the initial endpoint URL or a verbatim ``links.next``, so
    # we never re-send page params (they're baked into the cursor URL).
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise SecodaRetryableError(f"Secoda API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Secoda API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise SecodaRetryableError(f"Secoda returned an unexpected payload for {url}: {type(data).__name__}")

    return data["results"], _extract_next_url(data)


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SecodaResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SECODA_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    url: Optional[str] = resume.next_url if (resume and resume.next_url) else f"{SECODA_BASE_URL}{config.path}"
    if resume and resume.next_url:
        logger.debug(f"Secoda: resuming {endpoint} from cursor {url}")

    while url:
        items, next_url = _fetch_page(session, url, logger)
        if items:
            yield items

        # A null ``next`` link means we've reached the end of the collection.
        if not next_url:
            break

        url = next_url
        # Save AFTER yielding so a crash re-fetches from the next cursor (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(SecodaResumeConfig(next_url=next_url))


def secoda_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SecodaResumeConfig],
) -> SourceResponse:
    config = SECODA_ENDPOINTS[endpoint]

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
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{SECODA_BASE_URL}{path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Secoda: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Secoda returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Secoda API key"
    return False, message or "Could not validate Secoda API key"
