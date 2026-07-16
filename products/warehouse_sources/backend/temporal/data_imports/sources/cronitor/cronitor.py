import time
import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from dateutil import parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.settings import (
    BASE_URL,
    CRONITOR_ENDPOINTS,
    METRICS_FIELDS,
    METRICS_MAX_LOOKBACK_SECONDS,
    METRICS_MAX_MONITORS_PER_REQUEST,
    METRICS_MIN_WINDOW_SECONDS,
    METRICS_WINDOW_SECONDS,
    PAGE_SIZE,
)


class CronitorRetryableError(Exception):
    pass


@dataclasses.dataclass
class CronitorResumeConfig:
    # monitors: next 1-indexed page to fetch.
    page: int | None = None
    # invocations: stable key bookmark of the next monitor to fan out into (not a positional
    # index, so monitors added/removed between a crash and the retry can't shift the resume point).
    monitor_key: str | None = None
    # metrics: Unix start of the next time window to fetch.
    window_start: int | None = None


def _build_url(path: str, params: list[tuple[str, Any]] | dict[str, Any]) -> str:
    if not params:
        return f"{BASE_URL}{path}"
    return f"{BASE_URL}{path}?{urlencode(params)}"


def _coerce_epoch(value: Any) -> int | None:
    """Normalize a cursor value (epoch number, datetime, date, or string) to a Unix int."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            pass
        try:
            parsed = parser.parse(value)
        except (ValueError, OverflowError):
            return None
        aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return int(aware.timestamp())
    return None


@retry(
    retry=retry_if_exception_type((CronitorRetryableError, requests.ReadTimeout, requests.ConnectionError)),
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    reraise=True,
)
def _fetch(session: requests.Session, url: str, api_key: str, logger: FilteringBoundLogger) -> Any:
    # HTTP Basic auth: API key as the username, empty password.
    response = session.get(url, auth=(api_key, ""), headers={"Accept": "application/json"}, timeout=60)

    # Cronitor rate limits with 429 (exact limits undocumented); transient 5xx are retryable too.
    if response.status_code == 429 or response.status_code >= 500:
        raise CronitorRetryableError(f"Cronitor API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404s are expected in places (deleted monitor mid-fan-out, empty metrics window) and
        # handled by the caller; anything else is a real failure.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Cronitor API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _fetch_monitors_page(
    session: requests.Session, api_key: str, logger: FilteringBoundLogger, page: int
) -> tuple[list[dict[str, Any]], bool]:
    """Fetch one page of the monitors list, returning (rows, has_more).

    Sort by creation time so the page walk stays stable if monitors are added mid-sync. The list
    envelope documents no total count, so a short page signals the end.
    """
    url = _build_url("/monitors", {"page": page, "pageSize": PAGE_SIZE, "sort": "created"})
    data = _fetch(session, url, api_key, logger)
    monitors = data.get("monitors") if isinstance(data, dict) else data
    if not isinstance(monitors, list):
        return [], False
    rows = [monitor for monitor in monitors if isinstance(monitor, dict)]
    return rows, len(rows) >= PAGE_SIZE


def _get_monitor_rows(
    session: requests.Session,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CronitorResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None and resume.page else 1
    if page > 1:
        logger.debug(f"Cronitor: resuming monitors from page {page}")

    while True:
        rows, has_more = _fetch_monitors_page(session, api_key, logger, page)
        if not rows:
            break
        yield rows
        if not has_more:
            break
        page += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
        # merge dedupes on the primary key.
        resumable_source_manager.save_state(CronitorResumeConfig(page=page))


def _list_monitor_keys(session: requests.Session, api_key: str, logger: FilteringBoundLogger) -> list[str]:
    keys: list[str] = []
    page = 1
    while True:
        rows, has_more = _fetch_monitors_page(session, api_key, logger, page)
        keys.extend(str(monitor["key"]) for monitor in rows if monitor.get("key"))
        if not has_more:
            return keys
        page += 1


def _get_invocation_rows(
    session: requests.Session,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CronitorResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every monitor, materializing its recent invocations as rows.

    The API exposes no paginated invocation history — only the `latest_invocations` returned by the
    monitor detail with `?withInvocations=true` — so this is a full-refresh snapshot of each
    monitor's recent runs. Long-term trends come from the metrics endpoint instead.
    """
    monitor_keys = _list_monitor_keys(session, api_key, logger)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = monitor_keys
    if resume is not None and resume.monitor_key is not None and resume.monitor_key in monitor_keys:
        remaining = monitor_keys[monitor_keys.index(resume.monitor_key) :]
        logger.debug(f"Cronitor: resuming invocations from monitor {resume.monitor_key}")

    for index, monitor_key in enumerate(remaining):
        url = _build_url(f"/monitors/{quote(monitor_key, safe='')}", {"withInvocations": "true"})
        try:
            data = _fetch(session, url, api_key, logger)
        except requests.HTTPError as exc:
            # A monitor deleted between enumeration and this fetch 404s. Skip it rather than
            # failing the whole sync; any other HTTP error is re-raised.
            if exc.response is not None and exc.response.status_code == 404:
                logger.warning(f"Cronitor: monitor {monitor_key} not found while fetching invocations, skipping")
                data = None
            else:
                raise

        if isinstance(data, dict):
            rows: list[dict[str, Any]] = []
            for invocation in data.get("latest_invocations") or []:
                if not isinstance(invocation, dict):
                    continue
                row = {**invocation, "monitor_key": monitor_key}
                # `series` is part of the primary key; coalesce so the merge key is never null.
                row["series"] = row.get("series") or ""
                rows.append(row)
            if rows:
                yield rows

        # Advance the bookmark AFTER this monitor's rows are yielded so a crash re-yields them —
        # merge dedupes on the primary key.
        if index + 1 < len(remaining):
            resumable_source_manager.save_state(CronitorResumeConfig(monitor_key=remaining[index + 1]))


