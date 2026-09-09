import logging
import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponsePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.settings import (
    MESSAGE_ACTIVITY_BACKFILL_DAYS,
    SENDGRID_ENDPOINTS,
    SendGridEndpointConfig,
)

logger = logging.getLogger(__name__)

SENDGRID_BASE_URL = "https://api.sendgrid.com/v3"


@dataclasses.dataclass
class SendGridResumeConfig:
    # Full next-page URL to fetch within the current sync. Set by metadata pagination (the API
    # hands us the whole next URL) and by pre-migration saved states (which stored the offset URL
    # for offset pagination too). Optional so old single-field states still parse.
    next_url: Optional[str] = None
    # Row offset of the next unfetched page (offset pagination).
    offset: Optional[int] = None
    # Remaining unfetched Email Activity window (activity pagination), both bounds as normalized
    # UTC ISO timestamps. Saved together so a resumed sync keeps walking the original window
    # instead of recomputing it from "now" and losing the oldest slice of a first backfill.
    activity_window_start: Optional[str] = None
    activity_window_end: Optional[str] = None


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _to_epoch_seconds(value: Any) -> int:
    """Coerce an incremental cursor value to Unix epoch seconds for the `start_time` filter.

    SendGrid's suppression `created` field is already epoch seconds, but the pipeline may hand
    the cursor back as a datetime/date depending on how it round-tripped through storage.
    """
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return int(dt.timestamp())
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp())
    return int(value)


def _to_date_string(value: Any) -> str:
    """Coerce an incremental cursor value to a `YYYY-MM-DD` string for the `start_date` filter.

    The stats `date` field is a bare date string, but the pipeline may hand the cursor back as a
    datetime/date depending on how it round-tripped through storage.
    """
    if isinstance(value, datetime):
        dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return dt.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC).date().isoformat()
    # Already a string: trust the leading YYYY-MM-DD, tolerating a trailing time component.
    return str(value)[:10]


def _format_cursor(value: Any, param_format: str) -> Any:
    return _to_date_string(value) if param_format == "date" else _to_epoch_seconds(value)


def _default_backfill_value(config: SendGridEndpointConfig) -> Any:
    assert config.default_backfill_days is not None
    start = datetime.now(UTC) - timedelta(days=config.default_backfill_days)
    return _format_cursor(start, config.incremental_param_format)


