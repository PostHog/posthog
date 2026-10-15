from dataclasses import dataclass
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ClientConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.schematic.settings import (
    PAGE_SIZE,
    SCHEMATIC_BASE_URL,
    SCHEMATIC_ENDPOINTS,
)

API_KEY_HEADER = "X-Schematic-Api-Key"


@dataclass(frozen=True)
class SchematicResumeConfig:
    # The `offset` of the next page to fetch.
    offset: int


def _client_config(api_key: str) -> ClientConfig:
    return {
        "base_url": SCHEMATIC_BASE_URL,
        "headers": {"Accept": "application/json"},
        "auth": {"type": "api_key", "api_key": api_key, "name": API_KEY_HEADER, "location": "header"},
    }


def schematic_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[SchematicResumeConfig],
) -> SourceResponse:
    config = SCHEMATIC_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": _client_config(api_key),
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "table_name": endpoint,
                "write_disposition": "replace",
                "table_format": "delta",
                "endpoint": {
                    "path": config.path,
                    # Every list response is `{"data": [...], "params": {...}}` with no total, so the
                    # walk ends on the first page shorter than the limit.
                    "data_selector": "data",
                    "data_selector_required": True,
                    "paginator": {"type": "offset", "limit": PAGE_SIZE, "total_path": None},
                },
            }
        ],
    }

    initial_paginator_state: dict[str, Any] | None = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: dict[str, Any] | None) -> None:
        if state is not None:
            resumable_source_manager.save_state(SchematicResumeConfig(offset=int(state["offset"])))

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
        primary_keys=list(config.primary_keys),
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{SCHEMATIC_BASE_URL}/companies?limit=1",
        headers={API_KEY_HEADER: api_key, "Accept": "application/json"},
        timeout=15,
        allow_redirects=False,
    )
