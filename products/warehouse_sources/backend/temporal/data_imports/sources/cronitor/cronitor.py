import time
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import requests
from dateutil import parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.cronitor.settings import (
    BASE_URL,
    CRONITOR_ENDPOINTS,
    METRICS_FIELDS,
    METRICS_MAX_LOOKBACK_SECONDS,
    METRICS_MAX_MONITORS_PER_REQUEST,
    METRICS_MIN_WINDOW_SECONDS,
    METRICS_WINDOW_SECONDS,
    PAGE_SIZE,
    PAGINATED_LIST_ENDPOINTS,
    SITE_ERRORS_ENDPOINT,
    CronitorListEndpoint,
)


class CronitorRetryableError(Exception):
    pass


class CronitorResponseShapeError(Exception):
    pass


@frozen
class CronitorResumeConfig:
    # Paginated list endpoints (and site_errors within one site): next 1-indexed page to fetch.
    page: int | None = None
    # invocations: stable key bookmark of the next monitor to fan out into (not a positional
    # index, so monitors added/removed between a crash and the retry can't shift the resume point).
    monitor_key: str | None = None
    # metrics: Unix start of the next time window to fetch.
    window_start: int | None = None
    # site_errors: stable key bookmark of the next site to fan out into, paired with `page`.
    site_key: str | None = None


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


# HTTP-check monitors carry the outbound request config Cronitor uses to probe an endpoint, and
# that config can embed credentials (bearer tokens, API keys, session cookies, secrets in the
# POST body). Drop those wholesale before a row is persisted so they never land in the queryable
# warehouse table where any project member could read them back.
_SENSITIVE_REQUEST_FIELDS = ("headers", "cookies", "body")


def _sanitize_url(url: str) -> str:
    """Reduce a check URL to just scheme + host/port so no embedded credential can survive.

    Userinfo (``user:pass@``), the query string, and the fragment obviously carry tokens, but the
    path does too — Slack incoming webhooks and other tokenized callback endpoints put the secret
    in a path segment. There's no way to tell a credential-bearing path apart from a benign one, so
    drop the path entirely and keep only scheme and host/port: enough to say *which* endpoint is
    monitored without persisting anything secret.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if not parts.hostname:
        # No scheme/host to anchor on (relative or malformed) — nothing safe to keep.
        return ""
    netloc = parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, "", "", ""))


def _redact_monitor(monitor: dict[str, Any]) -> dict[str, Any]:
    request = monitor.get("request")
    if not isinstance(request, dict):
        return monitor
    redacted_request = {key: value for key, value in request.items() if key not in _SENSITIVE_REQUEST_FIELDS}
    url = redacted_request.get("url")
    if isinstance(url, str):
        redacted_request["url"] = _sanitize_url(url)
    if redacted_request == request:
        return monitor
    return {**monitor, "request": redacted_request}


def _extract_rows(data: Any, endpoint: CronitorListEndpoint) -> list[dict[str, Any]]:
    """Pull the row list out of a paginated response.

    Cronitor is not consistent about the envelope: monitors and groups nest the rows under a
    resource-named key while sites and site errors use `data`, so try the endpoint's documented
    key, then `data`, then a bare list.

    A 200 carrying none of them is a shape change rather than an empty page. Reading it as empty
    would let a full refresh replace the table with nothing and report success, so fail instead.
    An empty list is still a legitimate empty page.
    """
    rows: Any = data
    if isinstance(data, dict):
        rows = data.get(endpoint.envelope_key)
        if not isinstance(rows, list):
            rows = data.get("data")
    if not isinstance(rows, list):
        raise CronitorResponseShapeError(
            f"Cronitor returned an unexpected response shape for {endpoint.path}: "
            f"no list under '{endpoint.envelope_key}' or 'data'"
        )
    return [row for row in rows if isinstance(row, dict)]


def _fetch_list_page(
    session: requests.Session,
    api_key: str,
    logger: FilteringBoundLogger,
    endpoint: CronitorListEndpoint,
    page: int,
    extra_params: list[tuple[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Fetch one page of a `page`/`pageSize` list, returning (rows, has_more).

    No list envelope documents a total count, so a short page signals the end.
    """
    params: list[tuple[str, Any]] = [("page", page), ("pageSize", PAGE_SIZE)]
    params.extend(endpoint.params)
    if extra_params:
        params.extend(extra_params)
    data = _fetch(session, _build_url(endpoint.path, params), api_key, logger)
    rows = _extract_rows(data, endpoint)
    return rows, len(rows) >= PAGE_SIZE


# Anyone holding a site's public report key can open that report without a Cronitor login, so
# drop it before a row is persisted rather than leaving the capability in a table every project
# member can query. `client_key` stays: it ships in the site's own browser snippet.
_SENSITIVE_SITE_FIELDS = ("public_report_key",)


