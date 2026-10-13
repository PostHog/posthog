import json
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.instana.settings import (
    APPLICATION_METRICS,
    EVENTS_DEFAULT_LOOKBACK_DAYS,
    EVENTS_WINDOW_CHUNK_MS,
    INSTANA_ENDPOINTS,
    MAX_CATALOG_PAGES,
    MAX_CATALOG_WALK_SECONDS,
    METRICS_DEFAULT_LOOKBACK_DAYS,
    METRICS_MAX_LOOKBACK_DAYS,
    METRICS_WINDOW_MS,
    PAGE_SIZE,
    SNAPSHOTS_MAX_SIZE,
    InstanaEndpointConfig,
    InstanaFanOutConfig,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 5

# The base URL is customer-controlled, so a body must never be buffered unbounded: requests reads
# the whole response into memory by default, and the read timeout only guards idle gaps between
# reads, not a steady large (or gzip-expanded) transfer. Cap what we read into memory — generous
# for any real Instana page, anything past it is refused.
MAX_RESPONSE_BYTES = 256 * 1024 * 1024
RESPONSE_CHUNK_BYTES = 256 * 1024
# Error bodies are customer-controlled and can be as large as the response cap, so never
# interpolate the whole thing into a log event — log a small decoded preview plus the byte length.
ERROR_BODY_LOG_PREVIEW_BYTES = 8 * 1024
# Wall-clock budget for downloading one response body. The per-read timeout can't stop a host that
# dribbles the body slowly enough to stay under it while holding a shared worker open. 256 MiB in
# 300s is a ~0.85 MiB/s floor — far below any real API response, far above a slow-drip stall.
MAX_DOWNLOAD_SECONDS = 300

HOST_NOT_ALLOWED_ERROR = "Instana base URL is not allowed"
RESPONSE_TOO_LARGE_ERROR = "Instana response body was too large"
RESPONSE_TOO_SLOW_ERROR = "Instana response download was too slow"
PAGINATION_LIMIT_ERROR = "Instana catalog pagination exceeded the page limit"


class InstanaRetryableError(Exception):
    pass


class InstanaHostNotAllowedError(Exception):
    pass


class InstanaResponseTooLargeError(Exception):
    pass


class InstanaResponseTooSlowError(Exception):
    pass


class InstanaPaginationLimitError(Exception):
    pass


def _read_capped_body(response: requests.Response) -> bytes:
    """Stream the body into memory, aborting past MAX_RESPONSE_BYTES or MAX_DOWNLOAD_SECONDS.

    The host is customer-controlled, so a body must never be buffered unbounded (size cap) nor be
    allowed to hold the connection open indefinitely by dribbling under the per-read timeout (time
    cap). Both are non-retryable: re-fetching the same request yields the same oversized/slow body.
    """
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + MAX_DOWNLOAD_SECONDS
    try:
        for chunk in response.iter_content(chunk_size=RESPONSE_CHUNK_BYTES):
            if time.monotonic() > deadline:
                raise InstanaResponseTooSlowError(
                    f"{RESPONSE_TOO_SLOW_ERROR}: exceeded {MAX_DOWNLOAD_SECONDS}s download budget"
                )
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise InstanaResponseTooLargeError(f"{RESPONSE_TOO_LARGE_ERROR}: exceeded {MAX_RESPONSE_BYTES} bytes")
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks)


@frozen
class InstanaResumeConfig:
    # Next page to fetch for the page-paginated application-monitoring catalogs.
    next_page: int | None = None
    # Next `offset` to fetch for offset/limit-paginated endpoints. Instana counts it in pages.
    next_offset: int | None = None
    # Epoch-ms start of the next `/api/events` window chunk.
    events_window_from: int | None = None
    # Epoch-ms start of the metrics window being walked; `next_page` is the page within it.
    metrics_window_from: int | None = None


def normalize_base_url(url: str) -> str:
    """Reduce user input to a validated ``https://<host>`` Instana base URL.

    Accepts a SaaS tenant URL (``https://unit-tenant.instana.io``) or a self-hosted domain, with
    or without a scheme. Forcing https prevents a plaintext downgrade, and dropping any
    path/query/credentials means the API token is only ever sent to endpoint paths we build.
    """
    cleaned = url.strip()
    if not cleaned:
        raise ValueError("Instana base URL is required")
    if "://" not in cleaned:
        cleaned = f"https://{cleaned}"
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"Invalid Instana base URL: {url!r}. Enter it like 'https://unit-tenant.instana.io'.")
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://{parsed.hostname}{port}"


