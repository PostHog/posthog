from datetime import datetime
from typing import Any, Optional

from requests import Request, Response

from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    Endpoint,
    EndpointResource,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
    frozen,
    make_tracked_session,
    parse_datetime_value,
    rename_parent_fields,
    rest_api_resources,
    validate_via_probe,
)
from products.warehouse_sources.sources.svix.settings import SVIX_ENDPOINTS, SvixEndpointConfig

SVIX_BASE_URL = "https://api.svix.com/api/v1"
# The list endpoints accept a `limit` of up to 250; the largest page minimises round trips.
PAGE_SIZE = 250
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint.
DEFAULT_PROBE_PATH = "/event-type"


@frozen
class SvixResumeConfig:
    # Opaque cursor returned by the previous page. Svix cursor pagination is deterministic, so a
    # crashed full-refresh sync resumes from the page after the last one yielded; merge dedupes on
    # the primary key. `None` means start from the beginning.
    iterator: Optional[str] = None
    # Paginator state of a per-application fan-out (completed parents plus the in-progress child
    # cursor), as the REST framework hands it to the resume hook.
    fanout_state: Optional[dict[str, Any]] = None


def _headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs
    # and raised error messages; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


class SvixCursorPaginator(BasePaginator):
    """Svix list endpoints paginate with an opaque ``iterator`` cursor and flag the last page with a
    ``done`` boolean, returning ``{"data": [...], "iterator": "...", "done": bool}``. The cursor is
    echoed even on the final page, so termination keys off ``done`` (a missing ``done`` is treated as
    terminal, matching ``data.get("done", True)``) plus a missing/null next cursor. A plain cursor
    paginator that stops only on a falsy cursor would loop forever here."""

    def __init__(
        self,
        cursor_param: str = "iterator",
        stop_before: Optional[datetime] = None,
        timestamp_field: str = "timestamp",
    ) -> None:
        super().__init__()
        self.cursor_param = cursor_param
        self._cursor_value: Optional[str] = None
        # Svix lists newest first. An incremental run stops after the first page that reaches back
        # past the watermark instead of using `after`, because `after` flips the order to ascending
        # and caps the window at 90 days past that date, so a quiet period would stall the sync.
        self._stop_before = stop_before
        self._timestamp_field = timestamp_field

    def init_request(self, request: Request) -> None:
        # Omit the cursor on the first request — Svix rejects an empty cursor value. Only inject when
        # a resume cursor was seeded.
        if self._cursor_value is not None:
            self._inject(request)

    def update_state(self, response: Response, data: Optional[list[Any]] = None) -> None:
        try:
            body = response.json()
        except Exception:
            body = {}
        if not isinstance(body, dict) or body.get("done", True):
            self._has_next_page = False
            return
        cursor = body.get("iterator")
        if cursor is None or self._reached_watermark(data):
            self._has_next_page = False
            return
        self._cursor_value = cursor
        self._has_next_page = True

    def _reached_watermark(self, data: Optional[list[Any]]) -> bool:
        if self._stop_before is None or not data:
            return False
        timestamps = [parse_datetime_value(row.get(self._timestamp_field)) for row in data if isinstance(row, dict)]
        known = [ts for ts in timestamps if ts is not None]
        return bool(known) and min(known) < self._stop_before

    def update_request(self, request: Request) -> None:
        if self._cursor_value is not None:
            self._inject(request)

    def _inject(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.cursor_param] = self._cursor_value

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        return {"iterator": self._cursor_value} if self._has_next_page and self._cursor_value is not None else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        cursor = state.get("iterator")
        if cursor is not None:
            self._cursor_value = cursor
            self._has_next_page = True

    def __str__(self) -> str:
        return f"SvixCursorPaginator(cursor_param={self.cursor_param})"


def _list_endpoint(path: str, params: dict[str, Any], paginator: SvixCursorPaginator) -> Endpoint:
    return {
        "path": path,
        "params": {"limit": PAGE_SIZE, **params},
        # Set on every endpoint: a path that ends in a placeholder defaults to a single page.
        "paginator": paginator,
        "data_selector": "data",
        # A 200 whose body isn't the expected `{"data": [...]}` envelope is treated as a transient
        # bad shape and retried.
        "data_selector_malformed_retryable": True,
    }


def _app_id_param() -> dict[str, Any]:
    return {"app_id": {"type": "resolve", "resource": "applications", "field": "id"}}


