from dataclasses import dataclass, field


@dataclass
class FlowluEndpointConfig:
    name: str
    # Path under `https://{subdomain}.flowlu.com/api/v1/module` (e.g. "/crm/account/list").
    path: str
    # Flowlu record IDs are integers unique per entity type within an account, and each endpoint
    # maps to its own warehouse table, so `id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Flowlu REST API list endpoints (`/api/v1/module/<module>/<entity>/list`). All are full-refresh
# only: the list endpoints expose no documented server-side `updated_after`-style filter, so there
# is no genuine incremental cursor to advance (a client-side scan of every page would cost the
# same as a full refresh — see the implementing-warehouse-sources skill). Airbyte's Flowlu
# connector is likewise full-refresh only.
FLOWLU_ENDPOINTS: dict[str, FlowluEndpointConfig] = {
    "accounts": FlowluEndpointConfig(name="accounts", path="/crm/account/list"),
    # Flowlu's API keeps the legacy `lead` entity name for CRM opportunities.
    "leads": FlowluEndpointConfig(name="leads", path="/crm/lead/list"),
    "pipelines": FlowluEndpointConfig(name="pipelines", path="/crm/pipeline/list"),
    "tasks": FlowluEndpointConfig(name="tasks", path="/task/tasks/list"),
    "projects": FlowluEndpointConfig(name="projects", path="/st/projects/list"),
    "invoices": FlowluEndpointConfig(name="invoices", path="/fin/invoice/list"),
    "estimates": FlowluEndpointConfig(name="estimates", path="/fin/estimate/list"),
    "customer_payments": FlowluEndpointConfig(name="customer_payments", path="/fin/customer_payment/list"),
    "transactions": FlowluEndpointConfig(name="transactions", path="/fin/transaction/list"),
    "agile_issues": FlowluEndpointConfig(name="agile_issues", path="/agile/issues/list"),
    "agile_sprints": FlowluEndpointConfig(name="agile_sprints", path="/agile/sprints/list"),
    "timesheets": FlowluEndpointConfig(name="timesheets", path="/timetracker/timesheets/list"),
    "products": FlowluEndpointConfig(name="products", path="/products/product/list"),
}

ENDPOINTS = tuple(FLOWLU_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
