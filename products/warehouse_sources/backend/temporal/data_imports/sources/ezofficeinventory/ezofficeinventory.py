import re
import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.ezofficeinventory.settings import (
    EZOFFICEINVENTORY_ENDPOINTS,
    EZOfficeInventoryEndpointConfig,
)

# EZOfficeInventory enforces a per-account hostname, so only the subdomain label is user-supplied.
# Restricting it to host-safe characters keeps the request pinned to *.ezofficeinventory.com.
SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9-]+$")

REQUEST_TIMEOUT_SECONDS = 60


class EZOfficeInventoryRetryableError(Exception):
    """Raised for transient API responses (429 / 5xx) so tenacity retries them."""


@dataclasses.dataclass
class EZOfficeInventoryResumeConfig:
    # Next page (1-indexed) to fetch when resuming an interrupted sync.
    next_page: int


def base_url(subdomain: str) -> str:
    return f"https://{subdomain}.ezofficeinventory.com"


def _headers(api_key: str) -> dict[str, str]:
    return {"token": api_key, "Accept": "application/json"}


def _extract_items(data: dict[str, Any], config: EZOfficeInventoryEndpointConfig) -> list[dict[str, Any]]:
    """Pull the record list out of the response, unwrapping single-key item objects where needed."""
    items = data.get(config.data_selector) or []
    if not isinstance(items, list):
        return []
    if config.unwrap_key:
        unwrapped = []
        for item in items:
            if isinstance(item, dict) and config.unwrap_key in item:
                unwrapped.append(item[config.unwrap_key])
            else:
                unwrapped.append(item)
        return unwrapped
    return items


@retry(
    retry=retry_if_exception_type((EZOfficeInventoryRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(6),
    wait=wait_exponential_jitter(initial=2, max=70),
    reraise=True,
)
def _fetch_page(session: requests.Session, url: str, logger: FilteringBoundLogger) -> dict[str, Any]:
    response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)

    # Fair-use limit is ~60 req/min; the API returns 429 with a Retry-After header. Treat 429 and
    # 5xx as transient and let tenacity back off (max ~70s covers a full rate-limit window reset).
    if response.status_code == 429 or response.status_code >= 500:
        raise EZOfficeInventoryRetryableError(
            f"EZOfficeInventory API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        logger.error(f"EZOfficeInventory API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _build_url(subdomain: str, config: EZOfficeInventoryEndpointConfig, page: int) -> str:
    params: dict[str, Any] = dict(config.extra_params)
    params["page"] = page
    return f"{base_url(subdomain)}/{config.path}?{urlencode(params)}"


def get_rows(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EZOfficeInventoryResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = EZOFFICEINVENTORY_ENDPOINTS[endpoint]
    headers = _headers(api_key)
    # One session reused across pages so urllib3 keeps the connection alive.
    # Redirects are pinned off so the user-supplied token can't be replayed to a
    # cross-host redirect target (SSRF / credential-exfiltration defense-in-depth).
    # urllib3 retries are disabled so tenacity (on `_fetch_page`) is the single retry
    # layer — otherwise 429/5xx would be retried by both, compounding the backoff.
    session = make_tracked_session(
        headers=headers, redact_values=(api_key,), allow_redirects=False, retry=Retry(total=0)
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume else 1

    while True:
        data = _fetch_page(session, _build_url(subdomain, config, page), logger)
        items = _extract_items(data, config)
        if not items:
            break

        yield items

        total_pages = data.get("total_pages")
        has_more = total_pages is None or page < total_pages
        if not has_more:
            break

        # Checkpoint AFTER yielding so a crash re-fetches the page we just emitted rather than
        # skipping it — merge dedupes the re-yielded rows on the primary key.
        page += 1
        resumable_source_manager.save_state(EZOfficeInventoryResumeConfig(next_page=page))


def ezofficeinventory_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[EZOfficeInventoryResumeConfig],
) -> SourceResponse:
    config = EZOFFICEINVENTORY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            subdomain=subdomain,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str, subdomain: str) -> tuple[bool, str | None]:
    """Return (is_valid, error_message). A non-None message overrides the generic
    "invalid credentials" error so transient failures (e.g. rate limiting) aren't
    misreported as bad credentials."""
    if not SUBDOMAIN_REGEX.match(subdomain):
        return False, None
    try:
        response = make_tracked_session(
            headers=_headers(api_key), redact_values=(api_key,), allow_redirects=False, retry=Retry(total=0)
        ).get(
            f"{base_url(subdomain)}/assets.api?page=1",
            timeout=10,
        )
    except Exception:
        return False, None

    if response.status_code == 200:
        return True, None

    # The fair-use cap is ~60 req/min; a 429 here means we couldn't verify the token, not that it's
    # wrong. Surface that distinctly so the user isn't told their credentials are invalid.
    if response.status_code == 429:
        return (
            False,
            "EZOfficeInventory rate limit reached while validating credentials. Please wait a minute and try again.",
        )

    return False, None
