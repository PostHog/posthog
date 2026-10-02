from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime, time
from email.utils import parsedate_to_datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode

import requests
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.harvey.settings import (
    AUDIT_LOGS_PAGE_SIZE,
    HARVEY_BASE_URLS,
    HARVEY_ENDPOINTS,
    HISTORY_WINDOW_SECONDS,
    MAX_LOOKBACK_DAYS,
    VAULT_PROJECT_FILES_PAGE_SIZE,
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


@frozen
class HarveyResumeConfig:
    # audit_logs: last processed log ID - pagination resumes from it (`from` is exclusive)
    last_audit_log_id: str | None = None
    # usage_history / query_history: epoch start of the next time window to fetch
    window_start: int | None = None
    # vault_projects and the per-project fan-out endpoints: next projects page number to fetch
    next_page: int | None = None


def get_base_url(region: str | None) -> str:
    return HARVEY_BASE_URLS.get((region or "us").lower(), HARVEY_BASE_URLS["us"])


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _make_session(api_key: str, capture: bool = True) -> requests.Session:
    # `redact_values` masks the bearer token from any captured request samples or logged errors,
    # so the credential never leaks into warehouse job telemetry. `capture=False` additionally
    # excludes the response body from HTTP sample capture, for endpoints whose bodies carry
    # arbitrary user content the name-based scrubbers can't recognise.
    return make_tracked_session(redact_values=(api_key,), capture=capture)


def _endpoint_captures_samples(endpoint: str) -> bool:
    # Default off for anything unmapped - capture is opt-in per endpoint.
    config = HARVEY_ENDPOINTS.get(endpoint)
    return config.capture_http_samples if config is not None else False


def validate_credentials(api_key: str, region: str | None) -> bool:
    url = f"{get_base_url(region)}/api/whoami"
    try:
        response = _make_session(api_key).get(url, headers=_get_headers(api_key), timeout=10)
        return response.status_code == 200
    except Exception:
        return False


def _path_id(value: Any) -> str:
    return quote(str(value), safe="")


def _vault_projects_url(base_url: str, page: int, per_page: int) -> str:
    # Sort by name: the default `date` sort orders by content-update time, which
    # reshuffles rows mid-pagination as projects change.
    params = {"page": page, "per_page": per_page, "sort_by": "name", "sort_order": "asc"}
    return f"{base_url}/api/v1/vault/workspace/projects?{urlencode(params)}"


def _project_users_url(base_url: str, project_id: Any) -> str:
    return f"{base_url}/api/v1/vault/projects/{_path_id(project_id)}/users"


def _project_files_url(base_url: str, project_id: Any, cursor: str | None, limit: int) -> str:
    params: dict[str, Any] = {"limit": limit, "sort_by": "uploaded_at", "sort_order": "asc"}
    if cursor:
        params["cursor"] = cursor
    return f"{base_url}/api/v1/vault/projects/{_path_id(project_id)}/files?{urlencode(params)}"


def _project_metadata_url(base_url: str, project_id: Any) -> str:
    return f"{base_url}/api/v1/vault/get_metadata/{_path_id(project_id)}"


# Probes for the per-project fan-out endpoints, given one project ID to test against.
FAN_OUT_PROBE_URLS: dict[str, Callable[[str, Any], str]] = {
    "vault_project_users": _project_users_url,
    "vault_project_files": lambda base_url, project_id: _project_files_url(base_url, project_id, None, 1),
    "review_tables": _project_metadata_url,
    "review_table_rows": _project_metadata_url,
}


def _probe_url(base_url: str, endpoint: str) -> str:
    now = int(datetime.now(UTC).timestamp())
    if endpoint == "audit_logs":
        return f"{base_url}/api/v1/logs/audit/latest"
    if endpoint in HISTORY_PATHS:
        return f"{base_url}{HISTORY_PATHS[endpoint]}?{urlencode({'start_time': now - 3600, 'end_time': now})}"
    if endpoint == "vault_projects" or endpoint in FAN_OUT_PROBE_URLS:
        return _vault_projects_url(base_url, page=1, per_page=1)
    return f"{base_url}/api/v1/client_matters"


def _first_project_id(response: requests.Response) -> Any:
    try:
        projects = ((response.json().get("response") or {}).get("content") or {}).get("projects") or []
    except (ValueError, AttributeError):
        return None
    return projects[0].get("id") if projects else None


def check_endpoint_access(api_key: str, region: str | None, endpoint: str) -> str | None:
    """Return None when the token can reach the endpoint, or a short reason when it can't.

    Harvey API tokens carry a per-endpoint permissions list, so a valid token can still be
    denied on individual endpoints. Only a definitive denial (401/403) counts as missing
    access - throttles, 5xx, and network blips are treated as reachable.
    """
    url = _probe_url(get_base_url(region), endpoint)
    try:
        # The query_history probe fetches a live window of prompt/response text, so honour the
        # endpoint's capture flag here too - the probe body is as sensitive as the export body.
        session = _make_session(api_key, capture=_endpoint_captures_samples(endpoint))
        response = session.get(url, headers=_get_headers(api_key), timeout=30)
        # Fan-out endpoints need a project to probe against. A workspace with no projects has
        # nothing to deny, so it counts as reachable.
        if endpoint in FAN_OUT_PROBE_URLS and response.status_code == 200:
            project_id = _first_project_id(response)
            if project_id is None:
                return None
            child_url = FAN_OUT_PROBE_URLS[endpoint](get_base_url(region), project_id)
            response = session.get(child_url, headers=_get_headers(api_key), timeout=30)
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
        # handled by callers; anything else is a genuine failure. The response body is
        # deliberately left out of the log - it can contain confidential query content.
        log = logger.warning if response.status_code == 404 else logger.error
        log(f"Harvey API error: status={response.status_code}, url={url}")
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


def _parse_http_date(value: Any) -> datetime | None:
    """Parse the RFC 1123 dates the review table row endpoint returns, e.g. 'Wed, 10 Dec 2025 00:38:49 GMT'."""
    if not isinstance(value, str):
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return _parse_datetime(value)
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


@frozen
class VaultProjectPage:
    number: int
    projects: list[dict[str, Any]]
    has_more: bool


def _iter_vault_project_pages(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    start_page: int,
) -> Iterator[VaultProjectPage]:
    page = start_page
    while True:
        data = _fetch_json(session, _vault_projects_url(base_url, page, VAULT_PROJECTS_PAGE_SIZE), headers, logger)

        content = (data.get("response") or {}).get("content") or {}
        projects = content.get("projects") or []
        if not projects:
            return

        total_pages = (content.get("pagination") or {}).get("total_pages")
        has_more = total_pages is None or page < total_pages
        yield VaultProjectPage(number=page, projects=projects, has_more=has_more)

        if not has_more:
            return
        page += 1


def _resume_page(resumable_source_manager: ResumableSourceManager[HarveyResumeConfig]) -> int:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    return resume.next_page if resume is not None and resume.next_page else 1


def _get_vault_project_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HarveyResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    start_page = _resume_page(resumable_source_manager)
    for page in _iter_vault_project_pages(session, headers, base_url, logger, start_page):
        yield page.projects
        if page.has_more:
            resumable_source_manager.save_state(HarveyResumeConfig(next_page=page.number + 1))


def _fetch_json_or_none(
    session: requests.Session, url: str, headers: dict[str, str], logger: FilteringBoundLogger
) -> Any:
    """Like `_fetch_json`, but return None on a 404.

    Fan-out children 404 when their parent is deleted between listing and fetching, and the
    review table row endpoint 404s for a file that has no row yet.
    """
    try:
        return _fetch_json(session, url, headers, logger)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return None
        raise


def _get_project_user_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    project_id: Any,
) -> Iterator[list[dict[str, Any]]]:
    data = _fetch_json_or_none(session, _project_users_url(base_url, project_id), headers, logger)
    users = ((data or {}).get("data") or {}).get("users") or []
    if users:
        yield [{**user, "project_id": project_id} for user in users]


