from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
class InfisicalEndpointConfig:
    name: str
    # API path, optionally with `{organization_id}` / `{project_id}` placeholders.
    path: str
    # Key holding the row list in the response body, or None when the body is the list itself.
    data_key: str | None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable, immutable field to partition by. Never a mutable timestamp.
    partition_key: str | None = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Whether the endpoint supports `offset`/`limit` pagination. Unpaginated endpoints
    # return the full list in one response.
    paginated: bool = False
    page_limit: int = 500
    # Extra query params sent on every request (e.g. an explicit stable sort).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Fan out over every project (`{project_id}`), group (`{group_id}`), or project environment
    # (`{project_id}` + `{environment_id}`) in the configured org.
    fan_out_over: Literal["projects", "groups", "environments"] | None = None
    # Only fan out over projects of this type, for endpoints that reject other project types.
    fan_out_project_type: str | None = None
    # Send the parent ID as this query param rather than as a path placeholder.
    parent_id_param: str | None = None
    # Stamp the parent ID onto child rows under this key, for children that don't carry it.
    parent_id_field: str | None = None
    # The endpoint is scoped by the access token's org rather than a path parameter, so an
    # identity in several orgs could see other orgs' rows. Keep only the configured org's rows.
    filter_by_org_id: bool = False
    # The response holds a single object under `data_key` rather than a list.
    single_object: bool = False


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
        fan_out_over="projects",
    ),
    "organization_roles": InfisicalEndpointConfig(
        name="organization_roles",
        path="/api/v1/organization/roles",
        data_key="roles",
        filter_by_org_id=True,
    ),
    "project_roles": InfisicalEndpointConfig(
        name="project_roles",
        path="/api/v1/projects/{project_id}/roles",
        data_key="roles",
        # Built-in project roles (admin, member, viewer, ...) get a fresh random id on every
        # request, so key on the slug, which is unique within a project.
        primary_keys=["projectId", "slug"],
        fan_out_over="projects",
    ),
    "groups": InfisicalEndpointConfig(
        name="groups",
        path="/api/v1/groups",
        data_key=None,
        filter_by_org_id=True,
    ),
    # Users and machine identities in each group. Member rows don't carry the group ID.
    "group_members": InfisicalEndpointConfig(
        name="group_members",
        path="/api/v1/groups/{group_id}/members",
        data_key="members",
        primary_keys=["groupId", "id"],
        paginated=True,
        page_limit=100,  # documented maximum
        extra_params={"orderBy": "name", "orderDirection": "asc"},
        fan_out_over="groups",
        parent_id_field="groupId",
    ),
    "project_group_memberships": InfisicalEndpointConfig(
        name="project_group_memberships",
        path="/api/v1/projects/{project_id}/memberships/groups",
        data_key="groupMemberships",
        fan_out_over="projects",
    ),
    # Not in the published API reference, but the endpoint accepts machine identity tokens and
    # backs the dashboard's findings view. The response omits the matched secret value.
    "secret_scanning_findings": InfisicalEndpointConfig(
        name="secret_scanning_findings",
        path="/api/v2/secret-scanning/findings",
        data_key="findings",
        partition_key="createdAt",
        fan_out_over="projects",
        fan_out_project_type="secret-scanning",
        parent_id_param="projectId",
    ),
    # Project list entries embed only each environment's id, name, and slug, so fetch each one
    # for its position and timestamps.
    "project_environments": InfisicalEndpointConfig(
        name="project_environments",
        path="/api/v1/projects/{project_id}/environments/{environment_id}",
        data_key="environment",
        fan_out_over="environments",
        single_object=True,
    ),
    "project_identity_memberships": InfisicalEndpointConfig(
        name="project_identity_memberships",
        path="/api/v1/projects/{project_id}/identity-memberships",
        data_key="identityMemberships",
        paginated=True,
        page_limit=500,
        extra_params={"orderBy": "name", "orderDirection": "asc"},
        fan_out_over="projects",
    ),
    "secret_syncs": InfisicalEndpointConfig(
        name="secret_syncs",
        path="/api/v1/secret-syncs",
        data_key="secretSyncs",
        fan_out_over="projects",
        fan_out_project_type="secret-manager",
        parent_id_param="projectId",
    ),
}

ENDPOINTS = tuple(INFISICAL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INFISICAL_ENDPOINTS.items()
}
