import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.svix.settings import SVIX_ENDPOINTS

SVIX_BASE_URL = "https://api.svix.com/api/v1"
# The list endpoints accept a `limit` of up to 250; the largest page minimises round trips.
PAGE_SIZE = 250
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/event-type"


class SvixRetryableError(Exception):
    pass


@dataclasses.dataclass
class SvixResumeConfig:
    # Opaque cursor returned by the previous page. Svix cursor pagination is deterministic, so a
    # crashed full-refresh sync resumes from the page after the last one yielded; merge dedupes on
    # the primary key. `None` means start from the beginning.
    iterator: Optional[str] = None


def _headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((SvixRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    iterator: Optional[str],
    limit: int,
    logger: FilteringBoundLogger,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    # Omit `iterator` on the first request; Svix rejects an empty cursor value.
    if iterator is not None:
        params["iterator"] = iterator

    response = session.get(
        f"{SVIX_BASE_URL}{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise SvixRetryableError(f"Svix API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Svix API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Svix list endpoints return a `{"data": [...], "iterator": "...", "done": bool}` envelope.
    if not isinstance(data, dict) or "data" not in data:
        raise SvixRetryableError(f"Svix returned an unexpected payload for {path}: {type(data).__name__}")
    return data


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SvixResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SVIX_ENDPOINTS[endpoint]
    # `redact_values` masks the API key in logged URLs and captured samples.
    session = make_tracked_session(headers=_headers(api_key), redact_values=(api_key,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    iterator = resume.iterator if resume else None
    if resume and resume.iterator is not None:
        logger.debug(f"Svix: resuming {endpoint} from saved cursor")

    while True:
        data = _fetch_page(session, config.path, iterator, PAGE_SIZE, logger)

        items = data["data"]
        if items:
            yield items

        # `done` signals the last page; a missing/absent cursor is treated as terminal too.
        if data.get("done", True):
            break
        iterator = data.get("iterator")
        if iterator is None:
            break

        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(SvixResumeConfig(iterator=iterator))


def svix_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SvixResumeConfig],
) -> SourceResponse:
    config = SVIX_ENDPOINTS[endpoint]

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
        response = session.get(f"{SVIX_BASE_URL}{path}", params={"limit": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Svix: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Svix returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Svix API key"
    return False, message or "Could not validate Svix API key"
