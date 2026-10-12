import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.kong_konnect.settings import (
    CONTROL_PLANE_GROUP_CLUSTER_TYPE,
    CORE_ENTITY_PAGE_SIZE,
    DEFAULT_INITIAL_LOOKBACK_DAYS,
    KONG_KONNECT_ENDPOINTS,
    LIST_PAGE_SIZE,
    MAX_PAGE_SIZE,
    REGION_BASE_URLS,
    KongKonnectEndpointConfig,
)

REQUEST_TIMEOUT_SECONDS = 60


class KongKonnectRetryableError(Exception):
    pass


@dataclasses.dataclass
class KongKonnectResumeConfig:
    # Bounds of the absolute time window this run is paging through. Pinned in resume state so a resumed
    # attempt re-issues the identical window and its offset stays meaningful — recomputing `end` as
    # "now" on resume would shift the window and make the saved offset skip or duplicate rows.
    start: str | None = None
    end: str | None = None
    offset: int = 0


def _format_datetime(value: Any) -> str:
    """Format a datetime/date as a UTC ISO 8601 timestamp for Konnect's absolute time_range bounds."""
    if isinstance(value, datetime):
        dt = value.astimezone(UTC) if value.tzinfo is not None else value.replace(tzinfo=UTC)
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    else:
        # Already a string cursor — trust it as-is.
        return str(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp_future_value_to_now(value: Any) -> Any:
    """Cap a future incremental cursor at now.

    The watermark tracks the max `request_start` seen. A future-dated record would push the window
    start past now, producing an empty (or rejected) window on every later sync. Requesting rows newer
    than now is a no-op anyway, so clamping keeps the query valid and lets the sync self-heal.
    """
    now = datetime.now(UTC)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return now if aware > now else value
    if isinstance(value, date):
        return now.date() if value > now.date() else value
    return value


def _get_base_url(region: str, api_version: str = "v2") -> str:
    return f"{REGION_BASE_URLS.get(region, REGION_BASE_URLS['us'])}/{api_version}"


def _get_headers(api_token: str) -> dict[str, str]:
    # Personal Access Tokens and System Account tokens are both bearer tokens sent identically.
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _resolve_window(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    lookback_days: int,
) -> tuple[str, str]:
    """Compute the [start, end] absolute window for this run.

    Incremental runs start at the watermark; first sync / full refresh walks back `lookback_days`.
    `end` is pinned to now so pagination through the window is stable.
    """
    now = datetime.now(UTC)
    if should_use_incremental_field and db_incremental_field_last_value:
        start_value = _clamp_future_value_to_now(db_incremental_field_last_value)
        start = _format_datetime(start_value)
    else:
        start = _format_datetime(now - timedelta(days=lookback_days))
    return start, _format_datetime(now)


def _build_body(start: str, end: str, offset: int, size: int) -> dict[str, Any]:
    return {
        "filters": [],
        "time_range": {
            "type": "absolute",
            "start": start,
            "end": end,
            "tz": "Etc/UTC",
        },
        # Ascending by time so SourceResponse.sort_mode="asc" lets the pipeline advance the watermark
        # after each batch and resume mid-sync safely.
        "order": "ascending",
        "size": size,
        "offset": offset,
    }


@retry(
    retry=retry_if_exception_type(
        (
            KongKonnectRetryableError,
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
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    logger: FilteringBoundLogger,
) -> dict:
    response = session.post(url, headers=headers, json=body, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise KongKonnectRetryableError(f"Kong Konnect API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Kong Konnect API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _get_json(
    session: requests.Session,
    url: str,
    params: dict[str, Any],
    logger: FilteringBoundLogger,
    allow_not_found: bool = False,
) -> dict | None:
    # The tracked session already retries 429 and transient 5xx responses.
    response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)

    if allow_not_found and response.status_code == 404:
        return None

    if not response.ok:
        logger.error(f"Kong Konnect API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _iter_page_number(
    session: requests.Session,
    url: str,
    sort: str | None,
    logger: FilteringBoundLogger,
    allow_not_found: bool = False,
) -> Iterator[list[dict[str, Any]]]:
    page_number = 1
    while True:
        params: dict[str, Any] = {"page[size]": LIST_PAGE_SIZE, "page[number]": page_number}
        if sort:
            params["sort"] = sort
        data = _get_json(session, url, params, logger, allow_not_found=allow_not_found)
        if data is None:
            return
        rows = data.get("data") or []

        if rows:
            yield rows

        total = ((data.get("meta") or {}).get("page") or {}).get("total")
        if len(rows) < LIST_PAGE_SIZE or (total is not None and page_number * LIST_PAGE_SIZE >= total):
            break
        page_number += 1


def _next_page_after(data: dict[str, Any]) -> str | None:
    # `meta.next` is a URI path such as `/v1/realms?page[after]=...`, so read the cursor out of it.
    next_uri = (data.get("meta") or {}).get("next")
    if not next_uri:
        return None
    values = parse_qs(urlparse(next_uri).query).get("page[after]")
    return values[0] if values else None


def _iter_cursor(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
    allow_not_found: bool = False,
) -> Iterator[list[dict[str, Any]]]:
    params: dict[str, Any] = {"page[size]": LIST_PAGE_SIZE}
    while True:
        data = _get_json(session, url, params, logger, allow_not_found=allow_not_found)
        if data is None:
            return
        rows = data.get("data") or []

        if rows:
            yield rows

        page_after = _next_page_after(data)
        if not page_after:
            break
        params = {"page[size]": LIST_PAGE_SIZE, "page[after]": page_after}


def _iter_control_planes(
    session: requests.Session, base_url: str, logger: FilteringBoundLogger
) -> Iterator[list[dict[str, Any]]]:
    yield from _iter_page_number(
        session, f"{base_url}/control-planes", KONG_KONNECT_ENDPOINTS["control_planes"].sort, logger
    )


def _iter_offset(session: requests.Session, url: str, logger: FilteringBoundLogger) -> Iterator[list[dict[str, Any]]]:
    offset: str | None = None
    while True:
        params: dict[str, Any] = {"size": CORE_ENTITY_PAGE_SIZE}
        if offset:
            params["offset"] = offset
        data = _get_json(session, url, params, logger, allow_not_found=True)
        if data is None:
            # The parent was deleted between listing it and fanning out over it.
            logger.debug(f"Kong Konnect: {url} not found, skipping")
            return

        rows = data.get("data") or []
        if rows:
            yield rows

        offset = data.get("offset")
        if not offset:
            break


def _iter_core_entities(
    session: requests.Session,
    base_url: str,
    endpoint_config: KongKonnectEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KongKonnectResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    parent_config = KONG_KONNECT_ENDPOINTS[endpoint_config.parent] if endpoint_config.parent else None

    for control_planes in _iter_control_planes(session, base_url, logger):
        for control_plane in control_planes:
            if (control_plane.get("config") or {}).get("cluster_type") == CONTROL_PLANE_GROUP_CLUSTER_TYPE:
                continue

            control_plane_id = control_plane["id"]
            control_plane_url = f"{base_url}/control-planes/{control_plane_id}"

            if parent_config is None or endpoint_config.parent_id_field is None:
                for rows in _iter_offset(session, f"{control_plane_url}{endpoint_config.path}", logger):
                    yield [{**row, "control_plane_id": control_plane_id} for row in rows]
                resumable_source_manager.safe_point()
                continue

            for parents in _iter_offset(session, f"{control_plane_url}{parent_config.path}", logger):
                for parent in parents:
                    child_url = f"{control_plane_url}{endpoint_config.path.replace('{id}', parent['id'])}"
                    for rows in _iter_offset(session, child_url, logger):
                        yield [
                            {**row, "control_plane_id": control_plane_id, endpoint_config.parent_id_field: parent["id"]}
                            for row in rows
                        ]
                    resumable_source_manager.safe_point()


def _iter_list(
    session: requests.Session,
    url: str,
    endpoint_config: KongKonnectEndpointConfig,
    logger: FilteringBoundLogger,
    allow_not_found: bool = False,
) -> Iterator[list[dict[str, Any]]]:
    if endpoint_config.kind == "cursor":
        return _iter_cursor(session, url, logger, allow_not_found=allow_not_found)
    return _iter_page_number(session, url, endpoint_config.sort, logger, allow_not_found=allow_not_found)


def _iter_top_level(
    session: requests.Session,
    region: str,
    endpoint_config: KongKonnectEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KongKonnectResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    base_url = _get_base_url(region, endpoint_config.api_version)

    if endpoint_config.parent is None or endpoint_config.parent_id_field is None:
        yield from _iter_list(session, f"{base_url}{endpoint_config.path}", endpoint_config, logger)
        return

    parent_config = KONG_KONNECT_ENDPOINTS[endpoint_config.parent]
    for parents in _iter_list(session, f"{base_url}{parent_config.path}", parent_config, logger):
        for parent in parents:
            child_url = f"{base_url}{endpoint_config.path.replace('{id}', parent['id'])}"
            for rows in _iter_list(session, child_url, endpoint_config, logger, allow_not_found=True):
                yield [{**row, endpoint_config.parent_id_field: parent["id"]} for row in rows]
            resumable_source_manager.safe_point()


def get_lookup_rows(
    api_token: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KongKonnectResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    endpoint_config = KONG_KONNECT_ENDPOINTS[endpoint]
    session = make_tracked_session(headers=_get_headers(api_token), redact_values=(api_token,))

    if endpoint_config.kind == "core_entity":
        yield from _iter_core_entities(
            session, _get_base_url(region), endpoint_config, logger, resumable_source_manager
        )
    else:
        yield from _iter_top_level(session, region, endpoint_config, logger, resumable_source_manager)


def validate_credentials(api_token: str, region: str) -> bool:
    """Cheap probe that the bearer token is genuine: request a single record over a small window."""
    url = f"{_get_base_url(region)}/api-requests"
    body = _build_body(
        _format_datetime(datetime.now(UTC) - timedelta(hours=1)),
        _format_datetime(datetime.now(UTC)),
        offset=0,
        size=1,
    )
    try:
        response = make_tracked_session().post(url, headers=_get_headers(api_token), json=body, timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def get_rows(
    api_token: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KongKonnectResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    lookback_days: int = DEFAULT_INITIAL_LOOKBACK_DAYS,
) -> Iterator[list[dict[str, Any]]]:
    url = f"{_get_base_url(region)}{KONG_KONNECT_ENDPOINTS[endpoint].path}"
    headers = _get_headers(api_token)
    session = make_tracked_session()

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.start and resume.end:
        start, end, offset = resume.start, resume.end, resume.offset
        logger.debug(f"Kong Konnect: resuming api_requests window start={start} end={end} offset={offset}")
    else:
        start, end = _resolve_window(should_use_incremental_field, db_incremental_field_last_value, lookback_days)
        offset = 0

    while True:
        body = _build_body(start, end, offset, MAX_PAGE_SIZE)
        data = _fetch_page(session, url, headers, body, logger)
        results = data.get("results", [])

        if not results:
            break

        yield results

        offset += len(results)
        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on request_id) rather
        # than skipping it. Only persist when another page is likely, i.e. this page was full.
        if len(results) < MAX_PAGE_SIZE:
            break
        resumable_source_manager.save_state(KongKonnectResumeConfig(start=start, end=end, offset=offset))


def kong_konnect_source(
    api_token: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[KongKonnectResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    lookback_days: int = DEFAULT_INITIAL_LOOKBACK_DAYS,
) -> SourceResponse:
    endpoint_config = KONG_KONNECT_ENDPOINTS[endpoint]

    def items() -> Iterator[list[dict[str, Any]]]:
        if endpoint_config.kind != "analytics":
            return get_lookup_rows(
                api_token=api_token,
                region=region,
                endpoint=endpoint,
                logger=logger,
                resumable_source_manager=resumable_source_manager,
            )
        return get_rows(
            api_token=api_token,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
            lookback_days=lookback_days,
        )

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=endpoint_config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
