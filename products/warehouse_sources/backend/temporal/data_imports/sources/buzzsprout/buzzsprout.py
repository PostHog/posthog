from collections.abc import Iterator
from typing import Any

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.settings import (
    BUZZSPROUT_ENDPOINTS,
    BuzzsproutEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

BUZZSPROUT_BASE_URL = "https://www.buzzsprout.com/api"

# Buzzsprout blocks requests sent with a default/bot User-Agent, so we identify ourselves explicitly.
USER_AGENT = "PostHog Data Warehouse (https://posthog.com)"

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5


class BuzzsproutRetryableError(Exception):
    pass


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Token token={api_token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }


def _build_url(podcast_id: str, config: BuzzsproutEndpointConfig) -> str:
    if config.account_scoped:
        return f"{BUZZSPROUT_BASE_URL}/{config.path}"
    return f"{BUZZSPROUT_BASE_URL}/{podcast_id.strip()}/{config.path}"


@retry(
    retry=retry_if_exception_type((BuzzsproutRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> list[dict[str, Any]]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # Buzzsprout's docs recommend retrying on transient 5xx; 429 is retried too should rate limiting
    # ever be introduced (none is documented today).
    if response.status_code == 429 or response.status_code >= 500:
        raise BuzzsproutRetryableError(f"Buzzsprout API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Only the status and URL are logged — the upstream response body can carry account-specific
        # data (private episode metadata, emails) that must not be copied into PostHog logs.
        logger.error(f"Buzzsprout API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    data = response.json()
    # Every documented Buzzsprout endpoint returns a bare JSON array.
    return data if isinstance(data, list) else []


def validate_credentials(api_token: str, podcast_id: str) -> tuple[bool, str | None]:
    podcast_id = podcast_id.strip()
    if not podcast_id:
        return False, "A Buzzsprout podcast ID is required."

    # The episodes endpoint is scoped to the podcast_id, so a 200 confirms both the token and the ID
    # in a single cheap probe.
    url = f"{BUZZSPROUT_BASE_URL}/{podcast_id}/episodes.json"
    try:
        response = make_tracked_session(redact_values=(api_token,)).get(
            url, headers=_get_headers(api_token), timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return False, "Could not reach the Buzzsprout API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid Buzzsprout API token. Create a new token in your Buzzsprout account settings."
    if response.status_code == 404:
        return False, "Buzzsprout podcast not found. Check the podcast ID."
    # A transient 429/5xx (after the session's own retries are exhausted) is not a credential problem,
    # so surface it as a retryable condition rather than rejecting otherwise-valid credentials.
    if response.status_code == 429 or response.status_code >= 500:
        return False, "Buzzsprout API is temporarily unavailable. Please try again in a moment."

    return False, f"Buzzsprout API returned an unexpected status code: {response.status_code}"


def get_rows(
    api_token: str, podcast_id: str, endpoint: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    config = BUZZSPROUT_ENDPOINTS[endpoint]
    session = make_tracked_session(redact_values=(api_token,))
    url = _build_url(podcast_id, config)

    # Buzzsprout has no pagination: each endpoint returns its full array in one response, so a single
    # fetch is the whole table. The pipeline batches the yielded list for us.
    rows = _fetch(session, url, _get_headers(api_token), logger)
    if rows:
        yield rows


def buzzsprout_source(api_token: str, podcast_id: str, endpoint: str, logger: FilteringBoundLogger) -> SourceResponse:
    config = BUZZSPROUT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(api_token=api_token, podcast_id=podcast_id, endpoint=endpoint, logger=logger),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
