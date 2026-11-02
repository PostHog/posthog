import dataclasses
from typing import Any, Optional, cast

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
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.oncehub.settings import (
    ONCEHUB_ENDPOINTS,
    OncehubEndpointConfig,
)

ONCEHUB_BASE_URL = "https://api.oncehub.com/v2"
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/users"


def _probe_headers(api_key: str) -> dict[str, str]:
    return {"API-Key": api_key, "Accept": "application/json"}


@dataclasses.dataclass(frozen=True)
class OncehubResumeConfig:
    # Cursor for the next page: OnceHub paginates by passing the last item's object ID as `after`.
    # A crashed full-refresh sync resumes from the page after the last one yielded; merge dedupes
    # on `id`. `None` means start from the first page.
    cursor: str | None = None
    # `build_dependent_resource` checkpoint for fan-out endpoints (which parents finished, where the
    # current one stopped), mutually exclusive with `cursor`.
    fanout_state: dict[str, Any] | None = None


class OncehubCursorPaginator(BasePaginator):
    """Cursor pagination for OnceHub v2 list endpoints.

    OnceHub has no numeric offset — each next page is requested with ``after`` set to the previous
    page's last object ID. A page's ``has_more`` flag (or an empty page) terminates the walk. The
    saved cursor points at the next page to fetch, so a resumed run re-issues from there and merge
    dedupes the re-pulled page on ``id``.
    """

    def __init__(self, cursor_param: str = "after") -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self._cursor: Optional[str] = None

    def init_request(self, request: Request) -> None:
        self._apply(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        body = response.json()
        has_more = bool(body.get("has_more")) if isinstance(body, dict) else False
        # Stop on an empty page or once the API says there is no more — matching the hand-rolled walk.
        if not data or not has_more:
            self._has_next_page = False
            return
        self._cursor = data[-1]["id"]
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._apply(request)

    def _apply(self, request: Request) -> None:
        if self._cursor is not None:
            if request.params is None:
                request.params = {}
            request.params[self.cursor_param] = self._cursor

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"cursor": self._cursor} if self._has_next_page and self._cursor is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("cursor")
        if cursor is not None:
            self._cursor = cursor
            self._has_next_page = True


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": ONCEHUB_BASE_URL,
        # Only the non-secret Accept header goes here; the API key rides the framework auth config
        # so it is redacted from logs and raised error messages.
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": "API-Key", "location": "header"},
        "paginator": OncehubCursorPaginator(),
    }


def _list_resource(
    api_key: str,
    config: OncehubEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OncehubResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [
            {
                "name": config.name,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": config.page_size},
                    # OnceHub list endpoints wrap records in {"object": "list", "data": [...], "has_more": bool}.
                    "data_selector": "data",
                    # A 200 body that is not this envelope (missing `data`, or a bare/non-list payload)
                    # means the response shape changed — fail loud instead of silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None and resume.cursor is not None:
            initial_paginator_state = {"cursor": resume.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-fetches
        # the next page (already-yielded pages are persisted) and merge dedupes on the primary key.
        if state and state.get("cursor") is not None:
            resumable_source_manager.save_state(OncehubResumeConfig(cursor=str(state["cursor"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def _fanout_resource(
    api_key: str,
    config: OncehubEndpointConfig,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OncehubResumeConfig],
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    assert config.fanout is not None
    parent = ONCEHUB_ENDPOINTS[config.fanout.parent_name]

    initial_fanout_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_fanout_state = resume.fanout_state

    def save_fanout_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state:
            resumable_source_manager.save_state(OncehubResumeConfig(fanout_state=state))

    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs={config.name: config, parent.name: parent},
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=db_incremental_field_last_value,
            # OnceHub rejects unknown query params, so `limit` goes only to the parent listing
            # (via `fanout.parent_params`), never to the single-object child request.
            page_size_param=None,
            parent_endpoint_extra={
                "paginator": OncehubCursorPaginator(),
                "data_selector": "data",
            },
            child_endpoint_extra={
                "paginator": SinglePagePaginator(),
                "data_selector": "$",
            },
            resume_hook=save_fanout_checkpoint,
            initial_paginator_state=initial_fanout_state,
        ),
    )


def oncehub_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OncehubResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ONCEHUB_ENDPOINTS[endpoint]
    build = _fanout_resource if config.fanout is not None else _list_resource
    resource = build(api_key, config, team_id, job_id, resumable_source_manager, db_incremental_field_last_value)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    """Probe a cheap endpoint to validate the API key.

    The key is account-wide, so one probe validates access to every list endpoint. ``200`` is valid;
    ``401``/``403`` is an auth failure; any other outcome (unexpected status or an unreachable probe)
    is reported as not validated.
    """
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{ONCEHUB_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1",
        headers=_probe_headers(api_key),
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid OnceHub API key"
    if status is None:
        return False, "Could not validate OnceHub API key"
    return False, f"OnceHub returned HTTP {status}"
