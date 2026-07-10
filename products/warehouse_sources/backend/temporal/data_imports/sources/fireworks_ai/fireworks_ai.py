import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import (
    FIREWORKS_AI_ENDPOINTS,
    FireworksAIEndpointConfig,
)

FIREWORKS_AI_BASE_URL = "https://api.fireworks.ai/v1"
# Control-plane list endpoints cap pageSize at 200 (values above are coerced down). Large pages
# keep the request count low against undocumented but generous control-plane rate limits.
PAGE_SIZE = 200
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class FireworksAIRetryableError(Exception):
    pass


@dataclasses.dataclass
class FireworksAIResumeConfig:
    # Opaque pagination token from a prior response's `nextPageToken`. We only persist state once we
    # hold a token, so a resumed run picks pagination back up at the next unfetched page.
    page_token: str


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _build_url(account_id: str, path: str, params: dict[str, Any]) -> str:
    base = f"{FIREWORKS_AI_BASE_URL}/accounts/{account_id}{path}"
    clean_params = {key: value for key, value in params.items() if value is not None}
    if not clean_params:
        return base
    return f"{base}?{urlencode(clean_params)}"


def validate_credentials(api_key: str, account_id: str) -> tuple[bool, int | None]:
    """Cheap authenticated probe against the account's models collection.

    Returns ``(ok, status_code)`` so the caller can distinguish a bad token (401) from a valid token
    lacking scope for a resource (403). Network failures return ``(False, None)``.
    """
    url = _build_url(account_id, "/models", {"pageSize": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.ok, response.status_code
    except Exception:
        return False, None


def get_rows(
    api_key: str,
    account_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FireworksAIResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = FIREWORKS_AI_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_token: str | None = resume_config.page_token if resume_config is not None else None
    if page_token:
        logger.debug(f"Fireworks AI: resuming {endpoint} from saved page token")

    @retry(
        retry=retry_if_exception_type(
            (
                FireworksAIRetryableError,
                requests.ReadTimeout,
                requests.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            )
        ),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(url: str) -> dict[str, Any]:
        response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise FireworksAIRetryableError(
                f"Fireworks AI API error (retryable): status={response.status_code}, url={url}"
            )

        if not response.ok:
            logger.error(f"Fireworks AI API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    while True:
        params: dict[str, Any] = {"pageSize": PAGE_SIZE, "pageToken": page_token}
        data = fetch_page(_build_url(account_id, config.path, params))

        items = data.get(config.data_key, []) or []
        if items:
            yield items

        page_token = data.get("nextPageToken") or None
        if not page_token:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; merge
        # dedupes the re-pulled rows on the primary key.
        resumable_source_manager.save_state(FireworksAIResumeConfig(page_token=page_token))


def fireworks_ai_source(
    api_key: str,
    account_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FireworksAIResumeConfig],
) -> SourceResponse:
    config: FireworksAIEndpointConfig = FIREWORKS_AI_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            account_id=account_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
