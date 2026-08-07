from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class InfisicalEndpointConfig:
    name: str
    # API path, optionally with `{organization_id}` / `{project_id}` placeholders.
    path: str
    # Key holding the row list in the response body (Infisical wraps every list).
    data_key: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable, immutable field to partition by. Never a mutable timestamp.
    partition_key: str | None = None
    primary_key: str = "id"
    # Whether the endpoint supports `offset`/`limit` pagination. Unpaginated endpoints
    # return the full list in one response.
    paginated: bool = False
    page_limit: int = 500
    # Extra query params sent on every request (e.g. an explicit stable sort).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Fan out over every project from /api/v1/projects, formatting `{project_id}` per project.
    fan_out_over_projects: bool = False


INFISICAL_ENDPOINTS: dict[str, InfisicalEndpointConfig] = {
    # Audit log rows are immutable and the endpoint takes server-side startDate/endDate
    # filters, so createdAt is a true incremental cursor. Retention on Infisical Cloud is
    # plan-based, which bounds the first sync's history.
    "audit_logs": InfisicalEndpointConfig(
        name="audit_logs",
        path="/api/v1/organization/audit-logs",
        data_key="auditLogs",
        incremental_fields=[
            {
                "label": "createdAt",
                "type": IncrementalFieldType.DateTime,
                "field": "createdAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        partition_key="createdAt",
        paginated=True,
        page_limit=1000,  # documented maximum
    ),
    # Small dimension tables. None of these expose a server-side updated-since filter,
    # so they are full refresh only.
    "projects": InfisicalEndpointConfig(
        name="projects",
        path="/api/v1/projects",
        data_key="projects",
    ),
    "identities": InfisicalEndpointConfig(
        name="identities",
        path="/api/v2/organizations/{organization_id}/identity-memberships",
        data_key="identityMemberships",
        paginated=True,
        page_limit=500,
        # Explicit stable sort so page boundaries don't shift mid-sync.
        extra_params={"orderBy": "name", "orderDirection": "asc"},
    ),
    "organization_memberships": InfisicalEndpointConfig(
        name="organization_memberships",
        path="/api/v2/organizations/{organization_id}/memberships",
        data_key="users",
    ),
    "project_memberships": InfisicalEndpointConfig(
        name="project_memberships",
        path="/api/v1/projects/{project_id}/memberships",
        data_key="memberships",
        fan_out_over_projects=True,
    ),
}

ENDPOINTS = tuple(INFISICAL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INFISICAL_ENDPOINTS.items()
}
