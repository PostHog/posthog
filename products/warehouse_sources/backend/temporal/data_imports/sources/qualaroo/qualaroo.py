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
from products.warehouse_sources.backend.temporal.data_imports.sources.qualaroo.settings import QUALAROO_ENDPOINTS

QUALAROO_BASE_URL = "https://api.qualaroo.com/api/v1"
# The Reporting API caps a page at 500 records; the largest page minimises round trips.
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 60
# Cheap endpoint used to confirm the credentials are genuine. The API key/secret pair is
# account-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/nudges.json"


class QualarooRetryableError(Exception):
    pass


@dataclasses.dataclass
class QualarooResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    offset: int = 0


def _basic_auth_token(api_key: str, api_secret: str) -> str:
    # Qualaroo uses HTTP Basic auth with the API key as username and the API secret as password.
    return base64.b64encode(f"{api_key}:{api_secret}".encode()).decode("ascii")


def _headers(api_key: str, api_secret: str) -> dict[str, str]:
    return {"Authorization": f"Basic {_basic_auth_token(api_key, api_secret)}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((QualarooRetryableError, requests.ReadTimeout, requests.ConnectionError)),
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
) -> list[dict[str, Any]]:
    response = session.get(
        f"{QUALAROO_BASE_URL}{path}",
        params={"limit": limit, "offset": offset},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise QualarooRetryableError(f"Qualaroo API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Qualaroo API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Qualaroo list endpoints return a bare JSON array of records.
    if not isinstance(data, list):
        raise QualarooRetryableError(f"Qualaroo returned an unexpected payload for {path}: {type(data).__name__}")
    return data


def get_rows(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[QualarooResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = QUALAROO_ENDPOINTS[endpoint]
    session = make_tracked_session(
        headers=_headers(api_key, api_secret),
        redact_values=(api_key, api_secret, _basic_auth_token(api_key, api_secret)),
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume and resume.offset > 0:
        logger.debug(f"Qualaroo: resuming {endpoint} from offset {offset}")

    while True:
        items = _fetch_page(session, config.path, offset, PAGE_SIZE, logger)
        if items:
            yield items

        # A short page (or an empty one) means we've reached the end of the collection.
        if len(items) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(QualarooResumeConfig(offset=offset))


def qualaroo_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[QualarooResumeConfig],
) -> SourceResponse:
    config = QUALAROO_ENDPOINTS[endpoint]

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
    """Probe a single endpoint to validate the credentials.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(
        headers=_headers(api_key, api_secret),
        redact_values=(api_key, api_secret, _basic_auth_token(api_key, api_secret)),
    )
    try:
        response = session.get(f"{QUALAROO_BASE_URL}{path}", params={"limit": 1, "offset": 0}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Qualaroo: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Qualaroo returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str, api_secret: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key, api_secret)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Qualaroo API key or secret"
    return False, message or "Could not validate Qualaroo credentials"
