from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urlparse

import requests
import structlog

from products.warehouse_sources.sources.genesys_cloud.settings import (
    ANALYTICS_PAGE_SIZE,
    GENESYS_CLOUD_ENDPOINTS,
    LISTING_PAGE_SIZE,
    REGIONS,
    GenesysCloudEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    DEFAULT_RETRY,
    OAuth2Auth,
    OAuth2AuthRequestError,
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
)

logger = structlog.get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 60
VALIDATION_TIMEOUT_SECONDS = 10

# The analytics and user-analytics endpoints are queried via POST, but the body only carries the
# interval/paging to read, not a mutation. DEFAULT_RETRY excludes POST from `allowed_methods`, so a
# transient 429/5xx on these calls would otherwise fail the sync outright instead of retrying like
# the listing/scan endpoints' GETs do in the same session.
_GENESYS_CLOUD_RETRY = DEFAULT_RETRY.new(allowed_methods=frozenset(DEFAULT_RETRY.allowed_methods or ()) | {"POST"})

# History read on the first sync and on every full refresh.
INITIAL_HISTORY = timedelta(days=365)
ANALYTICS_WINDOW = timedelta(days=1)
# A conversation keeps changing after it starts (it ends, participants join), so an incremental
# sync reads again from a bit before the watermark. Merge on the primary key removes the overlap.
INCREMENTAL_LOOKBACK = timedelta(days=2)
# The details query pages by page number, which does not scale to very large result sets. A window
# with more hits than this is split in half until it fits, down to MIN_ANALYTICS_WINDOW.
MAX_RESULTS_PER_WINDOW = 10_000
MIN_ANALYTICS_WINDOW = timedelta(seconds=1)


class InvalidGenesysCloudRegionError(ValueError):
    pass


@frozen
class GenesysCloudResumeConfig:
    # Analytics endpoints: start of the next window to read (ISO 8601).
    window_start: Optional[str] = None
    # Listing endpoints: next page number to read.
    page_number: Optional[int] = None
    # Scan endpoints: cursor of the next page to read. Genesys Cloud keeps a cursor for 24 hours.
    cursor: Optional[str] = None
    # Fan-out endpoints: `page_number` is the parent page, `parent_id` the next parent to read on it, and
    # `next_uri` the next child page of that parent.
    parent_id: Optional[str] = None
    next_uri: Optional[str] = None


def _validated_region(region: str) -> str:
    if region not in REGIONS:
        raise InvalidGenesysCloudRegionError(f"Unknown Genesys Cloud region: {region!r}")
    return region


def _make_auth(region: str, client_id: str, client_secret: str) -> OAuth2Auth:
    return OAuth2Auth(
        token_url=f"https://login.{_validated_region(region)}/oauth/token",
        client_id=client_id,
        client_secret=client_secret,
        grant_type="client_credentials",
        client_auth_method="basic",
    )


def _make_session(region: str, client_id: str, client_secret: str) -> requests.Session:
    session = make_tracked_session(retry=_GENESYS_CLOUD_RETRY, redact_values=(client_secret,))
    session.auth = _make_auth(region, client_id, client_secret)
    return session


def _api_base_url(region: str) -> str:
    return f"https://api.{_validated_region(region)}"