def _redact_site(site: dict[str, Any]) -> dict[str, Any]:
    if not any(field in site for field in _SENSITIVE_SITE_FIELDS):
        return site
    return {key: value for key, value in site.items() if key not in _SENSITIVE_SITE_FIELDS}


# Row normalizers applied to a paginated list before its rows are yielded.
_LIST_ROW_MAPPERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "monitors": _redact_monitor,
    "sites": _redact_site,
}


def _get_paginated_rows(
    session: requests.Session,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CronitorResumeConfig],
    schema_name: str,
) -> Iterator[list[dict[str, Any]]]:
    endpoint = PAGINATED_LIST_ENDPOINTS[schema_name]
    row_mapper = _LIST_ROW_MAPPERS.get(schema_name)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.page if resume is not None and resume.page else 1
    if page > 1:
        logger.debug(f"Cronitor: resuming {schema_name} from page {page}")

    while True:
        rows, has_more = _fetch_list_page(session, api_key, logger, endpoint, page)
        if not rows:
            break
        yield [row_mapper(row) for row in rows] if row_mapper is not None else rows
        if not has_more:
            break
        page += 1
        # Save AFTER yielding so a crash re-yields the last page rather than skipping it —
        # merge dedupes on the primary key.
        resumable_source_manager.save_state(CronitorResumeConfig(page=page))


def _list_keys(
    session: requests.Session, api_key: str, logger: FilteringBoundLogger, endpoint: CronitorListEndpoint
) -> list[str]:
    keys: list[str] = []
    page = 1
    while True:
        rows, has_more = _fetch_list_page(session, api_key, logger, endpoint, page)
        keys.extend(str(row["key"]) for row in rows if row.get("key"))
        if not has_more:
            return keys
        page += 1


def _list_monitor_keys(session: requests.Session, api_key: str, logger: FilteringBoundLogger) -> list[str]:
    return _list_keys(session, api_key, logger, PAGINATED_LIST_ENDPOINTS["monitors"])


def _list_site_keys(session: requests.Session, api_key: str, logger: FilteringBoundLogger) -> list[str]:
    # The sites list takes no sort parameter, so the API order is not guaranteed between runs.
    # Sorting here gives the fan-out a stable order, which is what makes resuming at a saved site
    # key safe: without it a reordered list would skip the sites that moved behind the bookmark.
    return sorted(_list_keys(session, api_key, logger, PAGINATED_LIST_ENDPOINTS["sites"]))


def _get_site_error_rows(
    session: requests.Session,
    api_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[CronitorResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every RUM site, tagging each error with the site it came from.

    The errors list takes an optional `site` filter but returns no site key on the rows, so
    without the fan-out there would be no way to attribute an error to a site.
    """
    site_keys = _list_site_keys(session, api_key, logger)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    remaining = site_keys
    page = 1
    if resume is not None and resume.site_key is not None and resume.site_key in site_keys:
        remaining = site_keys[site_keys.index(resume.site_key) :]
        page = resume.page or 1
        logger.debug(f"Cronitor: resuming site errors from site {resume.site_key} page {page}")

    for index, site_key in enumerate(remaining):
        while True:
            rows, has_more = _fetch_list_page(
                session, api_key, logger, SITE_ERRORS_ENDPOINT, page, [("site", site_key)]
            )
            if rows:
                yield [{**row, "site_key": site_key} for row in rows]
            if not has_more:
                break
            page += 1
            # Save AFTER yielding, here and below, so a crash re-yields the last page rather than
            # skipping it — merge dedupes on the primary key.
            resumable_source_manager.save_state(CronitorResumeConfig(site_key=site_key, page=page))

        if index + 1 < len(remaining):
            resumable_source_manager.save_state(CronitorResumeConfig(site_key=remaining[index + 1], page=1))
        # Only the site resumed into starts mid-list; every later site starts at page one.
        page = 1


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
    # capture=False: raw monitor responses embed request cookies, bodies, and credential-bearing
    # URLs that only `_redact_monitor` strips (after sampling would have run), so keep them out of
    # HTTP sample capture entirely.
    session = make_tracked_session(capture=False)

    if endpoint in PAGINATED_LIST_ENDPOINTS:
        yield from _get_paginated_rows(session, api_key, logger, resumable_source_manager, endpoint)
    elif endpoint == "site_errors":
        yield from _get_site_error_rows(session, api_key, logger, resumable_source_manager)
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
        # capture=False for the same reason as the sync session: the probe returns a monitor whose
        # request config can carry credentials the generic sampler would not redact.
        response = make_tracked_session(capture=False).get(
            url, auth=(api_key, ""), headers={"Accept": "application/json"}, timeout=10
        )
    except Exception:
        return False, None
    return response.status_code == 200, response.status_code
