import dataclasses
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.settings import ALGUNA_ENDPOINTS
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

ALGUNA_BASE_URL = "https://api.alguna.io"
# Alguna's API is date-versioned; every request must send this header or calls fail.
ALGUNA_API_VERSION = "2026-04-01"
PAGE_LIMIT = 100


@dataclasses.dataclass
class AlgunaResumeConfig:
    # Row offset of the next unfetched page — Alguna list endpoints paginate with limit/offset.
    offset: int = 0


def _version_headers() -> dict[str, str]:
    # Auth (Bearer) is supplied via the framework auth config so its value is redacted from logs;
    # only the non-secret version/accept headers are set here.
    return {"Alguna-Version": ALGUNA_API_VERSION, "Accept": "application/json"}


def alguna_source(
    api_key: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[AlgunaResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    config = ALGUNA_ENDPOINTS[endpoint]

    params: dict[str, Any] = {"limit": PAGE_LIMIT}
    if config.sort is not None:
        params["sort"] = config.sort

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": ALGUNA_BASE_URL,
            "headers": _version_headers(),
            "auth": {"type": "bearer", "token": api_key},
            # Alguna has no top-level `total`; termination is short/empty page (OffsetPaginator default).
            "paginator": OffsetPaginator(limit=PAGE_LIMIT, total_path=None),
        },
        # Per-resource settings are fully specified below, so no shared defaults are needed.
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": config.path,
                    "params": params,
                    "data_selector": "data",
                    # A 200 body without `data` means the response shape changed — fail loud
                    # instead of silently syncing 0 rows.
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
        # Persist only when a next page remains; save AFTER a page is yielded so a crash re-yields
        # the last page (merge dedupes) rather than skipping it.
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(AlgunaResumeConfig(offset=int(state["offset"])))

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
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[config.partition_key],
        column_hints=resource.column_hints,
    )


def validate_credentials(api_key: str) -> bool:
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_key,)),
        f"{ALGUNA_BASE_URL}/customers?limit=1&offset=0&sort=created_at:asc",
        headers={"Authorization": f"Bearer {api_key}", **_version_headers()},
    )
    return ok