def _get_project_file_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    project_id: Any,
) -> Iterator[list[dict[str, Any]]]:
    cursor: str | None = None
    seen_cursors: set[str] = set()
    while True:
        url = _project_files_url(base_url, project_id, cursor, VAULT_PROJECT_FILES_PAGE_SIZE)
        data = _fetch_json_or_none(session, url, headers, logger)
        content = ((data or {}).get("response") or {}).get("content") or {}

        files = content.get("files") or []
        if files:
            rows = []
            for file in files:
                row = {**file, "project_id": project_id}
                # `uploaded_at` is epoch seconds; land it as a real datetime for partitioning.
                if isinstance(row.get("uploaded_at"), int | float):
                    row["uploaded_at"] = datetime.fromtimestamp(row["uploaded_at"], tz=UTC)
                rows.append(row)
            yield rows

        pagination = content.get("pagination") or {}
        next_cursor = pagination.get("next_cursor")
        if not files or not pagination.get("has_more") or not next_cursor:
            return
        if next_cursor in seen_cursors:
            raise HarveyRetryableError("Harvey returned a repeated Vault project files cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor


def _get_project_review_table_ids(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    project_id: Any,
) -> list[Any]:
    data = _fetch_json_or_none(session, _project_metadata_url(base_url, project_id), headers, logger)
    content = ((data or {}).get("response") or {}).get("content") or []
    # The spec documents a single metadata object but its example wraps it in a list; accept both.
    entries = content if isinstance(content, list) else [content]
    review_table_ids: list[Any] = []
    for entry in entries:
        if isinstance(entry, dict):
            review_table_ids.extend(entry.get("review_table_ids") or [])
    return review_table_ids


def _iter_project_review_tables(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    project_id: Any,
) -> Iterator[dict[str, Any]]:
    for review_table_id in _get_project_review_table_ids(session, headers, base_url, logger, project_id):
        url = f"{base_url}/api/v1/vault/review_table/{_path_id(review_table_id)}"
        data = _fetch_json_or_none(session, url, headers, logger)
        review_table = ((data or {}).get("response") or {}).get("content")
        if review_table:
            yield {"review_table_id": review_table_id, **review_table, "project_id": project_id}


def _get_review_table_metadata_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    project_id: Any,
) -> Iterator[list[dict[str, Any]]]:
    review_tables = list(_iter_project_review_tables(session, headers, base_url, logger, project_id))
    if review_tables:
        yield review_tables


