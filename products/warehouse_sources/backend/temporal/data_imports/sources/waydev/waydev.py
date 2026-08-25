from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    PageNumberPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.resource import Resource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import (
    ClientConfig,
    EndpointResource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe

BASE_URL = "https://api.waydev.co/v2"
# The public reference documents a `limit` param (default 25) with no stated maximum;
# 100 keeps page count down without a documented ceiling to test against.
INCIDENTS_PAGE_SIZE = 100


@frozen
class WaydevResumeConfig:
    next_page: int


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": BASE_URL,
        # The public reference sends the raw token under Authorization with no scheme prefix.
        "auth": {
            "type": "api_key",
            "name": "Authorization",
            "api_key": api_key,
            "location": "header",
        },
    }


def get_resource(name: str) -> EndpointResource:
    resources: dict[str, EndpointResource] = {
        "Metrics": {
            "name": "Metrics",
            "table_name": "metrics",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/metrics",
                # Response is a bare JSON array with no pagination documented.
                "paginator": SinglePagePaginator(),
            },
            "table_format": "delta",
        },
        "Incidents": {
            "name": "Incidents",
            "table_name": "incidents",
            "write_disposition": "replace",
            "endpoint": {
                "path": "/incidents",
                "params": {"limit": INCIDENTS_PAGE_SIZE},
                "data_selector": "data",
                "paginator": PageNumberPaginator(base_page=1, page_param="page", stop_after_empty_page=True),
            },
            "table_format": "delta",
        },
    }
    return resources[name]


def waydev_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[WaydevResumeConfig],
) -> Resource:
    config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resources": [get_resource(endpoint)],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"page": resume_config.next_page}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL handles
        # cleanup on completion.
        if state and state.get("page"):
            resumable_source_manager.save_state(WaydevResumeConfig(next_page=int(state["page"])))

    return rest_api_resource(
        config,
        team_id,
        job_id,
        db_incremental_field_last_value=None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Probe the metrics endpoint to confirm the token is genuine."""
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BASE_URL}/metrics",
        headers={"Authorization": api_key},
    )
