import time
import dataclasses
from collections import deque
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
from products.warehouse_sources.backend.temporal.data_imports.sources.sumo_logic.settings import (
    DEFAULT_LOGS_LOOKBACK_DAYS,
    SUMO_LOGIC_ENDPOINTS,
    SumoLogicEndpointConfig,
)

# Sumo Logic deployments. The deployment selects which regional API host the credentials are sent
# to; the set is a fixed allow-list, so the host can't be retargeted at an arbitrary server.
SUMO_LOGIC_DEPLOYMENTS = ("us1", "us2", "au", "ca", "de", "eu", "fed", "in", "jp", "kr")
DEFAULT_DEPLOYMENT = "us1"

REQUEST_TIMEOUT_SECONDS = 60
# Sumo Logic rate-limits at ~4 requests/second per access key (429 when exceeded); retries back off
# exponentially rather than hammering the window.
RETRY_ATTEMPTS = 5

# Search Job API tuning. Jobs run over bounded time windows; a window whose job hits the per-job
# message cap is split in half and re-run so no messages are silently dropped.
SEARCH_JOB_POLL_INTERVAL_SECONDS = 5
SEARCH_JOB_MAX_WAIT_SECONDS = 1800
SEARCH_JOB_MAX_MESSAGES = 100_000
SEARCH_JOB_INITIAL_WINDOW = timedelta(hours=24)
SEARCH_JOB_MIN_WINDOW = timedelta(minutes=1)
DEFAULT_SEARCH_QUERY = "*"


class SumoLogicRetryableError(Exception):
    pass


@dataclasses.dataclass
class SumoLogicResumeConfig:
    # Continuation token for token-paginated management endpoints.
    token: str | None = None
    # Row offset for offset-paginated management endpoints (also the collectors offset during the
    # collector_sources fan-out).
    offset: int | None = None
    # Start (epoch millis) of the next unprocessed search-job window for the logs endpoint.
    log_window_start_ms: int | None = None


def base_url(deployment: Optional[str]) -> str:
    resolved = deployment or DEFAULT_DEPLOYMENT
    if resolved not in SUMO_LOGIC_DEPLOYMENTS:
        resolved = DEFAULT_DEPLOYMENT
    if resolved == "us1":
        return "https://api.sumologic.com/api"
    return f"https://api.{resolved}.sumologic.com/api"


def _make_session(access_id: str, access_key: str) -> requests.Session:
    # One session for the whole run: Sumo Logic issues a session cookie on search-job creation that
    # must accompany the poll/fetch/delete calls, and `requests.Session` persists it automatically.
    # `capture=False`: raw log bodies (`_raw`) are free-form customer data that can embed credentials
    # the name-based sample scrubbers can't recognise, so keep response bodies out of HTTP sample
    # storage entirely. Requests are still metered and logged (status + url).
    session = make_tracked_session(redact_values=(access_key,), capture=False)
    session.auth = (access_id, access_key)
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    return session


def _to_epoch_ms(value: Any) -> int:
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return int(dt.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, int | float):
        return int(value)
    return int(datetime.fromisoformat(str(value)).replace(tzinfo=UTC).timestamp() * 1000)


def validate_credentials(deployment: Optional[str], access_id: str, access_key: str) -> tuple[bool, str | None]:
    """Validate Sumo Logic credentials with a single cheap probe.

    Every Sumo Logic endpoint is gated by a role capability, so a 403 means the key pair is genuine
    but this key lacks the probed capability — that must not block source creation (missing
    capabilities on selected tables surface at sync time via ``get_non_retryable_errors``). Only a
    401 proves the access ID / access key pair itself is invalid.
    """
    url = f"{base_url(deployment)}/v1/collectors?limit=1"
    try:
        session = _make_session(access_id, access_key)
        response = session.get(url, timeout=10)
        if response.status_code in (200, 403):
            return True, None
        if response.status_code == 401:
            return False, "Invalid Sumo Logic access ID or access key. Check the credentials and deployment region."
        return False, f"Sumo Logic credential validation failed (status {response.status_code})."
    except requests.exceptions.RequestException as e:
        return False, str(e)


