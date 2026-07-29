from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Nebius AI Studio (Token Factory) exposes an OpenAI-compatible REST API. The extractable metadata
# streams mirror OpenAI's object-management endpoints; the chat/embeddings/rerank endpoints are
# real-time inference and carry no listable data, so they are intentionally omitted.
#
# None of these list endpoints document (or, when probed, honor) a server-side timestamp filter, so
# every stream ships full-refresh only. Pagination is OpenAI-style cursor pagination (`after`/`limit`
# with `has_more`/`last_id`), which is what makes the source resumable within a run.


@dataclass
class NebiusAIEndpointConfig:
    name: str
    path: str
    # Stable created-style field used for datetime partitioning. Every object carries a Unix-epoch
    # creation timestamp that never changes, unlike status/updated fields.
    partition_key: Optional[str] = None
    # OpenAI-style cursor pagination (`after`/`limit`). `/models` returns the full list in one
    # response, so it opts out.
    paginated: bool = True
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
}

ENDPOINTS = tuple(NEBIUS_AI_ENDPOINTS.keys())

# No endpoint advertises incremental fields: the API has no server-side timestamp filter, so an
# "incremental" sync would still page through the whole list every run. Kept for parity with the
# per-endpoint schema wiring and to make the full-refresh posture explicit.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in NEBIUS_AI_ENDPOINTS}
