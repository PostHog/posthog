import bisect
import dataclasses
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.sources.sdk import (
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    retry_with_deadline,
)
from products.warehouse_sources.sources.segment.settings import (
    DELIVERY_METRICS_MAX_LOOKBACK_DAYS,
    DELIVERY_METRICS_WINDOW_DAYS,
    REGION_BASE_URLS,
    SEGMENT_ENDPOINTS,
    SegmentEndpointConfig,
)

# Segment's Public API caps a page at 1000 items (default 200). We request the max to minimize the
# number of round-trips while staying within documented limits and well clear of the lower per-endpoint
# rate caps (some endpoints are throttled to 250 req/min).
PAGE_SIZE = 200
# The Reverse ETL sync status endpoint pages with plain `count`/`cursor` params and caps `count` at 100.
SYNC_STATUS_PAGE_SIZE = 100


class SegmentRetryableError(Exception):
    pass


@dataclasses.dataclass(frozen=False)
class SegmentResumeConfig:
    # Opaque base64 cursor (`data.pagination.next`) for the next page of the endpoint being synced.
    cursor: str | None = None
    # Fan-out tables: the parent to read next. `cursor` is then the next child page of that parent.
    parent_id: str | None = None
    # Fan-out tables: every page of `parent_id` is already yielded, so resume after it.
    parent_done: bool = False
    # Delivery metrics: the end of the reporting window, so a resumed run reports the same window.
    window_end: str | None = None


@dataclasses.dataclass(frozen=True)
class _Parent:
    id: str
    path: str
    # Added to each child row, so the row names the parent it came from.
    row_fields: dict[str, Any]


def _base_url(region: str) -> str:
    return REGION_BASE_URLS.get(region, REGION_BASE_URLS["api"])


def _headers(api_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Accept": "application/json",
    }


def _build_url(base_url: str, path: str, cursor: str | None) -> str:
    """Build a list URL with Segment's pagination query params.

    Segment uses bracketed keys (`pagination[count]`, `pagination[cursor]`). The keys are constructed
    internally so they're left literal; only the opaque cursor value (base64, contains `=`) is encoded.
    """
    params = [f"pagination[count]={PAGE_SIZE}"]
    if cursor:
        params.append(f"pagination[cursor]={quote(cursor, safe='')}")
    return f"{base_url}{path}?{'&'.join(params)}"


