from datetime import date, datetime
from typing import Any, Optional

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
    Endpoint,
    EndpointResource,
    OffsetPaginator,
    PageNumberPaginator,
    RESTAPIConfig,
    ResumableSourceManager,
    SourceResponse,
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
    if config.pagination == "page":
        return PageNumberPaginator(base_page=1, page_param="page", total_path="paging.page_count")
    return OffsetPaginator(limit=OFFSET_PAGE_SIZE, offset_param="offset", limit_param="limit", total_path=None)


def get_resource(
    config: BexioEndpointConfig,
    is_incremental: bool,
    db_incremental_field_last_value: Optional[Any],
) -> EndpointResource:
    params: dict[str, Any] = {}
    if config.pagination == "page":
        params["limit"] = PAGE_NUMBER_PAGE_SIZE

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
        "primary_key": ["id"],
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if is_incremental else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }


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

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BEXIO_BASE_URL,
            "auth": {"type": "bearer", "token": api_token},
            "headers": {"Accept": "application/json"},
        },
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

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=config.name,
        items=lambda: resource,
        primary_keys=["id"],
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