def _host_from_url(base_url: str) -> str:
    return (urlparse(normalize_base_url(base_url)).hostname or "").lower()


def _headers(api_token: str) -> dict[str, str]:
    return {"Authorization": f"apiToken {api_token}", "Accept": "application/json"}


def _to_epoch_ms(value: Any) -> int | None:
    """Coerce an incremental cursor to epoch milliseconds (Instana's native timestamp unit)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(aware.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _build_url(root: str, path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{root}{path}"
    return f"{root}{path}?{urlencode(params)}"


def _check_host(base_url: str, team_id: int) -> None:
    # The base URL is fully customer-controlled (self-hosted Instana is a supported target), so
    # block hosts that resolve to private/internal addresses (SSRF). Re-checked at run time, not
    # just source-create, to cover URL edits and DNS rebinding. Only enforced on cloud.
    host_ok, host_err = _is_host_safe(_host_from_url(base_url), team_id)
    if not host_ok:
        raise InstanaHostNotAllowedError(host_err or HOST_NOT_ALLOWED_ERROR)


def validate_credentials(base_url: str, api_token: str, team_id: int | None = None) -> tuple[bool, int | None]:
    """Probe ``/api/instana/version`` — the cheapest authenticated endpoint — to confirm the token.

    Returns ``(ok, status_code)``; ``status_code`` is ``None`` on a transport error. Raises
    ``ValueError`` on a malformed base URL and ``InstanaHostNotAllowedError`` on a blocked host so
    the caller can surface precise messages.
    """
    root = normalize_base_url(base_url)
    if team_id is not None:
        _check_host(base_url, team_id)
    url = _build_url(root, "/api/instana/version", {})
    try:
        # stream=True so a customer-controlled host can't force us to buffer an unbounded probe
        # body; we only need the status, so read nothing and close immediately.
        response = make_tracked_session(allow_redirects=False, redact_values=(api_token,)).get(
            url, headers=_headers(api_token), timeout=10, stream=True
        )
    except requests.exceptions.RequestException:
        return False, None
    try:
        return response.status_code == 200, response.status_code
    finally:
        response.close()


def _fetch(
    session: requests.Session,
    url: str,
    logger: FilteringBoundLogger,
    json_body: Any = None,
) -> Any:
    @retry(
        retry=retry_if_exception_type((InstanaRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch_once() -> Any:
        # stream=True so the body isn't buffered until we cap it — see _read_capped_body.
        if json_body is None:
            response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)
        else:
            response = session.post(url, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS, stream=True)

        # Instana rate-limits to 5000 calls/hour and answers excess with 429; transient 5xx are
        # retryable too. Back off and retry rather than failing the sync.
        if response.status_code == 429 or response.status_code >= 500:
            response.close()
            raise InstanaRetryableError(f"Instana API error (retryable): status={response.status_code}, url={url}")

        body = _read_capped_body(response)

        if not response.ok:
            preview = body[:ERROR_BODY_LOG_PREVIEW_BYTES].decode(errors="replace")
            logger.error(
                f"Instana API error: status={response.status_code}, body_bytes={len(body)}, "
                f"body_preview={preview}, url={url}"
            )
            response.raise_for_status()

        return json.loads(body or b"null")

    return fetch_once()


def _extract_items(response_json: Any, config: InstanaEndpointConfig) -> list[dict[str, Any]]:
    if config.data_path is None:
        return response_json if isinstance(response_json, list) else []
    if isinstance(response_json, dict):
        items = response_json.get(config.data_path, [])
        return items if isinstance(items, list) else []
    return []


def _get_event_rows(
    session: requests.Session,
    root: str,
    config: InstanaEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InstanaResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Chunk `/api/events` into ascending from/to windows and yield each chunk's events.

    The endpoint has no pagination — the window bounds the response — so wide ranges are walked in
    fixed chunks. Chunk boundaries are inclusive on both requests, and an incremental run restarts
    exactly at the watermark, so boundary events are re-fetched and merge dedupes them on
    `eventId`. Ongoing events that started before the window are returned in every chunk they are
    active in; the merge refreshes their mutable `state`/`end` fields.
    """
    now_ms = int(datetime.now(UTC).timestamp() * 1000)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    watermark = _to_epoch_ms(db_incremental_field_last_value) if should_use_incremental_field else None
    if resume is not None and resume.events_window_from is not None:
        window_from = resume.events_window_from
        logger.debug(f"Instana: resuming events from window_from={window_from}")
    elif watermark is not None:
        # A future-dated watermark (bad clock upstream) would build an empty forward window every
        # run; clamping to now keeps the sync self-healing.
        window_from = min(watermark, now_ms)
    else:
        window_from = now_ms - EVENTS_DEFAULT_LOOKBACK_DAYS * 24 * 60 * 60 * 1000

    while window_from < now_ms:
        window_to = min(window_from + EVENTS_WINDOW_CHUNK_MS, now_ms)
        url = _build_url(root, config.path, {"from": window_from, "to": window_to})
        items = _extract_items(_fetch(session, url, logger), config)

        if items:
            yield items

        if window_to >= now_ms:
            break
        # Save AFTER yielding, and only while more windows remain, so a crash re-fetches the last
        # chunk rather than skipping it — merge dedupes on the primary key.
        resumable_source_manager.save_state(InstanaResumeConfig(events_window_from=window_to))
        window_from = window_to