@retry_with_deadline(
    retry=retry_if_exception_type((SegmentRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> dict:
    response = session.get(url, headers=headers, timeout=60)

    # 429 (rate limit) and 5xx are transient; back off and retry.
    if response.status_code == 429 or response.status_code >= 500:
        raise SegmentRetryableError(f"Segment API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        logger.error(f"Segment API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _extract_rows(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the resource array out of a Segment list response.

    The body is `{"data": {"<resource>": [...], "pagination": {...}}}`. The resource key varies and
    doesn't always match the endpoint name (e.g. `/audit-events` returns `events`, `/labels` returns
    `labels`), so we take the single list-valued entry under `data` rather than hardcoding the key.
    """
    payload = data.get("data", {})
    if not isinstance(payload, dict):
        return []
    for key, value in payload.items():
        if key == "pagination":
            continue
        if isinstance(value, list):
            return value
    return []


def _redact_rows(rows: list[dict[str, Any]], redacted_fields: frozenset[str]) -> list[dict[str, Any]]:
    """Drop credential-like top-level fields (e.g. destination `settings`, source `writeKeys`) so
    they never land in a queryable warehouse table. See `SegmentEndpointConfig.redacted_fields`.
    """
    if not redacted_fields:
        return rows
    return [
        {key: value for key, value in row.items() if key not in redacted_fields} if isinstance(row, dict) else row
        for row in rows
    ]


def _next_cursor(data: dict[str, Any]) -> str | None:
    payload = data.get("data", {})
    pagination = payload.get("pagination", {}) if isinstance(payload, dict) else {}
    next_cursor = pagination.get("next") if isinstance(pagination, dict) else None
    return next_cursor or None


def get_rows(
    api_token: str,
    region: str,
    config: SegmentEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SegmentResumeConfig],
) -> Iterator[Any]:
    base_url = _base_url(region)
    headers = _headers(api_token)
    # One session reused across pages so urllib3 keeps the connection alive instead of re-handshaking.
    # `redact_values` masks the bearer token in tracked request logs and captured HTTP samples.
    session = make_tracked_session(redact_values=(api_token,))

    # `GET /` (Get Workspace) returns a single object, not a paginated list.
    if config.single_object_key is not None:
        data = _fetch(session, f"{base_url}{config.path}", headers, logger)
        obj = data.get("data", {}).get(config.single_object_key)
        if obj:
            yield _redact_rows([obj], config.redacted_fields)
        return

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume else None
    if cursor:
        logger.debug(f"Segment: resuming {config.name} from cursor={cursor}")

    while True:
        url = _build_url(base_url, config.path, cursor)
        data = _fetch(session, url, headers, logger)

        rows = _extract_rows(data)
        if rows:
            yield _redact_rows(rows, config.redacted_fields)

        cursor = _next_cursor(data)
        if not cursor:
            break

        # Save AFTER yielding so a crash re-yields the last page (merge dedupes on the primary key)
        # rather than skipping it.
        resumable_source_manager.save_state(SegmentResumeConfig(cursor=cursor))


def _fetch_unless_not_found(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> dict | None:
    try:
        return _fetch(session, url, headers, logger)
    except requests.HTTPError as error:
        # A parent deleted after the parent listing returns 404. Skip it instead of failing the table.
        if error.response is not None and error.response.status_code == 404:
            logger.warning(f"Segment: skipping a parent that no longer exists, url={url}")
            return None
        raise


def _list_parents(
    session: requests.Session,
    base_url: str,
    path: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SegmentResumeConfig],
) -> list[dict[str, Any]]:
    parents: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        data = _fetch_unless_not_found(session, _build_url(base_url, path, cursor), headers, logger)
        if data is None:
            return parents
        parents.extend(row for row in _extract_rows(data) if isinstance(row, dict))
        # A parent page yields no rows, so let the pipeline hand the run over between requests.
        resumable_source_manager.safe_point()
        cursor = _next_cursor(data)
        if not cursor:
            return parents


_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S.000Z"


@frozen
class _MetricsWindow:
    start: str
    end: str


def _delivery_metrics_window(now: datetime, resumed_end: str | None) -> _MetricsWindow:
    """Whole UTC days, so every sync reports the same span and today's partial day is left out.

    A resumed run keeps the window of its first attempt while Segment still accepts that start time.
    """
    now = now.astimezone(UTC)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if resumed_end is not None:
        resumed = datetime.strptime(resumed_end, _TIME_FORMAT).replace(tzinfo=UTC)
        if now - (resumed - timedelta(days=DELIVERY_METRICS_WINDOW_DAYS)) < timedelta(
            days=DELIVERY_METRICS_MAX_LOOKBACK_DAYS
        ):
            end = resumed
    start = end - timedelta(days=DELIVERY_METRICS_WINDOW_DAYS)
    return _MetricsWindow(start=start.strftime(_TIME_FORMAT), end=end.strftime(_TIME_FORMAT))


def _tracking_plan_parents(plans: list[dict[str, Any]], config: SegmentEndpointConfig) -> list[_Parent]:
    return [
        _Parent(
            id=plan["id"],
            path=config.path.format(tracking_plan_id=quote(plan["id"], safe="")),
            row_fields={"trackingPlanId": plan["id"]},
        )
        for plan in plans
        if plan.get("id")
    ]


def _delivery_metrics_parents(
    destinations: list[dict[str, Any]], config: SegmentEndpointConfig, window: _MetricsWindow
) -> list[_Parent]:
    parents: list[_Parent] = []
    for destination in destinations:
        destination_id, source_id = destination.get("id"), destination.get("sourceId")
        if not destination_id or not source_id:
            continue
        query = urlencode(
            {"sourceId": source_id, "granularity": "DAY", "startTime": window.start, "endTime": window.end}
        )
        parents.append(
            _Parent(
                id=destination_id,
                path=f"{config.path.format(destination_id=quote(destination_id, safe=''))}?{query}",
                row_fields={
                    "destinationId": destination_id,
                    "sourceId": source_id,
                    "windowStart": window.start,
                    "windowEnd": window.end,
                },
            )
        )
    return parents


def _reverse_etl_parents(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SegmentResumeConfig],
    config: SegmentEndpointConfig,
) -> list[_Parent]:
    """Sync history is keyed by (model, subscription), and only a destination's subscriptions carry
    both. A Reverse ETL destination is connected to the Reverse ETL source of its model, so only
    those destinations are asked for subscriptions."""
    models = _list_parents(session, base_url, "/reverse-etl-models", headers, logger, resumable_source_manager)
    model_ids = {model["id"] for model in models if model.get("id")}
    model_source_ids = {model["sourceId"] for model in models if model.get("sourceId")}
    if not model_ids:
        return []

    destinations = _list_parents(session, base_url, "/destinations", headers, logger, resumable_source_manager)
    parents: list[_Parent] = []
    for destination in destinations:
        destination_id = destination.get("id")
        if not destination_id or destination.get("sourceId") not in model_source_ids:
            continue
        subscriptions = _list_parents(
            session,
            base_url,
            f"/destinations/{quote(destination_id, safe='')}/subscriptions",
            headers,
            logger,
            resumable_source_manager,
        )
        for subscription in subscriptions:
            subscription_id, model_id = subscription.get("id"), subscription.get("modelId")
            if not subscription_id or not model_id or model_id not in model_ids:
                continue
            parents.append(
                _Parent(
                    id=subscription_id,
                    path=config.path.format(
                        model_id=quote(model_id, safe=""), subscription_id=quote(subscription_id, safe="")
                    ),
                    row_fields={"subscriptionId": subscription_id},
                )
            )
    return parents


def _build_sync_status_url(base_url: str, path: str, cursor: str | None) -> str:
    params: dict[str, str | int] = {"count": SYNC_STATUS_PAGE_SIZE}
    if cursor:
        params["cursor"] = cursor
    return f"{base_url}{path}?{urlencode(params)}"


def _build_plain_url(base_url: str, path: str, _cursor: str | None) -> str:
    return f"{base_url}{path}"


def _shape_list_rows(parent: _Parent, data: dict[str, Any]) -> list[dict[str, Any]]:
    return [{**row, **parent.row_fields} for row in _extract_rows(data) if isinstance(row, dict)]


def _shape_rule_rows(parent: _Parent, data: dict[str, Any]) -> list[dict[str, Any]]:
    # `key` is part of the primary key, and identify, group and common rules have none.
    return [{**row, "key": row.get("key") or ""} for row in _shape_list_rows(parent, data)]


def _shape_delivery_metric_rows(parent: _Parent, data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("data")
    summary = payload.get("deliveryMetricsSummary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        return []
    return [
        {**metric, "destinationMetadataId": summary.get("destinationMetadataId"), **parent.row_fields}
        for metric in summary.get("metrics") or []
        if isinstance(metric, dict)
    ]


def _fan_out(
    session: requests.Session,
    base_url: str,
    headers: dict[str, str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SegmentResumeConfig],
    resume: SegmentResumeConfig | None,
    parents: list[_Parent],
    build_url: Callable[[str, str, str | None], str],
    shape: Callable[[_Parent, dict[str, Any]], list[dict[str, Any]]],
    redacted_fields: frozenset[str],
    window_end: str | None = None,
) -> Iterator[list[dict[str, Any]]]:
    # Sorted by id, so a resumed attempt finds its position even when the parent it saved is gone.
    parents = sorted(parents, key=lambda parent: parent.id)
    start, cursor = 0, None
    if resume is not None and resume.parent_id is not None:
        parent_ids = [parent.id for parent in parents]
        start = bisect.bisect_left(parent_ids, resume.parent_id)
        found = start < len(parent_ids) and parent_ids[start] == resume.parent_id
        if found and resume.parent_done:
            start += 1
        elif found:
            cursor = resume.cursor
        logger.debug(f"Segment: resuming at parent index={start} of {len(parents)}, cursor={cursor}")

    for index in range(start, len(parents)):
        parent = parents[index]
        while True:
            data = _fetch_unless_not_found(session, build_url(base_url, parent.path, cursor), headers, logger)
            rows = _redact_rows(shape(parent, data), redacted_fields) if data is not None else []
            cursor = _next_cursor(data) if data is not None else None

            resumable_source_manager.save_state(
                SegmentResumeConfig(
                    cursor=cursor, parent_id=parent.id, parent_done=cursor is None, window_end=window_end
                )
            )

            if rows:
                yield rows
            else:
                resumable_source_manager.safe_point()

            if not cursor:
                break


def get_fanout_rows(
    api_token: str,
    region: str,
    config: SegmentEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SegmentResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    base_url = _base_url(region)
    headers = _headers(api_token)
    session = make_tracked_session(redact_values=(api_token,))

    def list_parents(path: str) -> list[dict[str, Any]]:
        return _list_parents(session, base_url, path, headers, logger, resumable_source_manager)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    parents: list[_Parent]
    build_url: Callable[[str, str, str | None], str]
    shape: Callable[[_Parent, dict[str, Any]], list[dict[str, Any]]]
    window_end: str | None = None
    if config.fanout == "tracking_plan_rules":
        parents = _tracking_plan_parents(list_parents("/tracking-plans"), config)
        build_url, shape = _build_url, _shape_rule_rows
    elif config.fanout == "delivery_metrics":
        window = _delivery_metrics_window(datetime.now(UTC), resume.window_end if resume else None)
        window_end = window.end
        parents = _delivery_metrics_parents(list_parents("/destinations"), config, window)
        build_url, shape = _build_plain_url, _shape_delivery_metric_rows
    elif config.fanout == "reverse_etl_syncs":
        parents = _reverse_etl_parents(session, base_url, headers, logger, resumable_source_manager, config)
        build_url, shape = _build_sync_status_url, _shape_list_rows
    else:
        raise ValueError(f"Segment endpoint {config.name} is not a fan-out endpoint")

    yield from _fan_out(
        session,
        base_url,
        headers,
        logger,
        resumable_source_manager,
        resume,
        parents,
        build_url,
        shape,
        config.redacted_fields,
        window_end,
    )


def segment_source(
    api_token: str,
    region: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SegmentResumeConfig],
) -> SourceResponse:
    config = SEGMENT_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: (get_fanout_rows if config.fanout else get_rows)(
            api_token=api_token,
            region=region,
            config=config,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
        ),
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_token: str, region: str) -> bool:
    """Cheapest probe that a token is genuine: Get Workspace (`GET /`) for the token's region."""
    try:
        response = make_tracked_session(redact_values=(api_token,)).get(
            f"{_base_url(region)}/",
            headers=_headers(api_token),
            timeout=10,
        )
        return response.status_code == 200
    except Exception:
        return False
