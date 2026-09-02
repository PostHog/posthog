import logging
import dataclasses
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from requests import Request, Response
from requests.exceptions import RequestException

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.loop_returns.settings import (
    DEFAULT_BACKFILL_DAYS,
    DEFAULT_PAGE_SIZE,
    FILTER_FIELDS,
    LOOP_RETURNS_ENDPOINTS,
    MAX_BACKFILL_DAYS,
    MAX_WINDOW_DAYS,
    LoopReturnsEndpointConfig,
)

logger = logging.getLogger(__name__)

# Loop versions its API by date in the URL path (`/api/2026-07/...`). `v1` is a legacy
# convenience alias for the `2026-07` GA release, kept for backward compatibility and being
# phased out; new integrations pin the explicit date version.
API_VERSION_V1 = "v1"
API_VERSION_2026_07 = "2026-07"

API_HOST = "https://api.loopreturns.com"
AUTH_HEADER = "X-Authorization"
PROBE_TIMEOUT_SECONDS = 30
INVALID_START_DATE_ERROR = "Start date must be a date or datetime, for example 2024-01-01"
START_DATE_TOO_OLD_ERROR = (
    f"Start date can't be more than {MAX_BACKFILL_DAYS // 365} years ago. Pick a more recent date."
)


def base_url(api_version: str) -> str:
    return f"{API_HOST}/api/{api_version}"


def _format_datetime(value: datetime) -> str:
    """Loop's documented format is `2022-01-01T00:00:00.000Z`; millisecond precision keeps window
    boundaries exact so a watermark-derived start doesn't truncate backwards."""
    utc_value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    raise ValueError(f"Cannot parse a datetime from {value!r}")


def start_date_error(start_date: str, now: Optional[datetime] = None) -> Optional[str]:
    """Why a configured start date is unusable, or None if it's fine.

    Rejects a date we can't parse, and one reaching back further than `MAX_BACKFILL_DAYS`: the
    returns endpoint walks history one 120-day window per state pass, so an unbounded lookback
    would turn a single sync into thousands of empty-window requests.
    """
    try:
        parsed = parse_datetime(start_date)
    except ValueError:
        return INVALID_START_DATE_ERROR

    floor = (now or datetime.now(UTC)) - timedelta(days=MAX_BACKFILL_DAYS)
    if parsed < floor:
        return START_DATE_TOO_OLD_ERROR

    return None


