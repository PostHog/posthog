from datetime import date, datetime
from typing import Any, Optional, cast

from dateutil import parser
from requests import Request

from products.warehouse_sources.sources.bexio.settings import (
    BEXIO_BASE_URL,
    BEXIO_ENDPOINTS,
    OFFSET_PAGE_SIZE,
    PAGE_NUMBER_PAGE_SIZE,
    BexioEndpointConfig,
)
from products.warehouse_sources.sources.sdk import (
    BasePaginator,
    ClientConfig,
    Endpoint,
    EndpointResource,
    OffsetPaginator,
    PageNumberPaginator,
    Resource,
    RESTAPIConfig,
    ResumableSourceManager,
    SinglePagePaginator,
    SourceResponse,
    build_dependent_resource,
    frozen,
    make_tracked_session,
    rest_api_resource,
)

# bexio sorts on several fields when `order_by` lists them. The `id` tie-breaker keeps offset
# pages stable when many rows share one `updated_at` second.
INCREMENTAL_ORDER_BY = "updated_at,id"


@frozen
class BexioResumeConfig:
    offset: Optional[int] = None
    page: Optional[int] = None
    # Fan-out endpoints resume by parent: the child paths already read, the one in progress and its
    # paginator state. See `_make_paginate_dependent_resource` in the shared REST framework.
    completed: Optional[list[str]] = None
    current: Optional[str] = None
    child_state: Optional[dict[str, Any]] = None