def _to_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _format_instant(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def _interval(start: datetime, end: datetime) -> str:
    return f"{_format_instant(start)}/{_format_instant(end)}"


def _starts_in_window(conversation: dict[str, Any], start: datetime, end: datetime) -> bool:
    # The API can return conversations outside the exact interval (it matches by day), so keep
    # windows disjoint here. That prevents duplicate rows across windows.
    raw = conversation.get("conversationStart")
    if not raw:
        return True
    return start <= _to_utc(raw) < end


def _to_rows(conversations: list[dict[str, Any]], flatten_participants: bool) -> list[dict[str, Any]]:
    if not flatten_participants:
        return conversations
    rows: list[dict[str, Any]] = []
    for conversation in conversations:
        for participant in conversation.get("participants") or []:
            rows.append(
                {
                    **participant,
                    "conversationId": conversation.get("conversationId"),
                    "conversationStart": conversation.get("conversationStart"),
                    "conversationEnd": conversation.get("conversationEnd"),
                }
            )
    return rows


def _status_rows(
    user_detail: dict[str, Any], start: datetime, end: datetime, include_earlier: bool
) -> list[dict[str, Any]]:
    user_id = user_detail.get("userId")
    rows: list[dict[str, Any]] = []
    for record_type, key in (("presence", "primaryPresence"), ("routing_status", "routingStatus")):
        for record in user_detail.get(key) or []:
            raw = record.get("startTime")
            if not raw:
                continue
            record_start = _to_utc(raw)
            # A record overlaps every window it spans, so emit it once per run: in the window it starts in, or in
            # the first window when it started earlier. The first window refreshes the end time of long records.
            if record_start >= end or (record_start < start and not include_earlier):
                continue
            rows.append({**record, "userId": user_id, "recordType": record_type})
    return rows


def _query_user_window(
    session: requests.Session,
    url: str,
    start: datetime,
    end: datetime,
    include_earlier: bool,
) -> Iterator[tuple[list[dict[str, Any]], Optional[datetime]]]:
    """Yield `(rows, window_end)` per page. `window_end` is set on the last page of a window."""
    page_number = 1
    while True:
        body = {
            "interval": _interval(start, end),
            "order": "asc",
            "paging": {"pageSize": ANALYTICS_PAGE_SIZE, "pageNumber": page_number},
        }
        response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json() or {}
        total_hits = int(data.get("totalHits") or 0)
        user_details = data.get("userDetails") or []
        rows = [row for detail in user_details for row in _status_rows(detail, start, end, include_earlier)]
        # Genesys Cloud can return short pages before the last one, so only totalHits ends the window.
        is_last_page = not user_details or page_number * ANALYTICS_PAGE_SIZE >= total_hits
        yield rows, (end if is_last_page else None)
        if is_last_page:
            return
        page_number += 1


def _query_window(
    session: requests.Session,
    url: str,
    config: GenesysCloudEndpointConfig,
    start: datetime,
    end: datetime,
) -> Iterator[tuple[list[dict[str, Any]], Optional[datetime]]]:
    """Yield `(conversations, window_end)` per page. `window_end` is set on the last page of a window."""
    page_number = 1
    while True:
        body = {
            **config.query_body,
            "interval": _interval(start, end),
            "order": "asc",
            "orderBy": "conversationStart",
            "paging": {"pageSize": ANALYTICS_PAGE_SIZE, "pageNumber": page_number},
        }
        response = session.post(url, json=body, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json() or {}
        total_hits = int(data.get("totalHits") or 0)

        if page_number == 1 and total_hits > MAX_RESULTS_PER_WINDOW:
            if end - start > MIN_ANALYTICS_WINDOW:
                middle = start + (end - start) / 2
                yield from _query_window(session, url, config, start, middle)
                yield from _query_window(session, url, config, middle, end)
                return
            logger.warning(
                "genesys_cloud_window_over_result_limit",
                endpoint=config.name,
                interval=_interval(start, end),
                total_hits=total_hits,
            )

        conversations = [c for c in data.get("conversations") or [] if _starts_in_window(c, start, end)]
        returned = len(data.get("conversations") or [])
        is_last_page = returned < ANALYTICS_PAGE_SIZE or page_number * ANALYTICS_PAGE_SIZE >= total_hits
        yield conversations, (end if is_last_page else None)
        if is_last_page:
            return
        page_number += 1


def _iter_analytics_rows(
    session: requests.Session,
    base_url: str,
    config: GenesysCloudEndpointConfig,
    resumable_source_manager: ResumableSourceManager[GenesysCloudResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Iterator[list[dict[str, Any]]]:
    now = datetime.now(UTC)
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and resume.window_start:
        start = _to_utc(resume.window_start)
    elif db_incremental_field_last_value is not None:
        start = _to_utc(db_incremental_field_last_value) - INCREMENTAL_LOOKBACK
    else:
        start = now - INITIAL_HISTORY

    url = f"{base_url}{config.path}"
    # A resumed run already emitted the records that started before its checkpoint.
    first_window = resume is None or not resume.window_start
    while start < now:
        window_end = min(start + ANALYTICS_WINDOW, now)
        pages = (
            _query_user_window(session, url, start, window_end, include_earlier=first_window)
            if config.kind == "user_analytics"
            else _query_window(session, url, config, start, window_end)
        )
        for records, finished_window_end in pages:
            rows = _to_rows(records, config.flatten_participants)
            if finished_window_end is not None:
                # Stage the cursor before the yield that covers it, so a resume starts after this window.
                resumable_source_manager.save_state(
                    GenesysCloudResumeConfig(window_start=_format_instant(finished_window_end))
                )
                if not rows:
                    resumable_source_manager.safe_point()
            if rows:
                yield rows
        start = window_end
        first_window = False

    # A later sync must derive a fresh start from its watermark instead of reusing this run's cursor.
    resumable_source_manager.clear_state()


def _iter_listing_rows(
    session: requests.Session,
    base_url: str,
    config: GenesysCloudEndpointConfig,
    resumable_source_manager: ResumableSourceManager[GenesysCloudResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_number = resume.page_number if resume is not None and resume.page_number else 1

    url = f"{base_url}{config.path}"
    while True:
        response = session.get(
            url,
            params={**config.params, "pageSize": LISTING_PAGE_SIZE, "pageNumber": page_number},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json() or {}
        entities = data.get("entities") or []
        page_count = int(data.get("pageCount") or 0)
        has_next_page = bool(entities) and page_number < page_count
        if has_next_page:
            resumable_source_manager.save_state(GenesysCloudResumeConfig(page_number=page_number + 1))
        if entities:
            yield entities
        if not has_next_page:
            # A later full refresh must restart at page one, not the last checkpoint from this run.
            resumable_source_manager.clear_state()
            return
        page_number += 1


def _next_cursor(data: dict[str, Any], cursor_param: str) -> Optional[str]:
    cursor = (data.get("cursors") or {}).get("after")
    if cursor:
        return cursor
    # The teams listing returns its next cursor only inside nextUri.
    next_uri = data.get("nextUri")
    if not next_uri:
        return None
    values = parse_qs(urlparse(next_uri).query).get(cursor_param)
    return values[0] if values else None


def _iter_scan_rows(
    session: requests.Session,
    base_url: str,
    config: GenesysCloudEndpointConfig,
    resumable_source_manager: ResumableSourceManager[GenesysCloudResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    cursor = resume.cursor if resume is not None else None
    sends_resumed_cursor = cursor is not None

    url = f"{base_url}{config.path}"
    while True:
        params: dict[str, Any] = {**config.params, config.page_size_param: LISTING_PAGE_SIZE}
        if cursor:
            params[config.cursor_param] = cursor
        response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        if sends_resumed_cursor and response.status_code in (400, 422):
            # The saved cursor expired. Restarting here would append rows this run already loaded, so drop the
            # cursor and fail: the retry then runs as a fresh full refresh.
            resumable_source_manager.clear_state()
        sends_resumed_cursor = False
        response.raise_for_status()
        data = response.json() or {}
        entities = data.get("entities") or []
        next_cursor = _next_cursor(data, config.cursor_param)
        has_next_page = bool(entities) and bool(next_cursor)
        if has_next_page:
            resumable_source_manager.save_state(GenesysCloudResumeConfig(cursor=next_cursor))
        if entities:
            yield entities
        if not has_next_page:
            resumable_source_manager.clear_state()
            return
        cursor = next_cursor


def _child_url(base_url: str, config: GenesysCloudEndpointConfig, parent_id: str) -> str:
    if config.parent_id_param:
        return f"{base_url}{config.path}"
    return f"{base_url}{config.path.replace('{parent_id}', quote(parent_id, safe=''))}"


def _child_params(config: GenesysCloudEndpointConfig, parent_id: str, next_uri: Optional[str]) -> dict[str, Any]:
    # Only the query of nextUri is used. The request always goes to the configured host and path.
    params: dict[str, Any] = (
        dict(parse_qs(urlparse(next_uri).query))
        if next_uri
        else {**config.params, "pageSize": config.page_size, "pageNumber": 1}
    )
    if config.parent_id_param:
        params[config.parent_id_param] = parent_id
    return params


def _is_skipped_child_error(response: requests.Response, config: GenesysCloudEndpointConfig) -> bool:
    # A parent removed after the parent page was read returns 404.
    if response.status_code == 404:
        return True
    if response.status_code != 400 or not config.skipped_error_codes:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("code") in config.skipped_error_codes


def _iter_fan_out_rows(
    session: requests.Session,
    base_url: str,
    config: GenesysCloudEndpointConfig,
    resumable_source_manager: ResumableSourceManager[GenesysCloudResumeConfig],
) -> Iterator[list[dict[str, Any]]]:
    assert config.parent is not None
    parent = GENESYS_CLOUD_ENDPOINTS[config.parent]
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    page_number = resume.page_number if resume is not None and resume.page_number else 1
    resume_parent_id = resume.parent_id if resume is not None else None
    resume_next_uri = resume.next_uri if resume is not None else None

    parent_url = f"{base_url}{parent.path}"
    while True:
        response = session.get(
            parent_url,
            params={**parent.params, "pageSize": LISTING_PAGE_SIZE, "pageNumber": page_number},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json() or {}
        parents = data.get("entities") or []
        has_next_parent_page = bool(parents) and page_number < int(data.get("pageCount") or 0)
        parent_ids = [str(row["id"]) for row in parents if row.get("id")]
        if resume_parent_id in parent_ids:
            parent_ids = parent_ids[parent_ids.index(resume_parent_id) :]
        else:
            # The parent is gone from its page, so read the page from its first parent.
            resume_next_uri = None
        resume_parent_id = None

        for index, parent_id in enumerate(parent_ids):
            # After the last parent, the next parent page. On the last page that page is empty and ends the run.
            after_parent = (
                GenesysCloudResumeConfig(page_number=page_number, parent_id=parent_ids[index + 1])
                if index + 1 < len(parent_ids)
                else GenesysCloudResumeConfig(page_number=page_number + 1)
            )

            url = _child_url(base_url, config, parent_id)
            next_uri, resume_next_uri = resume_next_uri, None
            sends_resumed_uri = next_uri is not None
            params = _child_params(config, parent_id, next_uri)
            while True:
                response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
                if _is_skipped_child_error(response, config):
                    rows: list[dict[str, Any]] = []
                    next_uri = None
                else:
                    if sends_resumed_uri and response.status_code in (400, 422):
                        # The saved child page is no longer valid. Drop it, so the retry runs as a fresh full refresh.
                        resumable_source_manager.clear_state()
                    response.raise_for_status()
                    data = response.json() or {}
                    rows = data.get("entities") or []
                    next_uri = data.get("nextUri") if rows else None
                sends_resumed_uri = False

                next_params = _child_params(config, parent_id, next_uri) if next_uri else None
                if next_params == params:
                    next_params = None
                resumable_source_manager.save_state(
                    GenesysCloudResumeConfig(page_number=page_number, parent_id=parent_id, next_uri=next_uri)
                    if next_params is not None
                    else after_parent
                )

                if config.parent_key:
                    rows = [{**row, config.parent_key: parent_id} for row in rows]
                if rows:
                    yield rows
                else:
                    resumable_source_manager.safe_point()
                if next_params is None:
                    break
                params = next_params

        if not has_next_parent_page:
            resumable_source_manager.clear_state()
            return
        page_number += 1


def genesys_cloud_source(
    region: str,
    client_id: str,
    client_secret: str,
    endpoint: str,
    resumable_source_manager: ResumableSourceManager[GenesysCloudResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GENESYS_CLOUD_ENDPOINTS[endpoint]
    base_url = _api_base_url(region)

    def items() -> Iterator[list[dict[str, Any]]]:
        session = _make_session(region, client_id, client_secret)
        if config.kind in ("analytics", "user_analytics"):
            yield from _iter_analytics_rows(
                session, base_url, config, resumable_source_manager, db_incremental_field_last_value
            )
        elif config.kind == "scan":
            yield from _iter_scan_rows(session, base_url, config, resumable_source_manager)
        elif config.kind == "fan_out":
            yield from _iter_fan_out_rows(session, base_url, config, resumable_source_manager)
        else:
            yield from _iter_listing_rows(session, base_url, config, resumable_source_manager)

    return SourceResponse(
        name=endpoint,
        items=items,
        primary_keys=list(config.primary_keys),
        partition_mode="datetime" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        # User status records arrive grouped by user, and fan-out rows grouped by parent, not ordered.
        sort_mode=None if config.kind in ("user_analytics", "fan_out") else "asc",
    )


def _probe_fan_out(session: requests.Session, base_url: str, config: GenesysCloudEndpointConfig) -> requests.Response:
    assert config.parent is not None
    parent = GENESYS_CLOUD_ENDPOINTS[config.parent]
    response = session.get(
        f"{base_url}{parent.path}",
        params={**parent.params, "pageSize": 1, "pageNumber": 1},
        timeout=VALIDATION_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        return response
    parents = (response.json() or {}).get("entities") or []
    if not parents or not parents[0].get("id"):
        return response
    parent_id = str(parents[0]["id"])
    child_response = session.get(
        _child_url(base_url, config, parent_id),
        params={**_child_params(config, parent_id, None), "pageSize": 1},
        timeout=VALIDATION_TIMEOUT_SECONDS,
    )
    return response if _is_skipped_child_error(child_response, config) else child_response


def validate_credentials(
    region: str, client_id: str, client_secret: str, endpoint: Optional[str] = None
) -> tuple[bool, str | None]:
    if region not in REGIONS:
        return False, "Select the Genesys Cloud region your organization is hosted in."

    config = GENESYS_CLOUD_ENDPOINTS[endpoint] if endpoint else None
    base_url = _api_base_url(region)
    session = _make_session(region, client_id, client_secret)
    try:
        if config is None:
            response = session.get(f"{base_url}/api/v2/organizations/me", timeout=VALIDATION_TIMEOUT_SECONDS)
        elif config.kind in ("analytics", "user_analytics"):
            now = datetime.now(UTC)
            response = session.post(
                f"{base_url}{config.path}",
                json={"interval": _interval(now - timedelta(hours=1), now), "paging": {"pageSize": 1, "pageNumber": 1}},
                timeout=VALIDATION_TIMEOUT_SECONDS,
            )
        elif config.kind == "fan_out":
            response = _probe_fan_out(session, base_url, config)
        else:
            response = session.get(
                f"{base_url}{config.path}",
                # The scan listings reject a limit below 10.
                params={config.page_size_param: 10} if config.kind == "scan" else {"pageSize": 1, "pageNumber": 1},
                timeout=VALIDATION_TIMEOUT_SECONDS,
            )
    except OAuth2AuthRequestError as e:
        if e.is_permanent:
            return (
                False,
                "Genesys Cloud rejected the client ID and secret. Check that the OAuth client uses the client credentials grant and belongs to the selected region.",
            )
        return False, "Could not get an access token from Genesys Cloud. Try again in a few minutes."
    except requests.RequestException:
        return False, "Could not connect to Genesys Cloud. Check the selected region and try again."

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Genesys Cloud rejected the access token. Check the client ID, client secret, and region."
    if response.status_code == 403:
        # The token is valid. A missing permission only matters for the table the user asked about.
        if config is None:
            return True, None
        if config.permission:
            return (
                False,
                f"The OAuth client's role is missing the `{config.permission}` permission, which the {config.name} table needs.",
            )
        return False, f"The OAuth client does not have access to the {config.name} table."
    return False, f"Genesys Cloud returned HTTP {response.status_code}. Try again in a few minutes."
