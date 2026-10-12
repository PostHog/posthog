from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

KNOCK_BASE_URL = "https://api.knock.app"

# Knock caps `page_size` at 50 on every list endpoint.
KNOCK_PAGE_SIZE = 50


@dataclass(frozen=True)
class KnockEndpointConfig:
    name: str
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
    # Set on an endpoint reached by fanning out over a parent list endpoint, one child
    # request per parent row.
    fanout: DependentEndpointConfig | None = None
    # Cleared for a table too expensive to sync unless the user asks for it.
    should_sync_default: bool = True
    default_incremental_lookback_seconds: int | None = None
    page_size: int = KNOCK_PAGE_SIZE

    @property
    def default_incremental_field(self) -> str | None:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None


# A parent deleted between the parent listing and its child fetch 404s; skip it rather
# than failing the whole fan-out.
_SKIP_DELETED_PARENT: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


def _message_fanout() -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="messages",
        resolve_param="message_id",
        resolve_field="id",
        include_from_parent=["id", "inserted_at"],
        parent_field_renames={"id": "message_id", "inserted_at": "message_inserted_at"},
        child_response_actions=_SKIP_DELETED_PARENT,
    )


# Knock's list endpoints document "most recent first" ordering where they state one at
# all and accept no sort param, so every endpoint declares `sort_mode="desc"` — the
# pipeline then persists the incremental watermark only when a sync completes instead
# of checkpointing per batch on a newest-first stream.
ENDPOINTS_CONFIG: dict[str, KnockEndpointConfig] = {
    # Message delivery log — the highest-volume stream. `inserted_at[gte]` is a
    # documented server-side filter, so incremental sync genuinely reduces pages.
    "messages": KnockEndpointConfig(
        name="messages",
        path="/v1/messages",
        data_selector="items",
        incremental_fields=[incremental_field("inserted_at")],
        incremental_param="inserted_at[gte]",
        partition_key="inserted_at",
    ),
    # Identified recipients. No server-side updated-since filter exists, so full
    # refresh only. `created_at` is nullable on users, so no partition key.
    "users": KnockEndpointConfig(
        name="users",
        path="/v1/users",
        data_selector="entries",
    ),
    # Tenants (per-customer notification scoping). Small table, no server-side
    # timestamp filter — full refresh only.
    "tenants": KnockEndpointConfig(
        name="tenants",
        path="/v1/tenants",
        data_selector="entries",
    ),
    # Per-recipient workflow executions. `starting_at` is a documented server-side
    # filter on when the run started, which tracks `inserted_at`.
    "workflow_recipient_runs": KnockEndpointConfig(
        name="workflow_recipient_runs",
        path="/v1/workflow_recipient_runs",
        data_selector="items",
        incremental_fields=[incremental_field("inserted_at")],
        incremental_param="starting_at",
        partition_key="inserted_at",
    ),
    # Non-user recipients. Knock has no endpoint that lists collections, so the table
    # walks the collection names the user configures on the source. Object ids are only
    # unique within a collection, and `created_at` is nullable, so no partition key.
    "objects": KnockEndpointConfig(
        name="objects",
        path="/v1/objects/{collection}",
        data_selector="entries",
        primary_keys=("collection", "id"),
    ),
    # `GET /v1/schedules` requires a workflow key and the secret API key cannot list
    # workflows, so schedules are read per user instead. Schedules whose recipient is an
    # object are not reachable this way.
    "schedules": KnockEndpointConfig(
        name="schedules",
        path="/v1/users/{user_id}/schedules",
        data_selector="entries",
        partition_key="inserted_at",
        fanout=DependentEndpointConfig(
            parent_name="users",
            resolve_param="user_id",
            resolve_field="id",
            include_from_parent=[],
            child_response_actions=_SKIP_DELETED_PARENT,
        ),
        should_sync_default=False,
    ),
    # Per-message child endpoints take no timestamp filter, so incremental syncs window
    # the parent `messages` walk on the parent's `inserted_at` instead. The lookback picks
    # up events and retries that land on a message after it was created.
    "message_events": KnockEndpointConfig(
        name="message_events",
        path="/v1/messages/{message_id}/events",
        data_selector="items",
        primary_keys=("message_id", "id"),
        incremental_fields=[incremental_field("message_inserted_at")],
        incremental_param="inserted_at[gte]",
        partition_key="inserted_at",
        fanout=_message_fanout(),
        should_sync_default=False,
        default_incremental_lookback_seconds=3 * 24 * 60 * 60,
    ),
    "message_delivery_logs": KnockEndpointConfig(
        name="message_delivery_logs",
        path="/v1/messages/{message_id}/delivery_logs",
        data_selector="items",
        primary_keys=("message_id", "id"),
        incremental_fields=[incremental_field("message_inserted_at")],
        incremental_param="inserted_at[gte]",
        partition_key="inserted_at",
        fanout=_message_fanout(),
        should_sync_default=False,
        default_incremental_lookback_seconds=24 * 60 * 60,
    ),
}

ENDPOINTS = tuple(ENDPOINTS_CONFIG.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ENDPOINTS_CONFIG.items()
}

INCREMENTAL_LOOKBACK_SECONDS: dict[str, int] = {
    name: config.default_incremental_lookback_seconds
    for name, config in ENDPOINTS_CONFIG.items()
    if config.default_incremental_lookback_seconds is not None
}