def _flatten_metrics_response(data: Any) -> list[dict[str, Any]]:
    """Flatten the nested metrics response (monitor key -> dimension -> data points) into rows."""
    monitors = data.get("monitors") if isinstance(data, dict) else None
    if not isinstance(monitors, dict):
        return []
    rows: list[dict[str, Any]] = []
    for monitor_key, dimensions in monitors.items():
        if not isinstance(dimensions, dict):
            continue
        for dimension, points in dimensions.items():
            if not isinstance(points, list):
                continue
            for point in points:
                if not isinstance(point, dict):
                    continue
                # Coerce the stamp to a Unix int so the integer cursor and datetime partitioning
                # both work regardless of whether the API returns it as int or float.
                stamp = _coerce_epoch(point.get("stamp"))
                if stamp is None:
                    continue
                rows.append({**point, "monitor_key": monitor_key, "dimension": dimension, "stamp": stamp})
    return rows


def _get_metric_rows(
    session: requests.Session,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CronitorResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Walk time windows over the metrics API, batching monitors up to the per-request cap."""
    monitor_keys = _list_monitor_keys(session, api_key, logger)
    if not monitor_keys:
        return

    now = int(time.time())
    floor = now - METRICS_MAX_LOOKBACK_SECONDS

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start is not None:
        start = resume.window_start
        logger.debug(f"Cronitor: resuming metrics from window start {start}")
    else:
        last_value = _coerce_epoch(db_incremental_field_last_value) if should_use_incremental_field else None
        start = last_value if last_value is not None else floor
    # A single request's span is capped at one year, and older data points aren't retrievable
    # through a window that old anyway — clamp the walk to the max lookback.
    start = max(start, floor)

    while start < now:
        end = min(start + METRICS_WINDOW_SECONDS, now)
        # The API rejects windows narrower than an hour; widen backwards and let merge dedupe
        # the re-pulled points.
        window_start = min(start, end - METRICS_MIN_WINDOW_SECONDS)

        for batch_index in range(0, len(monitor_keys), METRICS_MAX_MONITORS_PER_REQUEST):
            batch = monitor_keys[batch_index : batch_index + METRICS_MAX_MONITORS_PER_REQUEST]
            params: list[tuple[str, Any]] = [("monitor", key) for key in batch]
            params.extend(("field", metric_field) for metric_field in METRICS_FIELDS)
            params.extend([("start", window_start), ("end", end)])
            try:
                data = _fetch(session, _build_url("/metrics", params), api_key, logger)
            except requests.HTTPError as exc:
                # The metrics API 404s when no monitor in the batch has data for the window.
                if exc.response is not None and exc.response.status_code == 404:
                    continue
                raise
            rows = _flatten_metrics_response(data)
            if rows:
                yield rows

        if end >= now:
            break
        start = end
        # Save AFTER the window's batches are yielded so a crash re-fetches the whole window
        # rather than skipping part of it — merge dedupes on the primary key.
        resumable_source_manager.save_state(CronitorResumeConfig(window_start=start))


def get_rows(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CronitorResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    # One session reused across every request so urllib3 keeps the connection alive.
    session = make_tracked_session()

    if endpoint == "monitors":
        yield from _get_monitor_rows(session, api_key, logger, resumable_source_manager)
    elif endpoint == "invocations":
        yield from _get_invocation_rows(session, api_key, logger, resumable_source_manager)
    elif endpoint == "metrics":
        yield from _get_metric_rows(
            session,
            api_key,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        raise ValueError(f"Unknown Cronitor endpoint: {endpoint}")


def cronitor_source(
    api_key: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CronitorResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = CRONITOR_ENDPOINTS[endpoint]

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
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe the monitors list to confirm the key is genuine.

    Returns ``(ok, status_code)``; ``status_code`` is ``None`` on a transport error.
    """
    url = _build_url("/monitors", {"page": 1, "pageSize": 1})
    try:
        response = make_tracked_session().get(
            url, auth=(api_key, ""), headers={"Accept": "application/json"}, timeout=10
        )
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
