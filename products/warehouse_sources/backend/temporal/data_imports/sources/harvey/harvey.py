import dataclasses
from collections.abc import Iterator
from datetime import UTC, date, datetime, time
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.settings import (
    AUDIT_LOGS_PAGE_SIZE,
    HARVEY_BASE_URLS,
    HARVEY_ENDPOINTS,
    HISTORY_WINDOW_SECONDS,
    MAX_LOOKBACK_DAYS,
    VAULT_PROJECTS_PAGE_SIZE,
)

REQUEST_TIMEOUT_SECONDS = 60
MAX_RETRY_ATTEMPTS = 6

HISTORY_PATHS: dict[str, str] = {
    "usage_history": "/api/v2/history/usage",
    "query_history": "/api/v2/history/query",
}


class HarveyRetryableError(Exception):
    pass


@dataclasses.dataclass
class HarveyResumeConfig:
    # audit_logs: last processed log ID - pagination resumes from it (`from` is exclusive)
    last_audit_log_id: str | None = None
    # usage_history / query_history: epoch start of the next time window to fetch
    window_start: int | None = None
    # vault_projects: next page number to fetch
    next_page: int | None = None


def get_base_url(region: str | None) -> str:
    return HARVEY_BASE_URLS.get((region or "us").lower(), HARVEY_BASE_URLS["us"])


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _make_session(api_key: str) -> requests.Session:
    # `redact_values` masks the bearer token from any captured request samples or logged errors,
    # so the credential never leaks into warehouse job telemetry.
    return make_tracked_session(redact_values=(api_key,))


def validate_credentials(api_key: str, region: str | None) -> bool:
    url = f"{get_base_url(region)}/api/whoami"
    try:
        response = _make_session(api_key).get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _probe_url(base_url: str, endpoint: str) -> str:
    now = int(datetime.now(UTC).timestamp())
    if endpoint == "audit_logs":
        return f"{base_url}/api/v1/logs/audit/latest"
    if endpoint in HISTORY_PATHS:
        return f"{base_url}{HISTORY_PATHS[endpoint]}?{urlencode({'start_time': now - 3600, 'end_time': now})}"
    if endpoint == "vault_projects":
        return f"{base_url}/api/v1/vault/workspace/projects?{urlencode({'page': 1, 'per_page': 1})}"
    return f"{base_url}/api/v1/client_matters"


def check_endpoint_access(api_key: str, region: str | None, endpoint: str) -> str | None:
    """Return None when the token can reach the endpoint, or a short reason when it can't.

    Harvey API tokens carry a per-endpoint permissions list, so a valid token can still be
    denied on individual endpoints. Only a definitive denial (401/403) counts as missing
    access - throttles, 5xx, and network blips are treated as reachable.
    """
    url = _probe_url(get_base_url(region), endpoint)
    try:
        response = _make_session(api_key).get(url, headers=_get_headers(api_key), timeout=30)
    except Exception:
        return None
    if response.status_code in (401, 403):
        return "Your API token does not have permission for this endpoint. Enable it in the token's permissions list in Harvey workspace settings (Settings → API Tokens)."
    return None


@retry(
    retry=retry_if_exception_type(
        (
            HarveyRetryableError,
            requests.ReadTimeout,
            requests.ConnectionError,
            requests.exceptions.ChunkedEncodingError,
        )
    ),
    stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
    # Harvey's per-minute rate limit windows reset each minute, so back off past a full
    # window before giving up on a 429.
    wait=wait_exponential_jitter(initial=2, max=70),
    reraise=True,
)
def _fetch_json(session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger) -> Any:
    response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT_SECONDS)

    if response.status_code == 429 or response.status_code >= 500:
        raise HarveyRetryableError(f"Harvey API error (retryable): status={response.status_code}, url={url}")

    if not response.ok:
        # 404 is expected from the seed endpoints (no logs at/after the watermark) and is
        # handled by callers; anything else is a genuine failure.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Harvey API error: status={response.status_code}, body={response.text}, url={url}")
        response.raise_for_status()

    return response.json()


