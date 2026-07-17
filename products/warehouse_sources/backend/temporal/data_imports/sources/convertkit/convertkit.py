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
from products.warehouse_sources.backend.temporal.data_imports.sources.convertkit.settings import (
    CONVERTKIT_ENDPOINTS,
    ConvertKitEndpointConfig,
)

# Kit (formerly ConvertKit) v4 API. v3 (api.convertkit.com) is deprecated.
CONVERTKIT_BASE_URL = "https://api.kit.com"
PAGE_SIZE = 1000  # v4 max per_page
REQUEST_TIMEOUT = 60


class ConvertKitRetryableError(Exception):
    pass


@dataclasses.dataclass
class ConvertKitResumeConfig:
    after: Optional[str]


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "X-Kit-Api-Key": api_key,
        "Accept": "application/json",
    }


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as ISO 8601 with a Z suffix.

    Kit's *_after / *_before filters accept full ISO 8601 timestamps (the docs example
    is ``2023-01-17T11:43:55Z``) even though they describe the format as ``yyyy-mm-dd``.
    """
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def build_initial_params(
    config: ConvertKitEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build the query params for the first page request (excluding the pagination cursor)."""
    params: dict[str, Any] = {"per_page": PAGE_SIZE}
    params.update(config.extra_params)

    if (
        config.supports_incremental
        and should_use_incremental_field
        and incremental_field
        and db_incremental_field_last_value is not None
    ):
        filter_param = config.incremental_param_map.get(incremental_field)
        if filter_param:
            params[filter_param] = _format_incremental_value(db_incremental_field_last_value)

    return params


def validate_credentials(api_key: str, endpoint: str | None = None) -> tuple[bool, str | None]:
    """Probe the API with the given key. Returns (is_valid, error_message).

    A 403 at source-create time (``endpoint is None``) is treated as valid — the key
    works but may lack scope for a specific endpoint, which the user can grant later.
    """
    if endpoint and endpoint not in CONVERTKIT_ENDPOINTS:
        return False, f"Unknown Kit endpoint: {endpoint}"
    config = CONVERTKIT_ENDPOINTS[endpoint] if endpoint else CONVERTKIT_ENDPOINTS["subscribers"]
    url = f"{CONVERTKIT_BASE_URL}{config.path}?{urlencode({'per_page': 1})}"
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            url, headers=_get_headers(api_key), timeout=REQUEST_TIMEOUT
        )
    except Exception:
        return False, "Could not reach the Kit API. Please try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 403 and endpoint is None:
        return True, None
    if response.status_code in (401, 403):
        return False, "Invalid or insufficiently scoped Kit API key"
    return False, f"Kit API returned status {response.status_code}"


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ConvertKitResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = CONVERTKIT_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    base_params = build_initial_params(
        config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
    )

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume_config.after if resume_config else None
    if cursor:
        logger.debug(f"ConvertKit: resuming {endpoint} from cursor: {cursor}")

    # One tracked session for the whole sync — keeps urllib3's TLS connection warm across pages.
    session = make_tracked_session(redact_values=(api_key,))

    @retry(
        retry=retry_if_exception_type((ConvertKitRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_page(page_cursor: str | None) -> dict[str, Any]:
        params = dict(base_params)
        if page_cursor:
            params["after"] = page_cursor
        url = f"{CONVERTKIT_BASE_URL}{config.path}?{urlencode(params)}"

        response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

        if response.status_code == 429 or response.status_code >= 500:
            raise ConvertKitRetryableError(
                f"ConvertKit API error (retryable): status={response.status_code}, endpoint={endpoint}"
            )
        if not response.ok:
            logger.error(f"ConvertKit API error: status={response.status_code}, body={response.text}")
            response.raise_for_status()

        return response.json()

    while True:
        data = fetch_page(cursor)

        items = data.get(config.data_key, [])
        if items:
            yield items

        pagination = data.get("pagination", {})
        if not pagination.get("has_next_page"):
            break

        next_cursor = pagination.get("end_cursor")
        if not next_cursor:
            break

        cursor = next_cursor
        # Save AFTER yielding the page so a crash re-fetches from here (merge dedupes on primary key).
        resumable_source_manager.save_state(ConvertKitResumeConfig(after=cursor))


def convertkit_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ConvertKitResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = CONVERTKIT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            incremental_field=incremental_field,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # The API does not guarantee ascending order; the merge cursor still advances to the
        # max incremental value across all pages, which we read in full each sync.
        sort_mode="asc",
    )