def format_bexio_datetime(value: Any) -> str:
    """Format a watermark as the `YYYY-MM-DD HH:MM:SS` text that bexio uses for `updated_at`."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return f"{value.isoformat()} 00:00:00"
    try:
        return parser.parse(str(value)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OverflowError):
        return str(value)


class BexioSearchPaginator(OffsetPaginator):
    """Offset paging for a POST search, whose body is a JSON array of criteria.

    The endpoint config merges its `json` value as an object, so it can't carry an array. The paginator
    sets the body on the first request instead, and later pages reuse the same request.
    """

    def __init__(self, criteria: list[dict[str, Any]]) -> None:
        super().__init__(limit=OFFSET_PAGE_SIZE, offset_param="offset", limit_param="limit", total_path=None)
        self.criteria = criteria

    def init_request(self, request: Request) -> None:
        super().init_request(request)
        request.json = self.criteria


def _paginator(config: BexioEndpointConfig) -> BasePaginator:
    if config.pagination == "single":
        return SinglePagePaginator()
    if config.pagination == "page":
        return PageNumberPaginator(base_page=1, page_param="page", total_path=config.page_count_path)
    return OffsetPaginator(limit=OFFSET_PAGE_SIZE, offset_param="offset", limit_param="limit", total_path=None)


def get_resource(
    config: BexioEndpointConfig,
    is_incremental: bool,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    params: dict[str, Any] = {}
    if config.pagination == "page":
        params[config.page_size_param] = PAGE_NUMBER_PAGE_SIZE

    endpoint: Endpoint = {"path": config.path, "params": params, "paginator": _paginator(config)}
    if config.data_selector:
        endpoint["data_selector"] = config.data_selector

    if is_incremental:
        params["order_by"] = INCREMENTAL_ORDER_BY
        # The first incremental run has no watermark, so it reads the plain list in `updated_at` order.
        if db_incremental_field_last_value is not None and config.search_path:
            endpoint["path"] = config.search_path
            endpoint["method"] = "POST"
            # `>=` reads the rows of the watermark second again, because rows changed later in that
            # second were not in the last run. The merge on `id` removes the duplicates.
            endpoint["paginator"] = BexioSearchPaginator(
                [
                    {
                        "field": "updated_at",
                        "value": format_bexio_datetime(db_incremental_field_last_value),
                        "criteria": ">=",
                    }
                ]
            )
    elif config.order_by:
        params["order_by"] = config.order_by

    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": list(config.primary_keys),
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


def _client_config(api_token: str) -> ClientConfig:
    return {
        "base_url": BEXIO_BASE_URL,
        "auth": {"type": "bearer", "token": api_token},
        "headers": {"Accept": "application/json"},
    }


def _endpoint_extra(config: BexioEndpointConfig) -> Endpoint:
    extra: Endpoint = {"paginator": _paginator(config)}
    if config.data_selector:
        extra["data_selector"] = config.data_selector
    return extra


def _fanout_resource(
    config: BexioEndpointConfig,
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BexioResumeConfig],
) -> Resource:
    assert config.fanout is not None
    parent_config = BEXIO_ENDPOINTS[config.fanout.parent_name]

    initial_state: Optional[dict[str, Any]] = None
    resume = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    if resume is not None and (resume.completed or resume.current):
        initial_state = {
            "completed": resume.completed or [],
            "current": resume.current,
            "child_state": resume.child_state,
        }

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state is not None:
            resumable_source_manager.save_state(
                BexioResumeConfig(
                    completed=state.get("completed"),
                    current=state.get("current"),
                    child_state=state.get("child_state"),
                )
            )

    # The helper returns the child `Resource` but declares a plain iterable.
    return cast(
        Resource,
        build_dependent_resource(
            endpoint_configs=BEXIO_ENDPOINTS,
            child_endpoint=config.name,
            fanout=config.fanout,
            client_config=_client_config(api_token),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            parent_endpoint_extra=_endpoint_extra(parent_config),
            child_endpoint_extra=_endpoint_extra(config),
            # A single-page child takes no page-size parameter. An offset parent sets its own `limit`.
            page_size_param=None if config.pagination == "single" else "limit",
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_state,
        ),
    )


def _top_level_resource(
    config: BexioEndpointConfig,
    api_token: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BexioResumeConfig],
    is_incremental: bool,
    db_incremental_field_last_value: Optional[Any],
) -> Resource:
    rest_config: RESTAPIConfig = {
        "client": _client_config(api_token),
        "resource_defaults": {},
        "resources": [get_resource(config, is_incremental, db_incremental_field_last_value)],
    }

    resume_config = resumable_source_manager.load_state() if resumable_source_manager.can_resume() else None
    # Each paginator reads only its own key (`offset` or `page`) and ignores the other one.
    initial_paginator_state = (
        {"offset": resume_config.offset, "page": resume_config.page} if resume_config is not None else None
    )

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if not state:
            return
        if state.get("page") is not None:
            resumable_source_manager.save_state(BexioResumeConfig(page=int(state["page"])))
        elif state.get("offset") is not None:
            resumable_source_manager.save_state(BexioResumeConfig(offset=int(state["offset"])))

    return rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def bexio_source(
    api_token: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BexioResumeConfig],
    should_use_incremental_field: bool,
    db_incremental_field_last_value: Optional[Any],
) -> SourceResponse:
    config = BEXIO_ENDPOINTS[endpoint]
    is_incremental = should_use_incremental_field and config.search_path is not None

    if config.fanout is not None:
        resource = _fanout_resource(config, api_token, team_id, job_id, resumable_source_manager)
    else:
        resource = _top_level_resource(
            config,
            api_token,
            team_id,
            job_id,
            resumable_source_manager,
            is_incremental,
            db_incremental_field_last_value,
        )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=list(config.primary_keys),
        column_hints=resource.column_hints,
        # Only the incremental path sorts on `updated_at`, through an explicit `order_by`.
        sort_mode="asc" if is_incremental else None,
        partition_count=1 if config.partition_key else None,
        partition_size=1 if config.partition_key else None,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
    )


def probe_token(api_token: str) -> Optional[int]:
    """Return the status of a cheap authenticated request, or None when the request itself failed."""
    try:
        response = make_tracked_session(redact_values=(api_token,)).get(
            f"{BEXIO_BASE_URL}/3.0/users/me",
            headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
            timeout=30,
        )
    except Exception:
        return None
    return response.status_code
