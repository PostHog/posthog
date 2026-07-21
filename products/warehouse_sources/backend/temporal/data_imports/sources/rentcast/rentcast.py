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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.rentcast.settings import RENTCAST_ENDPOINTS

RENTCAST_BASE_URL = "https://api.rentcast.io/v1"
# The list endpoints accept a `limit` between 1 and 500; the largest page minimises round trips
# (and paid requests, since RentCast bills per request against a monthly quota).
PAGE_SIZE = 500
# Cheap endpoint used to confirm an API key is genuine. The key is account-wide, so one probe
# validates access to every list endpoint. A `limit` of 1 keeps the billed request small.
DEFAULT_PROBE_PATH = "/properties"


@dataclasses.dataclass
class RentCastResumeConfig:
    # Offset of the next page to fetch. Offset pagination is deterministic, so a crashed
    # full-refresh sync resumes from the page after the last one yielded; merge dedupes on `id`.
    offset: int = 0


def rentcast_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[RentCastResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = RENTCAST_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": RENTCAST_BASE_URL,
            # The API key rides in the X-Api-Key header; framework auth redacts it from logs/errors.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-Api-Key", "location": "header"},
            # RentCast list endpoints return a bare JSON array with no total; termination is a
            # short/empty page (OffsetPaginator default).
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    # The body is a bare JSON array; a 200 body that isn't a list means an
                    # unexpected shape — retry it (transient) rather than syncing garbage.
                    "data_selector_malformed_retryable": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on `id`) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(RentCastResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value,
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> tuple[bool, str | None]:
    # The API key is account-wide, so a single probe validates access to every list endpoint.
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{RENTCAST_BASE_URL}{DEFAULT_PROBE_PATH}?limit=1",
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
        timeout=15,
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid RentCast API key"
    if status is None:
        return False, "Could not validate RentCast API key"
    return False, f"RentCast returned HTTP {status}"
