from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PAGE_SIZE = 100
# Sim rejects a custom usage window longer than 92 calendar days.
USAGE_WINDOW_DAYS = 90


@frozen
class SimEndpoint:
    name: str
    path: str
    primary_keys: tuple[str, ...]
    partition_key: str
    sort_field: str | None = "createdAt"
    workspace_scoped: bool = True
    page_size: int = PAGE_SIZE
    fanout: DependentEndpointConfig | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


ENDPOINTS: dict[str, SimEndpoint] = {
    "workflows": SimEndpoint(name="workflows", path="workflows", primary_keys=("id",), partition_key="createdAt"),
    "logs": SimEndpoint(
        name="logs", path="logs", primary_keys=("runId",), partition_key="startedAt", sort_field="startedAt"
    ),
    "workflow_versions": SimEndpoint(
        name="workflow_versions",
        path="workflows/{workflow_id}/versions",
        primary_keys=("workflowId", "id"),
        partition_key="createdAt",
        sort_field=None,
        workspace_scoped=False,
        fanout=DependentEndpointConfig(
            parent_name="workflows",
            resolve_param="workflow_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "workflowId"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "workspaces": SimEndpoint(
        name="workspaces", path="workspaces", primary_keys=("id",), partition_key="createdAt", workspace_scoped=False
    ),
    "tables": SimEndpoint(name="tables", path="tables", primary_keys=("id",), partition_key="createdAt"),
    "table_rows": SimEndpoint(
        name="table_rows",
        path="tables/{table_id}/rows",
        primary_keys=("tableId", "id"),
        partition_key="createdAt",
        sort_field=None,
        page_size=1000,
        fanout=DependentEndpointConfig(
            parent_name="tables",
            resolve_param="table_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "tableId"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "usage_events": SimEndpoint(
        name="usage_events",
        path="organizations/{organization_id}/usage/events",
        primary_keys=("organizationId", "id"),
        partition_key="createdAt",
        workspace_scoped=False,
        fanout=DependentEndpointConfig(
            parent_name="organizations",
            resolve_param="organization_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "organizationId"},
            # Usage needs organization admin rights, which a key can hold in only some of its organizations.
            child_response_actions=[{"status_code": 403, "action": "ignore"}],
        ),
        incremental_fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.DateTime,
                "field": "createdAt",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        default_incremental_field="createdAt",
    ),
}

# Fan-out parents that are not tables of their own.
PARENT_ENDPOINTS: dict[str, SimEndpoint] = {
    "organizations": SimEndpoint(
        name="organizations",
        path="organizations",
        primary_keys=("id",),
        partition_key="createdAt",
        workspace_scoped=False,
    ),
}

# Run status and cost can change after startedAt, and the other list endpoints have no timestamp filter.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items() if endpoint.incremental_fields
}
