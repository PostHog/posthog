import base64
import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.drip.settings import DRIP_ENDPOINTS

DRIP_BASE_URL = "https://api.getdrip.com/v2"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class DripRetryableError(Exception):
    pass


@dataclasses.dataclass
class DripResumeConfig:
    next_page: int


def _auth_headers(api_token: str) -> dict[str, str]:
    # Drip uses HTTP Basic auth with the API token as the username and an empty password.
    token = base64.b64encode(f"{api_token}:".encode("ascii")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def validate_credentials(api_token: str, account_id: str) -> tuple[bool, str | None]:
    url = f"{DRIP_BASE_URL}/{account_id}/subscribers"
    try:
        response = make_tracked_session().get(
            url, headers=_auth_headers(api_token), params={"per_page": 1}, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return False, "Could not connect to the Drip API"

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Drip API token"
    if response.status_code == 404:
        return False, "Drip account ID not found. Please check your account ID."
    return False, f"Drip API returned an unexpected status ({response.status_code})"


def _base_params(endpoint: str) -> dict[str, Any]:
    config = DRIP_ENDPOINTS[endpoint]
    params: dict[str, Any] = {}
    if config.per_page is not None:
        params["per_page"] = config.per_page
    if config.sort is not None:
        params["sort"] = config.sort
    if config.direction is not None:
        params["direction"] = config.direction
    return params


def get_rows(
    api_token: str,
    account_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DripResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = DRIP_ENDPOINTS[endpoint]
    headers = _auth_headers(api_token)
    base_params = _base_params(endpoint)
    url = f"{DRIP_BASE_URL}/{account_id}{config.path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1
    if resume is not None:
        logger.debug(f"Drip: resuming {endpoint} from page {page}")

    @retry(
        retry=retry_if_exception_type((DripRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_num: int) -> dict[str, Any]:
        response = make_tracked_session().get(
            url, headers=headers, params={**base_params, "page": page_num}, timeout=REQUEST_TIMEOUT_SECONDS
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise DripRetryableError(f"Drip API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Drip API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(page)
        items = data.get(config.data_key) or []

        if items:
            yield items

        if not _has_next_page(data, items, config.per_page, page):
            break

        page += 1
        # Save state AFTER yielding so a crash re-yields the last page rather than skipping it
        # (merge on the primary key dedupes the overlap).
        resumable_source_manager.save_state(DripResumeConfig(next_page=page))


def _has_next_page(data: dict[str, Any], items: list[Any], per_page: int | None, page: int) -> bool:
    meta = data.get("meta") or {}
    total_pages = meta.get("total_pages")
    if total_pages is not None:
        return page < total_pages
    # Fallback for paginated endpoints that don't return a meta block: a full page implies there may be
    # more. Non-paginated endpoints (per_page is None) always return everything in a single response.
    if per_page is not None:
        return len(items) >= per_page
    return False


def drip_source(
    api_token: str,
    account_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DripResumeConfig],
) -> SourceResponse:
    config = DRIP_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
            account_id=account_id,
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
