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
from products.warehouse_sources.backend.temporal.data_imports.sources.retently.settings import (
    RETENTLY_ENDPOINTS,
    RetentlyEndpointConfig,
)

RETENTLY_BASE_URL = "https://app.retently.com/api/v2"
# Documented maximum page size; the largest page minimises round trips against the ~150 req/min
# rate limit.
PAGE_SIZE = 1000
FIRST_PAGE = 1
REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRIES = 5


class RetentlyRetryableError(Exception):
    pass


@dataclasses.dataclass
class RetentlyResumeConfig:
    # Next page to fetch (1-based). Pages are requested in ascending creation order, so rows
    # created mid-sync land on the trailing pages and already-fetched pages stay stable; a crashed
    # sync resumes from the page after the last one yielded and merge dedupes any overlap.
    page: int = FIRST_PAGE


def _get_headers(api_key: str) -> dict[str, str]:
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def _format_start_date(value: Any) -> str:
    """Format an incremental cursor value as the ISO-8601 `...Z` string Retently's `startDate` expects.

    The API also accepts UNIX timestamps, so non-datetime values pass through as strings.
    """
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _extract_items(body: Any, config: RetentlyEndpointConfig) -> list[dict[str, Any]]:
    """Locate the record array in a Retently response.

    The docs are inconsistent about envelope nesting (records under ``data.<key>`` for most
    endpoints, a bare list under ``data`` for /reports, a top-level array for campaigns/templates),
    so all documented shapes are handled.
    """
    if not isinstance(body, dict):
        raise RetentlyRetryableError(f"Retently returned an unexpected payload for {config.path}")

    data = body.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        items = data.get(config.data_key)
        if isinstance(items, list):
            return items

    top_level = body.get(config.data_key)
    if isinstance(top_level, list):
        return top_level

    if isinstance(data, dict):
        # Defensive fallback: a single list-valued entry in `data` is unambiguous even if the
        # documented key drifts.
        lists = [value for value in data.values() if isinstance(value, list)]
        if len(lists) == 1:
            return lists[0]

    raise RetentlyRetryableError(f"Retently returned an unexpected payload for {config.path}")


def _has_more(body: dict[str, Any], page: int, item_count: int) -> bool:
    # Prefer the `pages` metadata when the API returns it — the docs place it inside `data` on
    # some endpoints (feedback, companies, outbox) and at the top level on others (customers), so
    # both spots are checked. Fall back to "a short page ends the loop" when it's missing.
    data = body.get("data")
    for meta in (data if isinstance(data, dict) else {}, body):
        pages = meta.get("pages")
        if isinstance(pages, int):
            return page < pages
    return item_count >= PAGE_SIZE


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RetentlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> Iterator[list[dict[str, Any]]]:
    config = RETENTLY_ENDPOINTS[endpoint]
    # `redact_values` masks the API key (sent in the X-Api-Key header) from captured HTTP samples.
    session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))

    @retry(
        retry=retry_if_exception_type((RetentlyRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(params: dict[str, Any]) -> Any:
        response = session.get(
            f"{RETENTLY_BASE_URL}{config.path}",
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        # Retently rate-limits at ~150 req/min and returns 429 on exceed; 5xx are transient.
        if response.status_code == 429 or response.status_code >= 500:
            raise RetentlyRetryableError(
                f"Retently API error (retryable): status={response.status_code}, path={config.path}"
            )

        if not response.ok:
            logger.error(f"Retently API error: status={response.status_code}, body={response.text}, path={config.path}")
            response.raise_for_status()

        return response.json()

    base_params: dict[str, Any] = {}
    if config.paginated:
        base_params["limit"] = PAGE_SIZE
        if config.sort_param is not None:
            base_params["sort"] = config.sort_param
    if config.incremental_fields and should_use_incremental_field and db_incremental_field_last_value is not None:
        # `startDate` is inclusive of the boundary as far as the docs indicate; the watermark row
        # is re-fetched and merge dedupes it on the primary key.
        base_params["startDate"] = _format_start_date(db_incremental_field_last_value)

    if not config.paginated:
        body = fetch_page(base_params)
        items = _extract_items(body, config)
        if items:
            yield items
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else FIRST_PAGE
    if resume is not None:
        logger.debug(f"Retently: resuming {endpoint} from page {page}")

    while True:
        body = fetch_page({**base_params, "page": page})
        items = _extract_items(body, config)
        if items:
            yield items

        if not items or not _has_more(body, page, len(items)):
            break

        page += 1
        # Save AFTER yielding so a crash re-fetches from the next page (already-yielded pages are
        # persisted); merge dedupes any re-pulled rows on the primary key.
        resumable_source_manager.save_state(RetentlyResumeConfig(page=page))


def retently_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[RetentlyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = RETENTLY_ENDPOINTS[endpoint]
    supports_incremental = bool(config.incremental_fields)

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
        primary_keys=config.primary_keys,
        # The incremental endpoint requests ascending creation order via `sort=createdDate`, but we
        # could not verify against a live account that the param is honored, so "desc" keeps the
        # pipeline from checkpointing the watermark mid-sync — it's only persisted once a sync
        # completes successfully.
        sort_mode="desc" if supports_incremental else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def check_access(api_key: str) -> tuple[int, Optional[str]]:
    """Probe /ping to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    session = make_tracked_session(headers=_get_headers(api_key), redact_values=(api_key,))
    try:
        response = session.get(f"{RETENTLY_BASE_URL}/ping", timeout=15)
    except Exception as e:
        return 0, f"Could not connect to Retently: {e}"

    if response.status_code in (401, 403):
        return response.status_code, None

    if not response.ok:
        return response.status_code, f"Retently returned HTTP {response.status_code}"

    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Retently API key"
    return False, message or "Could not validate Retently API key"
