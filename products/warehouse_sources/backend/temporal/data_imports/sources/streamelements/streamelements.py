import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional

import requests
from dateutil import parser as dateutil_parser
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.streamelements.settings import (
    STREAMELEMENTS_BASE_URL,
    STREAMELEMENTS_ENDPOINTS,
)


@dataclasses.dataclass
class StreamElementsResumeConfig:
    # Paginator snapshot: {"offset": int} for offset endpoints, {"before": int} for activities.
    paginator_state: dict[str, Any]


def _to_epoch_ms(value: Any) -> Optional[int]:
    """Convert an incremental cursor value (datetime/date/epoch/ISO string) to epoch
    milliseconds for StreamElements' after/before datetime filters."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return round(dt.timestamp() * 1000)
    if isinstance(value, date):
        return round(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return _to_epoch_ms(dateutil_parser.parse(value))
        except (ValueError, OverflowError):
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class StreamElementsActivitiesPaginator(BasePaginator):
    """Datetime-window paginator for GET /activities/{channel}.

    The activity feed has no offset or cursor pagination and no sort param: each request
    returns up to ``limit`` of the newest events inside the ``after``/``before`` window. We
    page by walking the ``before`` bound down to just past the oldest event of each page
    (+1ms so events sharing that millisecond aren't skipped at the page boundary; the
    resulting overlap dedupes on the ``_id`` merge key). ``after`` stays fixed, so on
    incremental syncs the server bounds the walk at the watermark.
    """

    def __init__(self, page_size: int, initial_before_ms: int) -> None:
        super().__init__()
        self._page_size = page_size
        self._next_before_ms = initial_before_ms

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = self._page_size
        request.params["before"] = self._next_before_ms

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data or len(data) < self._page_size:
            self._has_next_page = False
            return

        created_values = [
            _to_epoch_ms(item.get("createdAt")) for item in data if isinstance(item, dict) and item.get("createdAt")
        ]
        timestamps = [value for value in created_values if value is not None]
        if not timestamps:
            # A full page without parseable createdAt values means the response shape changed;
            # stop rather than loop on the same window forever.
            self._has_next_page = False
            return

        next_before = min(timestamps) + 1
        if next_before >= self._next_before_ms:
            # Force progress when a whole page shares the millisecond just below the current
            # bound; any events beyond page_size in that same millisecond are skipped.
            next_before = self._next_before_ms - 1
        self._next_before_ms = next_before
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["limit"] = self._page_size
        request.params["before"] = self._next_before_ms

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"before": self._next_before_ms} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        before = state.get("before")
        if before is not None:
            self._next_before_ms = int(before)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"StreamElementsActivitiesPaginator(before={self._next_before_ms})"


def _tracked_session(api_token: str) -> requests.Session:
    """Build the session every StreamElements request runs on.

    ``capture=False``: responses carry donor email addresses, tip and chat message text,
    activity payloads and redemption input — free-text the name-based scrubbers can't
    recognise, so their bodies must stay out of HTTP sample capture (still metered and logged).
    """
    return make_tracked_session(redact_values=(api_token,), capture=False)


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": STREAMELEMENTS_BASE_URL,
        "headers": {"Accept": "application/json"},
        # Channel JWT tokens and OAuth2 access tokens both go in a Bearer Authorization
        # header. Framework auth redacts the value from logs.
        "auth": {"type": "bearer", "token": api_token},
        "session": _tracked_session(api_token),
    }


def get_channel_id(api_token: str) -> str:
    """Resolve the 24-hex channel id every other endpoint is scoped by."""
    response = _tracked_session(api_token).get(
        f"{STREAMELEMENTS_BASE_URL}/channels/me",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    channel_id = response.json().get("_id")
    if not channel_id:
        raise ValueError("StreamElements did not return a channel id for this token")
    return str(channel_id)


def validate_credentials(api_token: str) -> tuple[bool, str | None]:
    """Confirm the token is genuine with one cheap probe of GET /channels/me."""
    try:
        response = _tracked_session(api_token).get(
            f"{STREAMELEMENTS_BASE_URL}/channels/me",
            headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        return False, str(e)

    if response.status_code in (401, 403):
        return (
            False,
            "Invalid StreamElements token. Copy the JWT token from your StreamElements dashboard and try again.",
        )
    if not response.ok:
        return False, f"StreamElements API error: {response.status_code} {response.text}"

    return True, None


def _now_ms() -> int:
    return round(datetime.now(tz=UTC).timestamp() * 1000)


def streamelements_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[StreamElementsResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = STREAMELEMENTS_ENDPOINTS[endpoint]

    path = config.path
    if "{channel}" in path:
        path = path.format(channel=get_channel_id(api_token))

    params: dict[str, Any] = dict(config.params)
    use_incremental = should_use_incremental_field and config.supports_incremental
    if use_incremental:
        # after accepts epoch milliseconds; on the first sync the watermark is None and the
        # param is dropped, fetching from the beginning of history.
        params["after"] = {
            "type": "incremental",
            "cursor_path": "createdAt",
            "convert": _to_epoch_ms,
        }

    paginator: BasePaginator
    if config.kind == "offset":
        paginator = OffsetPaginator(limit=config.page_size, total_path=config.total_path)
    elif config.kind == "activities":
        paginator = StreamElementsActivitiesPaginator(page_size=config.page_size, initial_before_ms=_now_ms())
    else:
        paginator = SinglePagePaginator()

    endpoint_config: Endpoint = {
        "path": path,
        "params": params,
        "paginator": paginator,
        "data_selector": config.data_selector,
        # Fail loud when the response shape changes instead of silently syncing 0 rows —
        # except for single-object endpoints, whose dict body intentionally becomes one row.
        "data_selector_required": config.returns_list,
    }

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
                "endpoint": endpoint_config,
                "table_format": "delta",
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.kind != "single" and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = resume.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only while a next page remains. Both paginators snapshot the NEXT page to
        # fetch and the hook runs after the current page is yielded, so a crash between pages
        # never skips rows.
        if state:
            resumable_source_manager.save_state(StreamElementsResumeConfig(paginator_state=state))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if use_incremental else None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        # Tips request sort=createdAt (documented ascending sort). Activities have no sort
        # param and arrive newest-first inside each window, so with sort_mode="desc" the
        # pipeline only commits the cursor watermark once a sync fully completes; the `after`
        # server filter (not row ordering) is what bounds each incremental fetch. Live
        # ordering semantics were not verified against the API as no test credentials were
        # available.
        sort_mode="desc" if config.kind == "activities" else "asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )
