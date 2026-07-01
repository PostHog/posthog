import re
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
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.settings import (
    PIPEDRIVE_ENDPOINTS,
    PipedriveEndpointConfig,
)

# Pipedrive caps list pages at 500 items (default 100).
PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9-]+$")


class PipedriveRetryableError(Exception):
    pass


@dataclasses.dataclass
class PipedriveResumeConfig:
    # Full URL (query string included, token is sent via header so never present here) of the
    # next page to fetch. Unifies cursor (v2) and offset (v1) pagination behind one resume key.
    next_url: str


def normalize_company_domain(raw: str) -> str:
    """Reduce whatever the user typed to the bare Pipedrive subdomain.

    Accepts ``mycompany``, ``mycompany.pipedrive.com`` or ``https://mycompany.pipedrive.com``.
    Raises ``ValueError`` if the result isn't a plain subdomain, which also pins outbound
    traffic to ``*.pipedrive.com`` (no SSRF to arbitrary hosts).
    """
    domain = raw.strip().lower()
    domain = domain.removeprefix("https://").removeprefix("http://")
    domain = domain.split("/")[0]
    domain = domain.removesuffix(".pipedrive.com")
    if not _SUBDOMAIN_RE.match(domain):
        raise ValueError(f"Invalid Pipedrive company domain: {raw!r}")
    return domain


def base_url(company_domain: str) -> str:
    return f"https://{normalize_company_domain(company_domain)}.pipedrive.com"


def _get_headers(api_token: str) -> dict[str, str]:
    return {"x-api-token": api_token, "Accept": "application/json"}


def _build_url(company_domain: str, path: str, params: dict[str, Any]) -> str:
    clean_params = {key: value for key, value in params.items() if value is not None}
    url = f"{base_url(company_domain)}{path}"
    if not clean_params:
        return url
    return f"{url}?{urlencode(clean_params)}"


def _initial_url(company_domain: str, config: PipedriveEndpointConfig) -> str:
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if config.pagination == "offset":
        params["start"] = 0
    return _build_url(company_domain, config.path, params)


def _next_url(company_domain: str, config: PipedriveEndpointConfig, response: dict[str, Any]) -> Optional[str]:
    additional_data = response.get("additional_data") or {}

    if config.pagination == "cursor":
        next_cursor = additional_data.get("next_cursor")
        if not next_cursor:
            return None
        return _build_url(company_domain, config.path, {"limit": PAGE_SIZE, "cursor": next_cursor})

    pagination = additional_data.get("pagination") or {}
    if not pagination.get("more_items_in_collection"):
        return None
    next_start = pagination.get("next_start")
    if next_start is None:
        return None
    return _build_url(company_domain, config.path, {"limit": PAGE_SIZE, "start": next_start})


def validate_credentials(company_domain: str, api_token: str) -> Optional[int]:
    """Return the status code of a cheap authenticated probe, or ``None`` on transport error.

    ``/api/v1/users/me`` resolves the token's own user and is reachable by any valid token.
    """
    # Built outside the `try` so an invalid-domain `ValueError` from `_build_url` propagates to
    # the caller rather than being swallowed into `None` by the broad transport-error handler.
    url = _build_url(company_domain, "/api/v1/users/me", {})
    try:
        session = make_tracked_session(headers=_get_headers(api_token), redact_values=(api_token,))
        response = session.get(url, timeout=10)
        return response.status_code
    except Exception:
        return None


def get_rows(
    company_domain: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PipedriveResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    config = PIPEDRIVE_ENDPOINTS[endpoint]
    # `redact_values` masks the token (sent via the custom `x-api-token` header, which the
    # name-based denylist can't catch) in logged URLs and captured HTTP samples.
    session = make_tracked_session(headers=_get_headers(api_token), redact_values=(api_token,))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str = resume_config.next_url
        logger.debug(f"Pipedrive: resuming {endpoint} from URL: {url}")
    else:
        url = _initial_url(company_domain, config)

    @retry(
        retry=retry_if_exception_type((PipedriveRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = session.get(page_url, timeout=REQUEST_TIMEOUT_SECONDS)

        # Pipedrive uses token-based rate limiting; 429s and transient 5xx are retried with
        # exponential backoff.
        if response.status_code == 429 or response.status_code >= 500:
            raise PipedriveRetryableError(
                f"Pipedrive API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Pipedrive API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(url)
        items = data.get("data") or []

        if items:
            yield items

        next_url = _next_url(company_domain, config, data)
        if not next_url:
            break

        # Save the next-page pointer only after the current page has been processed (yielded
        # above when it had rows), so a crash resumes at this page rather than past it. Merge
        # dedupes on primary key any rows re-yielded on resume.
        resumable_source_manager.save_state(PipedriveResumeConfig(next_url=next_url))
        url = next_url


def pipedrive_source(
    company_domain: str,
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[PipedriveResumeConfig],
) -> SourceResponse:
    config = PIPEDRIVE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            company_domain=company_domain,
            api_token=api_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
