from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    ResponseAction,
    incremental_field,
)

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
    # Set for sub-resources that Harvest only lists per parent object (e.g. an invoice's payments).
    fanout: Optional[DependentEndpointConfig] = None
    # False for endpoints that return one unpaginated response and document no `per_page`.
    paginated: bool = True
    # Nested objects whose `id` is copied to a top-level `<key>_id` column, for primary keys.
    nested_id_keys: tuple[str, ...] = ()

    @property
    def incremental_fields(self) -> list[IncrementalField]:
        return [incremental_field("updated_at")] if self.supports_updated_since else []

    @property
    def default_incremental_field(self) -> Optional[str]:
        return "updated_at" if self.supports_updated_since else None


# A parent deleted between the parent listing and its child fetch answers 404. Treat it as an
# empty child so one deleted invoice or user doesn't abort the whole fan-out.
_MISSING_PARENT_IGNORE: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


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
    "estimate_messages": HarvestEndpointConfig(
        name="estimate_messages",
        path="estimates/{estimate_id}/messages",
        data_key="estimate_messages",
        primary_keys=["estimate_id", "id"],
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="estimates",
            resolve_param="estimate_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "estimate_id"},
            child_response_actions=_MISSING_PARENT_IGNORE,
        ),
        description="Messages sent for each estimate, such as sends, acceptances and declines. Needs an "
        "administrator or a manager who can edit estimates.",
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
    "invoice_messages": HarvestEndpointConfig(
        name="invoice_messages",
        path="invoices/{invoice_id}/messages",
        data_key="invoice_messages",
        primary_keys=["invoice_id", "id"],
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="invoices",
            resolve_param="invoice_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "invoice_id"},
            child_response_actions=_MISSING_PARENT_IGNORE,
        ),
        description="Messages sent for each invoice, including payment reminders and thank-you notes. Needs "
        "an administrator or a manager who can edit invoices.",
    ),
    "invoice_payments": HarvestEndpointConfig(
        name="invoice_payments",
        path="invoices/{invoice_id}/payments",
        data_key="invoice_payments",
        primary_keys=["invoice_id", "id"],
        partition_key="created_at",
        # Payment rows don't carry their invoice, so the parent id is injected as `invoice_id`.
        fanout=DependentEndpointConfig(
            parent_name="invoices",
            resolve_param="invoice_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "invoice_id"},
            child_response_actions=_MISSING_PARENT_IGNORE,
        ),
        description="Payments recorded against each invoice, including partial payments.",
    ),
    "invoices": HarvestEndpointConfig(
        name="invoices",
        path="invoices",
        data_key="invoices",
        page_size=100,
        partition_key="created_at",
        description="Invoices issued to clients, including their line items.",
    ),
    "pto_balances": HarvestEndpointConfig(
        name="pto_balances",
        # Harvest returns balances for one user per request, so the user id goes in the query string.
        path="pto/balances?user_id={user_id}",
        data_key="balances",
        primary_keys=["user_id", "year", "pto_type_id"],
        supports_updated_since=False,
        paginated=False,
        nested_id_keys=("pto_type",),
        fanout=DependentEndpointConfig(
            parent_name="users",
            resolve_param="user_id",
            resolve_field="id",
            include_from_parent=["id"],
            # The child takes no page size, so the users listing gets its page size here.
            parent_params={"per_page": 1000},
            parent_field_renames={"id": "user_id"},
            child_response_actions=_MISSING_PARENT_IGNORE,
        ),
        description="Each user's time off balance per policy for the current year, as of the sync date. Full "
        "refresh only - balances are a point-in-time calculation. Needs an administrator.",
    ),
    "pto_requests": HarvestEndpointConfig(
        name="pto_requests",
        path="pto/requests",
        data_key="pto_requests",
        partition_key="created_at",
        description="Time off requests and their review status. Non-administrators only see their own requests.",
    ),
    "pto_types": HarvestEndpointConfig(
        name="pto_types",
        path="pto/types",
        data_key="pto_types",
        # The listing only returns active policies by default, so an incremental merge would never
        # see a policy get deactivated. The table is tiny, so full refresh keeps it accurate.
        supports_updated_since=False,
        description="Time off policies (leave categories) and their accrual rules. Only active policies are listed.",
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
    "user_billable_rates": HarvestEndpointConfig(
        name="user_billable_rates",
        path="users/{user_id}/billable_rates",
        data_key="billable_rates",
        primary_keys=["user_id", "id"],
        supports_updated_since=False,
        fanout=DependentEndpointConfig(
            parent_name="users",
            resolve_param="user_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "user_id"},
            child_response_actions=_MISSING_PARENT_IGNORE,
        ),
        description="Each user's billable rate history, with the dates each rate was in effect. Full refresh "
        "only - the endpoint has no server-side modified-since filter. Needs an administrator or a manager "
        "who can edit billable rates.",
    ),
    "user_cost_rates": HarvestEndpointConfig(
        name="user_cost_rates",
        path="users/{user_id}/cost_rates",
        data_key="cost_rates",
        primary_keys=["user_id", "id"],
        supports_updated_since=False,
        fanout=DependentEndpointConfig(
            parent_name="users",
            resolve_param="user_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "user_id"},
            child_response_actions=_MISSING_PARENT_IGNORE,
        ),
        description="Each user's cost rate history, with the dates each rate was in effect. Full refresh "
        "only - the endpoint has no server-side modified-since filter. Needs an administrator.",
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
    name: config.incremental_fields for name, config in HARVEST_ENDPOINTS.items()
}

DESCRIPTIONS: dict[str, str] = {
    name: config.description for name, config in HARVEST_ENDPOINTS.items() if config.description is not None
}
