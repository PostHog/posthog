import base64
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from dateutil import parser as dateutil_parser
from structlog.types import FilteringBoundLogger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.gong.settings import (
    GONG_ENDPOINTS,
    GongEndpointConfig,
)

# Gong's API base URL. Workspace API keys (HTTP Basic) authenticate against this host regardless
# of the customer's data region, so it stays fixed (no user-supplied host -> no SSRF surface).
GONG_BASE_URL = "https://api.gong.io"

# `/v2/calls` requires `fromDateTime` and rejects ranges wider than 90 days per request.
MAX_WINDOW_DAYS = 90
# How far back the first sync of `calls` reaches when there is no incremental cursor yet.
# Bounded so an initial backfill doesn't exhaust Gong's aggressive daily rate limit.
DEFAULT_INITIAL_LOOKBACK_DAYS = 365


class GongRetryableError(Exception):
    pass


@frozen
class GongResumeConfig:
    # ISO-8601 start of the next date window to fetch. Only the windowed, call-date-filtered
    # endpoints persist resume state; cursors are deliberately not cached (Gong expires
    # them quickly), so on resume we restart the in-progress window from scratch and let
    # primary-key merge semantics dedupe any re-yielded rows.
    window_start: Optional[str] = None


def _format_datetime(value: datetime) -> str:
    """ISO-8601 with a `Z` suffix, which Gong accepts for `fromDateTime`/`toDateTime`."""
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def _to_datetime(value: Any) -> Optional[datetime]:
    """Coerce an incremental cursor value (datetime/date/ISO string) to an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    try:
        parsed = dateutil_parser.parse(str(value))
    except (ValueError, TypeError, OverflowError):
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _get_headers(access_key: str, access_key_secret: str) -> dict[str, str]:
    token = base64.b64encode(f"{access_key}:{access_key_secret}".encode()).decode()
    return {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }


def validate_credentials(
    access_key: str, access_key_secret: str, schema_name: Optional[str] = None
) -> tuple[bool, str | None]:
    """Probe a cheap endpoint to confirm the key pair is genuine.

    401 means the credentials are invalid. 403 means the credentials are valid but lack the
    scope for this particular resource - accepted at source-create (``schema_name is None``)
    because users may grant only the scopes they intend to sync.
    """
    url = f"{GONG_BASE_URL}/v2/workspaces"
    try:
        response = make_tracked_session().get(url, headers=_get_headers(access_key, access_key_secret), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Gong access key or access key secret"
    if response.status_code == 403:
        if schema_name is None:
            return True, None
        return False, "Your Gong credentials do not have permission to access this endpoint"

    return False, f"Gong API returned an unexpected status code: {response.status_code}"


def _build_url(path: str, params: dict[str, Any]) -> str:
    if not params:
        return f"{GONG_BASE_URL}{path}"
    return f"{GONG_BASE_URL}{path}?{urlencode(params)}"


def _extensive_body(window_start: datetime, window_end: datetime, cursor: Optional[str]) -> dict[str, Any]:
    """Request body for `POST /v2/calls/extensive`.

    `contentSelector.context = "Extended"` asks Gong to return each call's CRM associations
    (linked Salesforce/HubSpot objects and their fields); `exposedFields.parties = true` returns
    the participants (name, email address, affiliation). Neither is available from the basic
    `/v2/calls` list endpoint. The pagination cursor travels in the body, not the query string.
    """
    body: dict[str, Any] = {
        "filter": {
            "fromDateTime": _format_datetime(window_start),
            "toDateTime": _format_datetime(window_end),
        },
        "contentSelector": {
            "context": "Extended",
            "exposedFields": {"parties": True},
        },
    }
    if cursor:
        body["cursor"] = cursor
    return body


def _flatten_extensive_call(call: dict[str, Any]) -> dict[str, Any]:
    """Lift the `metaData` block of an extensive call row to the top level.

    `/v2/calls/extensive` nests the core call fields under `metaData` and returns `parties`
    and CRM `context` as siblings. Flattening `metaData` up keeps `id` and `started` available
    at the top level for primary-key merge and datetime partitioning, while preserving the
    enrichment as nested `parties`/`context` columns.
    """
    meta = call.get("metaData") or {}
    flattened = dict(meta)
    flattened["parties"] = call.get("parties")
    flattened["context"] = call.get("context")
    return flattened


def get_rows(
    access_key: str,
    access_key_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GongResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> Iterator[Any]:
    config = GONG_ENDPOINTS[endpoint]
    headers = _get_headers(access_key, access_key_secret)

    @retry(
        retry=retry_if_exception_type((GongRetryableError, requests.ReadTimeout, requests.ConnectionError)),
        stop=stop_after_attempt(5),
        wait=wait_exponential_jitter(initial=1, max=60),
        reraise=True,
    )
    def fetch_page(url: str, json_body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        session = make_tracked_session(capture=config.capture_http_samples)
        # Extensive endpoints POST their filter/pagination in a JSON body; list endpoints GET.
        # `requests` sets `Content-Type: application/json` automatically for the `json=` kwarg.
        if json_body is not None:
            response = session.post(url, headers=headers, json=json_body, timeout=60)
        else:
            response = session.get(url, headers=headers, timeout=60)

        if response.status_code == 429 or response.status_code >= 500:
            raise GongRetryableError(f"Gong API error (retryable): status={response.status_code}, url={url}")

        # Gong's `/v2/calls` answers a date window with no processed calls using a 404
        # ("No calls found corresponding to the provided filters") rather than an empty 200.
        # Treat it as an empty page so the sync skips the window instead of failing.
        if config.uses_date_window and response.status_code == 404 and "no calls" in response.text.lower():
            return {}

        if not response.ok:
            logger.error(f"Gong API error: status={response.status_code}, body={response.text}, url={url}")
            response.raise_for_status()

        return response.json()

    if config.uses_date_window:
        yield from _iter_windowed_rows(
            config,
            fetch_page,
            logger,
            resumable_source_manager,
            should_use_incremental_field,
            db_incremental_field_last_value,
        )
    else:
        yield from _iter_cursor_rows(config, fetch_page)


def _iter_cursor_rows(config: GongEndpointConfig, fetch_page) -> Iterator[Any]:
    """Cursor-paginate a list endpoint until ``records.cursor`` is absent.

    Endpoints with no pagination (e.g. workspaces) return no cursor, so the loop exits after
    the first page.
    """
    cursor: str | None = None
    while True:
        params: dict[str, Any] = {"cursor": cursor} if cursor else {}
        data = fetch_page(_build_url(config.path, params))

        rows = data.get(config.response_key, [])
        if rows:
            yield rows

        cursor = data.get("records", {}).get("cursor")
        if not cursor:
            break


def _iter_windowed_rows(
    config: GongEndpointConfig,
    fetch_page,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GongResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> Iterator[Any]:
    """Sync `/v2/calls` by iterating bounded date windows oldest-first, cursor-paginating each.

    State is saved after each completed window. Cursors are never persisted; on resume we
    restart the in-progress window from its start and let merge dedupe re-yielded rows.
    """
    end = datetime.now(UTC)

    last_value = _to_datetime(db_incremental_field_last_value) if should_use_incremental_field else None
    window_start = last_value or (end - timedelta(days=DEFAULT_INITIAL_LOOKBACK_DAYS))

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume_config is not None and resume_config.window_start:
        resumed = _to_datetime(resume_config.window_start)
        if resumed is not None:
            logger.debug(f"Gong: resuming calls from window start {resume_config.window_start}")
            window_start = resumed

    while window_start < end:
        window_end = min(window_start + timedelta(days=MAX_WINDOW_DAYS), end)

        if config.uses_call_id_batches:
            yield from _iter_transcript_rows(config, fetch_page, window_start, window_end)
        else:
            yield from _iter_call_rows(config, fetch_page, window_start, window_end)

        window_start = window_end
        resumable_source_manager.save_state(GongResumeConfig(window_start=_format_datetime(window_start)))


def _iter_call_rows(
    config: GongEndpointConfig, fetch_page, window_start: datetime, window_end: datetime
) -> Iterator[Any]:
    """Cursor-paginate one date window of `/v2/calls`, or of its extensive POST form."""
    cursor: str | None = None

    while True:
        if config.uses_extensive:
            data = fetch_page(
                _build_url(config.path, {}),
                json_body=_extensive_body(window_start, window_end, cursor),
            )
            rows = [_flatten_extensive_call(row) for row in data.get(config.response_key, [])]
        else:
            params: dict[str, Any] = {
                "fromDateTime": _format_datetime(window_start),
                "toDateTime": _format_datetime(window_end),
            }
            if cursor:
                params["cursor"] = cursor

            data = fetch_page(_build_url(config.path, params))
            rows = data.get(config.response_key, [])

        if rows:
            yield rows

        cursor = data.get("records", {}).get("cursor")
        if not cursor:
            break


def _iter_transcript_rows(
    config: GongEndpointConfig, fetch_page, window_start: datetime, window_end: datetime
) -> Iterator[Any]:
    """Yield one date window of transcripts, each stamped with the start time of its call.

    Walks the `/v2/calls` list for the window and asks for the transcripts of one page of call ids
    at a time. That keeps the `callIds` filter bounded to a page, and gives every transcript the
    `started` of the call it belongs to — `POST /v2/calls/transcript` returns no date of its own.
    """
    calls_config = GONG_ENDPOINTS["calls"]
    cursor: str | None = None

    while True:
        params: dict[str, Any] = {
            "fromDateTime": _format_datetime(window_start),
            "toDateTime": _format_datetime(window_end),
        }
        if cursor:
            params["cursor"] = cursor

        calls_page = fetch_page(_build_url(calls_config.path, params))

        started_by_call_id = _call_start_times(calls_page.get(calls_config.response_key, []))
        if started_by_call_id:
            yield from _iter_transcripts_for_calls(config, fetch_page, window_start, window_end, started_by_call_id)

        cursor = calls_page.get("records", {}).get("cursor")
        if not cursor:
            break


def _call_start_times(calls: list[dict[str, Any]]) -> dict[str, Any]:
    """Map each call's id to its start time, refusing a call that is missing either.

    Both stamp the transcript rows that follow: the id is the primary key merge runs on, and
    the start time is what the table partitions by and syncs incrementally on. A row missing
    either is unmergeable and invisible to the watermark, so stop rather than write it.
    """
    start_times: dict[str, Any] = {}
    for call in calls:
        call_id, started = call.get("id"), call.get("started")
        if not call_id or not started:
            raise ValueError(f"Gong returned a call with no id or no start time (id={call_id!r})")
        start_times[call_id] = started
    return start_times


def _stamp_transcript(transcript: dict[str, Any], started_by_call_id: dict[str, Any]) -> dict[str, Any]:
    """Copy a transcript with the start time of the call it belongs to attached."""
    call_id: Any = transcript.get("callId")
    started = started_by_call_id.get(call_id)
    if started is None:
        raise ValueError(f"Gong returned a transcript for a call that was not asked for (callId={call_id!r})")
    return {**transcript, "started": started}


def _iter_transcripts_for_calls(
    config: GongEndpointConfig,
    fetch_page,
    window_start: datetime,
    window_end: datetime,
    started_by_call_id: dict[str, Any],
) -> Iterator[Any]:
    cursor: str | None = None

    while True:
        body: dict[str, Any] = {
            "filter": {
                "fromDateTime": _format_datetime(window_start),
                "toDateTime": _format_datetime(window_end),
                "callIds": list(started_by_call_id),
            }
        }
        if cursor:
            body["cursor"] = cursor

        data = fetch_page(_build_url(config.path, {}), json_body=body)

        rows = [_stamp_transcript(row, started_by_call_id) for row in data.get(config.response_key, [])]
        if rows:
            yield rows

        cursor = data.get("records", {}).get("cursor")
        if not cursor:
            break


def gong_source(
    access_key: str,
    access_key_secret: str,
    endpoint: str,
    logger: FilteringBoundLogger,
    resumable_source_manager: ResumableSourceManager[GongResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = GONG_ENDPOINTS[endpoint]

    return SourceResponse(
        name=endpoint,
        items=lambda: get_rows(
            access_key=access_key,
            access_key_secret=access_key_secret,
            endpoint=endpoint,
            logger=logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        ),
        primary_keys=[config.primary_key],
        # Windows are iterated oldest-first, so the cursor watermark advances correctly.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        chunk_size=config.chunk_size,
    )
