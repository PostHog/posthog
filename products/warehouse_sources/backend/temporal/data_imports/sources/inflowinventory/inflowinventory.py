import re
import dataclasses
from collections.abc import Iterator
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.settings import (
    INFLOWINVENTORY_ENDPOINTS,
)

INFLOWINVENTORY_BASE_URL = "https://cloudapi.inflowinventory.com"
# inFlow requires a date-based API version header on every request; pin a recent documented version.
INFLOWINVENTORY_API_VERSION = "2023-04-01"
# The list endpoints accept up to 100 records per page; the largest page minimises round trips.
PAGE_SIZE = 100
REQUEST_TIMEOUT_SECONDS = 60
# inFlow company IDs are GUIDs. Restrict to host/path-safe characters so the credential stays
# pinned to cloudapi.inflowinventory.com and can't be redirected via a crafted path segment.
COMPANY_ID_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")


class InflowInventoryRetryableError(Exception):
    """Raised for transient API responses (429 / 5xx) so tenacity retries them."""


@dataclasses.dataclass
class InflowInventoryResumeConfig:
    # The `after` cursor is the ID of the last row yielded. inFlow returns rows ordered by ID, so a
    # crashed full-refresh sync resumes from the record after the last one persisted; merge dedupes
    # on the primary key.
    after: str | None = None


def base_url(company_id: str) -> str:
    return f"{INFLOWINVENTORY_BASE_URL}/{company_id}"


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": f"application/json;version={INFLOWINVENTORY_API_VERSION}",
    }


def _make_session(api_key: str) -> requests.Session:
    # Redirects are pinned off so the Bearer key can't be replayed to a cross-host redirect target
    # (SSRF / credential-exfiltration defense). urllib3 retries are disabled so tenacity (on
    # `_fetch_page`) is the single retry layer — otherwise 429/5xx would be retried by both.
    return make_tracked_session(
        headers=_headers(api_key), redact_values=(api_key,), allow_redirects=False, retry=Retry(total=0)
    )


@retry(
    retry=retry_if_exception_type((InflowInventoryRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    company_id: str,
    path: str,
    after: str | None,
    count: int,
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"count": count}
    if after is not None:
        params["after"] = after

    response = session.get(
        f"{base_url(company_id)}/{path}",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429 or response.status_code >= 500:
        raise InflowInventoryRetryableError(
            f"inFlow Inventory API error (retryable): status={response.status_code}, path={path}"
        )

    if not response.ok:
        logger.error(f"inFlow Inventory API error: status={response.status_code}, body={response.text}, path={path}")
        response.raise_for_status()

    data = response.json()
    # inFlow list endpoints return a bare JSON array of records.
    if not isinstance(data, list):
        raise InflowInventoryRetryableError(
            f"inFlow Inventory returned an unexpected payload for {path}: {type(data).__name__}"
        )
    return data


def get_rows(
    api_key: str,
    company_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InflowInventoryResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = INFLOWINVENTORY_ENDPOINTS[endpoint]
    session = _make_session(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after = resume.after if resume else None
    if resume and resume.after:
        logger.debug(f"inFlow Inventory: resuming {endpoint} after cursor {after}")

    while True:
        items = _fetch_page(session, company_id, config.path, after, PAGE_SIZE, logger)
        if items:
            yield items

        # A short page (or an empty one) means we've reached the end of the collection.
        if len(items) < PAGE_SIZE:
            break

        next_after = items[-1].get(config.id_field)
        if next_after is None:
            # Without a cursor value we can't request the next page safely — stop rather than loop.
            logger.warning(f"inFlow Inventory: {endpoint} row missing '{config.id_field}', ending pagination")
            break

        after = str(next_after)
        # Save AFTER yielding so a crash re-fetches from the last cursor (already-yielded pages are
        # persisted); merge dedupes the re-pulled page on the primary key.
        resumable_source_manager.save_state(InflowInventoryResumeConfig(after=after))


def inflowinventory_source(
    api_key: str,
    company_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InflowInventoryResumeConfig],
) -> SourceResponse:
    config = INFLOWINVENTORY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            company_id=company_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
    )


def check_access(api_key: str, company_id: str, path: str = "products") -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the credentials.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, ``400`` for a malformed company ID, other HTTP status otherwise.
    """
    if not COMPANY_ID_REGEX.match(company_id):
        return 400, "The inFlow Inventory company ID contains unsupported characters"

    session = _make_session(api_key)
    try:
        response = session.get(f"{base_url(company_id)}/{path}", params={"count": 1}, timeout=15)
    except Exception as e:
        return 0, f"Could not connect to inFlow Inventory: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"inFlow Inventory returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str, company_id: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key, company_id)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid inFlow Inventory API key"
    return False, message or "Could not validate inFlow Inventory credentials"
