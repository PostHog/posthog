import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.recreation.settings import (
    PAGE_LIMIT,
    RECREATION_ENDPOINTS,
    RIDB_BASE_URL,
)

VALIDATION_TIMEOUT_SECONDS = 10


@dataclasses.dataclass
class RecreationResumeConfig:
    offset: int


def _build_paginator() -> OffsetPaginator:
    # RIDB reports the grand total at METADATA.RESULTS.TOTAL_COUNT, so pagination stops
    # without paying an extra empty-page request; the short-page check is the fallback.
    return OffsetPaginator(limit=PAGE_LIMIT, total_path="METADATA.RESULTS.TOTAL_COUNT")


def get_resource(endpoint: str) -> EndpointResource:
    config = RECREATION_ENDPOINTS[endpoint]
    return {
        "name": config.name,
        "table_name": config.name.lower(),
        "write_disposition": "replace",
        "endpoint": {
            "data_selector": "RECDATA",
            "path": config.path,
            "paginator": _build_paginator(),
        },
        "table_format": "delta",
    }


def recreation_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RecreationResumeConfig],
) -> SourceResponse:
    endpoint_config = RECREATION_ENDPOINTS[endpoint]

    config: RESTAPIConfig = {
        "client": {
            "base_url": RIDB_BASE_URL,
            "auth": {
                "type": "api_key",
                "name": "apikey",
                "api_key": api_key,
                "location": "header",
            },
            "headers": {"Accept": "application/json"},
            # The apikey credential rides a custom header, which `requests` would replay to a
            # cross-origin redirect target (unlike `Authorization`) — refuse redirects instead.
            "allow_redirects": False,
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
            initial_paginator_state = {"offset": resume_config.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist when there's a next page to resume to; the Redis TTL
        # handles cleanup on completion.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(RecreationResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_kwargs: dict[str, Any] = {}
    if endpoint_config.partition_key is not None:
        partition_kwargs = {
            "partition_count": 1,
            "partition_size": 1,
            "partition_mode": "datetime",
            "partition_format": "month",
            "partition_keys": [endpoint_config.partition_key],
        }

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[endpoint_config.primary_key],
        **partition_kwargs,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    try:
        # `allow_redirects=False` matches the sync path's credential boundary: never replay
        # the apikey header to a redirect target.
        res = make_tracked_session(redact_values=(api_key,), allow_redirects=False).get(
            f"{RIDB_BASE_URL}/activities",
            params={"limit": 1},
            headers={"apikey": api_key, "Accept": "application/json"},
            timeout=VALIDATION_TIMEOUT_SECONDS,
        )
        if res.status_code == 200:
            return True, None
        if res.status_code in (401, 403):
            return False, "Invalid RIDB API key. Copy the key from your profile at ridb.recreation.gov and try again."
        return False, f"RIDB API returned an unexpected response (HTTP {res.status_code})"
    except Exception as e:
        return False, str(e)
