import base64
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.sendowl.settings import SENDOWL_ENDPOINTS

SENDOWL_BASE_URL = "https://www.sendowl.com"
# SendOwl caps `per_page` at 50 (default 10); the largest page minimises round trips while
# staying under the documented ~1 request/second advisory.
PER_PAGE = 50
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm the credentials are genuine. The key pair is account-wide, so
# one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/api/v1/products"


class SendowlRetryableError(Exception):
    pass


@dataclasses.dataclass
class SendowlResumeConfig:
    # Next page to fetch (1-indexed). Page-number pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    next_page: int = 1


def _headers(api_key: str, api_secret: str) -> dict[str, str]:
    # SendOwl uses HTTP Basic auth with the API key as username and the secret as password.
    # `make_tracked_session` has no `auth=` hook, so the header is built by hand here.
    token = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((SendowlRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    path: str,
    wrapper_key: str,
    page: int,
    per_page: int,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    response = session.get(
        f"{SENDOWL_BASE_URL}{path}",
        params={"page": page, "per_page": per_page},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise SendowlRetryableError(f"SendOwl API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"SendOwl API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # SendOwl list endpoints return a bare JSON array of single-key wrapper objects, e.g.
    # `[{"product": {...}}, ...]`. Unwrap each item so downstream tables hold the flat record.
    # Subscript access fails fast if the wrapper key is missing rather than silently importing the
    # outer dict (which would lack the primary key and carry a nested object as a stray field).
    if not isinstance(data, list):
        raise SendowlRetryableError(f"SendOwl returned an unexpected payload for {path}: {type(data).__name__}")
    return [row[wrapper_key] if isinstance(row, dict) else row for row in data]


def get_rows(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SendowlResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = SENDOWL_ENDPOINTS[endpoint]
    # `redact_values` masks both credential strings in logged URLs and captured samples.
    session = make_tracked_session(headers=_headers(api_key, api_secret), redact_values=(api_key, api_secret))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume and resume.next_page > 1:
        logger.debug(f"SendOwl: resuming {endpoint} from page {page}")

    while True:
        items = _fetch_page(session, config.path, config.wrapper_key, page, PER_PAGE, logger)
        if items:
            yield items

        # SendOwl exposes no `has_more` flag, so a short (or empty) page marks the end of the
        # collection.
        if len(items) < PER_PAGE:
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(SendowlResumeConfig(next_page=page))


def sendowl_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SendowlResumeConfig],
) -> SourceResponse:
    config = SENDOWL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            api_secret=api_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_key: str, api_secret: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single list endpoint to validate the API key pair.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_key, api_secret), redact_values=(api_key, api_secret))
    try:
        response = session.get(f"{SENDOWL_BASE_URL}{path}", params={"page": 1, "per_page": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to SendOwl: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"SendOwl returned HTTP {response.status_code}"

    return 200, None
