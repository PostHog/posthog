from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

Env0EndpointScope = Literal["root", "organization", "project", "environment", "deployment"]


@dataclass
class Env0EndpointConfig:
    name: str
    # Path template; `{parent_id}` is replaced with the fan-out parent's id (organization,
    # project, environment or deployment, per `scope`).
    path: str
    # "root" endpoints are called once; every other scope fans out one request chain per
    # parent resource of that kind, walking organizations -> projects / environments ->
    # deployments to enumerate the parents.
    scope: Env0EndpointScope = "root"
    # env0's core list endpoints are mostly unpaginated JSON arrays; only environments,
    # deployments, and teams document limit/offset pagination.
    paginated: bool = False
    # Key the item list is nested under when the endpoint returns an object instead of a bare
    # array (teams returns {"teams": [...], "nextPageKey": ...} when paginating).
    data_key: Optional[str] = None
    # Query param that carries the organization id for org-scoped endpoints whose path
    # doesn't embed it.
    org_id_param: Optional[str] = None
    params: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field used for datetime partitioning. Never an updatedAt-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Response fields dropped client-side before yielding: huge free-text blobs (raw
    # Terraform output) and secret-bearing fields (deployment variable values, injected
    # OIDC/VCS tokens) that must not be persisted to the warehouse.
    strip_fields: tuple[str, ...] = ()
    # Endpoint supports env0's server-side fromDate/toDate window (must be passed together).
    supports_date_window: bool = False
    # Fan-out parent fields copied onto each row, mapped to the column they land in. The
    # parent id keeps the primary key unique table-wide; a parent timestamp gives a child with
    # no time field of its own an incremental cursor.
    inject_parent_fields: dict[str, str] = field(default_factory=dict)
    # Nested object lifted into the row root, for endpoints that bury the row's identity one
    # level down (organization users wrap everything but role and status under "user").
    flatten_field: Optional[str] = None
    # Safety overlap subtracted from the incremental watermark on every run, re-pulling a
    # window that merge dedupes on the primary key. Deployments mutate after creation
    # (status/finishedAt land when the run completes), so re-pulling the last day refreshes
    # rows first fetched mid-run. On a "deployment"-scoped endpoint the window bounds the
    # deployments parent walk rather than the child request.
    incremental_lookback: Optional[timedelta] = None


ENV0_ENDPOINTS: dict[str, Env0EndpointConfig] = {
    "organizations": Env0EndpointConfig(
        name="organizations",
        path="/organizations",
    ),
    "projects": Env0EndpointConfig(
        name="projects",
        path="/projects",
        scope="organization",
        org_id_param="organizationId",
    ),
    "teams": Env0EndpointConfig(
        name="teams",
        path="/teams/organizations/{parent_id}",
        scope="organization",
        paginated=True,
        data_key="teams",
    ),
    "templates": Env0EndpointConfig(
        name="templates",
        path="/blueprints",
        scope="organization",
        org_id_param="organizationId",
    ),
    "environments": Env0EndpointConfig(
        name="environments",
        path="/environments",
        scope="organization",
        org_id_param="organizationId",
        paginated=True,
        partition_key="createdAt",
        # The nested latest deployment carries megabytes of raw Terraform output/plan AND
        # secret-bearing fields (deployment variables, injected OIDC/VCS tokens). Excluded
        # server-side and stripped client-side too in case the API ignores the param; the
        # deployments table covers per-deployment analytics.
        params={"excludeFields": "latestDeploymentLog"},
        strip_fields=("latestDeploymentLog",),
    ),
    "deployments": Env0EndpointConfig(
        name="deployments",
        path="/environments/{parent_id}/deployments",
        scope="environment",
        paginated=True,
        partition_key="createdAt",
        # output/plan are huge free-text blobs; variables carries raw variable values and
        # customEnv0EnvironmentVariables carries injected credentials (oidcToken,
        # vcsAccessToken) — none of these may land in the warehouse.
        strip_fields=("output", "plan", "variables", "customEnv0EnvironmentVariables"),
        supports_date_window=True,
        incremental_lookback=timedelta(hours=24),
        incremental_fields=[
            {
                "label": "startedAt",
                "type": IncrementalFieldType.DateTime,
                "field": "startedAt",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "environment_costs": Env0EndpointConfig(
        name="environment_costs",
        path="/costs/environments/{parent_id}",
        scope="environment",
        # The cost endpoint only takes a relative timespan (DAY..YEAR), not an arbitrary date
        # range, so the widest window with daily grain is the best full-refresh shape.
        params={"timespan": "YEAR", "granularity": "DAILY"},
        primary_keys=["environment_id", "date"],
        inject_parent_fields={"id": "environment_id"},
    ),
    "project_costs": Env0EndpointConfig(
        name="project_costs",
        path="/costs/projects/{parent_id}",
        scope="project",
        params={"timespan": "YEAR", "granularity": "DAILY"},
        primary_keys=["project_id", "date"],
        inject_parent_fields={"id": "project_id"},
    ),
    "organization_costs": Env0EndpointConfig(
        name="organization_costs",
        path="/costs",
        scope="organization",
        org_id_param="organizationId",
        params={"timespan": "YEAR", "granularity": "DAILY"},
        # Returns {"costDataPoints": [...], "errors": [...], "staleProjectIds": [...]}; only the
        # data points are rows. One point per date and groupKey (the project the cost rolls up to).
        data_key="costDataPoints",
        primary_keys=["organization_id", "date", "groupKey"],
        inject_parent_fields={"id": "organization_id"},
    ),
    "organization_users": Env0EndpointConfig(
        name="organization_users",
        path="/organizations/{parent_id}/users",
        scope="organization",
        # API keys act as deployment initiators too, so including them makes this a complete
        # lookup for the user ids stamped on deployments and environments.
        params={"includeApiKeys": "true"},
        flatten_field="user",
        primary_keys=["organization_id", "user_id"],
        inject_parent_fields={"id": "organization_id"},
    ),
    "drift_causes": Env0EndpointConfig(
        name="drift_causes",
        path="/drift-causes",
        scope="organization",
        org_id_param="organizationId",
        data_key="causes",
        primary_keys=["organization_id", "causeId"],
        inject_parent_fields={"id": "organization_id"},
    ),
    "deployment_resources": Env0EndpointConfig(
        name="deployment_resources",
        path="/environments/deployments/{parent_id}/resources",
        scope="deployment",
        # Resources carry no id or timestamp of their own; the row is addressed by the Terraform
        # address parts within its deployment, and dated by the deployment that produced it.
        primary_keys=["deployment_id", "mode", "moduleName", "type", "name"],
        inject_parent_fields={"id": "deployment_id", "startedAt": "deployment_started_at"},
        supports_date_window=True,
        incremental_lookback=timedelta(hours=24),
        incremental_fields=[
            {
                "label": "deployment_started_at",
                "type": IncrementalFieldType.DateTime,
                "field": "deployment_started_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(ENV0_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ENV0_ENDPOINTS.items() if config.incremental_fields
}