def _make_fetch(session: requests.Session, logger: FilteringBoundLogger) -> Any:
    @retry(
        retry=retry_if_exception_type((SumoLogicRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_exponential_jitter(initial=1, max=30),
        reraise=True,
    )
    def fetch(method: str, url: str, json_body: dict[str, Any] | None = None) -> Any:
        response = session.request(method, url, json=json_body, timeout=REQUEST_TIMEOUT_SECONDS)

        if response.status_code == 429 or response.status_code >= 500:
            raise SumoLogicRetryableError(f"Sumo Logic API error (retryable): status={response.status_code}, url={url}")

        if not response.ok:
            logger.error(f"Sumo Logic API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    return fetch


def _build_url(host: str, path: str, params: dict[str, Any]) -> str:
    url = f"{host}{path}"
    if not params:
        return url
    return f"{url}?{urlencode(params)}"


def _extract_items(response_json: Any, config: SumoLogicEndpointConfig) -> list[dict[str, Any]]:
    if config.data_key is None:
        return response_json if isinstance(response_json, list) else []
    if isinstance(response_json, dict):
        items = response_json.get(config.data_key, [])
        return items if isinstance(items, list) else []
    return []


def _redact_nested(value: Any, redact_fields: frozenset[str]) -> Any:
    """Drop credential-bearing keys wherever they appear in a nested record (any depth).

    Monitor notifications embed destination secrets in ``payloadOverride`` /
    ``resolutionPayloadOverride`` below the top level, so a shallow key filter can't reach them.
    """
    if isinstance(value, dict):
        return {key: _redact_nested(val, redact_fields) for key, val in value.items() if key not in redact_fields}
    if isinstance(value, list):
        return [_redact_nested(item, redact_fields) for item in value]
    return value


def _redact_row(row: dict[str, Any], config: SumoLogicEndpointConfig) -> dict[str, Any]:
    """Drop credential-bearing keys from a record before it reaches the warehouse."""
    if config.redact_fields:
        row = {key: value for key, value in row.items() if key not in config.redact_fields}
    if config.redact_nested_fields:
        row = _redact_nested(row, config.redact_nested_fields)
    return row


def _unnest_item(item: dict[str, Any], config: SumoLogicEndpointConfig) -> dict[str, Any]:
    """Lift a nested record (e.g. monitors search's ``item``) to the root, keeping sibling keys."""
    if config.nest_key is None:
        return item
    nested = item.get(config.nest_key)
    if not isinstance(nested, dict):
        return item
    row = dict(nested)
    for key, value in item.items():
        if key != config.nest_key:
            row.setdefault(key, value)
    return row


def _get_token_paginated_rows(
    fetch: Any,
    host: str,
    config: SumoLogicEndpointConfig,
    resumable_source_manager: ResumableSourceManager[SumoLogicResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    token = resume.token if resume else None

    while True:
        params: dict[str, Any] = {"limit": config.page_size, **config.extra_params}
        if token:
            params["token"] = token

        data = fetch("GET", _build_url(host, config.path, params))
        items = _extract_items(data, config)
        next_token = data.get("next") if isinstance(data, dict) else None

        if items:
            yield [_unnest_item(item, config) for item in items]

        if not next_token:
            break
        # Save AFTER yielding the batch — a crash re-yields the last page (merge dedupes on the
        # primary key) instead of skipping it.
        resumable_source_manager.save_state(SumoLogicResumeConfig(token=next_token))
        token = next_token


def _get_offset_paginated_rows(
    fetch: Any,
    host: str,
    config: SumoLogicEndpointConfig,
    resumable_source_manager: ResumableSourceManager[SumoLogicResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume and resume.offset is not None else 0

    while True:
        params: dict[str, Any] = {"limit": config.page_size, "offset": offset, **config.extra_params}
        data = fetch("GET", _build_url(host, config.path, params))
        items = _extract_items(data, config)

        if items:
            yield [_unnest_item(item, config) for item in items]

        if len(items) < config.page_size:
            break
        offset += config.page_size
        resumable_source_manager.save_state(SumoLogicResumeConfig(offset=offset))


def _get_collector_fan_out_rows(
    fetch: Any,
    host: str,
    config: SumoLogicEndpointConfig,
    resumable_source_manager: ResumableSourceManager[SumoLogicResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    """Fan out over every collector, fetching this endpoint once per collector.

    Resume state tracks the collectors-list offset: a crash re-fetches the current collectors page
    and its children (merge dedupes on the composite primary key) rather than restarting the scan.
    """
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    offset = resume.offset if resume and resume.offset is not None else 0
    collectors_config = SUMO_LOGIC_ENDPOINTS["collectors"]

    while True:
        params: dict[str, Any] = {"limit": collectors_config.page_size, "offset": offset}
        data = fetch("GET", _build_url(host, collectors_config.path, params))
        collectors = _extract_items(data, collectors_config)

        rows: list[dict[str, Any]] = []
        for collector in collectors:
            collector_id = collector.get("id")
            if collector_id is None:
                continue
            child_path = config.path.format(collector_id=collector_id)
            child_data = fetch("GET", _build_url(host, child_path, dict(config.extra_params)))
            for item in _extract_items(child_data, config):
                rows.append({**item, "collector_id": collector_id})

        if rows:
            yield rows

        if len(collectors) < collectors_config.page_size:
            break
        offset += collectors_config.page_size
        resumable_source_manager.save_state(SumoLogicResumeConfig(offset=offset))


def _message_row(message: dict[str, Any]) -> dict[str, Any]:
    """Flatten a Search Job message's ``map`` and derive a typed ``message_time`` datetime."""
    row = dict(message.get("map", {}))
    raw_time = row.get("_messagetime")
    try:
        row["message_time"] = datetime.fromtimestamp(int(raw_time) / 1000, tz=UTC) if raw_time is not None else None
    except (TypeError, ValueError):
        row["message_time"] = None
    return row


def _delete_search_job(fetch: Any, host: str, job_id: str, logger: FilteringBoundLogger) -> None:
    # Best-effort cleanup; jobs also expire server-side, but the org caps concurrent search jobs.
    try:
        fetch("DELETE", f"{host}/v1/search/jobs/{job_id}")
    except Exception:
        logger.warning(f"Sumo Logic: failed to delete search job {job_id}")


def _submit_and_poll_search_job(
    fetch: Any,
    host: str,
    query: str,
    start_ms: int,
    end_ms: int,
    logger: FilteringBoundLogger,
) -> tuple[str, int]:
    """Submit a search job for [start_ms, end_ms) and poll it to completion.

    Returns ``(job_id, message_count)``; the caller decides whether to fetch the messages or split
    the window when the job hit the per-job message cap."""
    job = fetch(
        "POST",
        f"{host}/v1/search/jobs",
        json_body={"query": query, "from": start_ms, "to": end_ms, "timeZone": "UTC"},
    )
    job_id = str(job["id"])
    job_url = f"{host}/v1/search/jobs/{job_id}"

    deadline = time.monotonic() + SEARCH_JOB_MAX_WAIT_SECONDS
    while True:
        status = fetch("GET", job_url)
        state = status.get("state")
        if state == "DONE GATHERING RESULTS":
            return job_id, int(status.get("messageCount", 0))
        if state == "CANCELLED":
            raise ValueError(f"Sumo Logic search job {job_id} was cancelled")
        if time.monotonic() > deadline:
            _delete_search_job(fetch, host, job_id, logger)
            raise SumoLogicRetryableError(
                f"Sumo Logic search job {job_id} did not complete within {SEARCH_JOB_MAX_WAIT_SECONDS}s"
            )
        time.sleep(SEARCH_JOB_POLL_INTERVAL_SECONDS)


def _fetch_search_job_messages(
    fetch: Any, host: str, job_id: str, message_count: int, page_size: int
) -> Iterator[list[dict[str, Any]]]:
    offset = 0
    while offset < message_count:
        data = fetch(
            "GET",
            _build_url(host, f"/v1/search/jobs/{job_id}/messages", {"offset": offset, "limit": page_size}),
        )
        messages = data.get("messages", []) if isinstance(data, dict) else []
        if not messages:
            break
        yield [_message_row(message) for message in messages]
        offset += len(messages)


def _get_log_rows(
    fetch: Any,
    host: str,
    query: str,
    config: SumoLogicEndpointConfig,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SumoLogicResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    """Export logs via the async Search Job API over bounded time windows.

    Windows run chronologically from the incremental watermark (or the default lookback) to the
    stream's start time. A window whose job hits the per-job message cap is split in half and
    re-run, so no messages are silently dropped. Resume state advances one whole window at a time —
    a crash mid-window re-runs that window and merge dedupes the re-yielded rows.
    """
    end_ms = int(datetime.now(UTC).timestamp() * 1000)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.log_window_start_ms is not None:
        start_ms = resume.log_window_start_ms
        logger.debug(f"Sumo Logic: resuming logs from window start {start_ms}")
    elif should_use_incremental_field and db_incremental_field_last_value is not None:
        start_ms = _to_epoch_ms(db_incremental_field_last_value)
    else:
        start_ms = end_ms - int(timedelta(days=DEFAULT_LOGS_LOOKBACK_DAYS).total_seconds() * 1000)

    if start_ms >= end_ms:
        return

    window_ms = int(SEARCH_JOB_INITIAL_WINDOW.total_seconds() * 1000)
    min_window_ms = int(SEARCH_JOB_MIN_WINDOW.total_seconds() * 1000)
    pending: deque[tuple[int, int]] = deque()
    cursor = start_ms
    while cursor < end_ms:
        pending.append((cursor, min(cursor + window_ms, end_ms)))
        cursor += window_ms

    while pending:
        window_start, window_end = pending.popleft()
        job_id, message_count = _submit_and_poll_search_job(fetch, host, query, window_start, window_end, logger)

        if message_count >= SEARCH_JOB_MAX_MESSAGES and (window_end - window_start) > min_window_ms:
            _delete_search_job(fetch, host, job_id, logger)
            middle = window_start + (window_end - window_start) // 2
            pending.appendleft((middle, window_end))
            pending.appendleft((window_start, middle))
            logger.debug(
                f"Sumo Logic: window {window_start}-{window_end} hit the {SEARCH_JOB_MAX_MESSAGES} message cap, splitting"
            )
            continue

        if message_count >= SEARCH_JOB_MAX_MESSAGES:
            logger.warning(
                f"Sumo Logic: window {window_start}-{window_end} is already at the minimum size but "
                f"still reports {message_count} messages; results beyond the cap are truncated"
            )

        try:
            yield from _fetch_search_job_messages(fetch, host, job_id, message_count, config.page_size)
        finally:
            _delete_search_job(fetch, host, job_id, logger)

        if pending:
            # Save AFTER the window's rows are yielded so a crash re-runs this window instead of
            # skipping it; merge dedupes the re-yielded rows on the primary key.
            resumable_source_manager.save_state(SumoLogicResumeConfig(log_window_start_ms=window_end))


def get_rows(
    deployment: Optional[str],
    access_id: str,
    access_key: str,
    endpoint: str,
    search_query: Optional[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SumoLogicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    config = SUMO_LOGIC_ENDPOINTS[endpoint]
    host = base_url(deployment)
    session = _make_session(access_id, access_key)
    fetch = _make_fetch(session, logger)

    if config.pagination == "search_job":
        query = (search_query or "").strip() or DEFAULT_SEARCH_QUERY
        batches = _get_log_rows(
            fetch,
            host,
            query,
            config,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    elif config.fan_out_over_collectors:
        batches = _get_collector_fan_out_rows(fetch, host, config, resumable_source_manager)
    elif config.pagination == "offset":
        batches = _get_offset_paginated_rows(fetch, host, config, resumable_source_manager)
    else:
        batches = _get_token_paginated_rows(fetch, host, config, resumable_source_manager)

    if config.redact_fields or config.redact_nested_fields:
        for batch in batches:
            yield [_redact_row(row, config) for row in batch]
    else:
        yield from batches


def sumo_logic_source(
    deployment: Optional[str],
    access_id: str,
    access_key: str,
    endpoint: str,
    search_query: Optional[str],
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[SumoLogicResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SUMO_LOGIC_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            deployment=deployment,
            access_id=access_id,
            access_key=access_key,
            endpoint=endpoint,
            search_query=search_query,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=config.primary_keys,
        # Search Job messages come back newest-first within each window, so the logs stream isn't
        # globally ascending; "desc" makes the pipeline persist the incremental watermark only when
        # the whole run succeeds. Management endpoints are full refresh, where sort mode is moot.
        sort_mode="desc" if config.pagination == "search_job" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
