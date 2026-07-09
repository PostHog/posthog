import re
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.braze.settings import (
    BRAZE_ENDPOINTS,
    BrazeEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

# Shared so the source-layer 403 acceptance check can't drift from the message produced here.
BRAZE_FORBIDDEN_MSG = "Your Braze API key does not have permission for this endpoint"
HOST_NOT_ALLOWED_ERROR = "Braze REST endpoint URL is not allowed"


class BrazeRetryableError(Exception):
    pass


class BrazeHostNotAllowedError(Exception):
    pass


@dataclasses.dataclass
class BrazeResumeConfig:
    # Page index (page pagination) or row offset (offset pagination) of the
    # last-yielded page, so a resume re-fetches it and merge dedupes on primary key.
    cursor: int


def normalize_base_url(url: str) -> str:
    """Force https and strip any trailing slash so endpoint paths join cleanly.

    Forcing https prevents a downgrade to plaintext, matching the Okta/ServiceNow
    connectors that also take a user-supplied host.
    """
    url = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    return f"https://{url.rstrip('/')}"


def _host_from_url(base_url: str) -> str:
    return (urlparse(normalize_base_url(base_url)).hostname or "").lower()


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _format_modified_after(value: Any) -> str:
    """Format an incremental cursor value as an ISO-8601 string for Braze filters."""
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _build_params(config: BrazeEndpointConfig, cursor: int, modified_after: str | None) -> dict[str, Any]:
    params: dict[str, Any]
    if config.pagination == "page":
        params = {"page": cursor}
    else:
        params = {"limit": config.page_size, "offset": cursor}

    if modified_after and config.modified_after_param:
        params[config.modified_after_param] = modified_after

    return params


def _next_cursor(config: BrazeEndpointConfig, cursor: int) -> int:
    return cursor + 1 if config.pagination == "page" else cursor + config.page_size


def _normalize_items(config: BrazeEndpointConfig, items: list[Any]) -> list[dict[str, Any]]:
    if config.wrap_scalar_as:
        return [{config.wrap_scalar_as: item} for item in items]
    return [item for item in items if isinstance(item, dict)]


def validate_credentials(
    api_key: str, base_url: str, path: str = "/campaigns/list", team_id: int | None = None
) -> tuple[bool, str | None]:
    """Probe a Braze list endpoint to confirm the REST API key is valid.

    Braze keys are scoped per endpoint, so a 403 means the key is genuine but
    lacks the probed scope — the caller decides whether to accept that.
    """
    # The REST endpoint URL is fully customer-controlled, so block hosts that resolve to
    # private/internal addresses (SSRF). Only enforced on cloud — see _is_host_safe.
    if team_id is not None:
        host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
        if not host_ok:
            return False, host_err or HOST_NOT_ALLOWED_ERROR

    url = f"{normalize_base_url(base_url)}{path}?{urlencode({'page': 0})}"
    try:
        response = make_tracked_session(allow_redirects=False).get(url, headers=_get_headers(api_key), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Braze API key"
    if response.status_code == 403:
        return False, BRAZE_FORBIDDEN_MSG

    try:
        message = response.json().get("message", response.text)
    except Exception:
        message = response.text
    return False, message


def get_rows(
    api_key: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BrazeResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = BRAZE_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    root = normalize_base_url(base_url)

    # Re-check at run time (not just at source-create) in case the URL was edited or now
    # resolves to an internal address (SSRF / DNS rebinding). Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
    if not host_ok:
        raise BrazeHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)

    modified_after: str | None = None
    if config.modified_after_param and should_use_incremental_field and db_incremental_field_last_value:
        modified_after = _format_modified_after(db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume_config.cursor if resume_config is not None else 0
    if resume_config is not None:
        logger.debug(f"Braze: resuming {endpoint} from cursor={cursor}")

    @retry(
        retry=retry_if_exception_type((BrazeRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_cursor: int) -> dict[str, Any]:
        params = _build_params(config, page_cursor, modified_after)
        page_url = f"{root}{config.path}?{urlencode(params)}"
        response = make_tracked_session(allow_redirects=False).get(
            page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise BrazeRetryableError(f"Braze API error (retryable): status={response.status_code}, url={page_url}")

        if not response.ok:
            logger.error(f"Braze API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(cursor)

        raw_items = data.get(config.data_key, [])
        if not raw_items:
            break

        yield _normalize_items(config, raw_items)

        # Save the cursor of the page we just yielded (not the next one) so a
        # resume re-fetches it; merge semantics on the primary key dedupe.
        resumable_source_manager.save_state(BrazeResumeConfig(cursor=cursor))

        cursor = _next_cursor(config, cursor)


def braze_source(
    api_key: str,
    base_url: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[BrazeResumeConfig],
    team_id: int,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = BRAZE_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            base_url=base_url,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            team_id=team_id,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
