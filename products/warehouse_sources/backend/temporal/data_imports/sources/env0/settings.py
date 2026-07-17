from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

Env0EndpointScope = Literal["root", "organization", "environment"]


@dataclass
class Env0EndpointConfig:
    name: str
    # Path template; `{parent_id}` is replaced with the fan-out parent's id (organization or
    # environment, per `scope`).
    path: str
    # "root" endpoints are called once; "organization"/"environment" endpoints fan out one
    # request chain per parent resource.
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
    # Response fields dropped client-side before yielding (huge free-text blobs like raw
    # Terraform output that would bloat rows without being queryable).
    strip_fields: tuple[str, ...] = ()
    # Endpoint supports env0's server-side fromDate/toDate window (must be passed together).
    supports_date_window: bool = False
    # When set, each row gets the fan-out parent's id injected under this column so the
    # primary key stays unique table-wide.
    inject_parent_id_field: Optional[str] = None
    # Safety overlap subtracted from the incremental watermark on every run, re-pulling a
    # window that merge dedupes on the primary key. Deployments mutate after creation
    # (status/finishedAt land when the run completes), so re-pulling the last day refreshes
    # rows first fetched mid-run.
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
        # The nested latest deployment's raw Terraform output/plan can be megabytes per row.
        params={"excludeFields": "latestDeploymentLog.output,latestDeploymentLog.plan"},
    ),
    "deployments": Env0EndpointConfig(
        name="deployments",
        path="/environments/{parent_id}/deployments",
        scope="environment",
        paginated=True,
        partition_key="createdAt",
        strip_fields=("output", "plan"),
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
        inject_parent_id_field="environment_id",
    ),
}

ENDPOINTS = tuple(ENV0_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ENV0_ENDPOINTS.items() if config.incremental_fields
}
