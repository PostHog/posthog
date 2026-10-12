from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
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
    "accounts": PipelinerEndpointConfig(name="accounts", entity="Accounts"),
    "appointments": PipelinerEndpointConfig(name="appointments", entity="Appointments"),
    "clients": PipelinerEndpointConfig(name="clients", entity="Clients"),
    "contacts": PipelinerEndpointConfig(name="contacts", entity="Contacts"),
    "leads": PipelinerEndpointConfig(name="leads", entity="Leads"),
    "notes": PipelinerEndpointConfig(name="notes", entity="Notes"),
    "opportunities": PipelinerEndpointConfig(name="opportunities", entity="Opportunities"),
    "pipelines": PipelinerEndpointConfig(name="pipelines", entity="Pipelines"),
    "products": PipelinerEndpointConfig(name="products", entity="Products"),
    "steps": PipelinerEndpointConfig(name="steps", entity="Steps"),
    "tasks": PipelinerEndpointConfig(name="tasks", entity="Tasks"),
}

ENDPOINTS = tuple(PIPELINER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PIPELINER_ENDPOINTS.items()
}
