import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.loops.settings import LOOPS_ENDPOINTS

BASE_URL = "https://app.loops.so/api"

# Loops caps `perPage` at 50 (allowed range 10-50, default 20) on cursor-paginated
# list endpoints.
PAGE_SIZE = 50


@dataclasses.dataclass
class LoopsResumeConfig:
    cursor: str


def get_resource(endpoint: str) -> EndpointResource:
    config = LOOPS_ENDPOINTS[endpoint]

    params: dict[str, Any] = dict(config.extra_params)

    endpoint_config: Endpoint = {
        "path": config.path,
        "params": params,
    }

    if config.paginated:
        endpoint_config["data_selector"] = "data"
        params["perPage"] = PAGE_SIZE
        endpoint_config["paginator"] = JSONResponseCursorPaginator(
            cursor_path="pagination.nextCursor",
            cursor_param="cursor",
        )
    else:
        # Unpaginated endpoints (mailing lists, contact properties) return the
        # full collection as a bare JSON array with no wrapper object.
        endpoint_config["paginator"] = SinglePagePaginator()

    return {
        "name": config.name,
        "table_name": config.name,
        "write_disposition": "replace",
        "endpoint": endpoint_config,
        "table_format": "delta",
    }


def loops_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[LoopsResumeConfig],
) -> SourceResponse:
    endpoint_config = LOOPS_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "auth": {
                "type": "bearer",
                "token": api_key,
            },
            "headers": {
                "Accept": "application/json",
            },
        },
        "resource_defaults": {
            "write_disposition": "replace",
        },
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when there's a next page to resume to; the Redis TTL handles
        # cleanup once the sync finishes. Saving happens after each page is yielded,
        # so a crash re-fetches the last page rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(LoopsResumeConfig(cursor=str(state["cursor"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if endpoint_config.partition_key else None,
        partition_format="week" if endpoint_config.partition_key else None,
        partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    try:
        response = make_tracked_session(redact_values=(api_key,)).get(
            f"{BASE_URL}/v1/api-key",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            timeout=10,
        )
    except Exception as e:
        return False, str(e)

    if response.status_code == 200:
        return True, None
    if response.status_code == 401:
        return False, "Invalid Loops API key"
    return False, f"Loops returned an unexpected status code: {response.status_code}"
