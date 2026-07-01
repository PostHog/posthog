import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlsplit

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter
from urllib3.util.retry import Retry

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.capsule_crm.settings import (
    CAPSULE_CRM_ENDPOINTS,
    CapsuleCRMEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

CAPSULE_CRM_BASE_URL = "https://api.capsulecrm.com/api/v2"
CAPSULE_CRM_HOST = "api.capsulecrm.com"
CAPSULE_CRM_PATH_PREFIX = "/api/v2/"

# Capsule caps perPage at 100; always request the max to minimize round-trips.
PAGE_SIZE = 100

REQUEST_TIMEOUT_SECONDS = 60


class CapsuleCRMRetryableError(Exception):
    pass


class CapsuleCRMUntrustedURLError(Exception):
    """A pagination URL (resumed or upstream) pointed somewhere other than the Capsule CRM API."""


def _validate_pagination_url(url: str) -> str:
    """Pin every authenticated request to the Capsule CRM API origin.

    Both resumed `next_url` values (loaded from Redis) and upstream `Link` header URLs are followed
    verbatim with the customer's bearer token. Validating the scheme, host, and `/api/v2/` path prefix
    keeps a poisoned resume state or a hostile upstream response from retargeting the request at another
    host and leaking the token (SSRF). Returns the URL unchanged when it is trusted.
    """
    parts = urlsplit(url)
    is_trusted = (
        parts.scheme == "https" and parts.netloc == CAPSULE_CRM_HOST and parts.path.startswith(CAPSULE_CRM_PATH_PREFIX)
    )
    if not is_trusted:
        raise CapsuleCRMUntrustedURLError(f"Refusing to follow pagination URL outside {CAPSULE_CRM_BASE_URL}/")
    return url


@dataclasses.dataclass
class CapsuleCRMResumeConfig:
    # Absolute URL of the next page (from the RFC 5988 Link header). Capsule echoes the original
    # query params — perPage, embed and `since` — into this URL, so resuming from it preserves the
    # incremental window without recomputing it. None means "start from the first page".
    next_url: str | None = None


def _get_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _format_since_value(value: Any) -> str:
    """Format a cursor value as the ISO 8601 `Z`-suffixed UTC string Capsule's `since` expects."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now.

    If bad source data pushes the `updatedAt` cursor past now, every later sync would ask Capsule
    for changes since a future date and get nothing back, wedging the table until real data catches
    up. Asking for changes newer than now is a no-op anyway, so clamping lets the sync self-heal.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_initial_url(
    config: CapsuleCRMEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    params: dict[str, Any] = {"perPage": PAGE_SIZE}
    if config.embed:
        params["embed"] = config.embed

    if config.supports_since and should_use_incremental_field and db_incremental_field_last_value is not None:
        params["since"] = _format_since_value(_clamp_future_value_to_now(db_incremental_field_last_value))

    return f"{CAPSULE_CRM_BASE_URL}{config.path}?{urlencode(params)}"


@retry(
    retry=retry_if_exception_type((CapsuleCRMRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> tuple[dict, str | None]:
    """Fetch one page, returning the parsed body and the next-page URL from the Link header.

    Capsule signals pagination via the RFC 5988 `Link` header (rel="next"), not the body, so the
    caller follows the returned URL rather than building its own.
    """
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise CapsuleCRMRetryableError(f"Capsule CRM API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Capsule CRM API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    next_url = response.links.get("next", {}).get("url")
    return response.json(), next_url


def get_rows(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CapsuleCRMResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict]]:
    config = CAPSULE_CRM_ENDPOINTS[endpoint]
    headers = _get_headers(access_token)
    # One session reused across every page so urllib3 keeps the connection alive. `redact_values`
    # masks the bearer token in logged URLs and captured request samples. `allow_redirects=False`
    # stops a redirect response from sending the bearer token to another host. `retry=Retry(total=0)`
    # disables the adapter's built-in retries — `_fetch_page` already retries 429/5xx via tenacity, so
    # the adapter default would stack a second retry layer.
    session = make_tracked_session(redact_values=(access_token,), allow_redirects=False, retry=Retry(total=0))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        # Resume state comes from Redis — validate before sending the token to it.
        url = _validate_pagination_url(resume.next_url)
        logger.debug(f"Capsule CRM: resuming from URL: {url}")
    else:
        url = _build_initial_url(config, should_use_incremental_field, db_incremental_field_last_value)

    while True:
        data, next_url = _fetch_page(session, url, headers, logger)
        items = data.get(config.data_key, [])
        if items:
            yield items

        if not next_url:
            break

        # The upstream-supplied next-page URL is followed verbatim with the bearer token — pin it to
        # the Capsule CRM API so a hostile response can't retarget the authenticated request.
        next_url = _validate_pagination_url(next_url)

        # Save AFTER yielding (and only when more pages remain) so a crash re-yields the last page
        # rather than skipping it — merge dedupes on the primary key.
        resumable_source_manager.save_state(CapsuleCRMResumeConfig(next_url=next_url))
        url = next_url


def validate_credentials(access_token: str) -> bool:
    """Probe a cheap, always-available endpoint to confirm the access token is genuine."""
    url = f"{CAPSULE_CRM_BASE_URL}/users?perPage=1"
    try:
        session = make_tracked_session(redact_values=(access_token,), allow_redirects=False, retry=Retry(total=0))
        response = session.get(url, headers=_get_headers(access_token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def capsule_crm_source(
    access_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CapsuleCRMResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CAPSULE_CRM_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_token=access_token,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # Capsule does not document an ordering guarantee for `since`, but the ResumableSource
        # next-URL state (not the watermark) drives mid-sync resume, so the dominant interruption
        # path is order-independent. `asc` matches the framework's default incremental checkpointing.
        sort_mode="asc",
    )
