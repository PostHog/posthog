import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.jobnimbus.settings import JOBNIMBUS_ENDPOINTS

JOBNIMBUS_BASE_URL = "https://app.jobnimbus.com/api1"
# The Elasticsearch-backed list endpoints accept a `size` of up to 100; the largest page minimises
# round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/contacts"


class JobNimbusRetryableError(Exception):
    pass


@dataclasses.dataclass
class JobNimbusResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `jnid`.
    offset: int = 0


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((JobNimbusRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    offset: int,
    limit: int,
    logger: FilteringBoundLogger,
) -> tuple[list[dict[str, Any]], int]:
    response = session.get(
        f"{JOBNIMBUS_BASE_URL}{path}",
        params={"size": limit, "from": offset},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise JobNimbusRetryableError(f"JobNimbus API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"JobNimbus API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # JobNimbus list endpoints wrap rows in `{"count": N, "results": [...]}`.
    if not isinstance(data, dict):
        raise JobNimbusRetryableError(f"JobNimbus returned an unexpected payload for {path}: {type(data).__name__}")
    results = data.get("results")
    if not isinstance(results, list):
        raise JobNimbusRetryableError(f"JobNimbus returned no results list for {path}: {type(results).__name__}")
    count = data.get("count")
    # `count` is the total matching row count; if it's ever missing the short-page check still
    # terminates the scan safely.
    if not isinstance(count, int):
        count = offset + len(results)
    return results, count


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JobNimbusResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = JOBNIMBUS_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume and resume.offset > 0:
        logger.debug(f"JobNimbus: resuming {endpoint} from offset {offset}")

    while True:
        items, count = _fetch_page(session, config.path, offset, PAGE_SIZE, logger)
        if items:
            yield items

        # Stop on a short/empty page or once the offset has caught up to the reported total.
        if len(items) < PAGE_SIZE or offset + len(items) >= count:
            break

        offset += PAGE_SIZE
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(JobNimbusResumeConfig(offset=offset))


def jobnimbus_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[JobNimbusResumeConfig],
) -> SourceResponse:
    config = JOBNIMBUS_ENDPOINTS[endpoint]

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
        response = session.get(f"{JOBNIMBUS_BASE_URL}{path}", params={"size": 1, "from": 0}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to JobNimbus: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"JobNimbus returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid JobNimbus API key"
    return False, message or "Could not validate JobNimbus API key"
