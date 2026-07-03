import dataclasses
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.fulcrum.settings import (
    FULCRUM_ENDPOINTS,
    FulcrumEndpointConfig,
)

FULCRUM_BASE_URL = "https://api.fulcrumapp.com/api/v2"


class FulcrumRetryableError(Exception):
    pass


@dataclasses.dataclass
class FulcrumResumeConfig:
    # Next page number to fetch. Page-number pagination is deterministic and the incremental
    # `updated_since` filter is fixed for the job, so the page number alone is enough to resume.
    page: int


def _get_headers(api_token: str) -> dict[str, str]:
    return {
        "X-ApiToken": api_token,
        "Accept": "application/json",
    }


def _to_epoch_seconds(value: Any) -> Optional[int]:
    """Fulcrum's `updated_since` filter wants the cutoff as integer seconds since epoch."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return int(value.timestamp())
    if isinstance(value, date):
        return int(datetime(value.year, value.month, value.day).timestamp())
    if isinstance(value, (int, float)):
        return int(value)
    try:
        # ISO 8601 string fallback (e.g. a serialized watermark).
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


def _build_params(
    config: FulcrumEndpointConfig,
    page: int,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> dict[str, Any]:
    params: dict[str, Any] = {"page": page, "per_page": config.page_size}

    if config.supports_incremental and should_use_incremental_field:
        since = _to_epoch_seconds(db_incremental_field_last_value)
        if since is not None:
            # Server-side filter on updated_at. Records default to updated_at ascending order,
            # which matches SourceResponse.sort_mode="asc" so the watermark advances correctly.
            params["updated_since"] = since

    return params


def _build_url(config: FulcrumEndpointConfig, params: dict[str, Any]) -> str:
    return f"{FULCRUM_BASE_URL}{config.path}?{urlencode(params)}"


def validate_credentials(api_token: str) -> bool:
    # A cheap, always-available probe: list a single form. 200 means the token is genuine.
    url = _build_url(FULCRUM_ENDPOINTS["forms"], {"page": 1, "per_page": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_token), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            FulcrumRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict[str, Any]:
    response = session.get(url, headers=headers, timeout=60)

    # 429 (Fulcrum enforces an hourly request cap) and transient 5xx are retryable.
    if response.status_code == 429 or response.status_code >= 500:
        raise FulcrumRetryableError(f"Fulcrum API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Fulcrum API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _has_more_pages(data: dict[str, Any], items: list[Any], current_page: int, per_page: int) -> bool:
    """Fulcrum returns current_page/total_pages at the response root; fall back to a short-page
    heuristic if either is missing so we never loop forever or stop early."""
    total_pages = data.get("total_pages")
    if isinstance(total_pages, int):
        page = data.get("current_page")
        page = page if isinstance(page, int) else current_page
        return page < total_pages
    return len(items) >= per_page


def get_rows(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FulcrumResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = FULCRUM_ENDPOINTS[endpoint]
    headers = _get_headers(api_token)
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None else 1

    while True:
        params = _build_params(config, page, should_use_incremental_field, db_incremental_field_last_value)
        url = _build_url(config, params)
        data = _fetch_page(session, url, headers, logger)

        items = data.get(config.data_key) or []
        if not items:
            break

        yield items

        if not _has_more_pages(data, items, page, config.page_size):
            break

        page += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it — merge
        # dedupes on the primary key.
        resumable_source_manager.save_state(FulcrumResumeConfig(page=page))


def fulcrum_source(
    api_token: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[FulcrumResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = FULCRUM_ENDPOINTS[endpoint]

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
        # Records list defaults to updated_at ascending; full-refresh endpoints don't checkpoint a
        # watermark, so ascending is a safe default for them too.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
