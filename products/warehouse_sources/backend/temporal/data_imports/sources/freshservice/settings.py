"""Freshservice source settings and endpoint catalog."""

from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PER_PAGE = 100


@dataclass
class FreshserviceEndpointConfig:
    name: str
    path: str
    # Key the list lives under in the response envelope. Every Freshservice v2 list
    # endpoint wraps its results in a resource-named object (e.g. {"tickets": [...]}),
    # unlike Freshdesk which returns bare arrays for most endpoints.
    data_key: str
    # Server-side incremental filter param name (e.g. "updated_since"). ``None`` means the
    # endpoint has no server-side timestamp filter -> full refresh only.
    updated_since_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Stable field used for datetime partitioning. Always a creation timestamp, never a
    # mutable field like ``updated_at`` (partitions must not rewrite on every sync).
    partition_key: Optional[str] = None
    # Extra static query params (e.g. ordering on incremental endpoints).
    extra_params: dict[str, str] = field(default_factory=dict)


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Top-level Freshservice v2 endpoints. Fan-out resources (ticket conversations, solution
# articles/folders/categories) and webhook-driven deltas are intentionally left out of this
# first cut — see source.py module note.
FRESHSERVICE_ENDPOINTS: dict[str, FreshserviceEndpointConfig] = {
    "tickets": FreshserviceEndpointConfig(
        name="tickets",
        path="/api/v2/tickets",
        data_key="tickets",
        # The tickets list is the only Freshservice endpoint that documents a server-side
        # `updated_since` filter. Syncing incrementally on it keeps each window small and lets
        # the watermark advance across runs, which is also how you page past the deep-pagination
        # slowdown (Freshservice discourages paging beyond page 500).
        updated_since_param="updated_since",
        default_incremental_field="updated_at",
        incremental_fields=[_datetime_incremental_field("updated_at")],
        partition_key="created_at",
        # Force ascending updated_at so the incremental watermark advances monotonically and the
        # declared sort_mode="asc" is honest. NOTE: this ordering could not be curl-verified against
        # a live Freshservice account (no credentials); it mirrors the reviewed Freshdesk sibling
        # source, whose v2 API is near-identical. Freshworks APIs ignore unknown query params rather
        # than rejecting them, so an unsupported `order_by` degrades to the API default, not a 400.
        extra_params={"order_by": "updated_at", "order_type": "asc"},
    ),
    "problems": FreshserviceEndpointConfig(
        name="problems",
        path="/api/v2/problems",
        data_key="problems",
        partition_key="created_at",
    ),
    "changes": FreshserviceEndpointConfig(
        name="changes",
        path="/api/v2/changes",
        data_key="changes",
        partition_key="created_at",
    ),
    "releases": FreshserviceEndpointConfig(
        name="releases",
        path="/api/v2/releases",
        data_key="releases",
        partition_key="created_at",
    ),
    "requesters": FreshserviceEndpointConfig(
        name="requesters",
        path="/api/v2/requesters",
        data_key="requesters",
        partition_key="created_at",
    ),
    "requester_groups": FreshserviceEndpointConfig(
        name="requester_groups",
        path="/api/v2/requester_groups",
        data_key="requester_groups",
    ),
    "agents": FreshserviceEndpointConfig(
        name="agents",
        path="/api/v2/agents",
        data_key="agents",
    ),
    "agent_groups": FreshserviceEndpointConfig(
        name="agent_groups",
        path="/api/v2/groups",
        data_key="groups",
    ),
    "agent_roles": FreshserviceEndpointConfig(
        name="agent_roles",
        path="/api/v2/roles",
        data_key="roles",
    ),
    "assets": FreshserviceEndpointConfig(
        name="assets",
        path="/api/v2/assets",
        data_key="assets",
        partition_key="created_at",
    ),
    "asset_types": FreshserviceEndpointConfig(
        name="asset_types",
        path="/api/v2/asset_types",
        data_key="asset_types",
    ),
    "software": FreshserviceEndpointConfig(
        name="software",
        path="/api/v2/applications",
        data_key="applications",
    ),
    "purchase_orders": FreshserviceEndpointConfig(
        name="purchase_orders",
        path="/api/v2/purchase_orders",
        data_key="purchase_orders",
        partition_key="created_at",
    ),
    "products": FreshserviceEndpointConfig(
        name="products",
        path="/api/v2/products",
        data_key="products",
    ),
    "vendors": FreshserviceEndpointConfig(
        name="vendors",
        path="/api/v2/vendors",
        data_key="vendors",
    ),
    "locations": FreshserviceEndpointConfig(
        name="locations",
        path="/api/v2/locations",
        data_key="locations",
    ),
    "departments": FreshserviceEndpointConfig(
        name="departments",
        path="/api/v2/departments",
        data_key="departments",
    ),
}

ENDPOINTS = tuple(FRESHSERVICE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FRESHSERVICE_ENDPOINTS.items()
}
