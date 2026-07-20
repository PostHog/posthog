import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import urlencode

from requests import Request

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import BasePaginator
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.settings import (
    HUBPLANNER_ENDPOINTS,
    HubPlannerEndpointConfig,
)

HUBPLANNER_BASE_URL = "https://api.hubplanner.com/v1"

# Hub Planner caps `limit` at 1000; a limit of 0 or >1000 returns a 400. Bookings and time
# entries default to 20 rows/page, so we always request the max to minimise round-trips.
PAGE_SIZE = 1000


@dataclasses.dataclass
class HubPlannerResumeConfig:
    # Next 0-indexed page to fetch. Pagination is page-number based, so the page index is the
    # only cursor we need to persist to resume mid-endpoint after a heartbeat timeout.
    page: int = 0


class HubPlannerPagePaginator(BasePaginator):
    """Page-number paginator that terminates on a short page.

    Hub Planner's list/search endpoints have no next-page token; the last page is the one
    returning fewer rows than the requested limit. The built-in ``PageNumberPaginator`` only
    stops on a fully empty page (costing one extra request), so we keep the exact short-page
    stop here.
    """

    def __init__(self, page_size: int, page_param: str = "page", base_page: int = 0) -> None:
        super().__init__()
        self.page_size = page_size
        self.page_param = page_param
        self.page = base_page

    def _inject_page(self, request: Request) -> None:
        if request.params is None:
            request.params = {}
        request.params[self.page_param] = self.page

    def init_request(self, request: Request) -> None:
        self._inject_page(request)

    def update_state(self, response: Any, data: Optional[list[Any]] = None) -> None:
        # A short page (fewer rows than the limit) — including an empty page — is the last page.
        if data is None or len(data) < self.page_size:
            self._has_next_page = False
            return
        self.page += 1
        self._has_next_page = True

    def update_request(self, request: Request) -> None:
        self._inject_page(request)

    def get_resume_state(self) -> Optional[dict[str, Any]]:
        # self.page points at the next page to fetch once update_state has advanced it.
        return {"page": self.page} if self._has_next_page else None

    def set_resume_state(self, state: dict[str, Any]) -> None:
        page = state.get("page")
        if page is not None:
            self.page = int(page)
            self._has_next_page = True

    def __str__(self) -> str:
        return f"HubPlannerPagePaginator(page={self.page})"


def _format_value(value: Any) -> str:
    """Format an incremental cursor value as an ISO-8601 string Hub Planner accepts.

    The API's `updatedDate` search filter compares against ISO timestamps (e.g.
    `2018-09-04T08:15:11.487Z`), so datetimes are emitted in UTC with a `Z` suffix.
    """
    if isinstance(value, datetime):
        utc_dt = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _build_url(base_url: str, params: dict[str, Any]) -> str:
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _probe_headers(api_key: str) -> dict[str, str]:
    # Despite Hub Planner's docs calling this an "OAuth 2.0 Bearer Token", the API key is placed
    # raw in the Authorization header with no `Bearer ` prefix (verified against the live API).
    return {"Authorization": api_key, "Content-Type": "application/json", "Accept": "application/json"}


def _non_secret_headers() -> dict[str, str]:
    # Auth (the raw API key on the Authorization header) is supplied via the framework auth config
    # so its value is redacted from logs and error messages; only these non-secret headers are set.
    return {"Content-Type": "application/json", "Accept": "application/json"}


def validate_credentials(api_key: str) -> bool:
    # One cheap probe: list a single project. A valid key returns 200; an invalid or
    # insufficiently-permissioned key returns 403 (Hub Planner keys are account-wide, not
    # per-resource scoped, so a reachable /project confirms the whole token).
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        _build_url(f"{HUBPLANNER_BASE_URL}/project", {"page": 0, "limit": 1}),
        headers=_probe_headers(api_key),
    )
    return ok


def _build_request_plan(
    config: HubPlannerEndpointConfig,
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Any,
) -> tuple[str, str, Optional[dict[str, Any]], Optional[str]]:
    """Resolve (http_method, path, body, sort_field) for an endpoint's list request.

    Incremental endpoints (and search-only endpoints like milestones) POST to `<path>/search`;
    everything else GETs `<path>`.
    """
    incremental_active = bool(config.incremental_search_field and should_use_incremental_field)

    if config.list_via_search or incremental_active:
        body: dict[str, Any] = {}
        sort_field: Optional[str] = None
        field_name = config.incremental_search_field
        if incremental_active and field_name is not None:
            # Sort ascending on the cursor field so rows arrive oldest-first and the pipeline's
            # incremental watermark advances safely (matches SourceResponse.sort_mode="asc").
            sort_field = field_name
            if db_incremental_field_last_value is not None:
                body = {field_name: {"$gte": _format_value(db_incremental_field_last_value)}}
        return "POST", f"{config.path}/search", body, sort_field

    # Full-refresh GET. We deliberately don't pass a `sort` here: the API rejects an unsupported
    # sort field with a 400 that would fail the whole sync, and not every endpoint's sortable
    # fields are verifiable up front. A full refresh replaces the table each run, so the worst case
    # of unsorted paging (a row shifting across a page boundary mid-sync) self-heals next sync.
    return "GET", config.path, None, None


def hubplanner_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[HubPlannerResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = HUBPLANNER_ENDPOINTS[endpoint]

    method, path, body, sort_field = _build_request_plan(
        config, should_use_incremental_field, db_incremental_field_last_value
    )

    # `page` is injected per request by the paginator; `limit` and `sort` are static query params.
    params: dict[str, Any] = {"limit": PAGE_SIZE}
    if sort_field:
        params["sort"] = sort_field

    endpoint_config: dict[str, Any] = {
        "path": path,
        "method": method,
        "params": params,
        "paginator": HubPlannerPagePaginator(page_size=PAGE_SIZE),
        # Every list/search endpoint returns a bare JSON array; a non-list body means the
        # response shape changed — fail loud rather than syncing a stray object as a row.
        "data_selector_required": True,
    }
    # Only search (POST) requests carry a JSON body — an empty {} for a full search, or the
    # incremental `$gte` filter. Full-refresh GETs send no body at all.
    if body is not None:
        endpoint_config["json"] = body

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": HUBPLANNER_BASE_URL,
            "headers": _non_secret_headers(),
            # Raw API key on the Authorization header (no Bearer prefix); redacted from logs/errors.
            "auth": {"type": "api_key", "api_key": api_key, "name": "Authorization", "location": "header"},
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": endpoint_config,
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"page": resume.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(HubPlannerResumeConfig(page=int(state["page"])))

    # We inject the incremental filter into the POST body ourselves (Hub Planner uses a Mongo-style
    # `$gte` operator, not a flat query param), so the framework's server-side param injection is
    # unused here — pass None for its incremental value.
    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
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
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
