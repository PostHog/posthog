from datetime import date, datetime, timedelta
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.easybill.settings import (
    EASYBILL_BASE_URL,
    EASYBILL_ENDPOINTS,
    PAGE_LIMIT,
    EasybillEndpointConfig,
)


@frozen
class EasybillResumeConfig:
    page: int


def _coerce_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def date_range_since(value: Any) -> Optional[str]:
    """easybill's date filters take a single day or an inclusive "from,to" range - there's no
    open-ended "since" operator. Overlap the start by a day because the filter is day-granular,
    so a row edited earlier the same day as the last watermark could otherwise be missed."""
    start = _coerce_date(value)
    if start is None:
        return None
    return f"{(start - timedelta(days=1)).isoformat()},{date.today().isoformat()}"


def _build_endpoint_resource(config: EasybillEndpointConfig, should_use_incremental_field: bool) -> EndpointResource:
    endpoint: Endpoint = {
        "path": config.path,
        "data_selector": "items",
        "params": {"limit": PAGE_LIMIT},
        # `pages` in the response envelope is the max page count, so pagination stops exactly at
        # the last page instead of paying one extra empty-page request per sync.
        "paginator": PageNumberPaginator(base_page=1, page_param="page", total_path="pages"),
    }
    if config.incremental_param and should_use_incremental_field:
        endpoint["incremental"] = {
            "start_param": config.incremental_param,
            "cursor_path": config.incremental_param,
            "convert": date_range_since,
        }

    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.table_name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"}
        if should_use_incremental_field
        else "replace",
        "endpoint": endpoint,
        "table_format": "delta",
    }
    return resource


def easybill_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[EasybillResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = EASYBILL_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": EASYBILL_BASE_URL,
            "auth": {"type": "bearer", "token": api_key},
        },
        "resource_defaults": {},
        "resources": [_build_endpoint_resource(config, should_use_incremental_field)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles cleanup on
        # completion. Saved AFTER a page is yielded so a crash re-yields the last page (merge
        # dedupes on primary_keys) rather than skipping it.
        if state and state.get("page") is not None:
            resumable_source_manager.save_state(EasybillResumeConfig(page=int(state["page"])))

    last_value = db_incremental_field_last_value if should_use_incremental_field else None

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=resource.name,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        sort_mode="asc",
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="week" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    # A cheap, always-available probe: one page of customers. 200 means the key is genuine.
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{EASYBILL_BASE_URL}/customers?limit=1",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return ok
