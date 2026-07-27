import base64
import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.batcher import Batcher
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox_sign.settings import (
    DROPBOX_SIGN_ENDPOINTS,
)

DROPBOX_SIGN_BASE_URL = "https://api.hellosign.com/v3"
# The API caps page_size at 100 (default 20); always request the max to minimize round-trips.
PAGE_SIZE = 100


class DropboxSignRetryableError(Exception):
    pass


@dataclasses.dataclass
class DropboxSignResumeConfig:
    # Next page number (1-based) to fetch. Page-number pagination is the only resume key the API
    # offers — there's no cursor token or stable time filter — so a mid-sync restart re-fetches from
    # this page and merge/replace dedupes the small overlap on the endpoint's primary key.
    page: int = 1


def _get_headers(api_key: str) -> dict[str, str]:
    # HTTP Basic auth: the API key is the username with a blank password.
    token = base64.b64encode(f"{api_key}:".encode("ascii")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}


def validate_credentials(api_key: str) -> bool:
    # /account is the cheapest authenticated probe — it returns the connected account with no
    # pagination and requires no special scope beyond a valid key.
    try:
        response = make_tracked_session().get(
            f"{DROPBOX_SIGN_BASE_URL}/account", headers=_get_headers(api_key), timeout=10
        )
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type((DropboxSignRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    params: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict:
    response = session.get(url, headers=headers, params=params, timeout=60)

    # Dropbox Sign returns 429 when a rate-limit window is exceeded (10-100 req/min depending on
    # tier/mode). Back off and retry; 5xx is treated the same.
    if response.status_code == 429 or response.status_code >= 500:
        raise DropboxSignRetryableError(f"Dropbox Sign API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Dropbox Sign API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _redact(item: Any, paths: list[str]) -> Any:
    """Strip sensitive nested values (dotted paths) from an upstream record in place before it is
    persisted to the warehouse, so a warehouse reader never sees them."""
    if not isinstance(item, dict):
        return item
    for path in paths:
        keys = path.split(".")
        parent: Any = item
        for key in keys[:-1]:
            if not isinstance(parent, dict):
                break
            parent = parent.get(key)
        else:
            if isinstance(parent, dict):
                parent.pop(keys[-1], None)
    return item


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DropboxSignResumeConfig],
) -> Iterator[Any]:
    config = DROPBOX_SIGN_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    batcher = Batcher(logger=logger, chunk_size=2000, chunk_size_bytes=100 * 1024 * 1024)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()
    url = f"{DROPBOX_SIGN_BASE_URL}{config.path}"

    if config.is_single_object:
        data = _fetch_page(session, url, headers, {}, logger)
        obj = data.get(config.data_key)
        if obj:
            batcher.batch(_redact(obj, config.redact_paths))
        while batcher.should_yield(include_incomplete_chunk=True):
            yield batcher.get_table()
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 1

    while True:
        data = _fetch_page(session, url, headers, {"page": page, "page_size": PAGE_SIZE}, logger)
        items = data.get(config.data_key) or []
        num_pages = (data.get("list_info") or {}).get("num_pages") or 1

        for item in items:
            batcher.batch(_redact(item, config.redact_paths))
            while batcher.should_yield():
                yield batcher.get_table()
                # Save AFTER yielding so a crash re-yields (never skips) the in-flight page. Only
                # persist when a later page remains — the saved page is re-fetched on resume.
                if page < num_pages:
                    resumable_source_manager.save_state(DropboxSignResumeConfig(page=page))

        if page >= num_pages or not items:
            break
        page += 1

    while batcher.should_yield(include_incomplete_chunk=True):
        yield batcher.get_table()


def dropbox_sign_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DropboxSignResumeConfig],
) -> SourceResponse:
    config = DROPBOX_SIGN_ENDPOINTS[endpoint]

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
