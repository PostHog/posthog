import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponsePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.omnisend.settings import OMNISEND_ENDPOINTS

OMNISEND_BASE_URL = "https://api.omnisend.com/v3"

# Omnisend allows up to 250 items per page; larger pages mean fewer requests against the
# 400 req/min general rate limit.
PAGE_SIZE = 250


@dataclasses.dataclass
class OmnisendResumeConfig:
    # Fully-formed next-page URL from the API's `paging.next`; we follow it verbatim.
    next_url: str


def _headers() -> dict[str, str]:
    # Auth (X-API-KEY) is supplied via the framework auth config so its value is redacted from
    # logs and raised errors; only the non-secret Accept header is set here.
    return {"Accept": "application/json"}


def validate_credentials(api_key: str) -> tuple[bool, int | None]:
    """Cheap probe to confirm the API key is genuine. Returns (is_valid, status_code)."""
    return validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{OMNISEND_BASE_URL}/contacts?limit=1",
        headers={"X-API-KEY": api_key, **_headers()},
    )


def omnisend_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[OmnisendResumeConfig],
) -> SourceResponse:
    config = OMNISEND_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": OMNISEND_BASE_URL,
            "headers": _headers(),
            "auth": {"type": "api_key", "api_key": api_key, "name": "X-API-KEY", "location": "header"},
            # Omnisend returns a fully-formed next-page URL under `paging.next`; follow it verbatim.
            "paginator": JSONResponsePaginator(next_url_path="paging.next"),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": {"limit": PAGE_SIZE},
                    "data_selector": config.data_key,
                    # A 200 body missing the envelope key means the response shape changed — fail
                    # loud instead of silently syncing 0 rows.
                    "data_selector_required": True,
                },
            }
        ],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"next_url": resume.next_url}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes on the primary key) rather than skipping it.
        if state and state.get("next_url"):
            resumable_source_manager.save_state(OmnisendResumeConfig(next_url=state["next_url"]))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        None,  # every Omnisend endpoint is full refresh
        resume_hook=save_checkpoint,
        initial_paginator_state=initial_paginator_state,
    )

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=[config.primary_key],
        partition_count=1,
        partition_size=1,
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        sort_mode="asc",
        column_hints=resource.column_hints,
    )
