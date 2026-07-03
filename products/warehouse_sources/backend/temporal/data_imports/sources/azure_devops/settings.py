from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


# Azure DevOps mixes pagination styles per endpoint, dispatched by name in
# azure_devops.py:
# - projects/builds: continuationToken via the x-ms-continuationtoken header
# - pull_requests: $top/$skip offset paging
# - work_item_revisions: body continuationToken + isLastBatch (reporting endpoint)
# - repositories: single per-project response
@dataclass
class AzureDevOpsEndpointConfig:
    name: str
    # Path template under https://dev.azure.com/{organization}; `{project}` is
    # substituted during the per-project fan-out.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Query param that pushes the incremental cursor server-side.
    incremental_param: Optional[str] = None
    # Stable creation/event-time field used for datetime partitioning.
    partition_key: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"


AZURE_DEVOPS_ENDPOINTS: dict[str, AzureDevOpsEndpointConfig] = {
    "projects": AzureDevOpsEndpointConfig(
        name="projects",
        path="/_apis/projects",
    ),
    "repositories": AzureDevOpsEndpointConfig(
        name="repositories",
        path="/{project}/_apis/git/repositories",
    ),
    "builds": AzureDevOpsEndpointConfig(
        name="builds",
        path="/{project}/_apis/build/builds",
        partition_key="queueTime",
        # minTime filters on queue time; queryOrder=queueTimeAscending keeps
        # the watermark monotonic.
        incremental_param="minTime",
        incremental_fields=[
            {
                "label": "queueTime",
                "type": IncrementalFieldType.DateTime,
                "field": "queueTime",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "pull_requests": AzureDevOpsEndpointConfig(
        name="pull_requests",
        path="/{project}/_apis/git/pullrequests",
        primary_keys=["pullRequestId"],
        partition_key="creationDate",
        incremental_param="searchCriteria.minTime",
        # PR search returns newest-first with no ascending option; the pipeline
        # defers desc watermark commits until a run completes.
        sort_mode="desc",
        incremental_fields=[
            {
                "label": "creationDate",
                "type": IncrementalFieldType.DateTime,
                "field": "creationDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "work_item_revisions": AzureDevOpsEndpointConfig(
        name="work_item_revisions",
        path="/_apis/wit/reporting/workitemrevisions",
        # Revisions are append-only; (id, rev) identifies one revision.
        primary_keys=["id", "rev"],
        partition_key="changed_date",
        incremental_param="startDateTime",
        incremental_fields=[
            {
                "label": "changed_date",
                "type": IncrementalFieldType.DateTime,
                "field": "changed_date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(AZURE_DEVOPS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AZURE_DEVOPS_ENDPOINTS.items() if config.incremental_fields
}
