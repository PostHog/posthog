from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PaginationStyle = Literal["continuation_token", "page", "cursor"]


@dataclass
class PulumiCloudEndpointConfig:
    name: str
    path: str
    # Primary key columns for the merge upsert. Fan-out endpoints aggregate rows from every
    # stack, so their keys include the stack coordinates (orgName/projectName/stackName) to stay
    # unique table-wide — a bare per-stack `version` would collide across stacks.
    primary_keys: list[str]
    pagination: PaginationStyle
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-style field to partition by (never a mutable `modified`-style field).
    partition_key: Optional[str] = None
    # When True the endpoint is called once per stack discovered via GET /api/user/stacks,
    # formatting the stack's org/project/stack into `path`. When False it is a single top-level
    # request against the configured organization.
    fan_out_over_stacks: bool = False
    default_incremental_field: Optional[str] = None
    # Whether the table is selected for sync by default in the schema picker.
    should_sync_default: bool = True
    # Table description surfaced in the schema picker.
    description: Optional[str] = None


# Endpoint catalog. Pulumi Cloud's REST API lives at api.pulumi.com and is authenticated with a
# self-serve access token (`Authorization: token pul-...`) plus a versioned Accept header
# (`application/vnd.pulumi+8`). Endpoint parameters and response shapes below were verified against
# the live OpenAPI spec the service publishes at https://api.pulumi.com/api/openapi/pulumi-spec.json.
#
# Incremental sync:
# - `audit_logs` uses GET /api/orgs/{org}/auditlogs/v2, whose `startTime` param is a genuine
#   server-side lower bound on the query range ("Lower bound of the query range (unix timestamp)"),
#   so it maps straight from the stored watermark.
# - `stack_updates` has no server-side time filter, but the paginated format is documented to return
#   newest-first ("pageSize=1 with page=1 returns only the most recent update"), so the paginator
#   stops client-side once an entire page predates the watermark — each incremental run only pays
#   for the new pages instead of re-walking every stack's full history.
# - `stacks`, `deployments`, and `resources` are current-state listings/indexes with no reliable
#   server-side timestamp filter, so they ship as full refresh.
PULUMI_CLOUD_ENDPOINTS: dict[str, PulumiCloudEndpointConfig] = {
    "stacks": PulumiCloudEndpointConfig(
        name="stacks",
        path="/api/user/stacks",
        # `id` is "the logical identifier of the stack" and is a required response field.
        primary_keys=["id"],
        pagination="continuation_token",
        description="One row per stack the token can access in the organization, with its last update time and resource count",
    ),
    "stack_updates": PulumiCloudEndpointConfig(
        name="stack_updates",
        path="/api/stacks/{org}/{project}/{stack}/updates",
        # `version` is the stack-scoped ordinal of the update, so the stack coordinates are what
        # make the key unique table-wide across the fan-out.
        primary_keys=["orgName", "projectName", "stackName", "version"],
        pagination="page",
        fan_out_over_stacks=True,
        default_incremental_field="startTime",
        incremental_fields=[
            {
                "label": "startTime",
                "type": IncrementalFieldType.Integer,
                "field": "startTime",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        description="The full update/preview/refresh/destroy history of every stack, with outcomes, timings, and resource change counts",
    ),
    "deployments": PulumiCloudEndpointConfig(
        name="deployments",
        path="/api/orgs/{org}/deployments",
        primary_keys=["id"],
        pagination="page",
        partition_key="created",
        description="Pulumi Deployments runs across the organization, with status, operation, and job details. Empty unless the organization uses Pulumi Deployments",
    ),
    "audit_logs": PulumiCloudEndpointConfig(
        name="audit_logs",
        path="/api/orgs/{org}/auditlogs/v2",
        # Audit log events carry no id. Two genuinely distinct events sharing the same second, type,
        # and description would collapse into one row; the description embeds the acted-on object,
        # so this is vanishingly rare and preferable to duplicating rows on every overlap re-pull.
        primary_keys=["timestamp", "event", "description"],
        pagination="continuation_token",
        default_incremental_field="timestamp",
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.Integer,
                "field": "timestamp",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
        # Audit logs are gated to higher Pulumi Cloud tiers (Enterprise / Business Critical), so a
        # default-on selection would fail the first sync for most organizations.
        should_sync_default=False,
        description="Organization audit log events (who did what, when, from where). Requires a Pulumi Cloud plan with audit logs enabled",
    ),
    "resources": PulumiCloudEndpointConfig(
        name="resources",
        path="/api/orgs/{org}/search/resources",
        # `urn` is only unique within a stack, so project/stack complete the key table-wide.
        primary_keys=["project", "stack", "urn"],
        pagination="cursor",
        partition_key="created",
        description="Every resource in the organization's Pulumi Insights resource index, one row per resource",
    ),
}

ENDPOINTS = tuple(PULUMI_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PULUMI_CLOUD_ENDPOINTS.items()
}
