import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.motion.settings import MOTION_ENDPOINTS

MOTION_BASE_URL = "https://api.usemotion.com"
REQUEST_TIMEOUT_SECONDS = 30


@dataclasses.dataclass
class MotionResumeConfig:
    cursor: str


def get_resource(endpoint: str) -> EndpointResource:
    config = MOTION_ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name,
        "primary_key": config.primary_key,
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": f"{config.data_key}[*]",
            "path": config.path,
            "params": dict(config.params),
        },
        "table_format": "delta",
    }


def motion_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[MotionResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
):
    config: RESTAPIConfig = {
        "client": {
            "base_url": MOTION_BASE_URL,
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-Key", "location": "header"},
            "paginator": JSONResponseCursorPaginator(cursor_path="meta.nextCursor", cursor_param="cursor"),
        },
        "resource_defaults": {"write_disposition": "replace"},
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("cursor"):
            resumable_source_manager.save_state(MotionResumeConfig(cursor=str(state["cursor"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
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
