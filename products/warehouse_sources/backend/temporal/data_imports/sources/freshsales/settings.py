from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class FreshsalesSelectorFanout:
    # Parent selector to enumerate, e.g. "selector/deal_pipelines".
    parent_resource: str
    parent_object_key: str
    # Child path per parent, formatted with the parent's id.
    child_path: str
    # Page through the parent and each child. Selectors return everything in one response; listing
    # APIs such as /lists don't.
    paginated: bool = False
    # Column that carries the parent id on each child row, for children whose rows don't include it.
    parent_id_column: Optional[str] = None


@dataclass(frozen=True)
class FreshsalesEndpointConfig:
    name: str
    # API resource segment, e.g. "contacts" -> /crm/sales/api/contacts/...
    resource: str
    # Top-level array key in the JSON response envelope (Freshsales pluralizes the object name).
    object_key: str
    # View-based objects (contacts, deals, ...) must resolve a "view" id via /<resource>/filters
    # before they can be listed. Direct-list objects (tasks, appointments, ...) are queried directly.
    requires_view: bool = False
    # Static query params sent on every request (e.g. {"filter": "open"} for tasks).
    params: dict[str, str] = field(default_factory=dict)
    primary_key: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime field for datetime partitioning. Only set where the field is confirmed present
    # and immutable (never updated_at).
    partition_key: Optional[str] = None
    # Sort field to request for stable pagination. Only set on endpoints that support `sort`.
    sort: Optional[str] = None
    # Some objects (notably leads) don't exist on every Freshsales account; a 404 means "skip", not "fail".
    tolerate_missing: bool = False
    # Selector endpoints are portal-wide lookup collections returned whole in a single unpaginated
    # response: they ignore page/per_page, so asking for page 2 re-returns the same list. Freshsales
    # also doesn't publish their response bodies, so the envelope key falls back to whatever list the
    # response carries rather than silently syncing an empty table.
    is_selector: bool = False
    # Some selector endpoints only cover the default parent, so the whole collection needs a walk
    # over the parent selector instead of one request.
    selector_fanout: Optional[FreshsalesSelectorFanout] = None
    # Incremental sync is full-refresh only for now (see note below), so this stays empty for every
    # endpoint. Kept as the source of truth so enabling incremental later is a settings-only change.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Freshsales has no reliably paginated server-side timestamp filter: the only updated_at filter
# (POST /filtered_search) silently drops custom fields and has undocumented pagination, so every
# endpoint ships as full refresh (matching Airbyte's Freshsales connector). The view/scroll list
# APIs return complete records but offer no server-side incremental cutoff.
FRESHSALES_ENDPOINTS: dict[str, FreshsalesEndpointConfig] = {
    "contacts": FreshsalesEndpointConfig(
        name="contacts",
        resource="contacts",
        object_key="contacts",
        requires_view=True,
        partition_key="created_at",
        sort="created_at",
    ),
    "sales_accounts": FreshsalesEndpointConfig(
        name="sales_accounts",
        resource="sales_accounts",
        object_key="sales_accounts",
        requires_view=True,
        partition_key="created_at",
        sort="created_at",
    ),
    "deals": FreshsalesEndpointConfig(
        name="deals",
        resource="deals",
        object_key="deals",
        requires_view=True,
        partition_key="created_at",
        sort="created_at",
    ),
    "leads": FreshsalesEndpointConfig(
        name="leads",
        resource="leads",
        object_key="leads",
        requires_view=True,
        partition_key="created_at",
        sort="created_at",
        # Many newer "contacts-based" Freshsales accounts have no separate leads object.
        tolerate_missing=True,
    ),
    "sales_activities": FreshsalesEndpointConfig(
        name="sales_activities",
        resource="sales_activities",
        object_key="sales_activities",
    ),
    "open_tasks": FreshsalesEndpointConfig(
        name="open_tasks",
        resource="tasks",
        object_key="tasks",
        params={"filter": "open"},
    ),
    "completed_tasks": FreshsalesEndpointConfig(
        name="completed_tasks",
        resource="tasks",
        object_key="tasks",
        params={"filter": "completed"},
    ),
    "past_appointments": FreshsalesEndpointConfig(
        name="past_appointments",
        resource="appointments",
        object_key="appointments",
        params={"filter": "past"},
    ),
    "upcoming_appointments": FreshsalesEndpointConfig(
        name="upcoming_appointments",
        resource="appointments",
        object_key="appointments",
        params={"filter": "upcoming"},
    ),
    "owners": FreshsalesEndpointConfig(
        name="owners",
        resource="selector/owners",
        object_key="users",
        is_selector=True,
    ),
    "deal_stages": FreshsalesEndpointConfig(
        name="deal_stages",
        resource="selector/deal_stages",
        object_key="deal_stages",
        is_selector=True,
        # /selector/deal_stages returns the default pipeline's stages only, so an account with more
        # than one pipeline would be missing the stages its deals point at.
        selector_fanout=FreshsalesSelectorFanout(
            parent_resource="selector/deal_pipelines",
            parent_object_key="deal_pipelines",
            child_path="selector/deal_pipelines/{parent_id}/deal_stages",
        ),
    ),
    "deal_pipelines": FreshsalesEndpointConfig(
        name="deal_pipelines",
        resource="selector/deal_pipelines",
        object_key="deal_pipelines",
        is_selector=True,
    ),
    "lifecycle_stages": FreshsalesEndpointConfig(
        name="lifecycle_stages",
        resource="selector/lifecycle_stages",
        object_key="lifecycle_stages",
        is_selector=True,
    ),
    "lead_sources": FreshsalesEndpointConfig(
        name="lead_sources",
        resource="selector/lead_sources",
        object_key="lead_sources",
        is_selector=True,
    ),
    "sales_activity_types": FreshsalesEndpointConfig(
        name="sales_activity_types",
        resource="selector/sales_activity_types",
        object_key="sales_activity_types",
        is_selector=True,
    ),
    "sales_activity_outcomes": FreshsalesEndpointConfig(
        name="sales_activity_outcomes",
        resource="selector/sales_activity_outcomes",
        object_key="sales_activity_outcomes",
        is_selector=True,
    ),
    "lists": FreshsalesEndpointConfig(
        name="lists",
        resource="lists",
        object_key="lists",
    ),
    "list_contacts": FreshsalesEndpointConfig(
        name="list_contacts",
        # Probed by check_credentials; rows come from the fan-out below.
        resource="lists",
        object_key="contacts",
        # A contact can belong to several lists.
        primary_key=["list_id", "id"],
        partition_key="created_at",
        selector_fanout=FreshsalesSelectorFanout(
            parent_resource="lists",
            parent_object_key="lists",
            child_path="contacts/lists/{parent_id}",
            paginated=True,
            parent_id_column="list_id",
        ),
    ),
}

ENDPOINTS = tuple(FRESHSALES_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FRESHSALES_ENDPOINTS.items()
}
