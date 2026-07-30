import re
import base64
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.xmatters.settings import (
    XMATTERS_ENDPOINTS,
    XmattersEndpointConfig,
)

# xMatters is per-instance: every account lives at a customer-specific subdomain.
BASE_URL_TEMPLATE = "https://{subdomain}.xmatters.com/api/xm/1"

# A single DNS label: letters, digits, and internal hyphens only. Anything else (slashes, dots,
# `@`, etc.) could redirect worker requests to an attacker-controlled host (SSRF).
SUBDOMAIN_REGEX = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")

# xMatters caps `limit` at 1000; using the max reduces round-trips.
PAGE_SIZE = 1000

# Retry/throttle settings kept near the top for easy tuning.
RETRY_ATTEMPTS = 5
REQUEST_TIMEOUT_SECONDS = 60


class XmattersRetryableError(Exception):
    pass


@dataclasses.dataclass
class XmattersResumeConfig:
    offset: int


def is_valid_subdomain(subdomain: str) -> bool:
    return bool(SUBDOMAIN_REGEX.match(subdomain))


def _base_url(subdomain: str) -> str:
    if not is_valid_subdomain(subdomain):
        raise ValueError("xMatters subdomain is invalid")
    return BASE_URL_TEMPLATE.format(subdomain=subdomain)


def _format_incremental_value(value: Any) -> str:
    """Format an incremental field value as an ISO 8601 UTC string for xMatters' `from` filter."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return utc_value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _get_headers(username: str, password: str) -> dict[str, str]:
    # HTTP Basic works for both a service account (username/password) and an xMatters REST API
    # key (key as username, secret as password).
    basic_token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return {
        "Authorization": f"Basic {basic_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _build_params(
    config: XmattersEndpointConfig,
    offset: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": PAGE_SIZE, "offset": offset}

    if config.supports_from:
        # START_TIME is the event's initiation (created) time, which is exactly what `from`
        # filters on — sorting ascending on it means new events append to the end and never
        # shift pages we've already read. Sent on every sync so full refreshes paginate over a
        # stable ordering too.
        params["sortBy"] = "START_TIME"
        params["sortOrder"] = "ASCENDING"
        if should_use_incremental_field and db_incremental_field_last_value:
            params["from"] = _format_incremental_value(db_incremental_field_last_value)

    return params


def validate_credentials(
    subdomain: str, username: str, password: str, endpoint: Optional[str] = None
) -> tuple[bool, int, str | None]:
    """Probe xMatters with a cheap single-row request.

    Returns ``(ok, status_code, error_message)``. ``status_code`` is 0 on transport failure.
    The caller decides how to treat 403 (valid credentials, missing permission for the probed
    endpoint).
    """
    config = XMATTERS_ENDPOINTS.get(endpoint) if endpoint else None
    path = config.path if config else "/people"
    url = f"{_base_url(subdomain)}{path}?{urlencode({'limit': 1})}"

    try:
        response = make_tracked_session().get(url, headers=_get_headers(username, password), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)

    if response.status_code == 200:
        return True, 200, None
    if response.status_code == 401:
        return False, 401, "Invalid xMatters credentials"
    if response.status_code == 403:
        return False, 403, "Your xMatters account does not have access to this resource"

    try:
        message = response.json().get("message", response.text)
    except Exception:
        message = response.text
    return False, response.status_code, message


def get_rows(
    subdomain: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[XmattersResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = XMATTERS_ENDPOINTS[endpoint]
    headers = _get_headers(username, password)
    base_url = _base_url(subdomain)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume_config.offset if resume_config is not None else 0
    if resume_config is not None:
        logger.debug(f"xMatters: resuming {endpoint} from offset {offset}")

    @retry(
        retry=retry_if_exception_type((XmattersRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_offset: int) -> dict:
        params = _build_params(config, page_offset, should_use_incremental_field, db_incremental_field_last_value)
        url = f"{base_url}{config.path}?{urlencode(params)}"
        response = make_tracked_session().get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise XmattersRetryableError(f"xMatters API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"xMatters API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(offset)

        items = data.get("data", [])
        if not items:
            break

        yield items

        # xMatters signals more pages via a `links.next` URL. Fall back to the page-fill
        # heuristic if the field is absent.
        has_next = bool(data.get("links", {}).get("next")) or len(items) >= PAGE_SIZE
        if not has_next:
            break

        offset += PAGE_SIZE

        # Save AFTER yielding so a crash re-fetches the last page; merge dedupes on primary key.
        resumable_source_manager.save_state(XmattersResumeConfig(offset=offset))


def xmatters_source(
    subdomain: str,
    username: str,
    password: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[XmattersResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = XMATTERS_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            subdomain=subdomain,
            username=username,
            password=password,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        # We request START_TIME ascending where a sort is available, and full-refresh endpoints
        # replace wholesale, so ascending is correct everywhere.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
