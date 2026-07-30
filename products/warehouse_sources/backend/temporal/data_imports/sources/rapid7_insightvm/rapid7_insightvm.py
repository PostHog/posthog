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
from products.warehouse_sources.backend.temporal.data_imports.sources.rapid7_insightvm.settings import (
    API_BASE_PATH,
    MAX_PAGE_SIZE,
    RAPID7_INSIGHTVM_ENDPOINTS,
    REGION_HOSTS,
)

REQUEST_TIMEOUT_SECONDS = 120
RETRY_MAX_ATTEMPTS = 5


class Rapid7InsightvmRetryableError(Exception):
    pass


@dataclasses.dataclass
class Rapid7InsightvmResumeConfig:
    # Opaque cursor token returned in the previous page's `metadata.cursor`. `None` starts the
    # endpoint from its first page.
    cursor: str | None = None


def _host(region: str) -> str:
    return REGION_HOSTS.get(region, REGION_HOSTS["us"])


def _headers(api_key: str) -> dict[str, str]:
    return {
        "X-Api-Key": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _endpoint_url(region: str, path: str) -> str:
    return f"{_host(region)}{API_BASE_PATH}/{path}"


@retry(
    retry=retry_if_exception_type(
        (
            Rapid7InsightvmRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(RETRY_MAX_ATTEMPTS),
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
    # v4 search endpoints are POST operations; an empty JSON body returns all resources.
    full_url = f"{url}?{urlencode(params)}" if params else url
    response = session.post(full_url, headers=headers, json={}, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise Rapid7InsightvmRetryableError(
            f"Rapid7 InsightVM API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        logger.error(f"Rapid7 InsightVM API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[Rapid7InsightvmResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = RAPID7_INSIGHTVM_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    # `allow_redirects=False` keeps the credentialed `X-Api-Key` from being replayed to a
    # redirect target; `redact_values` masks the key in logged URLs and captured samples.
    session = make_tracked_session(redact_values=(api_key,), allow_redirects=False)
    url = _endpoint_url(region, config.path)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None

    while True:
        params: dict[str, Any] = {"size": MAX_PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor

        data = _fetch_page(session, url, headers, params, logger)

        items = data.get("data", [])
        if items:
            yield items

        metadata = data.get("metadata", {})
        next_cursor = metadata.get("cursor")

        # Cursored pagination terminates when the API stops handing back a fresh cursor: a missing
        # cursor, an unchanged cursor (some deployments echo the last token), or an empty page.
        if not items or not next_cursor or next_cursor == cursor:
            break

        cursor = next_cursor
        # Save state AFTER yielding the batch so a crash re-yields the last page (merge dedupes on
        # the primary key) rather than skipping it.
        resumable_source_manager.save_state(Rapid7InsightvmResumeConfig(cursor=cursor))


def validate_credentials(api_key: str, region: str) -> tuple[bool, Optional[str]]:
    # Probe the assets search endpoint with the smallest possible page. A valid key returns 200;
    # an invalid or expired key returns 401/403.
    url = _endpoint_url(region, RAPID7_INSIGHTVM_ENDPOINTS["assets"].path)
    try:
        response = make_tracked_session(redact_values=(api_key,), allow_redirects=False).post(
            f"{url}?{urlencode({'size': 1})}",
            headers=_headers(api_key),
            json={},
            timeout=30,
        )
    except Exception as e:
        return False, f"Could not reach Rapid7 InsightVM ({e}). Please check your network and selected region."

    if response.status_code == 200:
        return True, None
    if response.status_code in (401, 403):
        return False, "Rapid7 InsightVM rejected the API key. Check the key and selected region, then reconnect."
    return False, f"Rapid7 InsightVM returned an unexpected status ({response.status_code})."


def rapid7_insightvm_source(
    api_key: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[Rapid7InsightvmResumeConfig],
) -> SourceResponse:
    endpoint_config = RAPID7_INSIGHTVM_ENDPOINTS[endpoint]

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
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
