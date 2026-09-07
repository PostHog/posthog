from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Harvest exposes exactly one generally-available API version, addressed by the `/v2` path
# segment on a single global host. The base URL below is what the transport actually calls.
HARVEST_API_VERSION = "v2"
HARVEST_SUPPORTED_VERSIONS = (HARVEST_API_VERSION,)


@dataclass(frozen=True)
class HarvestEndpointConfig:
    name: str  # schema name shown to the user (matches the warehouse table)
    path: str  # API path relative to the versioned base URL, e.g. "clients"
    data_key: str  # key in the JSON response body holding the list of rows
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Rows per page. Harvest caps `per_page` at 2000 and rejects anything larger with a 422.
    # Endpoints whose rows embed a `line_items` array use a smaller page so one page stays a
    # reasonable size in memory.
    page_size: int = 1000
    # `updated_since` is Harvest's server-side "modified after" filter. The handful of
    # endpoints that don't accept it are full refresh only.
    supports_updated_since: bool = True
    # Stable creation-time field used for datetime partitioning. Never `updated_at`, which
    # would rewrite partitions on every sync. Left None for small lookup tables where
    # partitioning only adds overhead.
    partition_key: Optional[str] = None
    description: Optional[str] = None


HARVEST_ENDPOINTS: dict[str, HarvestEndpointConfig] = {
    "clients": HarvestEndpointConfig(
        name="clients",
        path="clients",
        data_key="clients",
        description="Clients you track time and bill against.",
    ),
    "contacts": HarvestEndpointConfig(
        name="contacts",
        path="contacts",
        data_key="contacts",
        description="Contact people belonging to a client.",
    ),
    "estimate_item_categories": HarvestEndpointConfig(
        name="estimate_item_categories",
        path="estimate_item_categories",
        data_key="estimate_item_categories",
        description="Categories available for estimate line items.",
    ),
    "estimates": HarvestEndpointConfig(
        name="estimates",
        path="estimates",
        data_key="estimates",
        page_size=100,
        partition_key="created_at",
        description="Estimates sent to clients, including their line items.",
    ),
    "expense_categories": HarvestEndpointConfig(
        name="expense_categories",
        path="expense_categories",
        data_key="expense_categories",
        description="Categories expenses can be filed under.",
    ),
    "expenses": HarvestEndpointConfig(
        name="expenses",
        path="expenses",
        data_key="expenses",
        partition_key="created_at",
        description="Expenses logged against projects.",
    ),
    "invoice_item_categories": HarvestEndpointConfig(
        name="invoice_item_categories",
        path="invoice_item_categories",
        data_key="invoice_item_categories",
        description="Categories available for invoice line items.",
    ),
    "invoices": HarvestEndpointConfig(
        name="invoices",
        path="invoices",
        data_key="invoices",
        page_size=100,
        partition_key="created_at",
        description="Invoices issued to clients, including their line items.",
    ),
    "projects": HarvestEndpointConfig(
        name="projects",
        path="projects",
        data_key="projects",
        description="Projects time and expenses are tracked against.",
    ),
    "roles": HarvestEndpointConfig(
        name="roles",
        path="roles",
        data_key="roles",
        supports_updated_since=False,
        description="Roles and the users assigned to them. Full refresh only - the roles "
        "endpoint has no server-side modified-since filter.",
    ),
    "task_assignments": HarvestEndpointConfig(
        name="task_assignments",
        path="task_assignments",
        data_key="task_assignments",
        description="Tasks assigned to projects, with their billable rate and budget.",
    ),
    "tasks": HarvestEndpointConfig(
        name="tasks",
        path="tasks",
        data_key="tasks",
        description="Tasks that can be assigned to projects.",
    ),
    "time_entries": HarvestEndpointConfig(
        name="time_entries",
        path="time_entries",
        data_key="time_entries",
        partition_key="created_at",
        description="Tracked time, one row per entry.",
    ),
    "user_assignments": HarvestEndpointConfig(
        name="user_assignments",
        path="user_assignments",
        data_key="user_assignments",
        description="Users assigned to projects, with their rate and budget.",
    ),
    "users": HarvestEndpointConfig(
        name="users",
        path="users",
        data_key="users",
        description="People in the Harvest account.",
    ),
}

ENDPOINTS = tuple(HARVEST_ENDPOINTS.keys())

# Every Harvest object carries `updated_at`, and the list endpoints filter on it server-side
# via `updated_since`. Endpoints without that filter advertise no incremental field, so
# `build_endpoint_schemas` marks them full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field("updated_at")] if config.supports_updated_since else []
    for name, config in HARVEST_ENDPOINTS.items()
}

DESCRIPTIONS: dict[str, str] = {
    name: config.description for name, config in HARVEST_ENDPOINTS.items() if config.description is not None
}
