from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Every ServiceNow table exposes the same audit columns, so every endpoint advertises
# the same incremental options. `sys_updated_on` catches both inserts and updates;
# `sys_created_on` is offered for append-only style syncs.
SERVICENOW_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "sys_updated_on",
        "type": IncrementalFieldType.DateTime,
        "field": "sys_updated_on",
        "field_type": IncrementalFieldType.DateTime,
    },
    {
        "label": "sys_created_on",
        "type": IncrementalFieldType.DateTime,
        "field": "sys_created_on",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class ServiceNowEndpointConfig:
    name: str
    """Stream name shown to the user."""
    table: str
    """The underlying ServiceNow table queried via the Table API."""
    primary_key: str = "sys_id"
    partition_key: str = "sys_created_on"
    """Stable creation timestamp used for datetime partitioning (never `sys_updated_on`)."""
    default_incremental_field: str = "sys_updated_on"
    incremental_fields: list[IncrementalField] = field(default_factory=lambda: list(SERVICENOW_INCREMENTAL_FIELDS))


# Default stream catalog, cross-referenced against the Airbyte/Fivetran ServiceNow
# connectors. Friendly stream names map to the canonical ITSM table names. Every table
# carries `sys_id`, `sys_created_on`, and `sys_updated_on`, so the incremental and
# partition config is uniform across all of them.
SERVICENOW_ENDPOINTS: dict[str, ServiceNowEndpointConfig] = {
    "incidents": ServiceNowEndpointConfig(name="incidents", table="incident"),
    "problems": ServiceNowEndpointConfig(name="problems", table="problem"),
    "change_requests": ServiceNowEndpointConfig(name="change_requests", table="change_request"),
    "change_tasks": ServiceNowEndpointConfig(name="change_tasks", table="change_task"),
    "tasks": ServiceNowEndpointConfig(name="tasks", table="task"),
    "catalog_requests": ServiceNowEndpointConfig(name="catalog_requests", table="sc_request"),
    "requested_items": ServiceNowEndpointConfig(name="requested_items", table="sc_req_item"),
    "catalog_tasks": ServiceNowEndpointConfig(name="catalog_tasks", table="sc_task"),
    "users": ServiceNowEndpointConfig(name="users", table="sys_user"),
    "user_groups": ServiceNowEndpointConfig(name="user_groups", table="sys_user_group"),
    "configuration_items": ServiceNowEndpointConfig(name="configuration_items", table="cmdb_ci"),
    "knowledge_articles": ServiceNowEndpointConfig(name="knowledge_articles", table="kb_knowledge"),
    "assets": ServiceNowEndpointConfig(name="assets", table="alm_asset"),
}

ENDPOINTS = tuple(SERVICENOW_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SERVICENOW_ENDPOINTS.items()
}
