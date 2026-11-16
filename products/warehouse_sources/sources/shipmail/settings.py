from dataclasses import field
from typing import Literal

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, frozen, incremental_field


@frozen
class ShipmailEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    required_scopes: tuple[str, ...]
    partition_key: str
    sort_mode: Literal["asc", "desc"] | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    page_size: int = 100
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = None


SHIPMAIL_ENDPOINTS: dict[str, ShipmailEndpointConfig] = {
    "messages": ShipmailEndpointConfig(
        name="messages",
        path="/messages/analytics",
        primary_keys=["id"],
        required_scopes=("messages:read",),
        partition_key="created_at",
        sort_mode="asc",
        incremental_fields=[incremental_field("updated_at")],
    ),
    "mailboxes": ShipmailEndpointConfig(
        name="mailboxes",
        path="/mailboxes",
        primary_keys=["id"],
        required_scopes=("mailboxes:read",),
        partition_key="created_at",
        sort_mode="desc",
    ),
    "domains": ShipmailEndpointConfig(
        name="domains",
        path="/domains",
        primary_keys=["id"],
        required_scopes=("domains:read",),
        partition_key="created_at",
        sort_mode="desc",
    ),
    "suppressions": ShipmailEndpointConfig(
        name="suppressions",
        path="/suppressions",
        primary_keys=["email_address"],
        required_scopes=("suppressions:read",),
        partition_key="created_at",
        sort_mode="desc",
    ),
    "threads": ShipmailEndpointConfig(
        name="threads",
        path="/threads?mailbox_id={mailbox_id}",
        primary_keys=["mailbox_id", "id"],
        required_scopes=("threads:read", "mailboxes:read"),
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="mailboxes",
            resolve_param="mailbox_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "mailbox_id"},
        ),
    ),
    "newsletters": ShipmailEndpointConfig(
        name="newsletters",
        path="/newsletters",
        primary_keys=["id"],
        required_scopes=("newsletters:read",),
        partition_key="created_at",
    ),
    "audience_subscribers": ShipmailEndpointConfig(
        name="audience_subscribers",
        path="/audiences/{audience_id}/subscribers",
        primary_keys=["audience_id", "id"],
        required_scopes=("audiences:read",),
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="audiences",
            resolve_param="audience_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "audience_id"},
        ),
    ),
    "members": ShipmailEndpointConfig(
        name="members",
        path="/members",
        primary_keys=["id"],
        required_scopes=("members:read",),
        partition_key="created_at",
    ),
}

SHIPMAIL_PARENT_ENDPOINTS = {
    "audiences": ShipmailEndpointConfig(
        name="audiences",
        path="/audiences",
        primary_keys=["id"],
        required_scopes=("audiences:read",),
        partition_key="created_at",
    )
}

ENDPOINTS = tuple(SHIPMAIL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SHIPMAIL_ENDPOINTS.items() if config.incremental_fields
}
