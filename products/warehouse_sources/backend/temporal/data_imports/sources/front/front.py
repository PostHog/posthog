import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import RetryCallState, retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.front.settings import (
    FRONT_ENDPOINTS,
    FrontEndpointConfig,
)

FRONT_BASE_URL = "https://api2.frontapp.com"
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 6
MAX_RETRY_WAIT_SECONDS = 60


class FrontRetryableError(Exception):
    """Raised for retryable Front responses (429 rate limiting, 5xx)."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


@dataclasses.dataclass
class FrontResumeConfig:
    next_url: str


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _to_unix_seconds(value: Any) -> Any:
    """Coerce an incremental cursor value into Unix epoch seconds for Front's q[after] filter.

    Front stores timestamps as Unix epoch seconds; the warehouse may hand the value back as a
    datetime/date or as the raw numeric column, so normalize both into something urlencode can
    serialize as a number.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.timestamp()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp()
    return value


def _resolve_after_value(
    config: FrontEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Any:
    if not should_use_incremental_field:
        return None
    if db_incremental_field_last_value is not None:
        return _to_unix_seconds(db_incremental_field_last_value)
    if config.default_lookback_days is not None:
        return (datetime.now(UTC) - timedelta(days=config.default_lookback_days)).timestamp()
    return None


def _build_initial_params(
    config: FrontEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {}

    if config.limit is not None:
        params["limit"] = config.limit
    if config.sort_by is not None:
        params["sort_by"] = config.sort_by
    if config.sort_order is not None:
        params["sort_order"] = config.sort_order

    if config.supports_incremental and config.incremental_query_property:
        after_value = _resolve_after_value(config, should_use_incremental_field, db_incremental_field_last_value)
        if after_value is not None:
            params[f"q[{config.incremental_query_property}]"] = after_value

    return params


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _parse_retry_after(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor Front's retry-after header on 429 when present; fall back to exponential backoff."""
    exc = retry_state.outcome.exception() if retry_state.outcome else None
    if isinstance(exc, FrontRetryableError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_WAIT_SECONDS)
    return wait_exponential_jitter(initial=1, max=30)(retry_state)


def validate_credentials(api_token: str, path: str, require_scope: bool) -> tuple[bool, str | None]:
    """Probe a Front endpoint with the token.

    401 always fails (bad token). 403 means the token is valid but lacks scope for that endpoint:
    we accept it at source-create (``require_scope=False``) and only reject it when validating a
    specific schema (``require_scope=True``).
    """
    try:
        response = make_tracked_session().get(f"{FRONT_BASE_URL}{path}", headers=_get_headers(api_token), timeout=10)
    except Exception as e:
        return False, f"Could not connect to Front: {e}"

    if response.status_code == 401:
        return False, "Invalid Front API token. Please reconnect with a valid token."
    if response.status_code == 403 and require_scope:
        return False, "Your Front API token does not have permission to access this resource."
    return True, None


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FrontResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = FRONT_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)

    params = _build_initial_params(config, should_use_incremental_field, db_incremental_field_last_value)

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None:
        url: str | None = resume_config.next_url
        logger.debug(f"Front: resuming {endpoint} from URL: {url}")
    else:
        url = _build_url(f"{FRONT_BASE_URL}{config.path}", params)

    @retry(
        retry=retry_if_exception_type((FrontRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=_retry_wait,
        reraise=True,
    )
    def fetch_page(page_url: str) -> dict[str, Any]:
        response = make_tracked_session().get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429:
            raise FrontRetryableError(
                f"Front rate limited: url={page_url}",
                retry_after=_parse_retry_after(response.headers.get("retry-after")),
            )
        if response.status_code >= 500:
            raise FrontRetryableError(f"Front server error: status={response.status_code}, url={page_url}")
        if not response.ok:
            logger.error(f"Front API error: status={response.status_code}, body={response.text}, url={page_url}")
            response.raise_for_status()

        return response.json()

    while url:
        data = fetch_page(url)

        results = data.get("_results") or []
        # Never infer the end from an empty/short page — deleted resources can shrink a page
        # while more pages remain. Only `_pagination.next == null` terminates the cursor.
        next_url = (data.get("_pagination") or {}).get("next")

        if results:
            yield results

        if not next_url:
            break

        # Save state after yielding the page so a crash re-yields the last page (merge dedupes on
        # primary key) rather than skipping it.
        resumable_source_manager.save_state(FrontResumeConfig(next_url=next_url))
        url = next_url


def front_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FrontResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FRONT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_token=api_token,
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
        partition_format=config.partition_format if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
    )
