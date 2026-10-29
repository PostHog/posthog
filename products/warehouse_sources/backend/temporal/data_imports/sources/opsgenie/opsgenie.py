import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional, cast
from urllib.parse import urlencode

import requests
from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    BasePaginator,
    JSONResponseCursorPaginator,
    JSONResponsePaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.opsgenie.settings import (
    DEFAULT_PAGE_SIZE,
    OPSGENIE_ENDPOINTS,
    OpsgenieEndpointConfig,
)

OPSGENIE_BASE_URLS = {
    "us": "https://api.opsgenie.com",
    "eu": "https://api.eu.opsgenie.com",
}

PAGE_SIZE = DEFAULT_PAGE_SIZE

# The alert/incident search endpoints reject requests where `offset + limit` exceeds
# 20,000. Instead of truncating there, we re-slice the search into a new createdAt
# window starting from the last row we read (rows are sorted createdAt ascending, and
# createdAt is immutable, so the slices tile the full history).
MAX_SEARCH_RESULTS = 20_000

REQUEST_TIMEOUT_SECONDS = 60


@dataclasses.dataclass(frozen=True)
class OpsgenieResumeConfig:
    offset: int = 0
    window_start_ms: Optional[int] = None
    # Fan-out tables checkpoint the shape `build_dependent_resource` emits: which parents finished
    # and where the current one stopped.
    fanout_state: Optional[dict[str, Any]] = None


def _get_base_url(region: str) -> str:
    return OPSGENIE_BASE_URLS.get(region, OPSGENIE_BASE_URLS["us"])


def _get_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"GenieKey {api_key}",
        "Content-Type": "application/json",
    }


