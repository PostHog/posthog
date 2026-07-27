import dataclasses
from typing import Any, Optional
from urllib.parse import urlencode

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.settings import BLUETALLY_ENDPOINTS
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

BLUETALLY_BASE_URL = "https://app.bluetallyapp.com/api/v1"
# BlueTally caps a single response at 1000 rows; using the max minimizes requests against the
# 10,000-requests-per-hour budget.
PAGE_SIZE = 1000


@dataclasses.dataclass
class BluetallyResumeConfig:
    # Offset of the next page to fetch. BlueTally paginates with limit/offset, so persisting the
    # offset is all we need to pick a full-refresh sync back up after a heartbeat timeout.
    offset: int = 0


def bluetally_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[BluetallyResumeConfig],
    tenant_id: Optional[str] = None,
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = BLUETALLY_ENDPOINTS[endpoint]

    # Sorting on `created_at` ascending keeps offset pagination stable even as new rows are
    # appended mid-sync.
    params: dict[str, Any] = {"sort": config.sort, "order": "asc"}
    if tenant_id:
        params["tenant_id"] = tenant_id

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BLUETALLY_BASE_URL,
            # Auth (Bearer) is supplied via the framework auth config so its value is redacted from
            # logged URLs and captured HTTP samples; only the non-secret Accept header is set here.
            "headers": {"Accept": "application/json"},
            "auth": {"type": "bearer", "token": api_key},
            # BlueTally reports no total anywhere; termination is short/empty page (OffsetPaginator default).
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    # Every list endpoint returns a bare JSON array. A non-list 200 (wrapped payload,
                    # proxy HTML, …) is a permanent API-contract violation — fail loud instead of
                    # syncing the stray object as a row.
                    "data_selector_required": True,
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
        # Persist only when a next page remains; saved AFTER a page is yielded so a crash re-runs
        # from the last persisted offset rather than skipping ahead (merge dedupes re-pulled rows).
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(BluetallyResumeConfig(offset=int(state["offset"])))

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
        partition_mode="datetime" if config.partition_key else None,
        partition_format="month" if config.partition_key else None,
        partition_keys=[config.partition_key] if config.partition_key else None,
        # We request `sort=created_at&order=asc`, so rows arrive oldest-first.
        sort_mode="asc",
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str, tenant_id: str | None = None, path: str = "/assets") -> bool:
    query: dict[str, Any] = {"limit": 1}
    if tenant_id:
        query["tenant_id"] = tenant_id
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{BLUETALLY_BASE_URL}{path}?{urlencode(query)}",
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    return ok