def _parse_datetime(value: Any) -> datetime | None:
    """Parse Harvey's timestamp strings (ISO 8601 or 'YYYY-MM-DD HH:MM:SS') as UTC."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _to_epoch(value: Any) -> int:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, time.min, tzinfo=UTC).timestamp())
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        parsed = _parse_datetime(value)
        if parsed is not None:
            return int(parsed.timestamp())
    raise ValueError(f"Cannot convert incremental field value to epoch: {value!r}")


def _lookback_floor_epoch(now_epoch: int) -> int:
    return now_epoch - MAX_LOOKBACK_DAYS * 24 * 60 * 60


def _normalize_audit_log(log: dict[str, Any]) -> dict[str, Any]:
    # Parse the ISO timestamp so the column lands as a real datetime (needed for the
    # incremental watermark and datetime partitioning). Nested `data` stays a dict - the
    # pipeline JSON-encodes nested objects.
    parsed = _parse_datetime(log.get("timestamp"))
    if parsed is not None:
        log["timestamp"] = parsed
    return log


def _normalize_history_event(event: dict[str, Any]) -> dict[str, Any]:
    parsed = _parse_datetime(event.get("utc_time"))
    if parsed is not None:
        event["utc_time"] = parsed
    return event


def _seed_audit_cursor(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    db_incremental_field_last_value: Any,
) -> dict[str, Any] | None:
    """Find the audit log to start paginating from, or None when there is nothing to sync.

    Incremental syncs seed via GET /logs/audit/search?time=<watermark epoch>, which returns
    the first log at or after that time. Full syncs (and watermarks older than the search
    endpoint's 1-year limit) start from GET /logs/audit/earliest - re-pulled rows are
    deduped on the `id` primary key at merge.
    """
    if db_incremental_field_last_value is not None:
        epoch = _to_epoch(db_incremental_field_last_value)
        now_epoch = int(datetime.now(UTC).timestamp())
        # A future watermark (bad source clock) would 400 - cap it at now.
        epoch = min(epoch, now_epoch)
        if epoch >= _lookback_floor_epoch(now_epoch):
            url = f"{base_url}/api/v1/logs/audit/search?{urlencode({'time': epoch})}"
            try:
                data = _fetch_json(session, url, headers, logger)
                return data.get("log")
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 404:
                    # No log at or after the watermark - fully caught up.
                    return None
                raise
        logger.debug("Harvey: incremental watermark is older than the 1-year search limit, restarting from earliest")

    url = f"{base_url}/api/v1/logs/audit/earliest"
    try:
        data = _fetch_json(session, url, headers, logger)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            # Workspace has no audit logs yet.
            return None
        raise
    return data.get("log")


def _get_audit_log_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HarveyResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None

    if resume is not None and resume.last_audit_log_id:
        from_id = resume.last_audit_log_id
        logger.debug(f"Harvey: resuming audit logs from id={from_id}")
    else:
        seed = _seed_audit_cursor(session, headers, base_url, logger, db_incremental_field_last_value)
        if seed is None:
            return
        # `from` is exclusive, so the seed log itself has to be yielded here.
        yield [_normalize_audit_log(dict(seed))]
        from_id = seed["id"]
        resumable_source_manager.save_state(HarveyResumeConfig(last_audit_log_id=from_id))

    while True:
        url = f"{base_url}/api/v1/logs/audit?{urlencode({'from': from_id, 'take': AUDIT_LOGS_PAGE_SIZE})}"
        logs = _fetch_json(session, url, headers, logger)
        if not logs:
            break

        yield [_normalize_audit_log(log) for log in logs]

        from_id = logs[-1]["id"]
        # Save AFTER yielding so a crash re-yields the last batch instead of skipping it -
        # audit logs are immutable and merge dedupes on the primary key.
        resumable_source_manager.save_state(HarveyResumeConfig(last_audit_log_id=from_id))

        if len(logs) < AUDIT_LOGS_PAGE_SIZE:
            break


def _get_history_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    path: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HarveyResumeConfig],
    db_incremental_field_last_value: Any,
) -> Iterator[list[dict[str, Any]]]:
    now_epoch = int(datetime.now(UTC).timestamp())
    floor = _lookback_floor_epoch(now_epoch)

    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start is not None:
        window_start = resume.window_start
        logger.debug(f"Harvey: resuming history export from window_start={window_start}")
    elif db_incremental_field_last_value is not None:
        # The API rejects start times older than 1 year, so clamp the watermark to the floor.
        window_start = max(_to_epoch(db_incremental_field_last_value), floor)
    else:
        window_start = floor

    while window_start < now_epoch:
        window_end = min(window_start + HISTORY_WINDOW_SECONDS, now_epoch)
        url = f"{base_url}{path}?{urlencode({'start_time': window_start, 'end_time': window_end})}"
        data = _fetch_json(session, url, headers, logger)

        events = data.get("events") or []
        if events:
            yield [_normalize_history_event(event) for event in events]

        # Save AFTER yielding; boundary events re-pulled by the next window are deduped on
        # `unique_usage_id` at merge.
        resumable_source_manager.save_state(HarveyResumeConfig(window_start=window_end))
        window_start = window_end


def _get_client_matter_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
) -> Iterator[list[dict[str, Any]]]:
    # Single unpaginated response containing every client matter (including deleted ones).
    matters = _fetch_json(session, f"{base_url}/api/v1/client_matters", headers, logger)
    if matters:
        yield matters


def _get_vault_project_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HarveyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page = resume.next_page if resume is not None and resume.next_page else 1

    while True:
        # Sort by name: the default `date` sort orders by content-update time, which
        # reshuffles rows mid-pagination as projects change.
        params = {"page": page, "per_page": VAULT_PROJECTS_PAGE_SIZE, "sort_by": "name", "sort_order": "asc"}
        url = f"{base_url}/api/v1/vault/workspace/projects?{urlencode(params)}"
        data = _fetch_json(session, url, headers, logger)

        content = (data.get("response") or {}).get("content") or {}
        projects = content.get("projects") or []
        if not projects:
            break

        yield projects

        pagination = content.get("pagination") or {}
        total_pages = pagination.get("total_pages")
        if total_pages is not None and page >= total_pages:
            break

        page += 1
        resumable_source_manager.save_state(HarveyResumeConfig(next_page=page))


def get_rows(
    api_key: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HarveyResumeConfig],
    db_incremental_field_last_value: Any = None,
) -> Iterator[list[dict[str, Any]]]:
    base_url = get_base_url(region)
    headers = _get_headers(api_key)
    # One session reused across every page so urllib3 keeps the connection alive.
    session = _make_session(api_key)

    if endpoint == "audit_logs":
        yield from _get_audit_log_rows(
            session, headers, base_url, logger, resumable_source_manager, db_incremental_field_last_value
        )
    elif endpoint in HISTORY_PATHS:
        yield from _get_history_rows(
            session,
            headers,
            base_url,
            HISTORY_PATHS[endpoint],
            logger,
            resumable_source_manager,
            db_incremental_field_last_value,
        )
    elif endpoint == "client_matters":
        yield from _get_client_matter_rows(session, headers, base_url, logger)
    elif endpoint == "vault_projects":
        yield from _get_vault_project_rows(session, headers, base_url, logger, resumable_source_manager)
    else:
        raise ValueError(f"Unknown Harvey endpoint: {endpoint}")


def harvey_source(
    api_key: str,
    region: str | None,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HarveyResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = HARVEY_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            api_key=api_key,
            region=region,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=db_incremental_field_last_value if should_use_incremental_field else None,
        ),
        primary_keys=endpoint_config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )
