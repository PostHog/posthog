from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, IncrementalFieldType

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


@dataclass(frozen=True)
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
    default_incremental_field: Optional[str] = "zylo_created_at"
    page_size: int = PAGE_LIMIT
    fanout: Optional[DependentEndpointConfig] = None


# Executions are only listable per automation, so they fan out over `/v2/automations`. Execution
# rows already carry `automation_id`, so nothing needs copying from the parent.
AUTOMATION_FANOUT = DependentEndpointConfig(
    parent_name="Automations",
    resolve_param="automationId",
    resolve_field="id",
    include_from_parent=[],
    parent_params={"sort": "+zylo_created_at"},
)

# Functionalities are only listable per application. Rows already carry `application_id`.
APPLICATION_FANOUT = DependentEndpointConfig(
    parent_name="Applications",
    resolve_param="applicationId",
    resolve_field="id",
    include_from_parent=[],
    parent_params={"sort": "+zylo_created_at"},
)


# Every resource except AutomationExecutions is a top-level list endpoint.
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
    # Requires a token created with the automation role (`automations`).
    "Automations": ZyloEndpointConfig(
        name="Automations",
        path="/v2/automations",
        table_name="automations",
    ),
    # Execution ids are global (Zylo serves `/v2/automations/executions/{executionId}`), so `id`
    # alone stays unique across every parent automation.
    "AutomationExecutions": ZyloEndpointConfig(
        name="AutomationExecutions",
        path="/v2/automations/{automationId}/executions",
        table_name="automation_executions",
        fanout=AUTOMATION_FANOUT,
    ),
    "PendingContracts": ZyloEndpointConfig(
        name="PendingContracts",
        path="/v2/pendingContracts",
        table_name="pending_contracts",
    ),
    # One row per application, keyed by the application id. The spend and usage aggregates change
    # every day, but the only timestamp filters are the application's own `zylo_*` dates, so an
    # incremental sync would keep stale stats. Full refresh only.
    "ApplicationStats": ZyloEndpointConfig(
        name="ApplicationStats",
        path="/v2/applicationStats",
        table_name="application_stats",
        incremental_fields=[],
        default_incremental_field=None,
    ),
    "Users": ZyloEndpointConfig(
        name="Users",
        path="/v2/users",
        table_name="users",
    ),
    # Requires the `admin` scope.
    "Views": ZyloEndpointConfig(
        name="Views",
        path="/v2/views",
        table_name="views",
    ),
    "PendingContractLineItems": ZyloEndpointConfig(
        name="PendingContractLineItems",
        path="/v2/pendingContractLineItems",
        table_name="pending_contract_line_items",
    ),
    # The docs do not say that a functionality id is unique across applications, so the key
    # includes the parent application.
    "ApplicationFunctionalities": ZyloEndpointConfig(
        name="ApplicationFunctionalities",
        path="/v2/applications/{applicationId}/functionalities",
        table_name="application_functionalities",
        primary_keys=["application_id", "id"],
        fanout=APPLICATION_FANOUT,
    ),
    # Requires the `admin` scope.
    "CustomFields": ZyloEndpointConfig(
        name="CustomFields",
        path="/v2/customFields",
        table_name="custom_fields",
    ),
}

ENDPOINTS = tuple(ZYLO_ENDPOINTS.keys())