def _get_review_table_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    project_id: Any,
) -> Iterator[list[dict[str, Any]]]:
    for review_table in _iter_project_review_tables(session, headers, base_url, logger, project_id):
        review_table_id = review_table["review_table_id"]
        for file_id in review_table.get("file_ids") or []:
            url = f"{base_url}/api/v1/vault/get_row/{_path_id(review_table_id)}/{_path_id(file_id)}"
            row = _fetch_json_or_none(session, url, headers, logger)
            if not row:
                continue
            # Files in a file group all resolve to the group's row, so (review_table_id, file_id)
            # is the unique key, not the row content.
            row = {**row, "review_table_id": review_table_id, "file_id": file_id, "project_id": project_id}
            parsed = _parse_http_date(row.get("updated_at"))
            if parsed is not None:
                row["updated_at"] = parsed
            yield [row]


ProjectChildRows = Callable[
    [requests.Session, dict[str, str], str, FilteringBoundLogger, Any], Iterator[list[dict[str, Any]]]
]

PROJECT_FAN_OUT_ROWS: dict[str, ProjectChildRows] = {
    "vault_project_users": _get_project_user_rows,
    "vault_project_files": _get_project_file_rows,
    "review_tables": _get_review_table_metadata_rows,
    "review_table_rows": _get_review_table_rows,
}


def _get_project_fan_out_rows(
    session: requests.Session,
    headers: dict[str, str],
    base_url: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[HarveyResumeConfig],
    get_child_rows: ProjectChildRows,
) -> Iterator[list[dict[str, Any]]]:
    start_page = _resume_page(resumable_source_manager)
    for page in _iter_vault_project_pages(session, headers, base_url, logger, start_page):
        for project in page.projects:
            project_id = project.get("id")
            if project_id is None:
                continue
            yield from get_child_rows(session, headers, base_url, logger, project_id)
            # Many projects yield no child rows; let the pipeline act on shutdowns between them.
            # Resuming from the staged page re-walks this page's projects, so no rows are lost.
            resumable_source_manager.safe_point()
        if page.has_more:
            resumable_source_manager.save_state(HarveyResumeConfig(next_page=page.number + 1))


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
    # One session reused across every page so urllib3 keeps the connection alive. Endpoints whose
    # bodies carry arbitrary user content (e.g. query_history) opt out of HTTP sample capture.
    session = _make_session(api_key, capture=_endpoint_captures_samples(endpoint))

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
    elif endpoint in PROJECT_FAN_OUT_ROWS:
        yield from _get_project_fan_out_rows(
            session, headers, base_url, logger, resumable_source_manager, PROJECT_FAN_OUT_ROWS[endpoint]
        )
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