def _applications_resource() -> EndpointResource:
    return {"name": "applications", "endpoint": _list_endpoint("/app", {}, SvixCursorPaginator())}


def _endpoints_resource(name: str, paginator: SvixCursorPaginator) -> EndpointResource:
    return {
        "name": name,
        "include_from_parent": ["id"],
        "endpoint": _list_endpoint(SVIX_ENDPOINTS["endpoints"].path, _app_id_param(), paginator),
        "data_map": rename_parent_fields("applications", {"id": "app_id"}),
    }


def _resources(config: SvixEndpointConfig, stop_before: Optional[datetime]) -> list[str | EndpointResource]:
    paginator = SvixCursorPaginator(stop_before=stop_before, timestamp_field=config.incremental_field or "timestamp")
    if config.parent is None:
        return [{"name": config.name, "endpoint": _list_endpoint(config.path, config.params, paginator)}]

    if config.parent == "applications":
        if config.name == "endpoints":
            return [_applications_resource(), _endpoints_resource(config.name, paginator)]
        child: EndpointResource = {
            "name": config.name,
            "include_from_parent": ["id"],
            "endpoint": _list_endpoint(config.path, {**_app_id_param(), **config.params}, paginator),
            "data_map": rename_parent_fields("applications", {"id": "app_id"}),
        }
        return [_applications_resource(), child]

    params: dict[str, Any] = {
        "app_id": {"type": "resolve", "resource": "endpoints", "field": "app_id"},
        "endpoint_id": {"type": "resolve", "resource": "endpoints", "field": "id"},
        **config.params,
    }
    renames = {"app_id": "app_id"}
    endpoint = _list_endpoint(config.path, params, paginator)
    if config.single_object:
        renames["id"] = "endpoint_id"
        endpoint = {
            "path": config.path,
            "params": params,
            "paginator": "single_page",
            "data_selector": None,
            "data_selector_required": False,
        }
    last: EndpointResource = {
        "name": config.name,
        "include_from_parent": list(renames),
        "endpoint": endpoint,
        "data_map": rename_parent_fields("endpoints", renames),
    }
    return [_applications_resource(), _endpoints_resource("endpoints", SvixCursorPaginator()), last]


def svix_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SvixResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = SVIX_ENDPOINTS[endpoint]
    stop_before = parse_datetime_value(db_incremental_field_last_value) if config.incremental_field else None
    is_fanout = config.parent is not None

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": SVIX_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "bearer", "token": api_key},
        },
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": _resources(config, stop_before),
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            if is_fanout:
                initial_paginator_state = resume.fanout_state
            elif resume.iterator is not None:
                initial_paginator_state = {"iterator": resume.iterator}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # The framework calls this only for a top-level list or a one-level fan-out. A two-level
        # fan-out (applications -> endpoints -> child) carries no resume state.
        if is_fanout:
            if state:
                resumable_source_manager.save_state(SvixResumeConfig(fanout_state=state))
        elif state and state.get("iterator") is not None:
            resumable_source_manager.save_state(SvixResumeConfig(iterator=state["iterator"]))

    resource = next(
        resource
        for resource in rest_api_resources(
            rest_config,
            team_id,
            job_id,
            # The watermark is applied by the paginator, not by an `incremental` endpoint config.
            None,
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        if resource.name == endpoint
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=None if config.partition_key else 1,
        partition_size=None if config.partition_key else 1,
        partition_keys=[config.partition_key] if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
    )


def check_access(api_key: str, path: str = DEFAULT_PROBE_PATH) -> tuple[int, Optional[str]]:
    """Probe a single endpoint to validate the API key.

    Returns ``(status, message)``: ``200`` reachable, ``401``/``403`` auth failure, ``0`` for a
    connection problem, other HTTP status otherwise.
    """
    _ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SVIX_BASE_URL}{path}?limit=1",
        headers={"Authorization": f"Bearer {api_key}", **_headers()},
        timeout=15,
    )
    if status is None:
        return 0, "Could not connect to Svix"
    if status in (401, 403):
        return status, None
    if status != 200:
        return status, f"Svix returned HTTP {status}"
    return 200, None


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    status, message = check_access(api_key)
    if status == 200:
        return True, None
    if status in (401, 403):
        return False, "Invalid Svix API key"
    return False, message or "Could not validate Svix API key"
