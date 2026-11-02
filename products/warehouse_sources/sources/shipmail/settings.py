from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class ShipmailEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    required_scope: str
    partition_key: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)


SHIPMAIL_ENDPOINTS: dict[str, ShipmailEndpointConfig] = {
    "messages": ShipmailEndpointConfig(
        name="messages",
        path="/messages/analytics",
        primary_keys=["id"],
        required_scope="messages:read",
        partition_key="created_at",
        incremental_fields=[incremental_field("updated_at")],
    ),
    "mailboxes": ShipmailEndpointConfig(
        name="mailboxes",
        path="/mailboxes",
        primary_keys=["id"],
        required_scope="mailboxes:read",
        partition_key="created_at",
    ),
    "domains": ShipmailEndpointConfig(
        name="domains",
        path="/domains",
        primary_keys=["id"],
        required_scope="domains:read",
        partition_key="created_at",
    ),
    "suppressions": ShipmailEndpointConfig(
        name="suppressions",
        path="/suppressions",
        primary_keys=["email_address"],
        required_scope="suppressions:read",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(SHIPMAIL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SHIPMAIL_ENDPOINTS.items() if config.incremental_fields
}
