"""Help Scout source settings and endpoint catalog."""

from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

HELP_SCOUT_API_BASE = "https://api.helpscout.net/v2"


@frozen
class HelpScoutEndpointConfig:
    name: str
    path: str
    # Key the rows live under inside the HAL `_embedded` object.
    embedded_key: str
    primary_key: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Server-side `modifiedSince` filter param name; None means full refresh only.
    updated_since_param: Optional[str] = None
    # Every Help Scout resource carries an immutable createdAt.
    partition_key: Optional[str] = "createdAt"
    # Only conversations/customers document a `sortField`/`sortOrder` param; other list
    # endpoints don't accept one (and reject unknown params on some Help Scout API versions).
    supports_sort: bool = False
    # Structural requirement of `FanoutEndpointLike` (see common/rest_source/fanout.py); unused
    # here since threads' fan-out passes `page_size_param=None` (Help Scout has no page-size param).
    page_size: int = 50
    fanout: Optional[DependentEndpointConfig] = None


HELP_SCOUT_ENDPOINTS: dict[str, HelpScoutEndpointConfig] = {
    "conversations": HelpScoutEndpointConfig(
        name="conversations",
        path="/conversations",
        embedded_key="conversations",
        incremental_fields=[incremental_field("modifiedAt")],
        default_incremental_field="modifiedAt",
        updated_since_param="modifiedSince",
        supports_sort=True,
    ),
    "customers": HelpScoutEndpointConfig(
        name="customers",
        path="/customers",
        embedded_key="customers",
        incremental_fields=[incremental_field("modifiedAt")],
        default_incremental_field="modifiedAt",
        updated_since_param="modifiedSince",
        supports_sort=True,
    ),
    "mailboxes": HelpScoutEndpointConfig(
        name="mailboxes",
        path="/mailboxes",
        embedded_key="mailboxes",
    ),
    "users": HelpScoutEndpointConfig(
        name="users",
        path="/users",
        embedded_key="users",
    ),
    "tags": HelpScoutEndpointConfig(
        name="tags",
        path="/tags",
        embedded_key="tags",
    ),
    "workflows": HelpScoutEndpointConfig(
        name="workflows",
        path="/workflows",
        embedded_key="workflows",
    ),
    "threads": HelpScoutEndpointConfig(
        name="threads",
        path="/conversations/{conversation_id}/threads",
        embedded_key="threads",
        # Thread ids are unique only within their conversation, so the parent id is part of the
        # key to keep it unique across the whole table.
        primary_key=["conversation_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="conversations",
            resolve_param="conversation_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "conversation_id"},
        ),
    ),
}

ENDPOINTS = tuple(HELP_SCOUT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HELP_SCOUT_ENDPOINTS.items()
}
