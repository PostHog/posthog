from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resources,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    rename_parent_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    Endpoint,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.motion.settings import MOTION_ENDPOINTS

MOTION_BASE_URL = "https://api.usemotion.com"
REQUEST_TIMEOUT_SECONDS = 30


@frozen
class MotionResumeConfig:
    cursor: Optional[str] = None
    # Fan-out progress: the parents already done, and the cursor of the one in progress.
    fanout_state: Optional[dict[str, Any]] = None


def get_resource(endpoint: str) -> EndpointResource:
    config = MOTION_ENDPOINTS[endpoint]
    parent = config.parent
    params: dict[str, Any] = dict(config.params)
    if parent is not None:
        params[parent.resolve_param] = {"type": "resolve", "resource": parent.name, "field": "id"}
    endpoint_config: Endpoint = {
        "data_selector": f"{config.data_key}[*]" if config.data_key else "$",
        "path": config.path,
        "params": params,
        # Explicit, because the framework treats a path that ends in a placeholder as a single
        # object and would stop a fan-out child after its first page.
        "paginator": (
            JSONResponseCursorPaginator(cursor_path="meta.nextCursor", cursor_param="cursor")
            if config.paginated
            else SinglePagePaginator()
        ),
    }
    resource: EndpointResource = {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_keys,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }
    if parent is not None:
        # A parent deleted between the parent listing and its child request has nothing left to sync.
        endpoint_config["response_actions"] = [{"status_code": 404, "action": "ignore"}]
        if parent.parent_id_column:
            resource["include_from_parent"] = ["id"]
            resource["data_map"] = rename_parent_fields(parent.name, {"id": parent.parent_id_column})
    return resource


def get_resources(endpoint: str) -> list[EndpointResource]:
    parent = MOTION_ENDPOINTS[endpoint].parent
    resource = get_resource(endpoint)
    return [get_resource(parent.name), resource] if parent else [resource]


def motion_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MotionResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    endpoint_config = MOTION_ENDPOINTS[endpoint]
    config: RESTAPIConfig = {
        "client": {
            "base_url": MOTION_BASE_URL,
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-Key", "location": "header"},
            "request_timeout": REQUEST_TIMEOUT_SECONDS,
        },
        "resource_defaults": {"write_disposition": "replace"},
        "resources": list(get_resources(endpoint)),
    }
    is_fanout = endpoint_config.parent is not None

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            if is_fanout:
                initial_paginator_state = resume_config.fanout_state
            elif resume_config.cursor:
                initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if is_fanout and state is not None:
            resumable_source_manager.save_state(MotionResumeConfig(fanout_state=state))
        elif state and state.get("cursor"):
            resumable_source_manager.save_state(MotionResumeConfig(cursor=str(state["cursor"])))
        elif state is None:
            resumable_source_manager.clear_state()

    resources = rest_api_resources(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )
    resource = next(r for r in resources if r.name == endpoint)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=endpoint_config.primary_keys,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="month" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
        column_hints=resource.column_hints,
        # A fan-out never hands the hook a final None, so its progress would otherwise survive the
        # run and make the next sync skip every parent it already finished.
        on_complete=resumable_source_manager.clear_state if is_fanout else None,
    )


def validate_credentials(api_key: str) -> tuple[bool, Optional[str]]:
    """Probe the workspace list, the cheapest call every Motion key can make."""
    try:
        response = make_tracked_session(headers={"X-API-Key": api_key}, redact_values=(api_key,)).get(
            f"{MOTION_BASE_URL}/v1/workspaces", timeout=REQUEST_TIMEOUT_SECONDS
        )
    except Exception:
        return False, "Could not reach the Motion API. Check your connection and try again."

    if response.ok:
        return True, None
    if response.status_code in (401, 403):
        return False, "Motion rejected this API key. Create a new key in Motion under Settings, then try again."
    if response.status_code == 429:
        return False, "Motion is rate limiting this API key. Wait a minute, then try again."
    return False, f"Motion returned an unexpected error ({response.status_code}) while checking this API key."
