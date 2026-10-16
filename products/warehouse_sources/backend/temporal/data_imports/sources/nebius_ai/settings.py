from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField

# Nebius AI Studio (Token Factory) exposes an OpenAI-compatible REST API. The extractable metadata
# streams mirror OpenAI's object-management endpoints; the chat/embeddings/rerank endpoints are
# real-time inference and carry no listable data, so they are intentionally omitted.
#
# None of these list endpoints document (or, when probed, honor) a server-side timestamp filter, so
# every stream ships full-refresh only. Pagination is OpenAI-style cursor pagination (`after`/`limit`
# with `has_more`/`last_id`), which is what makes the source resumable within a run.


@dataclass(frozen=True)
class NebiusAIEndpointConfig:
    name: str
    path: str
    # Stable created-style field used for datetime partitioning. Every object carries a Unix-epoch
    # creation timestamp that never changes, unlike status/updated fields.
    partition_key: Optional[str] = None
    # OpenAI-style cursor pagination (`after`/`limit`). `/models` returns the full list in one
    # response, so it opts out.
    paginated: bool = True
    # `/operations` pages with an ISO 8601 `cursor_time` instead of `after`, and returns no `has_more`.
    time_cursor_paginated: bool = False
    # Child endpoints listed once per fine-tuning job; `path` carries a `{job_id}` placeholder.
    per_fine_tuning_job: bool = False
    params: dict[str, Any] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


NEBIUS_AI_ENDPOINTS: dict[str, NebiusAIEndpointConfig] = {
    "models": NebiusAIEndpointConfig(
        name="models",
        path="/models",
        partition_key="created",
        paginated=False,
    ),
    "files": NebiusAIEndpointConfig(
        name="files",
        path="/files",
        partition_key="created_at",
    ),
    "batches": NebiusAIEndpointConfig(
        name="batches",
        path="/batches",
        partition_key="created_at",
    ),
    "fine_tuning_jobs": NebiusAIEndpointConfig(
        name="fine_tuning_jobs",
        path="/fine_tuning/jobs",
        partition_key="created_at",
    ),
    "fine_tuning_job_events": NebiusAIEndpointConfig(
        name="fine_tuning_job_events",
        path="/fine_tuning/jobs/{job_id}/events",
        partition_key="created_at",
        per_fine_tuning_job=True,
        # Event ids are only documented as unique within their job.
        primary_keys=["fine_tuning_job_id", "id"],
    ),
    "fine_tuning_job_checkpoints": NebiusAIEndpointConfig(
        name="fine_tuning_job_checkpoints",
        path="/fine_tuning/jobs/{job_id}/checkpoints",
        partition_key="created_at",
        per_fine_tuning_job=True,
        primary_keys=["fine_tuning_job_id", "id"],
    ),
    "datasets": NebiusAIEndpointConfig(
        name="datasets",
        path="/datasets",
        partition_key="created_at",
        params={"sort_by": "created_at", "sort_order": "desc"},
    ),
    "operations": NebiusAIEndpointConfig(
        name="operations",
        path="/operations",
        partition_key="created_at",
        time_cursor_paginated=True,
    ),
}

FINE_TUNING_JOBS_PATH = NEBIUS_AI_ENDPOINTS["fine_tuning_jobs"].path

ENDPOINTS = tuple(NEBIUS_AI_ENDPOINTS.keys())

# No endpoint advertises incremental fields: the API has no server-side timestamp filter, so an
# "incremental" sync would still page through the whole list every run. Kept for parity with the
# per-endpoint schema wiring and to make the full-refresh posture explicit.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in NEBIUS_AI_ENDPOINTS}