def _check_walk_bounds(config: InstanaEndpointConfig, walk_deadline: float, pages_walked: int) -> None:
    # A self-hosted host can return a full page forever while never signalling the end, so the
    # termination conditions never trip; bound the walk so the loop (and its ingestion) can't run
    # for the whole activity. Both bounds are non-retryable — the same host replays the same loop.
    # The wall-clock budget is the effective bound: a slow host can stay under the page cap while
    # streaming each page for MAX_DOWNLOAD_SECONDS, so pages alone wouldn't cap worker time.
    if time.monotonic() > walk_deadline:
        raise InstanaPaginationLimitError(
            f"{PAGINATION_LIMIT_ERROR}: exceeded {MAX_CATALOG_WALK_SECONDS}s walk budget for {config.name}"
        )
    if pages_walked >= MAX_CATALOG_PAGES:
        raise InstanaPaginationLimitError(
            f"{PAGINATION_LIMIT_ERROR}: stopped after {MAX_CATALOG_PAGES} pages for {config.name}"
        )


def _get_paged_rows(
    session: requests.Session,
    root: str,
    config: InstanaEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InstanaResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk a page/pageSize-paginated application-monitoring catalog.

    The OpenAPI spec doesn't document the first page index, so the first request omits `page` and
    the server's default page is read back from the response body (ApplicationResult et al. echo
    `page`), making the walk correct for either indexing base.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume is not None else None
    if page is not None:
        logger.debug(f"Instana: resuming {config.name} from page={page}")

    fetched = 0
    pages_walked = 0
    walk_deadline = time.monotonic() + MAX_CATALOG_WALK_SECONDS
    while True:
        _check_walk_bounds(config, walk_deadline, pages_walked)
        params: dict[str, Any] = {"pageSize": PAGE_SIZE}
        if page is not None:
            params["page"] = page
        url = _build_url(root, config.path, params)
        data = _fetch(session, url, logger)
        pages_walked += 1

        items = _extract_items(data, config)
        if not items:
            break

        yield items
        fetched += len(items)

        current_page = data.get("page") if isinstance(data, dict) else None
        total_hits = data.get("totalHits") if isinstance(data, dict) else None
        if len(items) < PAGE_SIZE:
            break
        if isinstance(total_hits, int) and fetched >= total_hits:
            break

        next_page = (current_page if isinstance(current_page, int) else page or 1) + 1
        resumable_source_manager.save_state(InstanaResumeConfig(next_page=next_page))
        page = next_page


