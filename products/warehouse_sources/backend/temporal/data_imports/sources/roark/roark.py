import dataclasses
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.roark.settings import (
    ROARK_ENDPOINTS,
    RoarkEndpointConfig,
)

ROARK_BASE_URL = "https://api.roark.ai/v1"


@dataclasses.dataclass
class RoarkResumeConfig:
    # Cursor (`after`) pointing at the next page to fetch for the cursor-paginated endpoints. `None`
    # means "start at the first page". Saved after a page is yielded so a crash resumes from the next
    # page; merge dedupes any rows already written on the primary key.
    after: str | None = None
    # Offset of the next page to fetch for the offset-paginated endpoints.
    offset: int | None = None


class RoarkCursorPaginator(BasePaginator):
    """Cursor pagination for Roark list endpoints.

    Roark returns rows under ``data`` and pagination signals under ``pagination`` (``hasMore`` +
    ``nextCursor``); the cursor is sent back as the ``after`` query param. Stops when either
    ``hasMore`` is false OR ``nextCursor`` is missing — a stale cursor with ``hasMore=false`` must
    not keep paging.
    """

    def __init__(self) -> None:
        super().__init__()
        self._cursor: Optional[str] = None

    def _apply(self, request: Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params["after"] = self._cursor

    def init_request(self, request: Request) -> None:
        # Honour a seeded resume cursor on the first request.
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        pagination = (response.json() or {}).get("pagination", {}) or {}
        next_cursor = pagination.get("nextCursor")
        if pagination.get("hasMore") and next_cursor:
            self._cursor = next_cursor
            self._has_next_page = True
        else:
            self._has_next_page = False

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"after": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        after = state.get("after")
        if after is not None:
            self._cursor = str(after)
            self._has_next_page = True


class RoarkOffsetPaginator(BasePaginator):
    """Offset pagination for Roark list endpoints that page by ``offset``.

    Advances by the number of rows actually returned, never the requested page size: Roark may cap a
    page below its max size, and jumping by the requested size would skip the rows in the gap. Stops
    when ``pagination.hasMore`` is false or the page is empty.
    """

    def __init__(self, offset: int = 0) -> None:
        super().__init__()
        self.offset = offset

    def init_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["offset"] = self.offset

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        pagination = (response.json() or {}).get("pagination", {}) or {}
        if not pagination.get("hasMore") or not data:
            self._has_next_page = False
            return
        self.offset += len(data)
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params["offset"] = self.offset

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.offset already points at the next page to fetch (update_state advanced it).
        return {"offset": self.offset} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        offset = state.get("offset")
        if offset is not None:
            self.offset = int(offset)
            self._has_next_page = True


def _unwrap_unpaginated(item: dict[str, Any]) -> Any:
    """Reshape an unpaginated (`pagination="none"`) response into rows.

    These endpoints may reply with either a ``{"data": [...]}`` envelope or a bare top-level list. A
    bare list arrives here already split into individual rows (passed through 1:1); an envelope
    arrives as the whole object, so its ``data`` list is exploded into one row per item (a missing or
    non-list ``data`` yields no rows rather than a stray envelope row).
    """
    if isinstance(item, dict) and "data" in item:
        data = item.get("data")
        return data if isinstance(data, list) else []
    return item


def _base_params(config: RoarkEndpointConfig) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if config.max_page_size > 0:
        params["limit"] = config.max_page_size
    if config.sort_by:
        params["sortBy"] = config.sort_by
    if config.sort_direction:
        params["sortDirection"] = config.sort_direction
    return params


def roark_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RoarkResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ROARK_ENDPOINTS[endpoint]

    paginator: BasePaginator
    data_selector: Optional[str]
    data_map = None
    if config.pagination == "cursor":
        paginator = RoarkCursorPaginator()
        data_selector = "data"
    elif config.pagination == "offset":
        paginator = RoarkOffsetPaginator()
        data_selector = "data"
    else:  # "none" — single unpaginated fetch
        paginator = SinglePagePaginator()
        data_selector = None
        data_map = _unwrap_unpaginated

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": _base_params(config),
        "paginator": paginator,
    }
    if data_selector is not None:
        endpoint_config["data_selector"] = data_selector

    resource_config: EndpointResource = {"name": endpoint, "endpoint": endpoint_config}
    if data_map is not None:
        resource_config["data_map"] = data_map

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ROARK_BASE_URL,
            # Auth (Bearer) goes through the framework auth config so its value is redacted from logs
            # and error messages; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
        },
        "resource_defaults": {},
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if resume.after is not None:
                initial_paginator_state = {"after": resume.after}
            elif resume.offset is not None:
                initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the next page (merge dedupes) rather than losing progress.
        if not state:
            return
        if state.get("after") is not None:
            resumable_source_manager.save_state(RoarkResumeConfig(after=str(state["after"])))
        elif state.get("offset") is not None:
            resumable_source_manager.save_state(RoarkResumeConfig(offset=int(state["offset"])))

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
        sort_mode=config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    # `/agent` is a cheap authenticated list endpoint; a 200 confirms the bearer token is genuine.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{ROARK_BASE_URL}/agent?limit=1",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    return ok