def _to_epoch_ms(value: Any) -> Optional[int]:
    """Convert an incremental field value to epoch milliseconds for Opsgenie's search syntax."""
    if isinstance(value, datetime):
        utc_value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
        return int(utc_value.timestamp() * 1000)
    if isinstance(value, date):
        return int(datetime.combine(value, datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    if isinstance(value, int | float):
        return int(value)
    if isinstance(value, str):
        try:
            return _to_epoch_ms(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _parse_created_at_ms(item: dict[str, Any]) -> Optional[int]:
    created_at = item.get("createdAt")
    if not isinstance(created_at, str):
        return None
    try:
        return _to_epoch_ms(datetime.fromisoformat(created_at.replace("Z", "+00:00")))
    except ValueError:
        return None


class OpsgeniePaginator(BasePaginator):
    """Offset paginator for Opsgenie's list/search endpoints.

    Beyond plain offset pagination it reproduces the search-window re-slicing the
    alert/incident search endpoints need: those cap `offset + limit` at 20,000, so
    when the next page would cross the cap this paginator anchors a new
    `createdAt >= <last row ms>` window and restarts the offset instead of truncating.
    Because createdAt is immutable and the search is sorted ascending, the windows tile
    the full history without dropping rows (the `>=` boundary re-reads one millisecond;
    the merge dedupes on id).
    """

    def __init__(
        self,
        limit: int,
        supports_search_window: bool,
        offset: int = 0,
        window_start_ms: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.limit = limit
        self.supports_search_window = supports_search_window
        self.offset = offset
        self.window_start_ms = window_start_ms

    def _apply(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["offset"] = self.offset
        # A re-sliced window takes precedence over any incremental `query` seeded on the
        # first request; once set it stays until the next re-slice.
        if self.window_start_ms is not None:
            request.params["query"] = f"createdAt >= {self.window_start_ms}"

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        if not data:
            self._has_next_page = False
            return

        try:
            body = response.json()
        except Exception:
            body = {}
        has_next = bool((body.get("paging") or {}).get("next"))
        if not has_next or len(data) < self.limit:
            self._has_next_page = False
            return

        next_offset = self.offset + self.limit
        if self.supports_search_window and next_offset + self.limit > MAX_SEARCH_RESULTS:
            # Approaching the 20,000-result search cap: open a new createdAt window from
            # the last row read and restart the offset instead of truncating the sync.
            new_window_start_ms = _parse_created_at_ms(data[-1])
            if new_window_start_ms is None or new_window_start_ms == self.window_start_ms:
                # Can't advance the window (missing createdAt, or >20k rows share one
                # millisecond) — stop rather than loop on the same slice forever.
                self._has_next_page = False
                return
            self.window_start_ms = new_window_start_ms
            self.offset = 0
        else:
            self.offset = next_offset

        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.offset/window_start_ms already point at the next page (update_state advanced them).
        if self._has_next_page:
            return {"offset": self.offset, "window_start_ms": self.window_start_ms}
        return None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self.window_start_ms = state.get("window_start_ms")
            self._has_next_page = True


def _flatten_team_member(row: dict[str, Any]) -> dict[str, Any]:
    user = row.get("user") or {}
    return {**row, "user_id": user.get("id"), "username": user.get("username")}


_CHILD_ROW_MAPS = {"team_members": _flatten_team_member}


def validate_credentials(api_key: str, region: str, endpoint: Optional[str] = None) -> tuple[bool, int, str | None]:
    """Probe Opsgenie with a cheap single-row request.

    Returns ``(ok, status_code, error_message)``. ``status_code`` is 0 on transport failure.
    The caller decides how to treat 403 (valid key, missing access for the probed endpoint).
    """
    config = OPSGENIE_ENDPOINTS.get(endpoint) if endpoint else None
    if config is not None and config.fanout is not None:
        # A fan-out path needs a parent id, so probe the parent listing it reads first.
        config = OPSGENIE_ENDPOINTS[config.fanout.parent_name]
    path = config.path if config else "/v2/users"
    params = {"limit": 1} if config is None or config.paginated else {}
    url = f"{_get_base_url(region)}{path}"
    if params:
        url = f"{url}?{urlencode(params)}"

    try:
        response = make_tracked_session(redact_values=(api_key,)).get(url, headers=_get_headers(api_key), timeout=10)
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)

    if response.status_code == 200:
        return True, 200, None
    if response.status_code == 401:
        return False, 401, "Invalid Opsgenie API key"
    if response.status_code == 403:
        return False, 403, "Your Opsgenie API key does not have access to this resource"
    if response.status_code == 422:
        # Opsgenie rejects malformed keys with a 422 before checking auth.
        return False, 422, "Your Opsgenie API key format is not valid"

    try:
        message = response.json().get("message", response.text)
    except Exception:
        message = response.text
    return False, response.status_code, message


def opsgenie_source(
    api_key: str,
    region: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpsgenieResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    config = OPSGENIE_ENDPOINTS[endpoint]
    client_config: ClientConfig = {
        "base_url": _get_base_url(region),
        # Framework auth so the key is redacted from logs and error messages; the GenieKey
        # scheme is Opsgenie's own bearer-style header.
        "auth": {
            "type": "api_key",
            "api_key": f"GenieKey {api_key}",
            "name": "Authorization",
            "location": "header",
        },
        # Alert logs follow the response's `paging.next` URL; pin it to the regional API host.
        "allowed_hosts": [],
    }

    if config.fanout is not None:
        return _fanout_source(endpoint, config, client_config, team_id, job_id, resumable_source_manager)

    params: dict[str, Any] = {}
    paginator: BasePaginator
    if config.paginated:
        params["limit"] = PAGE_SIZE
        if config.supports_search_window:
            # createdAt is immutable, so an ascending sort means new rows append to the end
            # and never shift pages we've already read. Sent on every sync (not just
            # incremental ones) so full refreshes paginate over a stable ordering too.
            params["sort"] = "createdAt"
            params["order"] = "asc"
            if should_use_incremental_field and db_incremental_field_last_value is not None:
                start_ms = _to_epoch_ms(db_incremental_field_last_value)
                if start_ms is not None:
                    # `>=` re-fetches rows sharing the boundary millisecond; merge dedupes on id.
                    params["query"] = f"createdAt >= {start_ms}"
        paginator = OpsgeniePaginator(limit=PAGE_SIZE, supports_search_window=config.supports_search_window)
    else:
        # teams, schedules, escalations, integrations return their full collection at once.
        paginator = SinglePagePaginator()

    rest_config: RESTAPIConfig = {
        "client": {**client_config, "paginator": paginator},
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Opsgenie wraps every collection under `data`; a missing key is treated as an
                    # empty page (matching the previous `data.get("data", [])`), not a hard error.
                    "data_selector": "data",
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if config.paginated and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset, "window_start_ms": resume.window_start_ms}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Save AFTER a page is yielded (only when a next page remains) so a crash re-yields the
        # last page rather than skipping it; merge dedupes on the primary key.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(
                OpsgenieResumeConfig(offset=int(state["offset"]), window_start_ms=state.get("window_start_ms"))
            )

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
        # Search-window endpoints request createdAt ascending; full-refresh endpoints
        # replace wholesale, so ascending is correct everywhere.
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def _fanout_source(
    endpoint: str,
    config: OpsgenieEndpointConfig,
    client_config: ClientConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OpsgenieResumeConfig],
) -> SourceResponse:
    assert config.fanout is not None
    parent_config = OPSGENIE_ENDPOINTS[config.fanout.parent_name]
    parent_paginator: BasePaginator = (
        OpsgeniePaginator(limit=parent_config.page_size, supports_search_window=parent_config.supports_search_window)
        if parent_config.paginated
        else SinglePagePaginator()
    )
    child_paginator: BasePaginator
    if config.next_cursor_path:
        child_paginator = JSONResponseCursorPaginator(cursor_path=config.next_cursor_path, cursor_param="offset")
    elif config.next_url_path:
        child_paginator = JSONResponsePaginator(next_url_path=config.next_url_path)
    else:
        child_paginator = SinglePagePaginator()

    # The shared fan-out checkpoint lists every finished parent, so its size grows with each parent.
    # Only the small, unpaginated parents (schedules, teams) are resumable; the incident timeline
    # and alert logs start again from the first parent after an interruption.
    resumable = not parent_config.paginated
    resume = resumable_source_manager.load_state() if resumable and resumable_source_manager.can_resume() else None

    def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(OpsgenieResumeConfig(fanout_state=state))

    resource = cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=OPSGENIE_ENDPOINTS,
            child_endpoint=endpoint,
            fanout=config.fanout,
            client_config=client_config,
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            # Schedules and teams return their full collection and take no page size.
            page_size_param="limit" if parent_config.paginated else None,
            parent_endpoint_extra={"paginator": parent_paginator, "data_selector": parent_config.data_selector},
            child_endpoint_extra={"paginator": child_paginator, "data_selector": config.data_selector},
            resume_hook=save_fanout_checkpoint if resumable else None,
            initial_paginator_state=resume.fanout_state if resume else None,
        ),
    )
    row_map = _CHILD_ROW_MAPS.get(endpoint)
    if row_map is not None:
        resource = resource.add_map(row_map)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )
