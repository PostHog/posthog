import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.lob.settings import (
    LOB_ENDPOINTS,
    LobEndpointConfig,
)

LOB_BASE_URL = "https://api.lob.com/v1"

# Lob's published rate limit is 150 requests / 5s per endpoint; with a single worker per sync we
# never approach it, but transient 429/5xx still warrant a bounded retry.
PAGE_SIZE = 100  # Lob's documented maximum `limit`.
REQUEST_TIMEOUT_SECONDS = 60


class LobRetryableError(Exception):
    pass


@dataclasses.dataclass
class LobResumeConfig:
    # The fully-formed `next_url` returned by Lob (already carries `limit` and the `after` cursor).
    # None means "start from the first page".
    next_url: str | None = None


def _format_date_filter_value(value: Any) -> str:
    """Format an incremental cursor value for Lob's `date_created[gt]` filter (ISO-8601)."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _parse_date_created(value: Any) -> datetime | None:
    """Parse a Lob `date_created` string (e.g. `2019-08-08T17:09:14.514Z`) into an aware datetime."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _coerce_watermark(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    return None


def _build_query_string(params: dict[str, str]) -> str:
    """Build a query string with literal brackets.

    Lob filter/sort params use deepObject bracket notation (`date_created[gt]=...`,
    `sort_by[date_created]=asc`). All keys/values here are internally constructed and ASCII-safe
    (ISO datetimes only use `:` and `.`, both legal in a query component), so we emit them verbatim
    to match Lob's documented format rather than percent-encoding the brackets.
    """
    return "&".join(f"{key}={value}" for key, value in params.items())


def _build_initial_url(
    config: LobEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> str:
    params: dict[str, str] = {"limit": str(PAGE_SIZE)}

    if config.supports_incremental:
        # Force ascending order so the cursor only ever moves forward to newer rows. Combined with the
        # `date_created[gt]` floor below, every page stays above the watermark and pagination ends when
        # Lob runs out of newer rows (empty `next_url`).
        params["sort_by[date_created]"] = "asc"

        if should_use_incremental_field and db_incremental_field_last_value:
            params["date_created[gt]"] = _format_date_filter_value(db_incremental_field_last_value)

    return f"{LOB_BASE_URL}{config.path}?{_build_query_string(params)}"


def _get_headers() -> dict[str, str]:
    return {"Accept": "application/json"}


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe a cheap list endpoint. Returns (is_valid, status_code)."""
    url = f"{LOB_BASE_URL}/addresses?limit=1"
    try:
        response = make_tracked_session().get(
            url, auth=(api_key, ""), headers=_get_headers(), timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code


@retry(
    retry=retry_if_exception_type((LobRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, api_key: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict:
    response = session.get(url, auth=(api_key, ""), headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise LobRetryableError(f"Lob API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Lob API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LobResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = LOB_ENDPOINTS[endpoint]
    headers = _get_headers()
    # One session reused across every page so urllib3 keeps the connection alive between requests.
    session = make_tracked_session()

    watermark = (
        _coerce_watermark(db_incremental_field_last_value)
        if config.supports_incremental and should_use_incremental_field
        else None
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.next_url:
        url: str | None = resume.next_url
        logger.debug(f"Lob: resuming from URL: {url}")
    else:
        url = _build_initial_url(config, should_use_incremental_field, db_incremental_field_last_value)

    while url:
        data = _fetch_page(session, url, api_key, headers, logger)

        items = data.get("data", [])
        if not items:
            break

        yield items

        next_url = data.get("next_url") or None

        # Defence-in-depth for incremental endpoints: Lob's `next_url` carries only `limit` + `after`,
        # so if the server were to stop honouring the ascending sort on later pages, the cursor could
        # walk backwards. Stop once an entire page predates the watermark — in the normal ascending
        # path every row is newer than the watermark, so this never triggers.
        if next_url and watermark is not None:
            page_max = max(
                (dt for item in items if (dt := _parse_date_created(item.get("date_created")))),
                default=None,
            )
            if page_max is not None and page_max <= watermark:
                logger.debug("Lob: stopping pagination, page predates incremental watermark")
                break

        if not next_url:
            break

        # Save state AFTER yielding so a crash re-yields the last page (merge dedupes on the primary
        # key) rather than skipping it. Advance before the next fetch to avoid re-fetching this page.
        resumable_source_manager.save_state(LobResumeConfig(next_url=next_url))
        url = next_url


def lob_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[LobResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = LOB_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        # Incremental endpoints force `sort_by[date_created]=asc`; full-refresh endpoints have no
        # sort param and return Lob's default newest-first (descending) order.
        sort_mode="asc" if endpoint_config.supports_incremental else "desc",
    )
