from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class MetorialEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # Field used to build the server-side `<field>[gt]` filter when the user hasn't picked one.
    default_incremental_field: Optional[str] = None
    # Stable datetime column to partition by. Never `updated_at` (partitions would rewrite each sync).
    partition_key: str = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Whether append is a safe sync mode. False for resources whose rows mutate (they carry an
    # `updated_at`, so a later version re-appears under the same id and append would duplicate it),
    # True only for immutable append-only event streams.
    supports_append: bool = False
    # Fields stripped from every row before it lands in the warehouse (e.g. live client secrets).
    drop_fields: list[str] = field(default_factory=list)


METORIAL_ENDPOINTS: dict[str, MetorialEndpointConfig] = {
    # Sessions carry an `updated_at`, so sync incrementally on it and merge (append would duplicate a
    # session each time its status/usage changes). `client_secret` is a live credential we never want
    # to persist to the warehouse.
    "sessions": MetorialEndpointConfig(
        name="sessions",
        path="/sessions",
        default_incremental_field="updated_at",
        incremental_fields=[_incremental_field("updated_at"), _incremental_field("created_at")],
        drop_fields=["client_secret"],
    ),
    # MCP protocol messages are immutable events keyed on `created_at` (the object exposes no
    # `updated_at`), so append is safe and cheap.
    "session_messages": MetorialEndpointConfig(
        name="session_messages",
        path="/session-messages",
        default_incremental_field="created_at",
        incremental_fields=[_incremental_field("created_at")],
        supports_append=True,
    ),
    # Session errors are append-only diagnostic records keyed on `created_at`.
    "session_errors": MetorialEndpointConfig(
        name="session_errors",
        path="/session-errors",
        default_incremental_field="created_at",
        incremental_fields=[_incremental_field("created_at")],
        supports_append=True,
    ),
    # Provider runs carry an `updated_at` (and a `completed_at` that lands after creation), so merge on
    # `updated_at` to pick up completions rather than appending duplicate rows.
    "provider_runs": MetorialEndpointConfig(
        name="provider_runs",
        path="/provider-runs",
        default_incremental_field="updated_at",
        incremental_fields=[_incremental_field("updated_at"), _incremental_field("created_at")],
    ),
    # Tool calls transition status (waiting_for_response -> succeeded/failed) but the object exposes no
    # `updated_at`, so we sync incrementally on `created_at` and merge: a status change after the
    # watermark has passed isn't re-captured (documented limitation), but merge keeps re-pulled
    # overlap rows deduped rather than duplicated.
    "tool_calls": MetorialEndpointConfig(
        name="tool_calls",
        path="/tool-calls",
        default_incremental_field="created_at",
        incremental_fields=[_incremental_field("created_at")],
    ),
    # Provider deployments are long-lived, mutable config objects with an `updated_at`.
    "provider_deployments": MetorialEndpointConfig(
        name="provider_deployments",
        path="/provider-deployments",
        default_incremental_field="updated_at",
        incremental_fields=[_incremental_field("updated_at"), _incremental_field("created_at")],
    ),
    # The provider catalog exposes no server-side timestamp filter, so it can only be full-refreshed.
    # It's a global reference catalog (not project-specific), so it's off by default.
    "providers": MetorialEndpointConfig(
        name="providers",
        path="/providers",
        incremental_fields=[],
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(METORIAL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in METORIAL_ENDPOINTS.items()
}
