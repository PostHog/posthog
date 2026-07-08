import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.docuseal.settings import (
    DOCUSEAL_ENDPOINTS,
    DocusealEndpointConfig,
)

# DocuSeal runs two hosted regions on separate base URLs. There is no programmatic way to
# discover which region an account lives in, so the user picks it on the connection form.
DOCUSEAL_HOSTS: dict[str, str] = {
    "us": "https://api.docuseal.com",
    "eu": "https://api.docuseal.eu",
}
DEFAULT_REGION = "us"

# Max page size the API accepts (`limit`, capped server-side at 100).
PAGE_SIZE = 100

REQUEST_TIMEOUT_SECONDS = 60


class DocusealRetryableError(Exception):
    pass


@dataclasses.dataclass
class DocusealResumeConfig:
    # The `after` cursor (a record id) used to fetch the page we're currently streaming. We persist
    # *this* page's cursor (not the next page's) so a crash mid-page resumes by re-fetching the same
    # page rather than skipping past rows still buffered but not yet yielded — merge dedupes the
    # re-pulled rows on the primary key. `None` means "start from the first page".
    after: int | None = None


def _base_url(region: str | None) -> str:
    return DOCUSEAL_HOSTS.get(region or DEFAULT_REGION, DOCUSEAL_HOSTS[DEFAULT_REGION])


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-Auth-Token": api_key,
        "Accept": "application/json",
    }


def _build_url(base_url: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{base_url}{path}"
    return f"{base_url}{path}?{urlencode(params)}"


def validate_credentials(api_key: str, region: str | None) -> tuple[bool, str | None]:
    """Confirm the API token is genuine with one cheap, low-limit list request.

    DocuSeal issues a single account-wide token (no per-resource scopes), so probing any list
    endpoint is sufficient. A 401 means the token is wrong; anything else reachable counts as valid.
    """
    url = _build_url(_base_url(region), "/templates", {"limit": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return False, "Could not reach DocuSeal. Check your network and try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid DocuSeal API key. Create a new key in your DocuSeal account settings and reconnect."
    return False, f"DocuSeal API returned an unexpected status ({response.status_code}) while validating credentials."


@retry(
    retry=retry_if_exception_type((DocusealRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise DocusealRetryableError(f"DocuSeal API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"DocuSeal API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DocusealResumeConfig],
) -> Iterator[Any]:
    config = DOCUSEAL_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    base_url = _base_url(region)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    # DocuSeal orders list responses by `id` descending (newest first) and paginates *backwards*:
    # `pagination.next` is the smallest id on the page, and passing it as `after` returns the next
    # page of older (smaller-id) records. There is no server-side time filter, so this is a full
    # walk newest -> oldest. Resume picks back up from the saved cursor.
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after: int | None = resume.after if resume is not None else None
    if resume is not None:
        logger.debug(f"DocuSeal: resuming {endpoint} from after={after}")

    while True:
        params: dict[str, Any] = {"limit": PAGE_SIZE}
        if after is not None:
            params["after"] = after

        data = _fetch_page(session, _build_url(base_url, config.path, params), headers, logger)
        rows = data.get("data", [])
        if not rows:
            break

        for row in rows:
            batcher.batch(row)
            if batcher.should_yield():
                yield batcher.get_table()
                # Save the cursor of the page we're on (not the next one) AFTER yielding, so a crash
                # re-fetches this page rather than skipping rows still buffered. Merge dedupes on the
                # primary key.
                resumable_source_manager.save_state(DocusealResumeConfig(after=after))

        next_cursor = data.get("pagination", {}).get("next")
        # A null `next` or a short page (< limit) both signal the end of the list. Either way we
        # stop without issuing a final empty request.
        if not next_cursor or len(rows) < PAGE_SIZE:
            break
        after = next_cursor

    if batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def docuseal_source(
    api_key: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DocusealResumeConfig],
) -> SourceResponse:
    endpoint_config: DocusealEndpointConfig = DOCUSEAL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        # Rows arrive newest-first; declare it so the pipeline doesn't assume ascending order.
        sort_mode="desc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
    )
