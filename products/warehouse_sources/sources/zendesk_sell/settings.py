from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, ResponseAction

# Max `per_page` the list endpoints share (some accept more, none accept less).
PER_PAGE = 100

# A deal or order deleted after the parent page was read returns 404 for its children; skip it.
CHILD_404_IGNORE: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


# The `resource_type` values `GET /v2/:resource_type/custom_fields` accepts.
CUSTOM_FIELD_RESOURCE_TYPES = ("lead", "contact", "deal", "prospect_and_customer")


@dataclass(frozen=False)
class ZendeskSellEndpointConfig:
    name: str
    # Path under the v2 base URL, e.g. "/v2/contacts".
    path: str
    # Every Core API resource exposes a globally-unique integer `id`, so a single-column key is safe.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation timestamp to partition by. Set only for the high-volume transactional resources;
    # the small config/lookup tables (pipelines, stages, tags, sources, reasons, outcomes) are left
    # unpartitioned because partitioning a handful of rows buys nothing. Never `updated_at` — partitions
    # must not move when a record is edited.
    partition_key: Optional[str] = None
    # Whether the table is selected for sync by default in the connection wizard.
    should_sync_default: bool = True
    # Set for per-parent sub-resources such as `/v2/deals/{deal_id}/associated_contacts`.
    fanout: Optional[DependentEndpointConfig] = None
    # Set for endpoints read once per resource type, such as `/v2/{resource_type}/custom_fields`.
    # Each row gets the type it was read for in a `resource_type` column.
    resource_types: tuple[str, ...] = ()
    # Read by the shared fan-out helper; every table here is full refresh.
    page_size: int = PER_PAGE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# Core API collection endpoints (https://api.getbase.com/v2/). Each returns the standard
# `{"items": [{"data": {...}}], "meta": {"links": {"next_page": ...}}}` envelope and is paginated by
# 1-based `page` + `per_page` (max 100). All are full-refresh: the Core API exposes `sort_by` but no
# server-side `updated_after`/`since` timestamp filter, so there is no cheap way to fetch only changed
# rows (see the module docstring in zendesk_sell.py).
ZENDESK_SELL_ENDPOINTS: dict[str, ZendeskSellEndpointConfig] = {
    "contacts": ZendeskSellEndpointConfig(name="contacts", path="/v2/contacts", partition_key="created_at"),
    "deals": ZendeskSellEndpointConfig(name="deals", path="/v2/deals", partition_key="created_at"),
    "leads": ZendeskSellEndpointConfig(name="leads", path="/v2/leads", partition_key="created_at"),
    "tasks": ZendeskSellEndpointConfig(name="tasks", path="/v2/tasks", partition_key="created_at"),
    "notes": ZendeskSellEndpointConfig(name="notes", path="/v2/notes", partition_key="created_at"),
    "calls": ZendeskSellEndpointConfig(name="calls", path="/v2/calls", partition_key="created_at"),
    "text_messages": ZendeskSellEndpointConfig(
        name="text_messages", path="/v2/text_messages", partition_key="created_at"
    ),
    "visits": ZendeskSellEndpointConfig(name="visits", path="/v2/visits", partition_key="created_at"),
    "orders": ZendeskSellEndpointConfig(name="orders", path="/v2/orders", partition_key="created_at"),
    "products": ZendeskSellEndpointConfig(name="products", path="/v2/products", partition_key="created_at"),
    "collaborations": ZendeskSellEndpointConfig(
        name="collaborations", path="/v2/collaborations", partition_key="created_at"
    ),
    "users": ZendeskSellEndpointConfig(name="users", path="/v2/users", partition_key="created_at"),
    "lead_conversions": ZendeskSellEndpointConfig(
        name="lead_conversions", path="/v2/lead_conversions", partition_key="created_at"
    ),
    # Needs the Reach add-on; accounts without it cannot read this endpoint, so it starts deselected.
    "sequence_enrollments": ZendeskSellEndpointConfig(
        name="sequence_enrollments",
        path="/v2/sequence_enrollments",
        partition_key="created_at",
        should_sync_default=False,
    ),
    # Associations carry no id of their own; the contact id is unique only within its deal.
    "associated_contacts": ZendeskSellEndpointConfig(
        name="associated_contacts",
        path="/v2/deals/{deal_id}/associated_contacts",
        primary_keys=["deal_id", "contact_id"],
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="deals",
            resolve_param="deal_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "deal_id"},
            child_response_actions=CHILD_404_IGNORE,
        ),
    ),
    # The docs do not say whether a line item id is unique outside its order, so the key includes it.
    "line_items": ZendeskSellEndpointConfig(
        name="line_items",
        path="/v2/orders/{order_id}/line_items",
        primary_keys=["order_id", "id"],
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="orders",
            resolve_param="order_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "order_id"},
            child_response_actions=CHILD_404_IGNORE,
        ),
    ),
    # Small config / lookup resources — full refresh, no partitioning.
    "pipelines": ZendeskSellEndpointConfig(name="pipelines", path="/v2/pipelines"),
    "stages": ZendeskSellEndpointConfig(name="stages", path="/v2/stages"),
    "tags": ZendeskSellEndpointConfig(name="tags", path="/v2/tags"),
    "deal_sources": ZendeskSellEndpointConfig(name="deal_sources", path="/v2/deal_sources"),
    "lead_sources": ZendeskSellEndpointConfig(name="lead_sources", path="/v2/lead_sources"),
    "loss_reasons": ZendeskSellEndpointConfig(name="loss_reasons", path="/v2/loss_reasons"),
    "deal_unqualified_reasons": ZendeskSellEndpointConfig(
        name="deal_unqualified_reasons", path="/v2/deal_unqualified_reasons"
    ),
    "lead_unqualified_reasons": ZendeskSellEndpointConfig(
        name="lead_unqualified_reasons", path="/v2/lead_unqualified_reasons"
    ),
    "call_outcomes": ZendeskSellEndpointConfig(name="call_outcomes", path="/v2/call_outcomes"),
    "visit_outcomes": ZendeskSellEndpointConfig(name="visit_outcomes", path="/v2/visit_outcomes"),
    # The docs do not say whether a custom field id is unique across resource types, so the key includes it.
    "custom_fields": ZendeskSellEndpointConfig(
        name="custom_fields",
        path="/v2/{resource_type}/custom_fields",
        primary_keys=["resource_type", "id"],
        resource_types=CUSTOM_FIELD_RESOURCE_TYPES,
    ),
}

ENDPOINTS = tuple(ZENDESK_SELL_ENDPOINTS.keys())

SHOULD_SYNC_DEFAULT: dict[str, bool] = {
    name: config.should_sync_default for name, config in ZENDESK_SELL_ENDPOINTS.items()
}

# Every endpoint is full refresh: the Core API exposes no server-side `updated_after`/`since` filter,
# so there are no incremental cursor fields. An empty list keeps `build_endpoint_schemas` marking each
# table full-refresh (supports_incremental / supports_append both False).
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
