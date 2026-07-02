import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

import orjson
import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.settings import (
    HUBPLANNER_ENDPOINTS,
    HubPlannerEndpointConfig,
)

HUBPLANNER_BASE_URL = "https://api.hubplanner.com/v1"

# Hub Planner caps `limit` at 1000; a limit of 0 or >1000 returns a 400. Bookings and time
# entries default to 20 rows/page, so we always request the max to minimise round-trips.
PAGE_SIZE = 1000


class HubPlannerRetryableError(Exception):
    pass


@dataclasses.dataclass
class HubPlannerResumeConfig:
    # Next 0-indexed page to fetch. Pagination is page-number based, so the page index is the
    # only cursor we need to persist to resume mid-endpoint after a heartbeat timeout.
    page: int = 0


def _format_value(value: Any) -> str:
    """Format an incremental cursor value as an ISO-8601 string Hub Planner accepts.

    The API's `updatedDate` search filter compares against ISO timestamps (e.g.
    `2018-09-04T08:15:11.487Z`), so datetimes are emitted in UTC with a `Z` suffix.
    """
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _get_headers(api_key: str) -> dict[str, str]:
    # Despite Hub Planner's docs calling this an "OAuth 2.0 Bearer Token", the API key is placed
    # raw in the Authorization header with no `Bearer ` prefix (verified against the live API).
    return {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def validate_credentials(api_key: str) -> bool:
    # One cheap probe: list a single project. A valid key returns 200; an invalid or
    # insufficiently-permissioned key returns 403 (Hub Planner keys are account-wide, not
    # per-resource scoped, so a reachable /project confirms the whole token).
    url = _build_url(f"{HUBPLANNER_BASE_URL}/project", {"page": 0, "limit": 1})
    try:
        response = make_tracked_session().get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


@retry(
    retry=retry_if_exception_type(
        (
            HubPlannerRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(5),
    # Hub Planner returns 429 with a Retry-After header on burst (50 req / 5s) or daily
    # (6000/day) limits; exponential jitter keeps us comfortably under both without parsing it.
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch_page(
    session: requests.Session,
    method: str,
    url: str,
    headers: dict[str, str],
    body: Optional[dict[str, Any]],
    logger: FilteringBoundLogger,
) -> list[dict[str, Any]]:
    data = orjson.dumps(body) if body is not None else None
    response = session.request(method, url, headers=headers, data=data, timeout=60)

    if response.status_code == 429 or response.status_code >= 500:
        raise HubPlannerRetryableError(f"Hub Planner API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # Never log the response body: Hub Planner echoes the supplied API key back in auth-error
        # bodies, so logging it would leak the credential.
        logger.error(f"Hub Planner API error: status={response.status_code}, url={url}")
        response.raise_for_status()

    payload = response.json()
    # Every list/search endpoint returns a bare JSON array; guard against an unexpected object.
    if not isinstance(payload, list):
        logger.warning(f"Hub Planner: expected a list response, got {type(payload).__name__} from url={url}")
        return []
    return payload


def _build_request_plan(
    config: HubPlannerEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> tuple[str, str, Optional[dict[str, Any]], Optional[str]]:
    """Resolve (http_method, path, body, sort_field) for an endpoint's list request.

    Incremental endpoints (and search-only endpoints like milestones) POST to `<path>/search`;
    everything else GETs `<path>`.
    """
    incremental_active = bool(config.incremental_search_field and should_use_incremental_field)

    if config.list_via_search or incremental_active:
        body: dict[str, Any] = {}
        sort_field: Optional[str] = None
        if incremental_active:
            field_name = config.incremental_search_field
            # Sort ascending on the cursor field so rows arrive oldest-first and the pipeline's
            # incremental watermark advances safely (matches SourceResponse.sort_mode="asc").
            sort_field = field_name
            if db_incremental_field_last_value is not None:
                body = {field_name: {"$gte": _format_value(db_incremental_field_last_value)}}
        return "POST", f"{config.path}/search", body, sort_field

    # Full-refresh GET. We deliberately don't pass a `sort` here: the API rejects an unsupported
    # sort field with a 400 that would fail the whole sync, and not every endpoint's sortable
    # fields are verifiable up front. A full refresh replaces the table each run, so the worst case
    # of unsorted paging (a row shifting across a page boundary mid-sync) self-heals next sync.
    return "GET", config.path, None, None


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HubPlannerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    incremental_field: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    config = HUBPLANNER_ENDPOINTS[endpoint]
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = make_tracked_session()

    method, path, body, sort_field = _build_request_plan(
        config, should_use_incremental_field, db_incremental_field_last_value
    )

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume else 0

    while True:
        params: dict[str, Any] = {"page": page, "limit": PAGE_SIZE}
        if sort_field:
            params["sort"] = sort_field
        url = _build_url(f"{HUBPLANNER_BASE_URL}{path}", params)

        items = _fetch_page(session, method, url, headers, body, logger)

        if items:
            yield items

        # A short page (fewer rows than requested) is the last page — the API has no next-page
        # token, so we page until the server returns less than the limit.
        if len(items) < PAGE_SIZE:
            break

        page += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it; the
        # delta merge dedupes the re-pulled rows on the primary key.
        resumable_source_manager.save_state(HubPlannerResumeConfig(page=page))


def hubplanner_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HubPlannerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    config = HUBPLANNER_ENDPOINTS[endpoint]

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
        sort_mode="asc",
    )
