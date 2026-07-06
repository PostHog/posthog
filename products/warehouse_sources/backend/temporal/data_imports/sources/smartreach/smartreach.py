import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.settings import SMARTREACH_ENDPOINTS

SMARTREACH_BASE_URL = "https://api.smartreach.io/api/v1"
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API key is genuine. The user key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_ENDPOINT = "campaigns"


class SmartreachRetryableError(Exception):
    pass


@dataclasses.dataclass
class SmartreachResumeConfig:
    # Full URL of the next page, taken verbatim from `links.next`. None means "start at the
    # endpoint's first page". The next URL already carries every pagination param, so the original
    # query params must NOT be re-sent alongside it (doing so can restart pagination from the top).
    next_url: str | None = None


def _headers(api_key: str) -> dict[str, str]:
    return {"X-API-KEY": api_key, "Accept": "application/json"}


def _extract_rows(data: dict[str, Any], data_key: str) -> list[dict[str, Any]]:
    # SmartReach wraps the list in `{"data": {"<data_key>": [...]}, "links": {"next": ...}}`.
    # Tolerate a bare `{"data": [...]}` shape too, in case an endpoint returns the list directly.
    payload = data.get("data")
    if isinstance(payload, dict):
        rows = payload.get(data_key)
        return rows if isinstance(rows, list) else []
    if isinstance(payload, list):
        return payload
    return []


def _next_url(data: dict[str, Any]) -> Optional[str]:
    links = data.get("links")
    if isinstance(links, dict):
        return links.get("next")
    return None


@retry(
    retry=retry_if_exception_type((SmartreachRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    # `url` is either the endpoint's first-page URL or a `links.next` URL that already encodes its
    # own pagination params, so no query params are passed here.
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise SmartreachRetryableError(f"SmartReach API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"SmartReach API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmartreachResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SMARTREACH_ENDPOINTS[endpoint]
    # `redact_values` masks the user key in logged URLs and captured samples.
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume and resume.next_url:
        url = resume.next_url
        logger.debug(f"SmartReach: resuming {endpoint} from saved cursor URL")
    else:
        url = f"{SMARTREACH_BASE_URL}{config.path}"

    while True:
        data = _fetch_page(session, url, logger)

        rows = _extract_rows(data, config.data_key)
        if rows:
            yield rows

        next_url = _next_url(data)
        if not next_url:
            break

        url = next_url
        # Save AFTER yielding so a crash re-fetches from the next cursor (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(SmartreachResumeConfig(next_url=next_url))


def smartreach_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SmartreachResumeConfig],
) -> SourceResponse:
    config = SMARTREACH_ENDPOINTS[endpoint]

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


def check_access(api_key: str, endpoint: str = DEFAULT_PROBE_ENDPOINT) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the user key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    config = SMARTREACH_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{SMARTREACH_BASE_URL}{config.path}", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to SmartReach: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"SmartReach returned HTTP {response.status_code}"

    return 200, None
