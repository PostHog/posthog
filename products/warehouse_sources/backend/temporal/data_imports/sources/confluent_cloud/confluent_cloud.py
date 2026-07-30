import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.confluent_cloud.settings import (
    CONFLUENT_CLOUD_BASE_URL,
    CONFLUENT_CLOUD_ENDPOINTS,
    DATASET,
    DEFAULT_LOOKBACK_DAYS,
    DESCRIPTOR_PAGE_SIZE,
    GRANULARITY,
    INCREMENTAL_OVERLAP,
    QUERY_GROUP_LIMIT,
    QUERY_WINDOW,
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


def _format_timestamp(dt: datetime) -> str:
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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


@retry(
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
) -> tuple[datetime, datetime]:
    retention_floor = now - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    start = retention_floor
    if should_use_incremental_field:
        watermark = _coerce_datetime(db_incremental_field_last_value)
        if watermark is not None:
            # Cap a future-dated watermark at now, then re-pull a trailing overlap because recent
            # buckets get restated; merge dedupes on the primary key. Never reach past retention.
            start = max(min(watermark, now) - INCREMENTAL_OVERLAP, retention_floor)
    return start, now


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

    start, end = _sync_range(should_use_incremental_field, db_incremental_field_last_value, datetime.now(UTC))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start:
        resumed_start = _coerce_datetime(resume.window_start)
        if resumed_start is not None and start <= resumed_start < end:
            start = resumed_start
            logger.debug(f"Confluent Cloud: resuming {endpoint} from window start {resume.window_start}")

    metric_names = _get_metric_names(session, config.resource_type, logger)
    if not metric_names:
        logger.warning(f"Confluent Cloud: no metrics found for resource type {config.resource_type}")
        return

    window_start = start
    while window_start < end:
        window_end = min(window_start + QUERY_WINDOW, end)
        interval = f"{_format_timestamp(window_start)}/{_format_timestamp(window_end)}"

        for metric in metric_names:
            body = _build_query_body(metric, config.resource_label, resource_ids, interval)
            for page in _iter_query_pages(session, body, logger):
                yield [_normalize_point(point, metric, config.resource_label) for point in page]

        window_start = window_end
        # Checkpoint AFTER the window's rows are yielded (and only while more windows remain), so a
        # crash re-yields the current window rather than skipping it — merge dedupes on the primary
        # key.
        if window_start < end:
            resumable_source_manager.save_state(
                ConfluentCloudResumeConfig(window_start=_format_timestamp(window_start))
            )


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
        # only persist at successful job end (desc mode).
        sort_mode="desc",
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
        f"{_format_timestamp(now - timedelta(hours=1))}/{_format_timestamp(now)}",
    )
    url = f"{CONFLUENT_CLOUD_BASE_URL}/v2/metrics/{DATASET}/query"
    try:
        response = session.post(url, json=body, timeout=15)
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
