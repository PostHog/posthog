from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

KNOCK_BASE_URL = "https://api.knock.app"

# Knock caps `page_size` at 50 on every list endpoint.
KNOCK_PAGE_SIZE = 50


@dataclass(frozen=True)
class KnockEndpointConfig:
    path: str
    # Knock wraps list responses in `entries` on most endpoints but `items` on
    # messages and workflow recipient runs (per the vendor OpenAPI spec).
    data_selector: str
    primary_keys: tuple[str, ...] = ("id",)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Request param carrying the server-side lower-bound timestamp filter.
    incremental_param: str | None = None
    # Stable datetime field to partition on; None disables partitioning.
    partition_key: str | None = None
    sort_mode: SortMode = "desc"


# Knock's list endpoints document "most recent first" ordering where they state one at
# all and accept no sort param, so every endpoint declares `sort_mode="desc"` — the
# pipeline then persists the incremental watermark only when a sync completes instead
# of checkpointing per batch on a newest-first stream.
ENDPOINTS_CONFIG: dict[str, KnockEndpointConfig] = {
    # Message delivery log — the highest-volume stream. `inserted_at[gte]` is a
    # documented server-side filter, so incremental sync genuinely reduces pages.
    "messages": KnockEndpointConfig(
        path="/v1/messages",
        data_selector="items",
        incremental_fields=[incremental_field("inserted_at")],
        incremental_param="inserted_at[gte]",
        partition_key="inserted_at",
    ),
    # Identified recipients. No server-side updated-since filter exists, so full
    # refresh only. `created_at` is nullable on users, so no partition key.
    "users": KnockEndpointConfig(
        path="/v1/users",
        data_selector="entries",
    ),
    # Tenants (per-customer notification scoping). Small table, no server-side
    # timestamp filter — full refresh only.
    "tenants": KnockEndpointConfig(
        path="/v1/tenants",
        data_selector="entries",
    ),
    # Per-recipient workflow executions. `starting_at` is a documented server-side
    # filter on when the run started, which tracks `inserted_at`.
    "workflow_recipient_runs": KnockEndpointConfig(
        path="/v1/workflow_recipient_runs",
        data_selector="items",
        incremental_fields=[incremental_field("inserted_at")],
        incremental_param="starting_at",
        partition_key="inserted_at",
    ),
}

ENDPOINTS = tuple(ENDPOINTS_CONFIG.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ENDPOINTS_CONFIG.items()
}
