from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


# Azure DevOps mixes pagination styles per endpoint, dispatched by name in
# azure_devops.py:
# - projects/builds: continuationToken via the x-ms-continuationtoken header
# - pull_requests/commits/teams/team_members: $top/$skip offset paging
# - work_item_revisions: body continuationToken + isLastBatch (reporting endpoint)
# - repositories/pull request threads/reviewers: single response per parent
@dataclass(frozen=True)
class AzureDevOpsEndpointConfig:
    name: str
    # Path template under https://dev.azure.com/{organization}. `{project}`,
    # `{repositoryId}`, `{pullRequestId}` and `{teamId}` are substituted during
    # the fan-out that reaches the endpoint.
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
    "commits": AzureDevOpsEndpointConfig(
        name="commits",
        path="/{project}/_apis/git/repositories/{repositoryId}/commits",
        # A commit SHA is unique within a repository, but the same commit can be
        # reachable from several repositories in one organization (forks, imports).
        primary_keys=["repository_id", "commitId"],
        partition_key="committer_date",
        incremental_param="searchCriteria.fromDate",
        # Pages arrive oldest-first within a repository, but the fan-out visits
        # repositories one after another, so the stream as a whole is not ascending.
        # `desc` makes the pipeline finalize the watermark only after a fully
        # successful sync, so a partial run can't advance it past a repository it
        # never reached.
        sort_mode="desc",
        incremental_fields=[
            {
                "label": "committer_date",
                "type": IncrementalFieldType.DateTime,
                "field": "committer_date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "pull_request_threads": AzureDevOpsEndpointConfig(
        name="pull_request_threads",
        path="/{project}/_apis/git/repositories/{repositoryId}/pullRequests/{pullRequestId}/threads",
        # Thread IDs restart per pull request.
        primary_keys=["repository_id", "pull_request_id", "id"],
        partition_key="publishedDate",
    ),
    "pull_request_thread_comments": AzureDevOpsEndpointConfig(
        name="pull_request_thread_comments",
        # Comments arrive nested in the threads response; they get their own table
        # rather than a second request.
        path="/{project}/_apis/git/repositories/{repositoryId}/pullRequests/{pullRequestId}/threads",
        primary_keys=["repository_id", "pull_request_id", "thread_id", "id"],
        partition_key="publishedDate",
    ),
    "pull_request_reviewers": AzureDevOpsEndpointConfig(
        name="pull_request_reviewers",
        path="/{project}/_apis/git/repositories/{repositoryId}/pullRequests/{pullRequestId}/reviewers",
        primary_keys=["repository_id", "pull_request_id", "id"],
    ),
    "teams": AzureDevOpsEndpointConfig(
        name="teams",
        # The organization-wide GET /_apis/teams is preview-only, so teams are read
        # per project through the generally available Core endpoint.
        path="/_apis/projects/{project}/teams",
    ),
    "team_members": AzureDevOpsEndpointConfig(
        name="team_members",
        path="/_apis/projects/{project}/teams/{teamId}/members",
        # Members carry no identifier of their own; the identity ID is lifted to the
        # row root during the fan-out.
        primary_keys=["team_id", "identity_id"],
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