def _flatten_daily_stats(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten one `{date, stats: [{metrics: {...}}]}` bucket into a row per metrics entry, with the
    bucket `date` merged in. `aggregated_by=day` with no breakdown yields one row per date."""
    date_value = item.get("date")
    rows: list[dict[str, Any]] = []
    for entry in item.get("stats") or []:
        metrics = entry.get("metrics") or {}
        rows.append({"date": date_value, **metrics})
    return rows


_ACTIVITY_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _to_activity_timestamp(value: Any) -> str:
    """Normalize a cursor, resume, or response timestamp to the UTC second-precision form the
    Email Activity query's TIMESTAMP literal takes.

    Flooring sub-second parts is safe: both window bounds are inclusive, so a floored bound only
    re-fetches boundary rows and merge dedupes them on the primary key.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    elif isinstance(value, int | float):
        dt = datetime.fromtimestamp(value, tz=UTC)
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt.strftime(_ACTIVITY_TIMESTAMP_FORMAT)


def _require_activity_timestamp(value: Any) -> str:
    # Re-normalizing rejects a tampered Redis value before it can smuggle arbitrary syntax into
    # the Email Activity query.
    try:
        return _to_activity_timestamp(value)
    except (TypeError, ValueError, OverflowError, OSError):
        raise ValueError(f"SendGrid resume state contains an unexpected timestamp: {value!r}")


def _activity_query(window_start: str, window_end: str) -> str:
    # Both bounds are inclusive; `requests` URL-encodes the spaces and quotes.
    return f'last_event_time BETWEEN TIMESTAMP "{window_start}" AND TIMESTAMP "{window_end}"'


def _offset_from_url(url: str) -> int:
    """Recover the `offset` query param so a resumed offset-paginated sync keeps advancing."""
    values = parse_qs(urlparse(url).query).get("offset", ["0"])
    try:
        return int(values[0])
    except (ValueError, IndexError):
        return 0


def _is_sendgrid_url(url: Any) -> bool:
    # Only follow URLs that stay on the canonical SendGrid host, so a tampered or compromised API
    # response (or Redis resume state) can't point our authenticated request at an internal address
    # (SSRF) and leak the API key carried in the Authorization header.
    return isinstance(url, str) and url.startswith(SENDGRID_BASE_URL)


def _require_sendgrid_url(url: str) -> None:
    if not _is_sendgrid_url(url):
        raise ValueError(f"SendGrid resume state contains an unexpected URL: {url!r}")


class SendGridMetadataPaginator(JSONResponsePaginator):
    """Follow the absolute `_metadata.next` URL SendGrid returns, dropping any off-host next link
    (stop cleanly) rather than following it — the SSRF guard for marketing/asm metadata endpoints."""

    def __init__(self) -> None:
        super().__init__(next_url_path="_metadata.next")

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        super().update_state(response, data)
        if self._next_url is not None and not _is_sendgrid_url(self._next_url):
            self._next_url = None
            self._has_next_page = False


class SendGridMessagesPaginator(BasePaginator):
    """Page the Email Activity API by narrowing its query window newest to oldest.

    `GET /v3/messages` exposes no cursor or offset — `limit` (max 1000) just caps how many of the
    most recent matches come back. Each full page therefore moves the window end back to the
    oldest `last_event_time` on the page (inclusive, so boundary rows re-appear and merge dedupes
    them on `msg_id`); a short page means the window is drained.
    """

    def __init__(self, window_start: str, window_end: str, limit: int) -> None:
        super().__init__()
        self._window_start = window_start
        self._window_end = window_end
        self._limit = limit

    def _apply_window(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["query"] = _activity_query(self._window_start, self._window_end)
        request.params["limit"] = self._limit

    def init_request(self, request: Request) -> None:
        self._apply_window(request)

    def update_request(self, request: Request) -> None:
        self._apply_window(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        rows = data or []
        if len(rows) < self._limit:
            self._has_next_page = False
            return

        oldest: Optional[str] = None
        for row in rows:
            raw = row.get("last_event_time") if isinstance(row, dict) else None
            if not raw:
                continue
            try:
                normalized = _to_activity_timestamp(raw)
            except (TypeError, ValueError):
                continue
            if oldest is None or normalized < oldest:
                oldest = normalized

        if oldest is None or oldest >= self._window_end:
            # A full page that can't narrow the window: more than `limit` messages share the
            # window-end second, or no row carried a parseable last_event_time. Stop instead of
            # refetching the same page until the activity times out; anything older is skipped.
            logger.warning(
                "SendGrid message activity window cannot advance; stopping pagination",
                extra={"window_start": self._window_start, "window_end": self._window_end},
            )
            self._has_next_page = False
            return

        self._window_end = oldest
        self._has_next_page = True

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        if not self._has_next_page:
            return None
        return {"activity_window_start": self._window_start, "activity_window_end": self._window_end}

    def set_resume_state(self, state: dict[str, Any]) -> None:
        window_start = state.get("activity_window_start")
        window_end = state.get("activity_window_end")
        if window_start is None or window_end is None:
            return
        self._window_start = _require_activity_timestamp(window_start)
        self._window_end = _require_activity_timestamp(window_end)
        self._has_next_page = True

    def __str__(self) -> str:
        return f"SendGridMessagesPaginator(window_start={self._window_start}, window_end={self._window_end})"


def _build_paginator(config: SendGridEndpointConfig) -> BasePaginator:
    if config.pagination == "offset":
        # No top-level `total`; termination is a short/empty page (OffsetPaginator default).
        return OffsetPaginator(limit=config.page_size, total_path=None)
    if config.pagination == "metadata":
        return SendGridMetadataPaginator()
    return SinglePagePaginator()


def _build_activity_paginator(
    config: SendGridEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> SendGridMessagesPaginator:
    now = datetime.now(UTC)
    if should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None:
        # The window is inclusive of the watermark, so the boundary message re-appears and merge
        # updates it. Because the filter rides every request, pagination terminates at the
        # watermark by construction.
        window_start = _to_activity_timestamp(db_incremental_field_last_value)
    else:
        window_start = _to_activity_timestamp(now - timedelta(days=MESSAGE_ACTIVITY_BACKFILL_DAYS))
    return SendGridMessagesPaginator(
        window_start=window_start,
        window_end=_to_activity_timestamp(now),
        limit=config.page_size,
    )


def _build_params(
    config: SendGridEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
    incremental_field: Optional[str],
) -> dict[str, Any]:
    params: dict[str, Any] = dict(config.extra_params)

    # Metadata endpoints carry the page size as a query param; offset endpoints get limit/offset
    # from the paginator, single endpoints take no pagination params.
    if config.pagination == "metadata":
        params["page_size"] = config.page_size

    if config.incremental_param:
        cursor = (
            db_incremental_field_last_value
            if (should_use_incremental_field and incremental_field and db_incremental_field_last_value is not None)
            else None
        )
        if cursor is not None:
            # The filter is inclusive (e.g. created >= start_time); the boundary row re-appears but
            # merge dedupes it on the primary key.
            params[config.incremental_param] = _format_cursor(cursor, config.incremental_param_format)
        elif config.default_backfill_days is not None:
            # No cursor, but the API requires the start param (stats). Backfill a fixed window rather
            # than sending a request the API would reject.
            params[config.incremental_param] = _default_backfill_value(config)

    return params


def _initial_paginator_state(
    config: SendGridEndpointConfig,
    resumable_source_manager: ResumableSourceManager[SendGridResumeConfig],
) -> Optional[dict[str, Any]]:
    if not resumable_source_manager.can_resume():
        return None
    resume = resumable_source_manager.load_state()
    if resume is None:
        return None

    if config.pagination == "offset":
        if resume.offset is not None:
            return {"offset": resume.offset}
        if resume.next_url is not None:
            # Pre-migration state stored the offset inside a URL; re-check the host before trusting it.
            _require_sendgrid_url(resume.next_url)
            return {"offset": _offset_from_url(resume.next_url)}
        return None

    if config.pagination == "metadata" and resume.next_url is not None:
        _require_sendgrid_url(resume.next_url)
        return {"next_url": resume.next_url}

    if (
        config.pagination == "activity"
        and resume.activity_window_start is not None
        and resume.activity_window_end is not None
    ):
        # The paginator re-normalizes both bounds when seeded, rejecting tampered state.
        return {
            "activity_window_start": resume.activity_window_start,
            "activity_window_end": resume.activity_window_end,
        }

    return None


def sendgrid_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SendGridResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
) -> SourceResponse:
    config = SENDGRID_ENDPOINTS[endpoint]

    params = _build_params(config, should_use_incremental_field, db_incremental_field_last_value, incremental_field)

    resource_config: EndpointResource = {
        "name": endpoint,
        "endpoint": {
            "path": config.path,
            "params": params,
            # data_key wraps the array for metadata endpoints ("result"); None means the body
            # is the array itself (suppression/asm/stats). Fail loud on a shape change instead
            # of silently syncing 0 rows.
            "data_selector": config.data_key,
            "data_selector_required": True,
        },
    }

    if config.response_shape == "daily_stats":
        # stats rows are nested one level deeper than the bare array; flatten them into flat daily rows.
        resource_config["data_map"] = _flatten_daily_stats

    # Activity pagination owns its own request params (`query` window + `limit`), including the
    # server-side incremental filter, so it is built with the cursor instead of via `params`.
    paginator: BasePaginator = (
        _build_activity_paginator(
            config, should_use_incremental_field, db_incremental_field_last_value, incremental_field
        )
        if config.pagination == "activity"
        else _build_paginator(config)
    )

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SENDGRID_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so its value is redacted from logs
            # and raised errors; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": paginator,
        },
        "resource_defaults": {},
        "resources": [resource_config],
    }

    initial_paginator_state = _initial_paginator_state(config, resumable_source_manager)

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields the
        # last page (merge dedupes) rather than skipping it.
        if not state:
            return
        if state.get("offset") is not None:
            resumable_source_manager.save_state(SendGridResumeConfig(offset=int(state["offset"])))
        elif state.get("activity_window_end") is not None:
            resumable_source_manager.save_state(
                SendGridResumeConfig(
                    activity_window_start=state.get("activity_window_start"),
                    activity_window_end=state["activity_window_end"],
                )
            )
        elif state.get("next_url"):
            resumable_source_manager.save_state(SendGridResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode=config.sort_mode,
    )


def get_status_code(api_key: str, path: str, params: Optional[dict[str, Any]] = None) -> Optional[int]:
    """Probe an endpoint to classify the credentials. Returns the HTTP status, or None on a
    transport error."""
    query = urlencode(params if params is not None else {"limit": 1})
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SENDGRID_BASE_URL}{path}?{query}",
        headers=_get_headers(api_key),
    )
    return status


