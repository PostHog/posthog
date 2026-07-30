import re
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fireworks_ai.settings import (
    FIREWORKS_AI_ENDPOINTS,
    PAGE_SIZE,
)

FIREWORKS_AI_BASE_URL = "https://api.fireworks.ai/v1"

_ACCOUNT_ID_REGEX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


class FireworksAIRetryableError(Exception):
    pass


@dataclasses.dataclass
class FireworksAIResumeConfig:
    # Opaque nextPageToken from the last committed page. The API requires all other params to
    # match the original call, so the transport re-sends the same pageSize alongside it.
    page_token: str


def normalize_account_id(account_id: str) -> str:
    """Reduce whatever the user entered to the bare Fireworks account id.

    Users may paste the full resource prefix ("accounts/my-account") shown throughout the
    Fireworks docs and firectl output. Without normalizing, the request path becomes
    /v1/accounts/accounts/my-account/... which can never resolve.
    """
    account_id = account_id.strip().strip("/")
    if account_id.startswith("accounts/"):
        account_id = account_id[len("accounts/") :]
    return account_id


def is_valid_account_id(account_id: str) -> bool:
    return _ACCOUNT_ID_REGEX.match(account_id) is not None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


@retry(
    retry=retry_if_exception_type(
        (
            FireworksAIRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session,
    url: str,
    params: dict[str, Any] | None,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
) -> Any:
    response = session.get(url, params=params, headers=headers, timeout=60)

    # 429 (rate limit) and 5xx are transient — retry with backoff.
    if response.status_code == 429 or response.status_code >= 500:
        raise FireworksAIRetryableError(f"Fireworks AI API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Never log response.text or the raw URL: the error body can echo account content and the
        # query string carries pagination tokens. Log only status plus scheme/host/path.
        safe = urlsplit(response.url)
        safe_url = f"{safe.scheme}://{safe.netloc}{safe.path}"
        logger.error("Fireworks AI API error", status=response.status_code, url=safe_url)
        # raise_for_status() would embed the full request URL in the exception, which is surfaced as
        # the schema's latest_error. Rebuild the error from scheme/host/path only. The
        # "<status> Client Error: <reason> for url: https://api.fireworks.ai" prefix stays stable
        # for get_non_retryable_errors() matching.
        raise requests.HTTPError(
            f"{response.status_code} Client Error: {response.reason} for url: {safe_url}",
            response=response,
        )

    return response.json()


def _extract_rows(payload: Any, data_key: str, endpoint: str) -> list[dict[str, Any]]:
    """Unwrap the AIP list envelope: {"<collection>": [...], "nextPageToken": ..., "totalSize": n}.

    Proto3 JSON omits empty repeated fields, so a missing collection key means an empty page,
    not a shape error.
    """
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected Fireworks AI response shape for endpoint '{endpoint}': {type(payload).__name__}")

    rows = payload.get(data_key, [])
    if not isinstance(rows, list):
        raise ValueError(f"Unexpected Fireworks AI '{data_key}' value for endpoint '{endpoint}': not a list")

    return [row for row in rows if isinstance(row, dict)]


def get_rows(
    api_key: str,
    account_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FireworksAIResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = FIREWORKS_AI_ENDPOINTS[endpoint]
    # Disable the session's built-in urllib3 retry layer: `_fetch` already retries 429/5xx (via
    # `FireworksAIRetryableError`) and timeouts/connection errors through tenacity. Leaving the
    # default in place would stack retries under tenacity's 5 attempts.
    session = make_tracked_session(redact_values=(api_key,), retry=Retry(total=0))
    headers = _get_headers(api_key)
    url = f"{FIREWORKS_AI_BASE_URL}/accounts/{normalize_account_id(account_id)}/{endpoint_config.path}"

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_token: str | None = resume.page_token if resume else None
    if page_token:
        logger.debug("Fireworks AI: resuming from saved page token", endpoint=endpoint)

    while True:
        params: dict[str, Any] = {"pageSize": PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token

        payload = _fetch(session, url, params, headers, logger)
        rows = _extract_rows(payload, endpoint_config.data_key, endpoint)
        logger.debug("Fireworks AI: fetched page", count=len(rows), endpoint=endpoint)
        if rows:
            yield rows

        next_token = payload.get("nextPageToken")
        if not next_token:
            break
        # Save state after yielding the batch: a crash re-yields the last page (merge dedupes on
        # the primary key) rather than skipping it.
        resumable_source_manager.save_state(FireworksAIResumeConfig(page_token=next_token))
        page_token = next_token


def fireworks_ai_source(
    api_key: str,
    account_id: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FireworksAIResumeConfig],
) -> SourceResponse:
    endpoint_config = FIREWORKS_AI_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            account_id=account_id,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[endpoint_config.partition_key],
    )


def get_status_code(api_key: str, account_id: str, endpoint: str | None = None) -> int:
    """Cheap probe used by credential validation. Returns the HTTP status code."""
    if endpoint is not None and endpoint in FIREWORKS_AI_ENDPOINTS:
        path = FIREWORKS_AI_ENDPOINTS[endpoint].path
    else:
        # Models is account-scoped and readable by any key — a cheap token + account check.
        path = FIREWORKS_AI_ENDPOINTS["models"].path

    url = f"{FIREWORKS_AI_BASE_URL}/accounts/{normalize_account_id(account_id)}/{path}"
    response = make_tracked_session(redact_values=(api_key,)).get(
        url, params={"pageSize": 1}, headers=_get_headers(api_key), timeout=10
    )
    return response.status_code
