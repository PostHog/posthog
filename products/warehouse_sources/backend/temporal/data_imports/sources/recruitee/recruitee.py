import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.recruitee.settings import RECRUITEE_ENDPOINTS

RECRUITEE_HOST = "https://api.recruitee.com"
# The list endpoints accept a `limit`; the largest page minimises round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# Cheap probe used to confirm credentials. Departments is the smallest company-level list, and the
# token is company-wide, so one probe validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/departments"
# The company_id is interpolated into the request path, so restrict it to path-safe characters to
# keep the request pinned to api.recruitee.com/c/<company_id>.
COMPANY_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]+$")


class RecruiteeRetryableError(Exception):
    pass


@dataclasses.dataclass
class RecruiteeResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    offset: int = 0


def base_url(company_id: str) -> str:
    if not COMPANY_ID_REGEX.match(company_id):
        raise ValueError("Recruitee company ID contains invalid characters")
    return f"{RECRUITEE_HOST}/c/{company_id}"


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}


@retry(
    retry=retry_if_exception_type((RecruiteeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    company_id: str,
    path: str,
    data_key: str,
    offset: int,
    limit: int,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    response = session.get(
        f"{base_url(company_id)}{path}",
        params={"limit": limit, "offset": offset},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise RecruiteeRetryableError(f"Recruitee API error (retryable): status={response.status_code}, path={path}")

    if not response.ok:
        logger.error(f"Recruitee API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # Recruitee list endpoints wrap the records under a key named after the resource, e.g.
    # {"candidates": [...]}. Anything else means the payload shape changed unexpectedly.
    if not isinstance(data, dict):
        raise RecruiteeRetryableError(f"Recruitee returned an unexpected payload for {path}: {type(data).__name__}")
    items = data.get(data_key)
    if not isinstance(items, list):
        raise RecruiteeRetryableError(f"Recruitee response for {path} missing list under '{data_key}'")
    return items


def get_rows(
    company_id: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RecruiteeResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = RECRUITEE_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume else 0
    if resume and resume.offset > 0:
        logger.debug(f"Recruitee: resuming {endpoint} from offset {offset}")

    while True:
        items = _fetch_page(session, company_id, config.path, config.data_key, offset, PAGE_SIZE, logger)
        if items:
            yield items

        # A short page (or an empty one) means we've reached the end of the collection.
        if len(items) < PAGE_SIZE:
            break

        offset += PAGE_SIZE
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(RecruiteeResumeConfig(offset=offset))


def recruitee_source(
    company_id: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RecruiteeResumeConfig],
) -> SourceResponse:
    config = RECRUITEE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            company_id=company_id,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(company_id: str, api_token: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the credentials.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,))
    try:
        response = session.get(f"{base_url(company_id)}{path}", params={"limit": 1, "offset": 0}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Recruitee: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Recruitee returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(company_id: str, api_token: str) -> tuple[bool, str | None]:
    status, message = check_access(company_id, api_token)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Recruitee company ID or API token"
    return False, message or "Could not validate Recruitee credentials"
