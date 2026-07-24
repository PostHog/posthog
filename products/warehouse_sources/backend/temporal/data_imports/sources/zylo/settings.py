from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Zylo Enterprise (v2) API base URL. Every endpoint path below is relative to this.
ZYLO_BASE_URL = "https://api.zylo.com"

# Zylo list endpoints cap `limit` at 1000 (default 50 if unset); we always pass the max.
PAGE_LIMIT = 1000

# Every Zylo resource carries these two system timestamps and both accept the same
# `field=value,operator` filter syntax (see https://developer.zylo.com/reference/filtering),
# so both are safe, genuine server-side incremental cursors.
_SYSTEM_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "zylo_created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "zylo_created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
    {
        "label": "zylo_modified_at",
        "type": IncrementalFieldType.DateTime,
        "field": "zylo_modified_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class ZyloEndpointConfig:
    name: str
    path: str
    table_name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Advertised incremental cursor options. Empty => full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(_SYSTEM_INCREMENTAL_FIELDS))
    # Stable, never-updated datetime field used for partitioning. `zylo_created_at` is set once at
    # record creation and never changes, unlike `zylo_modified_at`.
    partition_key: Optional[str] = "zylo_created_at"


# All resources are top-level list endpoints (no fan-out): every id in this catalog is a genuine
# top-level list, so no parent identifier needs to ride in the primary key.
ZYLO_ENDPOINTS: dict[str, ZyloEndpointConfig] = {
    "Applications": ZyloEndpointConfig(
        name="Applications",
        path="/v2/applications",
        table_name="applications",
    ),
    "ApplicationLicenses": ZyloEndpointConfig(
        name="ApplicationLicenses",
        path="/v2/applicationLicenses",
        table_name="application_licenses",
    ),
    "ApplicationUsers": ZyloEndpointConfig(
        name="ApplicationUsers",
        path="/v2/applicationUsers",
        table_name="application_users",
    ),
    "Contracts": ZyloEndpointConfig(
        name="Contracts",
        path="/v2/contracts",
        table_name="contracts",
    ),
    "ContractLineItems": ZyloEndpointConfig(
        name="ContractLineItems",
        path="/v2/contractLineItems",
        table_name="contract_line_items",
    ),
    "Payments": ZyloEndpointConfig(
        name="Payments",
        path="/v2/payments",
        table_name="payments",
    ),
    # Premium feature — requires `applications:read` and `spend:read` scopes; a key without them
    # gets a 403 for this endpoint only (see ZyloSource.get_endpoint_permissions).
    "PurchaseOrders": ZyloEndpointConfig(
        name="PurchaseOrders",
        path="/v2/purchaseOrders",
        table_name="purchase_orders",
    ),
    "POLineItems": ZyloEndpointConfig(
        name="POLineItems",
        path="/v2/poLineItems",
        table_name="po_line_items",
    ),
    "Suppliers": ZyloEndpointConfig(
        name="Suppliers",
        path="/v2/suppliers",
        table_name="suppliers",
    ),
    "SavingsEvents": ZyloEndpointConfig(
        name="SavingsEvents",
        path="/v2/savingsEvents",
        table_name="savings_events",
    ),
    # No `id` field — one row per application per fiscal year, so the pair is the natural key.
    "ApplicationBudgets": ZyloEndpointConfig(
        name="ApplicationBudgets",
        path="/v2/applicationBudgets",
        table_name="application_budgets",
        primary_keys=["application_id", "year"],
    ),
    "ActivityHistory": ZyloEndpointConfig(
        name="ActivityHistory",
        path="/v2/activityHistory",
        table_name="activity_history",
    ),
}

ENDPOINTS = tuple(ZYLO_ENDPOINTS.keys())