def resolve_window_start(
    *,
    now: datetime,
    start_date: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> datetime:
    """Where a sync begins walking Loop's history.

    An incremental run resumes at the stored watermark. Everything else starts at the configured
    start date, falling back to `DEFAULT_BACKFILL_DAYS` — Loop returns only the previous 24 hours
    when neither `from` nor `to` is sent, so a fresh sync always needs an explicit start.
    """
    if should_use_incremental_field and db_incremental_field_last_value is not None:
        return parse_datetime(db_incremental_field_last_value)

    if start_date:
        return parse_datetime(start_date)

    return now - timedelta(days=DEFAULT_BACKFILL_DAYS)


def resolve_filter_field(should_use_incremental_field: bool, incremental_field: Optional[str]) -> str:
    """Which timestamp `from`/`to` apply to. Honors the cursor field the user picked."""
    if should_use_incremental_field and incremental_field in FILTER_FIELDS:
        return incremental_field
    return FILTER_FIELDS[0]


def next_cursor(response: Response) -> Optional[str]:
    """The `cursor` value of the response's `nextPageUrl`, or `None` on the last page.

    The cursor is re-applied to our own params rather than following `nextPageUrl` verbatim, so the
    window and state filters stay attached to every page even if Loop's link were to drop them.
    """
    try:
        body = response.json()
    except ValueError:
        return None

    if not isinstance(body, dict):
        return None

    next_page_url = body.get("nextPageUrl")
    if not next_page_url or not isinstance(next_page_url, str):
        return None

    cursors = parse_qs(urlsplit(next_page_url).query).get("cursor")
    if not cursors or not cursors[0]:
        # Undocumented shape: a next link we can't turn into a cursor. Stop this window rather than
        # refetch page one forever, and log it so a link format change is visible.
        logger.warning("Loop Returns nextPageUrl carried no cursor; treating the page as the last one")
        return None

    return cursors[0]


@dataclasses.dataclass
class LoopReturnsResumeConfig:
    """Checkpoint for a windowed endpoint: which state pass, which window, which page.

    Windows are re-derived from `window_start` with a fixed width, so boundaries stay identical
    across attempts. State is saved after a batch is yielded, so a crash re-yields the last batch
    (merge dedupes on the primary key) instead of skipping it.
    """

    window_start: str
    state_index: int = 0
    cursor: Optional[str] = None


class LoopReturnsPaginator(BasePaginator):
    """Walks `state` passes, then 120-day windows within each pass, then cursor pages in a window.

    Loop caps a list request at a 120-day range and its `state` filter takes a single value, so a
    full history needs several requests along both axes. Pages are ordered oldest window first;
    within a window Loop documents no ordering, which is why the source declares `sort_mode="desc"`
    for incremental syncs and lets the watermark land only once a run completes.
    """

    def __init__(
        self,
        *,
        config: LoopReturnsEndpointConfig,
        window_start: datetime,
        window_end: datetime,
        filter_field: Optional[str] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        super().__init__()
        self._config = config
        self._overall_start = window_start
        self._overall_end = window_end
        self._filter_field = filter_field
        self._page_size = page_size
        self._state_index = 0
        self._current_start = window_start
        self._cursor: Optional[str] = None
        self._previous_cursor: Optional[str] = None

    @property
    def current_window(self) -> tuple[datetime, datetime]:
        end = min(self._current_start + timedelta(days=MAX_WINDOW_DAYS), max(self._overall_end, self._current_start))
        return self._current_start, end

    def _apply(self, request: Request) -> None:
        params = request.params if request.params is not None else {}
        request.params = params

        if self._config.windowed:
            start, end = self.current_window
            params["from"] = _format_datetime(start)
            params["to"] = _format_datetime(end)
            if self._config.supports_filter_param and self._filter_field:
                params["filter"] = self._filter_field

        if self._config.states:
            params["state"] = self._config.states[self._state_index]

        if self._config.paginate:
            params["paginate"] = "true"
            params["pageSize"] = self._page_size
            if self._cursor is not None:
                params["cursor"] = self._cursor
            else:
                params.pop("cursor", None)

    def _advance_window(self) -> None:
        _, end = self.current_window
        if end < self._overall_end:
            self._current_start = end
            self._has_next_page = True
            return

        if self._state_index + 1 < len(self._config.states):
            self._state_index += 1
            self._current_start = self._overall_start
            self._has_next_page = True
            return

        self._has_next_page = False

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if self._config.paginate:
            cursor = next_cursor(response)
            if cursor is not None and cursor != self._previous_cursor:
                self._previous_cursor = cursor
                self._cursor = cursor
                self._has_next_page = True
                return
            if cursor is not None:
                logger.warning("Loop Returns pagination is not advancing; treating the page as the last one")

        self._cursor = None
        self._previous_cursor = None
        self._advance_window()

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {
            "window_start": _format_datetime(self._current_start),
            "state_index": self._state_index,
            "cursor": self._cursor,
        }

    def set_resume_state(self, state: dict[str, Any]) -> None:
        window_start = state.get("window_start")
        if window_start is None:
            return

        self._current_start = parse_datetime(window_start)
        saved_index = int(state.get("state_index") or 0)
        self._state_index = min(max(saved_index, 0), max(len(self._config.states) - 1, 0))
        cursor = state.get("cursor")
        self._cursor = str(cursor) if cursor is not None else None
        # Seed the repeat guard so a checkpoint whose cursor the API echoes back stops the window
        # instead of looping on the same page.
        self._previous_cursor = self._cursor
        self._has_next_page = True

    def __str__(self) -> str:
        return f"LoopReturnsPaginator(endpoint={self._config.name})"


def get_resource(config: LoopReturnsEndpointConfig, should_use_incremental_field: bool) -> EndpointResource:
    endpoint: Endpoint = {"path": config.path}
    if config.data_selector is not None:
        endpoint["data_selector"] = config.data_selector

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def probe_endpoint(api_key: str, api_version: str, endpoint: str) -> tuple[bool, str | None]:
    """One cheap request against `endpoint`, reporting whether the key can read it."""
    config = LOOP_RETURNS_ENDPOINTS[endpoint]

    params: dict[str, Any] = {}
    if config.windowed:
        end = datetime.now(UTC)
        params["from"] = _format_datetime(end - timedelta(hours=1))
        params["to"] = _format_datetime(end)
    if config.paginate:
        params["paginate"] = "true"
        params["pageSize"] = 1

    session = make_tracked_session(redact_values=(api_key,))
    try:
        response = session.get(
            f"{base_url(api_version)}{config.path}",
            headers={AUTH_HEADER: api_key},
            params=params,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except RequestException as e:
        return False, str(e)

    if response.ok:
        return True, None

    if response.status_code in (401, 403):
        return (
            False,
            f"Loop rejected the API key for {endpoint}. Check that the key exists and has the "
            f"{config.required_scope} scope.",
        )

    return False, f"Loop returned HTTP {response.status_code} for {endpoint}: {response.text[:200]}"


def validate_credentials(api_key: str, api_version: str, schema_name: Optional[str] = None) -> tuple[bool, str | None]:
    if schema_name is not None and schema_name in LOOP_RETURNS_ENDPOINTS:
        return probe_endpoint(api_key, api_version, schema_name)

    is_valid, error = probe_endpoint(api_key, api_version, "returns")
    if is_valid:
        return True, None

    # A key scoped for another table only is still a working key, so don't block setup on the
    # returns probe alone. Per-table scope gaps surface in the table picker instead.
    fallback_valid, _ = probe_endpoint(api_key, api_version, "destinations")
    if fallback_valid:
        return True, None

    return False, error


def endpoint_permissions(api_key: str, api_version: str, endpoints: list[str]) -> dict[str, str | None]:
    permissions: dict[str, str | None] = {}
    for endpoint in endpoints:
        if endpoint not in LOOP_RETURNS_ENDPOINTS:
            permissions[endpoint] = None
            continue

        is_valid, error = probe_endpoint(api_key, api_version, endpoint)
        permissions[endpoint] = None if is_valid else error
    return permissions


def loop_returns_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    api_version: str,
    resumable_source_manager: ResumableSourceManager[LoopReturnsResumeConfig],
    start_date: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: Optional[str] = None,
    now: Optional[datetime] = None,
) -> SourceResponse:
    config = LOOP_RETURNS_ENDPOINTS[endpoint]
    window_end = now or datetime.now(UTC)

    paginator: BasePaginator
    if config.windowed:
        paginator = LoopReturnsPaginator(
            config=config,
            window_start=resolve_window_start(
                now=window_end,
                start_date=start_date,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            ),
            window_end=window_end,
            filter_field=resolve_filter_field(should_use_incremental_field, incremental_field),
        )
    else:
        paginator = SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": base_url(api_version),
            "auth": {
                "type": "api_key",
                "api_key": api_key,
                "name": AUTH_HEADER,
                "location": "header",
            },
            "paginator": paginator,
        },
        "resources": [get_resource(config, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.windowed and resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = dataclasses.asdict(resume_config)

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Called after each batch is yielded; `None` once the paginator is exhausted.
        if not state or not state.get("window_start"):
            return
        resumable_source_manager.save_state(
            LoopReturnsResumeConfig(
                window_start=str(state["window_start"]),
                state_index=int(state.get("state_index") or 0),
                cursor=state.get("cursor"),
            )
        )

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        # Window bounds are computed here, not by the framework's incremental params.
        None,
        resume_hook=save_checkpoint if config.windowed else None,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=list(config.primary_keys),
        # Loop documents no ordering within a window, so a mid-sync watermark write could skip rows
        # the run never reached. "desc" defers that write to a successful job end
        # (finalize_desc_sort_incremental_value); the next run re-reads from the old watermark and
        # merge dedupes. Full-refresh syncs keep no watermark, so their sort mode is moot.
        sort_mode="desc" if should_use_incremental_field else "asc",
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
