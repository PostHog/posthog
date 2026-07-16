import dataclasses
from typing import Any, Optional
from urllib.parse import quote

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.settings import (
    APIFY_BASE_URL,
    PRIMARY_KEYS,
)
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

# One request to /datasets/{id}/items returns this many rows. The dataset endpoints carry a high
# rate limit (~400 req/s), so a large page keeps the round-trip count down on big datasets.
PAGE_SIZE = 1000
# Apify reports the dataset's total item count in this response header (the body is a bare JSON array).
APIFY_TOTAL_HEADER = "X-Apify-Pagination-Total"


@dataclasses.dataclass
class ApifyResumeConfig:
    # Absolute offset of the next dataset row to fetch. Apify datasets are append-only and returned in
    # stable storage order, so an offset always points at the same row — making it a safe resume cursor.
    offset: int = 0


def _items_path(dataset_id: str) -> str:
    # Encode the dataset_id as a single path segment so a crafted value can't inject extra path
    # segments or query params.
    return f"/datasets/{quote(dataset_id, safe='')}/items"


def apify_dataset_source(
    api_token: str,
    dataset_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ApifyResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
) -> SourceResponse:
    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": APIFY_BASE_URL,
            "auth": {"type": "bearer", "token": api_token},
            # Total lives in a response header, not the body; the bare JSON array is the row list.
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None, total_header=APIFY_TOTAL_HEADER),
        },
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": _items_path(dataset_id),
                    "params": {"format": "json"},
                    # The body is a bare JSON array; require it to be a list so a misrouted request
                    # returning an error object fails loud instead of syncing the object as a row.
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
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(ApifyResumeConfig(offset=int(state["offset"])))

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
        primary_keys=PRIMARY_KEYS.get(endpoint),
        column_hints=resource.column_hints,
    )


def validate_credentials(api_token: str, dataset_id: str) -> tuple[bool, str | None]:
    """Probe the dataset itself so a bad token (401/403) and a wrong/inaccessible dataset (404) are both caught."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{APIFY_BASE_URL}/datasets/{quote(dataset_id, safe='')}",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Apify API token, or the token cannot access this dataset."
    if status == 404:
        return False, "Dataset not found. Check the dataset ID and that the token can access it."
    if status is None:
        return False, "Could not reach the Apify API. Please try again."
    return False, f"Unexpected response from Apify (status {status})."
