"""Freshdesk source settings and endpoint catalog."""

from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PER_PAGE = 100


@dataclass(frozen=True)
class FreshdeskChainedFanoutConfig:
    """A second-level fan-out whose parent is itself a fan-out child.

    `build_dependent_resource` resolves its path param from a top-level endpoint, so it cannot
    express `/solutions/folders/{folder_id}/articles`, where the folder rows themselves come
    from `/solutions/categories/{category_id}/folders`.
    """

    parent_name: str
    resolve_param: str
    resolve_field: str


@dataclass(frozen=True)
class FreshdeskEndpointConfig:
    name: str
    path: str
    # Server-side incremental filter param name (e.g. "updated_since", "_updated_since").
    # ``None`` means the endpoint has no server-side timestamp filter -> full refresh only.
    updated_since_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Stable field used for datetime partitioning. Always a creation timestamp, never a
    # mutable field like ``updated_at`` (partitions must not rewrite on every sync).
    partition_key: Optional[str] = None
    # Extra static query params (e.g. ordering on incremental endpoints).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Key the list lives under when the response is an object rather than a bare array.
    data_key: Optional[str] = None
    # Read by the shared fan-out helper to size parent and child pages.
    page_size: int = PER_PAGE
    # Set on a sub-resource that is fetched once per row of a top-level endpoint.
    fanout: Optional[DependentEndpointConfig] = None
    chained_fanout: Optional[FreshdeskChainedFanoutConfig] = None


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# A parent row can be deleted between the listing page it arrived on and the child fetch that
# follows it, which 404s. That must not sink the whole fan-out.
IGNORE_DELETED_PARENT: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


FRESHDESK_ENDPOINTS: dict[str, FreshdeskEndpointConfig] = {
    "tickets": FreshdeskEndpointConfig(
        name="tickets",
        path="/api/v2/tickets",
        # Freshdesk caps the tickets list at ~300 pages per query. Syncing incrementally on
        # `updated_since` keeps each window small and lets the watermark advance across runs,
        # which is the documented way to page beyond that cap.
        updated_since_param="updated_since",
        default_incremental_field="updated_at",
        incremental_fields=[_datetime_incremental_field("updated_at")],
        partition_key="created_at",
        # Force ascending updated_at so the incremental watermark advances monotonically.
        extra_params={"order_by": "updated_at", "order_type": "asc"},
    ),
    "contacts": FreshdeskEndpointConfig(
        name="contacts",
        path="/api/v2/contacts",
        # Freshdesk uses the underscore-prefixed `_updated_since` on the contacts endpoint.
        updated_since_param="_updated_since",
        default_incremental_field="updated_at",
        incremental_fields=[_datetime_incremental_field("updated_at")],
        partition_key="created_at",
    ),
    "companies": FreshdeskEndpointConfig(
        name="companies",
        path="/api/v2/companies",
        partition_key="created_at",
    ),
    "agents": FreshdeskEndpointConfig(name="agents", path="/api/v2/agents"),
    "groups": FreshdeskEndpointConfig(name="groups", path="/api/v2/groups"),
    "roles": FreshdeskEndpointConfig(name="roles", path="/api/v2/roles"),
    "products": FreshdeskEndpointConfig(name="products", path="/api/v2/products"),
    "skills": FreshdeskEndpointConfig(name="skills", path="/api/v2/skills", data_key="skills"),
    "ticket_fields": FreshdeskEndpointConfig(name="ticket_fields", path="/api/v2/ticket_fields"),
    "time_entries": FreshdeskEndpointConfig(
        name="time_entries",
        path="/api/v2/time_entries",
        partition_key="created_at",
    ),
    "satisfaction_ratings": FreshdeskEndpointConfig(
        name="satisfaction_ratings",
        path="/api/v2/surveys/satisfaction_ratings",
        partition_key="created_at",
    ),
    "sla_policies": FreshdeskEndpointConfig(name="sla_policies", path="/api/v2/sla_policies"),
    "business_hours": FreshdeskEndpointConfig(name="business_hours", path="/api/v2/business_hours"),
    "canned_response_folders": FreshdeskEndpointConfig(
        name="canned_response_folders", path="/api/v2/canned_response_folders"
    ),
    "contact_fields": FreshdeskEndpointConfig(name="contact_fields", path="/api/v2/contact_fields"),
    "conversations": FreshdeskEndpointConfig(
        name="conversations",
        path="/api/v2/tickets/{ticket_id}/conversations",
        # The endpoint takes no timestamp filter of its own. Incremental sync instead narrows
        # the tickets the fan-out walks, so the watermark still has to be a conversation field.
        default_incremental_field="updated_at",
        incremental_fields=[_datetime_incremental_field("updated_at")],
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="tickets",
            resolve_param="ticket_id",
            resolve_field="id",
            # Conversation rows already carry `ticket_id`; nothing needs injecting from the parent.
            include_from_parent=[],
            # Walk the parent oldest-first so the run covers whole tickets in watermark order.
            parent_params={"order_by": "updated_at", "order_type": "asc"},
            child_response_actions=IGNORE_DELETED_PARENT,
        ),
    ),
    "canned_responses": FreshdeskEndpointConfig(
        name="canned_responses",
        path="/api/v2/canned_response_folders/{folder_id}/responses",
        fanout=DependentEndpointConfig(
            parent_name="canned_response_folders",
            resolve_param="folder_id",
            resolve_field="id",
            # Canned response rows already carry `folder_id`.
            include_from_parent=[],
            child_response_actions=IGNORE_DELETED_PARENT,
        ),
    ),
    "solution_categories": FreshdeskEndpointConfig(name="solution_categories", path="/api/v2/solutions/categories"),
    "solution_folders": FreshdeskEndpointConfig(
        name="solution_folders",
        path="/api/v2/solutions/categories/{category_id}/folders",
        fanout=DependentEndpointConfig(
            parent_name="solution_categories",
            resolve_param="category_id",
            resolve_field="id",
            # A folder row places itself only through the nested `hierarchy` list, so the owning
            # category has to come from the parent to be queryable as a column.
            include_from_parent=["id"],
            parent_field_renames={"id": "category_id"},
            child_response_actions=IGNORE_DELETED_PARENT,
        ),
    ),
    "solution_articles": FreshdeskEndpointConfig(
        name="solution_articles",
        path="/api/v2/solutions/folders/{folder_id}/articles",
        partition_key="created_at",
        chained_fanout=FreshdeskChainedFanoutConfig(
            parent_name="solution_folders", resolve_param="folder_id", resolve_field="id"
        ),
    ),
}

ENDPOINTS = tuple(FRESHDESK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FRESHDESK_ENDPOINTS.items()
}
