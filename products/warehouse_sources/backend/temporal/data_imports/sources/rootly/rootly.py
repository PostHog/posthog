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
from products.warehouse_sources.backend.temporal.data_imports.sources.rootly.settings import (
    ROOTLY_ENDPOINTS,
    RootlyEndpointConfig,
)

ROOTLY_BASE_URL = "https://api.rootly.com/v1"
# Rootly is a JSON:API service and expects/returns the JSON:API media type.
ROOTLY_JSON_API_MEDIA_TYPE = "application/vnd.api+json"
REQUEST_TIMEOUT_SECONDS = 60


class RootlyRetryableError(Exception):
    pass


@dataclasses.dataclass
class RootlyResumeConfig:
    # Full next-page URL from the JSON:API `links.next` field. It already carries the page,
    # sort, and filter params, so following it preserves the incremental window on every page.
    next_url: str | None = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": ROOTLY_JSON_API_MEDIA_TYPE,
    }


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    """Build a URL. Rootly is Rails/JSON:API and parses percent-encoded bracket params
    (`filter[updated_at][gt]`, `page[size]`) correctly, so standard urlencode is safe."""
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor value as an ISO 8601 UTC timestamp for Rootly's date filters."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future datetime/date cursor at now. A future-dated record could push the cursor
    past now; asking for records newer than now is a no-op, so clamping keeps the filter sane."""
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _build_initial_params(
    config: RootlyEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: str | None,
) -> dict[str, Any]:
    """Build query params for the first request to a Rootly collection endpoint."""
    params: dict[str, Any] = {"page[size]": config.page_size}

    if config.supports_incremental and should_use_incremental_field:
        # Cursor on the user's chosen field; fall back to the endpoint's first advertised field.
        field_name = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)
        if field_name:
            # Sort ascending on the same field we filter on so rows arrive in watermark order and
            # the pipeline can checkpoint safely (matches SourceResponse.sort_mode="asc").
            params["sort"] = field_name
            if db_incremental_field_last_value:
                value = _clamp_future_value_to_now(db_incremental_field_last_value)
                params[f"filter[{field_name}][gt]"] = _format_incremental_value(value)

    return params


def _flatten_item(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a JSON:API resource object's `attributes` into the root and keep `id`/`type`."""
    flattened = {k: v for k, v in item.items() if k != "attributes"}
    attributes = item.get("attributes")
    if isinstance(attributes, dict):
        flattened.update(attributes)
    return flattened


@retry(
    retry=retry_if_exception_type((RootlyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, page_url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict:
    response = session.get(page_url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    # 429 (rate limited — Rootly's default is 3000 req/min) and 5xx are transient; retry them.
    if response.status_code == 429 or response.status_code >= 500:
        raise RootlyRetryableError(f"Rootly API error (retryable): status={response.status_code}, url={page_url}")

    if not response.ok:
        logger.error(f"Rootly API error: status={response.status_code}, body={response.text}, url={page_url}")
        response.raise_for_status()

    return response.json()


def probe_credentials(api_key: str, endpoint: str | None = None) -> int | None:
    """Cheap probe of a Rootly collection. Returns the HTTP status code, or None on a connection
    failure. Probes the given endpoint's path when set, else a generic, cheap collection."""
    config = ROOTLY_ENDPOINTS.get(endpoint) if endpoint else None
    path = config.path if config else "/users"
    url = _build_url(f"{ROOTLY_BASE_URL}{path}", {"page[size]": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
    except Exception:
        return None
    return response.status_code


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RootlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[Any]:
    config = ROOTLY_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across pages so urllib3 keeps the connection alive.
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url = resume.next_url
        logger.debug(f"Rootly: resuming {endpoint} from URL: {url}")
    else:
        params = _build_initial_params(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )
        url = _build_url(f"{ROOTLY_BASE_URL}{config.path}", params)

    while True:
        data = _fetch_page(session, url, headers, logger)

        items = data.get("data", [])
        next_url = data.get("links", {}).get("next")

        if items:
            # Yield one page at a time as a list[dict]; the pipeline buffers and batches for us.
            yield [_flatten_item(item) for item in items]

        if not next_url:
            break

        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key. Advance the URL before the next fetch to avoid re-looping it.
        resumable_source_manager.save_state(RootlyResumeConfig(next_url=next_url))
        url = next_url


def rootly_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RootlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = ROOTLY_ENDPOINTS[endpoint]

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
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