def _get_offset_rows(
    session: requests.Session,
    root: str,
    config: InstanaEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InstanaResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk an offset/limit-paginated list (synthetic CI/CD runs) until a short page.

    Instana's `offset` is the number of pages of `limit` items to skip, not an item count.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.next_offset if resume is not None and resume.next_offset is not None else 0
    if offset:
        logger.debug(f"Instana: resuming {config.name} from offset={offset}")

    pages_walked = 0
    walk_deadline = time.monotonic() + MAX_CATALOG_WALK_SECONDS
    while True:
        _check_walk_bounds(config, walk_deadline, pages_walked)
        url = _build_url(root, config.path, {"offset": offset, "limit": PAGE_SIZE})
        items = _extract_items(_fetch(session, url, logger), config)
        pages_walked += 1

        if not items:
            break

        yield items

        if len(items) < PAGE_SIZE:
            break

        offset += 1
        resumable_source_manager.save_state(InstanaResumeConfig(next_offset=offset))


def _metric_rows(item: dict[str, Any], entity_key: str) -> list[dict[str, Any]]:
    """Pivot one metrics item into a row per timestamp, one column per metric.

    Instana returns each metric as ``{"latency.mean": [[timestamp, value], ...]}``; the dot in the
    key becomes an underscore so every metric is a plain column.
    """
    entity = item.get(entity_key)
    metrics = item.get("metrics")
    if not isinstance(entity, dict) or not isinstance(metrics, dict):
        return []
    entity_id = entity.get("id")
    if not isinstance(entity_id, str) or not entity_id:
        return []

    rows: dict[int, dict[str, Any]] = {}
    for metric_name, points in metrics.items():
        if not isinstance(points, list):
            continue
        for point in points:
            if not isinstance(point, list) or len(point) != 2 or not isinstance(point[0], int | float):
                continue
            timestamp = int(point[0])
            row = rows.setdefault(timestamp, {f"{entity_key}Id": entity_id, entity_key: entity, "timestamp": timestamp})
            row[metric_name.replace(".", "_")] = point[1]
    return list(rows.values())


def _floor_to_window(epoch_ms: int) -> int:
    return epoch_ms - epoch_ms % METRICS_WINDOW_MS


def _get_metric_rows(
    session: requests.Session,
    root: str,
    config: InstanaEndpointConfig,
    entity_key: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InstanaResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Walk the daily golden-signal metrics for every application, service or endpoint.

    Each one-day window is one POST query, paginated by entity. A window holds a single bucket,
    so the incremental watermark is the bucket timestamp. The spec does not say whether that
    timestamp marks the start or the end of the bucket, so an incremental run restarts one window
    before the watermark's window. That re-fetches at most one extra day, and merge dedupes it.
    """
    end = _floor_to_window(int(datetime.now(UTC).timestamp() * 1000))

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    watermark = _to_epoch_ms(db_incremental_field_last_value) if should_use_incremental_field else None
    page = 1
    if resume is not None and resume.metrics_window_from is not None:
        window_from = resume.metrics_window_from
        page = resume.next_page or 1
        logger.debug(f"Instana: resuming {config.name} from window_from={window_from}, page={page}")
    elif watermark is not None:
        window_from = max(
            _floor_to_window(min(watermark, end) - METRICS_WINDOW_MS),
            end - METRICS_MAX_LOOKBACK_DAYS * METRICS_WINDOW_MS,
        )
    else:
        window_from = end - METRICS_DEFAULT_LOOKBACK_DAYS * METRICS_WINDOW_MS

    url = _build_url(root, config.path, {})
    granularity_seconds = METRICS_WINDOW_MS // 1000
    while window_from < end:
        window_to = window_from + METRICS_WINDOW_MS
        fetched = 0
        pages_walked = 0
        walk_deadline = time.monotonic() + MAX_CATALOG_WALK_SECONDS
        while True:
            _check_walk_bounds(config, walk_deadline, pages_walked)
            body = {
                "metrics": [{**metric, "granularity": granularity_seconds} for metric in APPLICATION_METRICS],
                "timeFrame": {"to": window_to, "windowSize": METRICS_WINDOW_MS},
                "pagination": {"page": page, "pageSize": PAGE_SIZE},
            }
            data = _fetch(session, url, logger, json_body=body)
            pages_walked += 1

            items = _extract_items(data, config)
            rows = [row for item in items if isinstance(item, dict) for row in _metric_rows(item, entity_key)]
            if rows:
                yield rows
            fetched += len(items)

            total_hits = data.get("totalHits") if isinstance(data, dict) else None
            if len(items) < PAGE_SIZE or (isinstance(total_hits, int) and fetched >= total_hits):
                break
            page += 1
            resumable_source_manager.save_state(InstanaResumeConfig(metrics_window_from=window_from, next_page=page))
            if not rows:
                resumable_source_manager.safe_point()

        page = 1
        window_from = window_to
        if window_from < end:
            resumable_source_manager.save_state(InstanaResumeConfig(metrics_window_from=window_from, next_page=1))


def _get_fan_out_rows(
    session: requests.Session,
    root: str,
    config: InstanaEndpointConfig,
    fan_out: InstanaFanOutConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InstanaResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Walk the parent catalog and fetch one child resource per parent row.

    Each child response is yielded on its own, so memory stays bounded by one response rather
    than one parent page of them. Resume state is the parent walk's page, which the parent walk
    saves only after all of that page's children are yielded, so a resumed run re-fetches the
    children of at most one parent page.
    """
    parent_config = INSTANA_ENDPOINTS[fan_out.parent]
    if parent_config.pagination == "page":
        parent_pages = _get_paged_rows(session, root, parent_config, logger, resumable_source_manager)
    else:
        parent_pages = _get_list_rows(session, root, parent_config, logger)

    # The parent walk checks its bounds only between parent pages, so the child requests of one
    # page need their own: one page holds up to PAGE_SIZE slow or retried child requests.
    window_params: dict[str, Any] = {}
    if config.report_window_ms is not None:
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        window_params = {"from": now_ms - config.report_window_ms, "to": now_ms}

    children_fetched = 0
    walk_deadline = time.monotonic() + MAX_CATALOG_WALK_SECONDS
    for parent_rows in parent_pages:
        yielded_any = False
        for parent_row in parent_rows:
            parent_id = parent_row.get(fan_out.parent_field)
            if not isinstance(parent_id, str) or not parent_id:
                continue
            _check_walk_bounds(config, walk_deadline, children_fetched)
            children_fetched += 1
            path = config.path.format(**{fan_out.child_field: quote(parent_id, safe="")})
            url = _build_url(root, path, window_params)
            try:
                data = _fetch(session, url, logger)
            except requests.HTTPError as e:
                # The parent can be deleted between listing it and fetching its child.
                if e.response is not None and e.response.status_code == 404:
                    logger.debug(f"Instana: {config.name} not found for {fan_out.child_field}={parent_id}, skipping")
                    continue
                raise
            records = data if isinstance(data, list) else [data]
            child_rows = [{**record, fan_out.child_field: parent_id} for record in records if isinstance(record, dict)]
            if child_rows:
                yielded_any = True
                yield child_rows
        if not yielded_any:
            resumable_source_manager.safe_point()


def _get_list_rows(
    session: requests.Session,
    root: str,
    config: InstanaEndpointConfig,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    """Fetch a single-shot list endpoint (websites, alerting settings, snapshots, releases, ...)."""
    url = _build_url(root, config.path, dict(config.extra_params))
    items = _extract_items(_fetch(session, url, logger), config)
    if config.name == "infrastructure_snapshots" and len(items) >= SNAPSHOTS_MAX_SIZE:
        logger.warning(
            f"Instana: infrastructure_snapshots returned {len(items)} items, hitting the size cap "
            f"({SNAPSHOTS_MAX_SIZE}) — the inventory may be truncated"
        )
    if items:
        yield items


def get_rows(
    base_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InstanaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = INSTANA_ENDPOINTS[endpoint]
    root = normalize_base_url(base_url)
    _check_host(base_url, team_id)

    # One tracked session reused across every request; the token is redacted from logged URLs and
    # captured samples, and redirects are never followed (SSRF boundary for user-supplied hosts).
    session = make_tracked_session(headers=_headers(api_token), redact_values=(api_token,), allow_redirects=False)

    if config.is_events:
        yield from _get_event_rows(
            session,
            root,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.metrics_entity is not None:
        yield from _get_metric_rows(
            session,
            root,
            config,
            config.metrics_entity,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.fan_out is not None:
        yield from _get_fan_out_rows(session, root, config, config.fan_out, logger, resumable_source_manager)
    elif config.pagination == "page":
        yield from _get_paged_rows(session, root, config, logger, resumable_source_manager)
    elif config.pagination == "offset":
        yield from _get_offset_rows(session, root, config, logger, resumable_source_manager)
    else:
        yield from _get_list_rows(session, root, config, logger)


def instana_source(
    base_url: str,
    api_token: str,
    endpoint: str,
    team_id: int,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[InstanaResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = INSTANA_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            base_url=base_url,
            api_token=api_token,
            endpoint=endpoint,
            team_id=team_id,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Event and metrics windows ascend, so batches arrive in (window-level) ascending order; the
        # catalog endpoints are full refresh where the watermark is unused.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        # Instana timestamps are epoch-ms integers rather than ISO datetimes, so there is no safe
        # datetime partition key — tables are left unpartitioned.
    )
