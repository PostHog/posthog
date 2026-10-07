"""Freshservice source settings and endpoint catalog."""

from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PER_PAGE = 100

# Freshservice's ticket listing only returns the last 30 days unless `updated_since` is set, so
# the time-entry fan-out asks for everything from the epoch — a sweep of every ticket's time
# entries has to visit every ticket, not just the recent ones.
_ALL_TICKETS_SINCE = "1970-01-01T00:00:00Z"

# A ticket, problem, change, release or application can be deleted between the parent listing and the child fetch; treat
# that 404 as an empty child rather than failing the whole sweep.
_IGNORE_MISSING_PARENT: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]

_SOFTWARE_FANOUT = DependentEndpointConfig(
    parent_name="software",
    resolve_param="application_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "application_id"},
    child_response_actions=_IGNORE_MISSING_PARENT,
)

_TICKET_FANOUT = DependentEndpointConfig(
    parent_name="tickets",
    resolve_param="ticket_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "ticket_id"},
    parent_params={"updated_since": _ALL_TICKETS_SINCE, "order_by": "updated_at", "order_type": "asc"},
    child_response_actions=_IGNORE_MISSING_PARENT,
)


def _parent_fanout(parent_name: str, parent_id_field: str) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name=parent_name,
        resolve_param=parent_id_field,
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": parent_id_field},
        child_response_actions=_IGNORE_MISSING_PARENT,
    )


# The account-wide approvals listing rejects a request that carries only `parent`, so the table
# is swept one (parent module, status) slice at a time.
APPROVAL_PARENTS = ("ticket", "change")
APPROVAL_STATUSES = ("requested", "approved", "rejected", "cancelled")


# Mutable by choice: instances flow into `build_dependent_resource`'s
# `endpoint_configs: Mapping[str, FanoutEndpointLike]`, and mypy treats a frozen dataclass's
# fields as read-only, which is incompatible with that Protocol's plain attributes.
@dataclass(frozen=False)
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
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    page_size: int = PER_PAGE
    # Set when the endpoint is a sub-resource reached by iterating a parent listing.
    fanout: Optional[DependentEndpointConfig] = None


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Freshservice v2 endpoints. Most are top-level listings; the ones carrying a `fanout` config
# are sub-resources reached by iterating their parent listing.
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
    "sla_policies": FreshserviceEndpointConfig(
        name="sla_policies",
        path="/api/v2/sla_policies",
        data_key="sla_policies",
    ),
    "approvals": FreshserviceEndpointConfig(
        name="approvals",
        path="/api/v2/approvals",
        data_key="approvals",
        partition_key="created_at",
        # Ticket and change approvals come from separate modules, so `parent` stays in the key.
        primary_keys=["parent", "id"],
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
    "contracts": FreshserviceEndpointConfig(
        name="contracts",
        path="/api/v2/contracts",
        data_key="contracts",
        partition_key="created_at",
    ),
    "contract_types": FreshserviceEndpointConfig(
        name="contract_types",
        path="/api/v2/contract_types",
        data_key="contract_types",
    ),
    # The account-wide listing, rather than the per-asset one: it returns the same edges plus
    # those anchored on agents, requesters, departments and software, without fanning out.
    "relationships": FreshserviceEndpointConfig(
        name="relationships",
        path="/api/v2/relationships",
        data_key="relationships",
        partition_key="created_at",
    ),
    "relationship_types": FreshserviceEndpointConfig(
        name="relationship_types",
        path="/api/v2/relationship_types",
        data_key="relationship_types",
    ),
    # `id` is documented as unique per application user, not across applications, so the parent
    # id stays in the key.
    "software_users": FreshserviceEndpointConfig(
        name="software_users",
        path="/api/v2/applications/{application_id}/users",
        data_key="application_users",
        partition_key="created_at",
        primary_keys=["application_id", "id"],
        fanout=_SOFTWARE_FANOUT,
    ),
    "software_installations": FreshserviceEndpointConfig(
        name="software_installations",
        path="/api/v2/applications/{application_id}/installations",
        data_key="installations",
        partition_key="created_at",
        primary_keys=["application_id", "id"],
        fanout=_SOFTWARE_FANOUT,
    ),
    # Time entries have no server-side timestamp filter of their own, so this table is full
    # refresh only; the row carries no ticket reference either, hence the injected `ticket_id`.
    "ticket_time_entries": FreshserviceEndpointConfig(
        name="ticket_time_entries",
        path="/api/v2/tickets/{ticket_id}/time_entries",
        data_key="time_entries",
        partition_key="created_at",
        primary_keys=["ticket_id", "id"],
        fanout=_TICKET_FANOUT,
    ),
    # Conversation rows already carry `ticket_id`; the injected parent id writes the same value.
    "ticket_conversations": FreshserviceEndpointConfig(
        name="ticket_conversations",
        path="/api/v2/tickets/{ticket_id}/conversations",
        data_key="conversations",
        partition_key="created_at",
        primary_keys=["ticket_id", "id"],
        fanout=_TICKET_FANOUT,
    ),
    # Task ids are numbered per parent record, so the parent id stays in each task table's key.
    "ticket_tasks": FreshserviceEndpointConfig(
        name="ticket_tasks",
        path="/api/v2/tickets/{ticket_id}/tasks",
        data_key="tasks",
        partition_key="created_at",
        primary_keys=["ticket_id", "id"],
        fanout=_TICKET_FANOUT,
    ),
    "problem_tasks": FreshserviceEndpointConfig(
        name="problem_tasks",
        path="/api/v2/problems/{problem_id}/tasks",
        data_key="tasks",
        partition_key="created_at",
        primary_keys=["problem_id", "id"],
        fanout=_parent_fanout("problems", "problem_id"),
    ),
    "change_tasks": FreshserviceEndpointConfig(
        name="change_tasks",
        path="/api/v2/changes/{change_id}/tasks",
        data_key="tasks",
        partition_key="created_at",
        primary_keys=["change_id", "id"],
        fanout=_parent_fanout("changes", "change_id"),
    ),
    "release_tasks": FreshserviceEndpointConfig(
        name="release_tasks",
        path="/api/v2/releases/{release_id}/tasks",
        data_key="tasks",
        partition_key="created_at",
        primary_keys=["release_id", "id"],
        fanout=_parent_fanout("releases", "release_id"),
    ),
}

ENDPOINTS = tuple(FRESHSERVICE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FRESHSERVICE_ENDPOINTS.items()
}
