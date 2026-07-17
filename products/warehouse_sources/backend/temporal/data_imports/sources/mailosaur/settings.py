from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class MailosaurEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime column to partition by (never a mutable field like `updated`).
    partition_key: Optional[str] = None
    # Whether the endpoint is scoped per server and must be fanned out over `GET /api/servers`.
    fan_out_over_servers: bool = False
    should_sync_default: bool = True


MAILOSAUR_ENDPOINTS: dict[str, MailosaurEndpointConfig] = {
    # Every server (virtual inbox) on the account. Full refresh only — the servers list
    # carries no timestamp we could filter or partition on.
    "servers": MailosaurEndpointConfig(
        name="servers",
        path="/api/servers",
        primary_keys=["id"],
    ),
    # Message summaries per server. Fanned out over every server, incremental via the
    # `receivedAfter` server-side filter on the immutable `received` timestamp. Message ids
    # are GUIDs, but the summary payload omits the server, so we inject it and key on
    # (server, id) to stay unique table-wide across the fan-out.
    "messages": MailosaurEndpointConfig(
        name="messages",
        path="/api/messages",
        primary_keys=["server", "id"],
        partition_key="received",
        fan_out_over_servers=True,
        incremental_fields=[
            {
                "label": "received",
                "type": IncrementalFieldType.DateTime,
                "field": "received",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Rolling last-31-days of account transactional usage (emails / SMS / previews per day).
    # No server-side time filter, so it is full refresh only.
    "usage_transactions": MailosaurEndpointConfig(
        name="usage_transactions",
        path="/api/usage/transactions",
        primary_keys=["timestamp"],
    ),
}

ENDPOINTS = tuple(MAILOSAUR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MAILOSAUR_ENDPOINTS.items()
}
