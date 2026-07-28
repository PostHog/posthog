import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.torii.settings import (
    PARTITION_KEYS,
    PRIMARY_KEYS,
    TORII_BASE_URL,
    get_resource,
)


@dataclasses.dataclass
class ToriiResumeConfig:
    cursor: str


def torii_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ToriiResumeConfig],
    api_version: str,
) -> SourceResponse:
    resource = get_resource(endpoint)

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": TORII_BASE_URL,
            "headers": {"X-API-Version": api_version},
            "auth": {"type": "bearer", "token": api_key},
            "paginator": {"type": "cursor", "cursor_path": "nextCursor", "cursor_param": "cursor"},
        },
        "resources": [resource],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume_config = resumable_source_manager.load_state()
        if resume_config is not None:
            initial_paginator_state = {"cursor": resume_config.cursor}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Only persist while there's a next page to resume to; the Redis TTL handles cleanup on
        # completion. Saved after a page is yielded (see rest_api_resource) so a crash re-yields the
        # last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("cursor"):
            resumable_source_manager.save_state(ToriiResumeConfig(cursor=str(state["cursor"])))

    result = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    partition_key = PARTITION_KEYS.get(endpoint)

    return SourceResponse(
        name=result.name,
        items=lambda: result,
        primary_keys=PRIMARY_KEYS[endpoint],
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
        column_hints=result.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    """Confirm the API key is genuine. GET /orgs/my is the cheapest authenticated call and needs
    no resource-specific scope."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{TORII_BASE_URL}/orgs/my",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    return ok
