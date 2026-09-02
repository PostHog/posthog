from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

UPDATED_AT = "updatedAt"
CREATED_AT = "createdAt"
ID = "id"

LINEAR_API_URL = "https://api.linear.app/graphql"
LINEAR_DEFAULT_PAGE_SIZE = 250

INCREMENTAL_DATETIME_FIELDS: list[IncrementalField] = [
    {
        "label": UPDATED_AT,
        "type": IncrementalFieldType.DateTime,
        "field": UPDATED_AT,
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class LinearEndpointConfig:
    incremental_fields: list[IncrementalField]
    graphql_query_name: str | None = None
    primary_key: str = ID
    partition_count: int = 1
    partition_size: int = 1
    partition_mode: PartitionMode | None = "datetime"
    partition_format: PartitionFormat | None = "week"
    partition_keys: list[str] | None = field(default_factory=lambda: [CREATED_AT])
    should_sync_default: bool = True


LINEAR_ENDPOINTS: dict[str, LinearEndpointConfig] = {
    "issues": LinearEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "projects": LinearEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "teams": LinearEndpointConfig(
        incremental_fields=[],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "users": LinearEndpointConfig(
        incremental_fields=[],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "comments": LinearEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "labels": LinearEndpointConfig(
        graphql_query_name="issueLabels",
        incremental_fields=[],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "cycles": LinearEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "resources": LinearEndpointConfig(
        graphql_query_name="attachments",
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "workflow_states": LinearEndpointConfig(
        graphql_query_name="workflowStates",
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    "project_milestones": LinearEndpointConfig(
        graphql_query_name="projectMilestones",
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    # Initiatives are only available on Linear's higher-tier plans, so most workspaces have
    # nothing to sync here — leave it off by default and let those who use them opt in.
    "initiatives": LinearEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
        should_sync_default=False,
    ),
    "team_memberships": LinearEndpointConfig(
        graphql_query_name="teamMemberships",
        incremental_fields=[],
        partition_mode=None,
        partition_format=None,
        partition_keys=None,
    ),
    # `issueRelations` takes no filter argument, so there is no server-side timestamp filter
    # to drive an incremental sync — full refresh only.
    "issue_relations": LinearEndpointConfig(
        graphql_query_name="issueRelations",
        incremental_fields=[],
    ),
    "project_updates": LinearEndpointConfig(
        graphql_query_name="projectUpdates",
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
    "documents": LinearEndpointConfig(
        incremental_fields=INCREMENTAL_DATETIME_FIELDS,
    ),
}

ENDPOINTS = tuple(LINEAR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in LINEAR_ENDPOINTS.items()
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in LINEAR_ENDPOINTS.items()}