def _probe_params(config: SendGridEndpointConfig) -> dict[str, Any]:
    """Smallest valid request for a permission probe, using the endpoint's own pagination params so
    the probe is never rejected for a param that endpoint doesn't accept."""
    params: dict[str, Any] = dict(config.extra_params)
    if config.pagination == "offset":
        params["limit"] = 1
    elif config.pagination == "metadata":
        params["page_size"] = 1
    elif config.pagination == "activity":
        # `query` is required on /messages, so probe a one-day window for one row. The 403 for a
        # missing add-on or scope fires regardless of the window.
        now = datetime.now(UTC)
        params["limit"] = 1
        params["query"] = _activity_query(_to_activity_timestamp(now - timedelta(days=1)), _to_activity_timestamp(now))
    return params


def get_endpoint_status_code(api_key: str, config: SendGridEndpointConfig) -> Optional[int]:
    return get_status_code(api_key, config.path, _probe_params(config))


def permission_error_for(config: SendGridEndpointConfig) -> str:
    message = f"Your SendGrid API key is missing the `{config.required_scope}` scope."
    if config.permission_note:
        return f"{message} {config.permission_note}"
    return message


def get_endpoint_permissions(api_key: str, endpoints: list[str]) -> dict[str, str | None]:
    """Per-table scope probe for the schema picker: None when the key can read an endpoint, a short
    reason naming the missing scope when it can't.

    Only a definitive denial counts as unreachable. A throttle, 5xx, or transport error leaves the
    table selectable, since sending someone to change scopes that are already correct is worse than
    letting the sync report the real error.
    """
    results: dict[str, str | None] = {}
    for name in endpoints:
        config = SENDGRID_ENDPOINTS.get(name)
        if config is None:
            results[name] = None
            continue
        status = get_endpoint_status_code(api_key, config)
        if status == 401:
            results[name] = "Your SendGrid API key is invalid or expired."
        elif status == 403:
            results[name] = permission_error_for(config)
        else:
            results[name] = None
    return results
