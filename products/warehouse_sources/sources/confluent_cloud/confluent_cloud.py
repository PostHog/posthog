import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.confluent_cloud.settings import (
    CLOUD_API_BASE_URL,
    CLOUD_API_PAGE_SIZE,
    CONFLUENT_CLOUD_BASE_URL,
    CONFLUENT_CLOUD_ENDPOINTS,
    COSTS_INCREMENTAL_OVERLAP,
    COSTS_LOOKBACK_DAYS,
    COSTS_QUERY_WINDOW,
    DATASET,
    DEFAULT_LOOKBACK_DAYS,
    DESCRIPTOR_PAGE_SIZE,
    GRANULARITY,
    INCREMENTAL_OVERLAP,
    QUERY_GROUP_LIMIT,
    QUERY_WINDOW,
)
from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    SyncWindow,
    coerce_date,
    format_datetime,
    make_tracked_session,
    retry_with_deadline,
)


class ConfluentCloudRetryableError(Exception):
    pass


class MissingResourceIdsError(Exception):
    pass


@dataclasses.dataclass
class ConfluentCloudResumeConfig:
    # ISO-8601 start of the next day-window still to query. None means "start from the beginning
    # of the sync range". Only whole windows are checkpointed — page cursors are short-lived, so a
    # retried window always restarts fresh and merge dedupes the re-pulled rows.
    window_start: str | None = None


def parse_resource_ids(raw: str | None) -> list[str]:
    """Split a comma/whitespace-separated resource id list into clean ids, preserving order."""
    if not raw:
        return []
    seen: set[str] = set()
    ids: list[str] = []
    for part in raw.replace(",", " ").split():
        if part not in seen:
            seen.add(part)
            ids.append(part)
    return ids


def _make_session(api_key: str, api_secret: str) -> requests.Session:
    session = make_tracked_session(headers={"Accept": "application/json"})
    # The Metrics API authenticates with HTTP Basic auth: Cloud API key id as the username, the
    # secret as the password.
    session.auth = (api_key, api_secret)
    return session


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


