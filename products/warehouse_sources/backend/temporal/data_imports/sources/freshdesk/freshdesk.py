import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.freshdesk.settings import (
    FRESHDESK_ENDPOINTS,
    PER_PAGE,
    FreshdeskEndpointConfig,
)

REQUEST_TIMEOUT = 60
VALIDATE_TIMEOUT = 10
MAX_RETRIES = 5
MAX_RETRY_WAIT = 60.0

_EXPONENTIAL_WAIT = wait_exponential_jitter(initial=1, max=MAX_RETRY_WAIT)


class FreshdeskRetryableError(Exception):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header. Freshdesk sends an integer number of seconds."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a server-provided Retry-After (capped); otherwise fall back to exponential jitter."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, FreshdeskRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_WAIT)
    return _EXPONENTIAL_WAIT(retry_state)


@dataclasses.dataclass
class FreshdeskResumeConfig:
    next_url: str


def normalize_subdomain(domain: str) -> str:
    """Accept either a bare subdomain ("acme") or a full host ("acme.freshdesk.com")."""
    domain = domain.strip().removeprefix("https://").removeprefix("http://")
    domain = domain.split("/")[0]
    return domain.removesuffix(".freshdesk.com")


def _base_url(subdomain: str) -> str:
    return f"https://{normalize_subdomain(subdomain)}.freshdesk.com"


def _get_headers(api_key: str) -> dict[str, str]:
    # Freshdesk uses HTTP Basic auth with the API key as the username and any
    # non-empty string as the password.
    token = base64.b64encode(f"{api_key}:X".encode("ascii")).decode("ascii")
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def _format_updated_since(value: Any) -> str:
    """Format an incremental cursor value as the ISO 8601 UTC string Freshdesk expects."""
    if isinstance(value, datetime):
        utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def build_initial_url(
    subdomain: str,
    config: FreshdeskEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    params: dict[str, str] = {"per_page": str(PER_PAGE)}
    params.update(config.extra_params)

    if should_use_incremental_field and config.updated_since_param and db_incremental_field_last_value:
        params[config.updated_since_param] = _format_updated_since(db_incremental_field_last_value)

    return f"{_base_url(subdomain)}{config.path}?{urlencode(params)}"


def extract_items(data: Any, config: FreshdeskEndpointConfig) -> list[dict]:
    """Most Freshdesk list endpoints return a bare JSON array; a few wrap it in an object."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if config.data_key and isinstance(data.get(config.data_key), list):
            return data[config.data_key]
        # `results` is used by Freshdesk's search endpoints; defensive fallback.
        if isinstance(data.get("results"), list):
            return data["results"]
    return []


def get_rows(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FreshdeskResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict]]:
    config = FRESHDESK_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None:
        url: Optional[str] = resume.next_url
        logger.debug(f"Freshdesk: resuming from URL: {url}")
    else:
        url = build_initial_url(subdomain, config, should_use_incremental_field, db_incremental_field_last_value)

    @retry(
        retry=retry_if_exception_type((FreshdeskRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(page_url: str) -> tuple[Any, Optional[str]]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT)

        # Freshdesk throttles with 429 and a Retry-After header; honor it when present.
        if response.status_code == 429:
            raise FreshdeskRetryableError(
                f"Freshdesk API rate limited: url={page_url}",
                retry_after=_parse_retry_after(response.headers.get("Retry-After")),
            )

        # Transient upstream issues surface as 5xx.
        if response.status_code >= 500:
            raise FreshdeskRetryableError(
                f"Freshdesk API error (retryable): status={response.status_code}, url={page_url}"
            )

        if not response.ok:
            logger.error(f"Freshdesk API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        next_url = response.links.get("next", {}).get("url")
        return response.json(), next_url

    while url:
        data, next_url = fetch_page(url)

        items = extract_items(data, config)
        if items:
            yield items

        if not next_url:
            break

        # Save state AFTER yielding so a crash re-yields the last page (merge dedupes on
        # primary key) rather than skipping it.
        resumable_source_manager.save_state(FreshdeskResumeConfig(next_url=next_url))
        url = next_url


def freshdesk_source(
    api_key: str,
    subdomain: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FreshdeskResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FRESHDESK_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            subdomain=subdomain,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=["id"],
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(subdomain: str, api_key: str) -> Optional[int]:
    """Probe the Freshdesk API. Returns the HTTP status code, or ``None`` on a connection error."""
    url = f"{_base_url(subdomain)}/api/v2/tickets?per_page=1"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=VALIDATE_TIMEOUT)
    except Exception:
        return None

    return response.status_code
