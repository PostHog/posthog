"""Transport layer for the Zendesk Sell (Base CRM) Core API.

Zendesk Sell's Core API lives at https://api.getbase.com/v2/. It returns a uniform envelope
(`{"items": [{"data": {...}, "meta": {...}}], "meta": {"links": {"next_page": ...}}}`) and paginates
with a 1-based `page` parameter plus `per_page` (max 100). We follow `meta.links.next_page` verbatim
rather than constructing page URLs ourselves, as the API docs instruct — but only after validating
each URL is still pinned to the Zendesk Sell API origin, so a hostile response or poisoned resume
state can't retarget an authenticated request at another host (`_validate_pagination_url`).

Every endpoint is full refresh. The Core API supports `sort_by` ordering but exposes no server-side
`updated_after` / `since` timestamp filter on its list endpoints, so there is no way to fetch only
changed rows cheaply — an "incremental" sort-and-skip would still page through the entire history each
run. True change capture is only available via the separate, queue-based Sync API. We therefore ship
full refresh and leave incremental off until that can be verified against a live account.
"""

import dataclasses
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zendesk_sell.settings import (
    ZENDESK_SELL_ENDPOINTS,
)

ZENDESK_SELL_BASE_URL = "https://api.getbase.com"
ZENDESK_SELL_HOST = "api.getbase.com"
ZENDESK_SELL_PATH_PREFIX = "/v2/"
PER_PAGE = 100
REQUEST_TIMEOUT_SECONDS = 60


class ZendeskSellRetryableError(Exception):
    pass


class ZendeskSellUntrustedURLError(Exception):
    """A pagination URL (resumed or upstream) pointed somewhere other than the Zendesk Sell API."""


def _validate_pagination_url(url: str) -> str:
    """Pin every authenticated request to the Zendesk Sell API origin.

    Both resumed `next_url` values (loaded from Redis) and upstream `meta.links.next_page` URLs are
    followed verbatim with the customer's bearer token. Validating the scheme, host, and `/v2/` path
    prefix keeps a poisoned resume state or a hostile upstream response from retargeting the request at
    another host and leaking the token (SSRF). Returns the URL unchanged when it is trusted.
    """
    parts = urlsplit(url)
    is_trusted = (
        parts.scheme == "https"
        and parts.netloc == ZENDESK_SELL_HOST
        and parts.path.startswith(ZENDESK_SELL_PATH_PREFIX)
    )
    if not is_trusted:
        raise ZendeskSellUntrustedURLError(
            f"Refusing to follow pagination URL outside {ZENDESK_SELL_BASE_URL}{ZENDESK_SELL_PATH_PREFIX}"
        )
    return url


@dataclasses.dataclass
class ZendeskSellResumeConfig:
    # Full next-page URL returned by the API. None means "start the endpoint at its first page".
    next_url: str | None = None


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _build_initial_url(path: str) -> str:
    return f"{ZENDESK_SELL_BASE_URL}{path}?{urlencode({'per_page': PER_PAGE})}"


@retry(
    retry=retry_if_exception_type((ZendeskSellRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (rate limit: 10 req/s, 36k/hour) and transient 5xx are safe to retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise ZendeskSellRetryableError(f"Zendesk Sell API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error("Zendesk Sell API error", status=response.status_code, body=response.text, url=url)
        response.raise_for_status()

    return response.json()


def _extract_records(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Unwrap each item's `data` object from the collection envelope.

    Every item in the Zendesk Sell envelope carries a `data` object — direct access fails fast on a
    malformed response rather than silently dropping records.
    """
    return [item["data"] for item in payload.get("items", [])]


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendeskSellResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = ZENDESK_SELL_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    # One session reused across every page so urllib3 keeps the connection alive. `redact_values`
    # masks the bearer token in logged URLs and captured request samples. `allow_redirects=False`
    # stops a redirect response from sending the bearer token to another host.
    session = make_tracked_session(redact_values=(access_token,), allow_redirects=False)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        # Resume state comes from Redis — validate before sending the token to it.
        url: str | None = _validate_pagination_url(resume.next_url)
        logger.debug(f"Zendesk Sell: resuming {endpoint} from URL: {url}")
    else:
        url = _build_initial_url(config.path)

    while url:
        payload = _fetch_page(session, url, headers, logger)

        records = _extract_records(payload)
        next_url = payload.get("meta", {}).get("links", {}).get("next_page")
        # The upstream-supplied next-page URL is followed verbatim with the bearer token — pin it to
        # the Zendesk Sell API so a hostile response can't retarget the authenticated request.
        if next_url:
            next_url = _validate_pagination_url(next_url)

        if records:
            yield records

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; merge dedupes
        # on the primary key. Only persist when there's another page to resume to.
        if next_url:
            resumable_source_manager.save_state(ZendeskSellResumeConfig(next_url=next_url))

        url = next_url


def zendesk_sell_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ZendeskSellResumeConfig],
) -> SourceResponse:
    config = ZENDESK_SELL_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
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


def validate_credentials(access_token: str) -> bool:
    """Cheap probe that the access token is genuine: list a single contact."""
    url = f"{ZENDESK_SELL_BASE_URL}/v2/contacts?{urlencode({'per_page': 1})}"
    try:
        session = make_tracked_session(redact_values=(access_token,), allow_redirects=False)
        response = session.get(url, headers=_get_headers(access_token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False
