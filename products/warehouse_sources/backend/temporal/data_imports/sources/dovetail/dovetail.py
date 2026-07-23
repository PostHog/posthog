import dataclasses
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    build_dependent_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    Endpoint,
    EndpointResource,
    PaginatorConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.dovetail.settings import (
    DOVETAIL_BASE_URL,
    DOVETAIL_ENDPOINTS,
    DovetailEndpointConfig,
)


@dataclasses.dataclass
class DovetailResumeConfig:
    # Opaque framework checkpoint: `{"cursor": ...}` for a top-level endpoint's
    # JSONResponseCursorPaginator, or the fan-out manager's `{"completed": [...], "current":
    # ..., "child_state": {...}}` for DocComments - round-tripped into
    # `initial_paginator_state` on resume.
    paginator_state: dict[str, Any]


def _paginator_config() -> PaginatorConfig:
    return {
        "type": "cursor",
        "cursor_path": "page.next_cursor",
        "cursor_param": "page[start_cursor]",
    }


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": DOVETAIL_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "bearer", "token": api_key},
    }


def _format_incremental_value(value: Any) -> str:
    """Format an incremental cursor as ISO 8601, which Dovetail's `filter[<field>][gte]` expects."""
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time(), tzinfo=UTC).isoformat()
    return str(value)


def _incremental_filter_param(cursor_field: str) -> dict[str, Any]:
    return {
        "type": "incremental",
        "cursor_path": cursor_field,
        "initial_value": None,
        "convert": _format_incremental_value,
    }


def get_resource(name: str, should_use_incremental_field: bool, incremental_field: str | None) -> EndpointResource:
    config = DOVETAIL_ENDPOINTS[name]
    cursor_field = incremental_field or (config.incremental_fields[0]["field"] if config.incremental_fields else None)
    use_incremental = should_use_incremental_field and cursor_field is not None

    params: dict[str, Any] = {
        "page[limit]": config.page_size,
        # Dovetail defaults every list endpoint to `created_at:desc`; sort ascending explicitly
        # so the incremental watermark advances monotonically (and, for full-refresh endpoints,
        # so page boundaries stay stable if rows are inserted mid-sync).
        "sort": "created_at:asc",
    }
    if cursor_field is not None:
        params[f"filter[{cursor_field}][gte]"] = _incremental_filter_param(cursor_field) if use_incremental else None

    endpoint: Endpoint = {
        "path": config.path,
        "data_selector": "data",
        "params": params,
        "paginator": _paginator_config(),
    }

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": ({"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace"),
        "endpoint": endpoint,
        "table_format": "delta",
    }


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{DOVETAIL_BASE_URL}/v1/token/info",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status == 401:
        return False, "Dovetail rejected the API token. Please generate a new personal API key and reconnect."
    if status == 403:
        return False, "Your Dovetail API token does not have permission for this resource."
    if status is None:
        return False, "Could not reach Dovetail. Please check your network and try again."
    return False, f"Dovetail API returned an unexpected status: {status}"


def _make_source_response(endpoint_config: DovetailEndpointConfig, items_fn: Any) -> SourceResponse:
    return SourceResponse(
        name=endpoint_config.name,
        items=items_fn,
        primary_keys=(
            endpoint_config.primary_key
            if isinstance(endpoint_config.primary_key, list)
            else [endpoint_config.primary_key]
        ),
        sort_mode=endpoint_config.sort_mode,
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def dovetail_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[DovetailResumeConfig],
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Optional[Any] = None,
    incremental_field: str | None = None,
) -> SourceResponse:
    endpoint_config = DOVETAIL_ENDPOINTS[endpoint]

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = resume_config.paginator_state

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's somewhere to resume to; the manager's 24h Redis TTL
        # handles cleanup once a sync completes.
        if state:
            resumable_source_manager.save_state(DovetailResumeConfig(paginator_state=dict(state)))

    if endpoint_config.fanout:
        # DocComments has no server-side filter of its own, so every sync walks the full Docs
        # list to discover doc ids and re-fetches comments per doc; that's inherent to the API
        # (no workspace-wide comments-list endpoint exists) and mirrors other fan-out sources.
        dependent_resource = build_dependent_resource(
            endpoint_configs=cast(Any, DOVETAIL_ENDPOINTS),
            child_endpoint=endpoint,
            fanout=endpoint_config.fanout,
            client_config=_client_config(api_key),
            path_format_values={},
            team_id=team_id,
            job_id=job_id,
            db_incremental_field_last_value=None,
            page_size_param="page[limit]",
            parent_endpoint_extra={
                "paginator": _paginator_config(),
                "data_selector": "data",
            },
            child_endpoint_extra={
                "paginator": _paginator_config(),
                "data_selector": "data",
            },
            child_params_extra={"sort": "created_at:asc"},
            resume_hook=save_checkpoint,
            initial_paginator_state=initial_paginator_state,
        )
        return _make_source_response(endpoint_config, lambda: dependent_resource)

    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [get_resource(endpoint, should_use_incremental_field, incremental_field)],
    }

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    return _make_source_response(endpoint_config, lambda: resource)
