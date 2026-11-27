from dataclasses import dataclass, field

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass(frozen=False)
class PipelinerEndpointConfig:
    name: str
    # Entity collection name in the REST path, e.g. `/entities/Accounts`.
    entity: str
    # Every Pipeliner entity carries a server-maintained `modified` timestamp and the list
    # endpoints accept `filter[modified]` + `filter-op[modified]=gte`, so all endpoints
    # advertise it as the incremental cursor.
    incremental_fields: list[IncrementalField] = field(
        default_factory=lambda: [_datetime_incremental_field("modified")]
    )
    # `created` never changes; `modified` mutates on every edit and would rewrite partitions.
    partition_key: str = "created"
    # Pipeliner entity ids are UUIDs, unique across the whole team space.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Pipeliner CRM (Coevera) REST API list endpoints (https://developers.pipelinersales.com).
# The API exposes ~200 entity collections; these are the core CRM streams a user actually
# wants to analyze. `Activities` is deliberately absent — it is an abstract union of Tasks
# and Appointments, which are synced directly instead.
PIPELINER_ENDPOINTS: dict[str, PipelinerEndpointConfig] = {
    "account_types": PipelinerEndpointConfig(name="account_types", entity="AccountTypes"),
    "accounts": PipelinerEndpointConfig(name="accounts", entity="Accounts"),
    "appointment_types": PipelinerEndpointConfig(name="appointment_types", entity="AppointmentTypes"),
    "appointments": PipelinerEndpointConfig(name="appointments", entity="Appointments"),
    "clients": PipelinerEndpointConfig(name="clients", entity="Clients"),
    "contact_account_account_role_relations": PipelinerEndpointConfig(
        name="contact_account_account_role_relations", entity="ContactAccountAccountRoleRelations"
    ),
    "contact_account_relations": PipelinerEndpointConfig(
        name="contact_account_relations", entity="ContactAccountRelations"
    ),
    "contact_types": PipelinerEndpointConfig(name="contact_types", entity="ContactTypes"),
    "contacts": PipelinerEndpointConfig(name="contacts", entity="Contacts"),
    "currencies": PipelinerEndpointConfig(name="currencies", entity="Currencies"),
    "currency_exchange_rates": PipelinerEndpointConfig(name="currency_exchange_rates", entity="CurrencyExchangeRates"),
    "currency_exchange_rates_lists": PipelinerEndpointConfig(
        name="currency_exchange_rates_lists", entity="CurrencyExchangeRatesLists"
    ),
    "lead_types": PipelinerEndpointConfig(name="lead_types", entity="LeadTypes"),
    "leads": PipelinerEndpointConfig(name="leads", entity="Leads"),
    "notes": PipelinerEndpointConfig(name="notes", entity="Notes"),
    "opportunities": PipelinerEndpointConfig(name="opportunities", entity="Opportunities"),
    "opportunity_types": PipelinerEndpointConfig(name="opportunity_types", entity="OpportunityTypes"),
    "oppty_product_relations": PipelinerEndpointConfig(name="oppty_product_relations", entity="OpptyProductRelations"),
    "pipelines": PipelinerEndpointConfig(name="pipelines", entity="Pipelines"),
    "products": PipelinerEndpointConfig(name="products", entity="Products"),
    "quote_processes": PipelinerEndpointConfig(name="quote_processes", entity="QuoteProcesses"),
    "quote_types": PipelinerEndpointConfig(name="quote_types", entity="QuoteTypes"),
    "quotes": PipelinerEndpointConfig(name="quotes", entity="Quotes"),
    "sales_unit_client_relations": PipelinerEndpointConfig(
        name="sales_unit_client_relations", entity="SalesUnitClientRelations"
    ),
    "sales_units": PipelinerEndpointConfig(name="sales_units", entity="SalesUnits"),
    "steps": PipelinerEndpointConfig(name="steps", entity="Steps"),
    "task_types": PipelinerEndpointConfig(name="task_types", entity="TaskTypes"),
    "tasks": PipelinerEndpointConfig(name="tasks", entity="Tasks"),
}

ENDPOINTS = tuple(PIPELINER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PIPELINER_ENDPOINTS.items()
}