@retry_with_deadline(
    retry=retry_if_exception_type((ConfluentCloudRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    reraise=True,
)
def _fetch_json(
    session: requests.Session,
    method: str,
    url: str,
    logger: FilteringBoundLogger,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict:
    if params:
        url = f"{url}?{urlencode(params)}"
    response = session.request(method, url, json=json_body, timeout=60)

    # The API enforces 300 requests/minute per IP; 429 and transient 5xx are worth backing off on.
    if response.status_code == 429 or response.status_code >= 500:
        raise ConfluentCloudRetryableError(
            f"Confluent Cloud API error (retryable): status={response.status_code}, url={url}"
        )

    if not response.ok:
        logger.error(f"Confluent Cloud API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _next_page_token(data: dict) -> str | None:
    return ((data.get("meta") or {}).get("pagination") or {}).get("next_page_token")


def _iter_descriptor_pages(
    session: requests.Session,
    descriptor_path: str,
    logger: FilteringBoundLogger,
    resource_type: str | None = None,
) -> Iterator[list[dict]]:
    url = f"{CONFLUENT_CLOUD_BASE_URL}/v2/metrics/{DATASET}/{descriptor_path}"
    params: dict[str, Any] = {"page_size": DESCRIPTOR_PAGE_SIZE}
    if resource_type:
        params["resource_type"] = resource_type

    page_token: str | None = None
    while True:
        page_params = {**params, "page_token": page_token} if page_token else params
        data = _fetch_json(session, "GET", url, logger, params=page_params)
        items = data.get("data", [])
        if items:
            yield items
        page_token = _next_page_token(data)
        if not page_token:
            break


def _get_metric_names(session: requests.Session, resource_type: str, logger: FilteringBoundLogger) -> list[str]:
    """List the queryable metric names for a resource type from the live descriptor catalog.

    Discovering the catalog at sync time means new Confluent metrics start flowing without a code
    change. Deprecated metrics are excluded — they stop returning data and eventually get removed.
    """
    names: list[str] = []
    for page in _iter_descriptor_pages(session, "descriptors/metrics", logger, resource_type=resource_type):
        for descriptor in page:
            if descriptor.get("lifecycle_stage") == "DEPRECATED":
                continue
            name = descriptor.get("name")
            if name:
                names.append(name)
    return names


def _build_query_body(metric: str, resource_label: str, resource_ids: list[str], interval: str) -> dict[str, Any]:
    id_filters: list[dict[str, Any]] = [
        {"field": resource_label, "op": "EQ", "value": resource_id} for resource_id in resource_ids
    ]
    query_filter = id_filters[0] if len(id_filters) == 1 else {"op": "OR", "filters": id_filters}
    return {
        # The query endpoint accepts exactly one aggregation per request, so each metric is its
        # own query.
        "aggregations": [{"metric": metric}],
        "filter": query_filter,
        "granularity": GRANULARITY,
        "group_by": [resource_label],
        "intervals": [interval],
        "limit": QUERY_GROUP_LIMIT,
        "format": "FLAT",
    }


def _iter_query_pages(
    session: requests.Session, body: dict[str, Any], logger: FilteringBoundLogger
) -> Iterator[list[dict]]:
    """POST a metrics query and follow `next_page_token` pages.

    Per the API spec, pagination re-POSTs the identical body with the token passed as the
    `page_token` query parameter. Tokens are short-lived, but each page is requested immediately
    after the previous one, and our absolute-timestamp intervals keep them valid across pages.
    """
    url = f"{CONFLUENT_CLOUD_BASE_URL}/v2/metrics/{DATASET}/query"
    page_token: str | None = None
    while True:
        params = {"page_token": page_token} if page_token else None
        data = _fetch_json(session, "POST", url, logger, json_body=body, params=params)
        items = data.get("data", [])
        if items:
            yield items
        page_token = _next_page_token(data)
        if not page_token:
            break


def _normalize_point(point: dict[str, Any], metric: str, resource_label: str) -> dict[str, Any]:
    """Reshape a FLAT-format point into a stable row: the grouped resource id label (e.g.
    `resource.kafka.id`) becomes a plain `resource_id` column and the queried metric name is
    attached, forming the [metric, resource_id, timestamp] primary key."""
    return {
        "metric": metric,
        "resource_id": point.get(resource_label),
        "timestamp": point.get("timestamp"),
        "value": point.get("value"),
    }


def _sync_range(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    now: datetime,
) -> SyncWindow[datetime]:
    retention_floor = now - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    start = retention_floor
    if should_use_incremental_field:
        watermark = _coerce_datetime(db_incremental_field_last_value)
        if watermark is not None:
            # Cap a future-dated watermark at now, then re-pull a trailing overlap because recent
            # buckets get restated; merge dedupes on the primary key. Never reach past retention.
            start = max(min(watermark, now) - INCREMENTAL_OVERLAP, retention_floor)
    return SyncWindow(start=start, end=now)


def _iter_metrics_rows(
    session: requests.Session,
    endpoint: str,
    resource_ids: list[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ConfluentCloudResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict]]:
    config = CONFLUENT_CLOUD_ENDPOINTS[endpoint]
    assert config.resource_type is not None and config.resource_label is not None

    if not resource_ids:
        raise MissingResourceIdsError(
            f"No Confluent Cloud resource IDs configured for table '{endpoint}'. "
            "Add the resource IDs in the source settings, or disable this table."
        )

    window = _sync_range(should_use_incremental_field, db_incremental_field_last_value, datetime.now(UTC))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start:
        resumed_start = _coerce_datetime(resume.window_start)
        if resumed_start is not None and window.start <= resumed_start < window.end:
            window = SyncWindow(start=resumed_start, end=window.end)
            logger.debug(f"Confluent Cloud: resuming {endpoint} from window start {resume.window_start}")

    metric_names = _get_metric_names(session, config.resource_type, logger)
    if not metric_names:
        logger.warning(f"Confluent Cloud: no metrics found for resource type {config.resource_type}")
        return

    window_start = window.start
    while window_start < window.end:
        window_end = min(window_start + QUERY_WINDOW, window.end)
        interval = f"{format_datetime(window_start)}/{format_datetime(window_end)}"

        for metric in metric_names:
            body = _build_query_body(metric, config.resource_label, resource_ids, interval)
            for page in _iter_query_pages(session, body, logger):
                yield [_normalize_point(point, metric, config.resource_label) for point in page]

        window_start = window_end
        # Checkpoint AFTER the window's rows are yielded (and only while more windows remain), so a
        # crash re-yields the current window rather than skipping it — merge dedupes on the primary
        # key.
        if window_start < window.end:
            resumable_source_manager.save_state(ConfluentCloudResumeConfig(window_start=format_datetime(window_start)))


def _next_cloud_page_token(data: dict) -> str | None:
    # `metadata.next` is a full URL. Only its page_token is taken, and the original filters are sent
    # again, because the documented next links carry no filters.
    next_url = (data.get("metadata") or {}).get("next")
    if not next_url:
        return None
    tokens = parse_qs(urlparse(next_url).query).get("page_token")
    return tokens[0] if tokens else None


def _iter_cloud_api_pages(
    session: requests.Session,
    path: str,
    logger: FilteringBoundLogger,
    params: dict[str, Any],
) -> Iterator[list[dict]]:
    url = f"{CLOUD_API_BASE_URL}/{path}"
    page_token: str | None = None
    while True:
        page_params = {**params, "page_token": page_token} if page_token else params
        data = _fetch_json(session, "GET", url, logger, params=page_params)
        items = data.get("data") or []
        if items:
            yield items
        page_token = _next_cloud_page_token(data)
        if not page_token:
            break


def _iter_kafka_cluster_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ConfluentCloudResumeConfig],
) -> Iterator[list[dict]]:
    environments_path = CONFLUENT_CLOUD_ENDPOINTS["environments"].cloud_api_path
    clusters_path = CONFLUENT_CLOUD_ENDPOINTS["kafka_clusters"].cloud_api_path
    assert environments_path is not None and clusters_path is not None

    # The clusters list requires an environment filter, so walk every environment the key can see.
    for environments in _iter_cloud_api_pages(session, environments_path, logger, {"page_size": CLOUD_API_PAGE_SIZE}):
        for environment in environments:
            environment_id = environment.get("id")
            if not environment_id:
                continue
            found = False
            for clusters in _iter_cloud_api_pages(
                session,
                clusters_path,
                logger,
                {"environment": environment_id, "page_size": CLOUD_API_PAGE_SIZE},
            ):
                found = True
                yield [{**cluster, "environment_id": environment_id} for cluster in clusters]
            if not found:
                resumable_source_manager.safe_point()


def _costs_range(
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    today: date,
) -> SyncWindow[date]:
    floor = today - timedelta(days=COSTS_LOOKBACK_DAYS)
    start = floor
    if should_use_incremental_field:
        watermark = coerce_date(db_incremental_field_last_value)
        if watermark is not None:
            start = max(min(watermark, today) - COSTS_INCREMENTAL_OVERLAP, floor)
    # end_date is exclusive, so the in-progress day is left for the next sync.
    return SyncWindow(start=start, end=today)


def _iter_cost_rows(
    session: requests.Session,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ConfluentCloudResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict]]:
    path = CONFLUENT_CLOUD_ENDPOINTS["costs"].cloud_api_path
    assert path is not None

    window = _costs_range(should_use_incremental_field, db_incremental_field_last_value, datetime.now(UTC).date())

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start:
        resumed_start = coerce_date(resume.window_start)
        if resumed_start is not None and window.start <= resumed_start < window.end:
            window = SyncWindow(start=resumed_start, end=window.end)
            logger.debug(f"Confluent Cloud: resuming costs from window start {resume.window_start}")

    window_start = window.start
    while window_start < window.end:
        window_end = min(window_start + COSTS_QUERY_WINDOW, window.end)
        params = {"start_date": format_datetime(window_start, "date"), "end_date": format_datetime(window_end, "date")}

        # One page is held back so the next window's start is staged before the last page of this
        # window is yielded.
        held: list[dict] | None = None
        for page in _iter_cloud_api_pages(session, path, logger, params):
            if held is not None:
                yield held
            held = page

        if window_end < window.end:
            resumable_source_manager.save_state(
                ConfluentCloudResumeConfig(window_start=format_datetime(window_end, "date"))
            )
        if held is not None:
            yield held
        else:
            resumable_source_manager.safe_point()
        window_start = window_end


def get_rows(
    api_key: str,
    api_secret: str,
    endpoint: str,
    resource_ids: list[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ConfluentCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict]]:
    config = CONFLUENT_CLOUD_ENDPOINTS[endpoint]
    session = _make_session(api_key, api_secret)

    if config.kind == "descriptors":
        assert config.descriptor_path is not None
        yield from _iter_descriptor_pages(session, config.descriptor_path, logger)
        return

    if config.kind == "cloud_list":
        assert config.cloud_api_path is not None
        yield from _iter_cloud_api_pages(session, config.cloud_api_path, logger, {"page_size": CLOUD_API_PAGE_SIZE})
        return

    if config.kind == "kafka_clusters":
        yield from _iter_kafka_cluster_rows(session, logger, resumable_source_manager)
        return

    if config.kind == "costs":
        yield from _iter_cost_rows(
            session, logger, resumable_source_manager, should_use_incremental_field, db_incremental_field_last_value
        )
        return

    yield from _iter_metrics_rows(
        session,
        endpoint,
        resource_ids,
        logger,
        resumable_source_manager,
        should_use_incremental_field,
        db_incremental_field_last_value,
    )


def confluent_cloud_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    resource_ids: list[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[ConfluentCloudResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CONFLUENT_CLOUD_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            api_secret=api_secret,
            endpoint=endpoint,
            resource_ids=resource_ids,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # The API returns points newest-first within each group, and we interleave per-metric
        # queries per window — rows are not globally ascending, so the incremental watermark must
        # only persist at successful job end (desc mode). Cost rows have no documented order.
        sort_mode="desc" if config.kind in ("descriptors", "metrics") else None,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(
    api_key: str,
    api_secret: str,
    probe_metric: str,
    resource_label: str,
    resource_id: str,
    logger: FilteringBoundLogger | None = None,
) -> tuple[bool, int | None]:
    """Probe the query endpoint (the descriptor endpoints are public, so only a query proves the
    key). Returns ``(ok, status_code)``; ``status_code`` is ``None`` on a transport error."""
    session = _make_session(api_key, api_secret)
    now = datetime.now(UTC)
    body = _build_query_body(
        probe_metric,
        resource_label,
        [resource_id],
        f"{format_datetime(now - timedelta(hours=1))}/{format_datetime(now)}",
    )
    url = f"{CONFLUENT_CLOUD_BASE_URL}/v2/metrics/{DATASET}/query"
    try:
        response = session.post(url, json=body, timeout=15)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
