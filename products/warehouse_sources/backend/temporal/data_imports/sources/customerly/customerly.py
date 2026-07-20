import dataclasses
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.settings import (
    CUSTOMERLY_ENDPOINTS,
    CustomerlyEndpointConfig,
)

CUSTOMERLY_BASE_URL = "https://api.customerly.io/v1"
PAGE_SIZE = 50
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

AUTH_ERROR_MARKERS = (
    "Access token not found",
    "You must provide a valid header",
)


class CustomerlyRetryableError(Exception):
    pass


class CustomerlyAuthenticationError(Exception):
    pass


@dataclasses.dataclass
class CustomerlyResumeConfig:
    page: int
    # Set while walking the knowledge base articles fan-out: collections with a lower id
    # have already been fully synced and are skipped on resume.
    collection_id: Optional[int] = None


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _build_url(path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return f"{CUSTOMERLY_BASE_URL}{path}"
    return f"{CUSTOMERLY_BASE_URL}{path}?{urlencode(clean_params)}"


def _is_auth_error_body(body: str) -> bool:
    return any(marker in body for marker in AUTH_ERROR_MARKERS)


def _make_fetch_page(headers: dict[str, str], logger: FilteringBoundLogger):
    @retry(
        retry=retry_if_exception_type((CustomerlyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        # Customerly reports missing/invalid access tokens as HTTP 500 with an error body,
        # so auth failures must be detected before the generic retryable-5xx handling.
        if response.status_code in (401, 403, 500) and _is_auth_error_body(response.text):
            raise CustomerlyAuthenticationError(
                f"Customerly authentication failed: invalid or expired access token (url={page_url})"
            )

        if response.status_code == 429 or response.status_code >= 500:
            raise CustomerlyRetryableError(
                f"Customerly API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Customerly API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    return fetch_page


def _extract_items(data: dict[str, Any], config: CustomerlyEndpointConfig) -> list[Any]:
    payload = data.get("data")
    if config.data_key is not None:
        if not isinstance(payload, dict):
            return []
        return payload.get(config.data_key) or []
    if isinstance(payload, list):
        return payload
    return []


def _normalize_tags(items: list[Any]) -> list[dict[str, Any]]:
    # /v1/tags returns a bare list of tag names; shape them into rows.
    return [{"name": tag} for tag in items if isinstance(tag, str)]


def validate_credentials(access_token: str) -> bool:
    """Confirm the access token is valid. /v1/tags is a cheap single-request probe."""
    try:
        response = make_tracked_session().get(
            f"{CUSTOMERLY_BASE_URL}/tags",
            headers=_get_headers(access_token),
            timeout=10,
        )
        return response.ok
    except Exception:
        return False


def _paginate(
    fetch_page,
    path: str,
    base_params: dict[str, Any],
    config: CustomerlyEndpointConfig,
    start_page: int,
    on_page_complete,
) -> Iterator[list[dict[str, Any]]]:
    """Walk a page-number paginated endpoint from `start_page` until a short/empty page.

    `on_page_complete(next_page)` is called after each full page has been yielded so the
    caller can persist resume state (re-yielding the last page on crash is fine — merge
    dedupes on primary key).
    """
    page = start_page
    while True:
        url = _build_url(path, {**base_params, "page": page, "per_page": PAGE_SIZE})
        data = fetch_page(url)
        items = _extract_items(data, config)

        if items:
            yield items

        # The API signals the end of the list only by returning a short or empty page.
        if len(items) < PAGE_SIZE:
            break

        page += 1
        on_page_complete(page)


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CustomerlyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = CUSTOMERLY_ENDPOINTS[endpoint]
    fetch_page = _make_fetch_page(_get_headers(access_token), logger)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        logger.debug(f"Customerly: resuming {endpoint} from page={resume_config.page}")

    if config.fan_out_by_collection:
        yield from _get_article_rows(fetch_page, config, resumable_source_manager, resume_config, logger)
        return

    if not config.paginated:
        data = fetch_page(_build_url(config.path, {}))
        items = _extract_items(data, config)
        if endpoint == "tags":
            items = _normalize_tags(items)
        if items:
            yield items
        return

    start_page = resume_config.page if resume_config is not None else 0
    # Sort params match the documented example for the users/leads lists; an explicit sort
    # keeps page boundaries stable while paginating (merge on primary key dedupes any
    # rows that shift across pages mid-sync).
    base_params = {"sort": "name", "sort_direction": "asc"}

    yield from _paginate(
        fetch_page,
        config.path,
        base_params,
        config,
        start_page,
        lambda next_page: resumable_source_manager.save_state(CustomerlyResumeConfig(page=next_page)),
    )


def _get_article_rows(
    fetch_page,
    config: CustomerlyEndpointConfig,
    resumable_source_manager: ResumableSourceManager[CustomerlyResumeConfig],
    resume_config: Optional[CustomerlyResumeConfig],
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Articles are listed per knowledge base collection, so fan out over the collections
    (walked in ascending id order to make resume deterministic)."""
    collections_config = CUSTOMERLY_ENDPOINTS["knowledge_base_collections"]
    collections_data = fetch_page(_build_url(collections_config.path, {}))
    collections = _extract_items(collections_data, collections_config)

    collection_ids = sorted(
        cid
        for cid in (collection.get("knowledge_base_collection_id") for collection in collections)
        if isinstance(cid, int)
    )

    for collection_id in collection_ids:
        start_page = 0
        if resume_config is not None and resume_config.collection_id is not None:
            if collection_id < resume_config.collection_id:
                continue
            if collection_id == resume_config.collection_id:
                start_page = resume_config.page

        logger.debug(f"Customerly: fetching articles for collection_id={collection_id} from page={start_page}")

        yield from _paginate(
            fetch_page,
            config.path,
            {"knowledge_base_collection_id": collection_id},
            config,
            start_page,
            lambda next_page, cid=collection_id: resumable_source_manager.save_state(
                CustomerlyResumeConfig(page=next_page, collection_id=cid)
            ),
        )

        # Checkpoint the next collection so a resume doesn't rewalk this one from page 0.
        resumable_source_manager.save_state(CustomerlyResumeConfig(page=0, collection_id=collection_id + 1))


def customerly_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CustomerlyResumeConfig],
) -> SourceResponse:
    config = CUSTOMERLY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
