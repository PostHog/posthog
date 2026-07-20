import re
import dataclasses
from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.devin_ai.settings import DEVIN_AI_ENDPOINTS

DEVIN_AI_BASE_URL = "https://api.devin.ai"
# v3 cursor pagination caps `first` at 200.
PAGE_SIZE = 200


class DevinAIRetryableError(Exception):
    pass


@dataclasses.dataclass
class DevinAIResumeConfig:
    # Opaque cursor from the previous page's `end_cursor`, passed back as `after`. None starts at page 1.
    after: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


# Devin org IDs look like `org-<slug>`. Constrain to the characters an ID can legitimately contain so a
# malformed value can't inject `/` or `?` and route the stored API key at a different Devin API path.
_ORG_ID_RE = re.compile(r"[a-zA-Z0-9._-]+")


def _validate_org_id(org_id: str) -> str:
    org = org_id.strip()
    if not _ORG_ID_RE.fullmatch(org):
        raise ValueError(f"Invalid Devin organization ID: {org_id}")
    return org


def _endpoint_path(endpoint: str, org_id: str) -> str:
    return DEVIN_AI_ENDPOINTS[endpoint].path.format(org_id=_validate_org_id(org_id))


@retry(
    retry=retry_if_exception_type(
        (
            DevinAIRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> dict:
    response = session.get(url, params=params, headers=headers, timeout=60)

    # 429 (rate limit) and 5xx are transient — retry with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise DevinAIRetryableError(f"Devin API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Devin API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_status_code(api_key: str, org_id: str, endpoint: str) -> int:
    """Cheap single-page probe used by credential validation. Returns the HTTP status code."""
    url = f"{DEVIN_AI_BASE_URL}{_endpoint_path(endpoint, org_id)}"
    response = make_tracked_session().get(url, params={"first": 1}, headers=_get_headers(api_key), timeout=10)
    return response.status_code


def get_rows(
    api_key: str,
    org_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DevinAIResumeConfig],
) -> Iterator[Any]:
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    url = f"{DEVIN_AI_BASE_URL}{_endpoint_path(endpoint, org_id)}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    after = resume.after if resume else None
    if after:
        logger.debug(f"Devin: resuming {endpoint} from cursor: {after}")

    # Yield one full page at a time and only save state at the page boundary, after the page has been
    # yielded. The pipeline batches internally, so a source-level batcher would only double-buffer and,
    # because it spans pages, would force a mid-page save that drops the un-yielded tail on crash-resume.
    while True:
        params: dict[str, Any] = {"first": PAGE_SIZE}
        if after:
            params["after"] = after

        data = _fetch_page(session, url, params, headers, logger)

        items = data.get("items", [])
        if items:
            yield items

        next_cursor = data.get("end_cursor")
        if not data.get("has_next_page") or not next_cursor:
            break

        after = next_cursor
        # Save state AFTER yielding the page so a crash re-fetches this page (merge dedupes on the
        # primary key) rather than skipping it.
        resumable_source_manager.save_state(DevinAIResumeConfig(after=next_cursor))


def devin_ai_source(
    api_key: str,
    org_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[DevinAIResumeConfig],
) -> SourceResponse:
    endpoint_config = DEVIN_AI_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            org_id=org_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(api_key: str, org_id: str, endpoint: str = "sessions") -> int:
    """Probe the given endpoint and return its HTTP status code (or raise on transport failure)."""
    return get_status_code(api_key, org_id, endpoint)
