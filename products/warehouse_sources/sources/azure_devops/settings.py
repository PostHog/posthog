from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

AZURE_DEVOPS_BASE_URL = "https://dev.azure.com"
# Release Management is the one area served from its own host.
AZURE_DEVOPS_RELEASE_BASE_URL = "https://vsrm.dev.azure.com"


# Azure DevOps mixes pagination styles per endpoint, dispatched by name in
# azure_devops.py:
# - projects/builds/build_definitions/releases/release_deployments/pipelines:
#   continuationToken via the x-ms-continuationtoken header
# - pull_requests/commits/teams/team_members/test_runs: $top/$skip offset paging
# - work_item_revisions: body continuationToken + isLastBatch (reporting endpoint)
# - repositories/pull request threads/reviewers/work items/build timelines/pipeline runs/
#   work item types/type states/classification nodes/team iterations: single response per parent
@dataclass(frozen=True)
class AzureDevOpsEndpointConfig:
    name: str
    # Path template under {base_url}/{organization}. `{project}`, `{repositoryId}`,
    # `{pullRequestId}`, `{buildId}`, `{teamId}`, `{pipelineId}` and `{workItemType}`
    # are substituted during the fan-out that reaches the endpoint.
    path: str
    base_url: str = AZURE_DEVOPS_BASE_URL
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
    "build_definitions": AzureDevOpsEndpointConfig(
        name="build_definitions",
        path="/{project}/_apis/build/definitions",
        # Definition IDs restart per project.
        primary_keys=["project_id", "id"],
        partition_key="createdDate",
        # The listing filters on build times (builtAfter/notBuiltAfter), never on when
        # the definition itself changed, so there is no cursor to sync incrementally on.
    ),
    "build_timeline_records": AzureDevOpsEndpointConfig(
        name="build_timeline_records",
        path="/{project}/_apis/build/builds/{buildId}/timeline",
        # Record IDs are GUIDs; the build is carried so a row identifies the run it
        # describes without joining.
        primary_keys=["build_id", "id"],
        # Queue time never moves, unlike the finish time the cursor tracks.
        partition_key="build_queue_time",
        # A timeline takes no filter of its own, so the watermark bounds the parent build
        # listing instead. It tracks the build's finish time rather than its queue time,
        # because a record changes until its build ends and again on every retry — see
        # `builds_for` in azure_devops.py.
        incremental_param="minTime",
        # The fan-out visits projects one after another, so the stream as a whole is
        # not ascending. `desc` makes the pipeline finalize the watermark only after a
        # fully successful sync.
        sort_mode="desc",
        incremental_fields=[
            {
                "label": "build_finish_time",
                "type": IncrementalFieldType.DateTime,
                "field": "build_finish_time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "pipelines": AzureDevOpsEndpointConfig(
        name="pipelines",
        path="/{project}/_apis/pipelines",
        # Pipeline IDs restart per project.
        primary_keys=["project_id", "id"],
    ),
    "pipeline_runs": AzureDevOpsEndpointConfig(
        name="pipeline_runs",
        path="/{project}/_apis/pipelines/{pipelineId}/runs",
        # Run IDs restart per project.
        primary_keys=["project_id", "id"],
        partition_key="createdDate",
        # The run listing takes no time filter — it answers with the pipeline's most recent
        # runs — so there is no cursor to sync incrementally on.
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
    "pull_request_work_items": AzureDevOpsEndpointConfig(
        name="pull_request_work_items",
        path="/{project}/_apis/git/repositories/{repositoryId}/pullRequests/{pullRequestId}/workitems",
        # The row is a link, not the work item itself: the same work item can be linked
        # from pull requests in several repositories.
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
    "work_item_types": AzureDevOpsEndpointConfig(
        name="work_item_types",
        path="/{project}/_apis/wit/workitemtypes",
        # A type is defined by the project's process, so the same reference name
        # describes a different type in another project.
        primary_keys=["project_id", "referenceName"],
    ),
    "work_item_type_states": AzureDevOpsEndpointConfig(
        name="work_item_type_states",
        path="/{project}/_apis/wit/workitemtypes/{workItemType}/states",
        # A state is named per type; only the state category is shared vocabulary.
        primary_keys=["project_id", "work_item_type", "name"],
    ),
    "work_item_classification_nodes": AzureDevOpsEndpointConfig(
        name="work_item_classification_nodes",
        path="/{project}/_apis/wit/classificationnodes",
        # Node IDs restart per project.
        primary_keys=["project_id", "id"],
    ),
    "work_iterations": AzureDevOpsEndpointConfig(
        name="work_iterations",
        path="/{project}/{teamId}/_apis/work/teamsettings/iterations",
        # Teams subscribe to iterations from the project's shared tree, so one iteration
        # yields a row per team that uses it.
        primary_keys=["team_id", "id"],
    ),
    "releases": AzureDevOpsEndpointConfig(
        name="releases",
        path="/{project}/_apis/release/releases",
        base_url=AZURE_DEVOPS_RELEASE_BASE_URL,
        # Release IDs restart per project.
        primary_keys=["project_id", "id"],
        partition_key="createdOn",
        # A release keeps changing after it is created — its status, its modified time,
        # its environments — and the listing only filters on creation time, so a cursor
        # would stop re-reading rows that are still moving. Full refresh instead; the
        # per-environment history lives in release_deployments, which does have a
        # modified-time filter.
    ),
    "release_deployments": AzureDevOpsEndpointConfig(
        name="release_deployments",
        path="/{project}/_apis/release/deployments",
        base_url=AZURE_DEVOPS_RELEASE_BASE_URL,
        # Deployment IDs restart per project.
        primary_keys=["project_id", "id"],
        # A deployment's status changes as it promotes, so the queue time is the
        # stable field and the modified time is the cursor.
        partition_key="queuedOn",
        incremental_param="minModifiedTime",
        sort_mode="desc",
        incremental_fields=[
            {
                "label": "lastModifiedOn",
                "type": IncrementalFieldType.DateTime,
                "field": "lastModifiedOn",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "test_runs": AzureDevOpsEndpointConfig(
        name="test_runs",
        path="/{project}/_apis/test/runs",
        primary_keys=["project_id", "id"],
        partition_key="createdDate",
        # The cursor is pushed through minLastUpdatedDate/maxLastUpdatedDate, which the
        # vendor caps at a 7-day span, so azure_devops.py walks windows rather than
        # sending one filter param. Full refresh takes the unfiltered listing instead.
        sort_mode="desc",
        incremental_fields=[
            {
                "label": "lastUpdatedDate",
                "type": IncrementalFieldType.DateTime,
                "field": "lastUpdatedDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(AZURE_DEVOPS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AZURE_DEVOPS_ENDPOINTS.items() if config.incremental_fields
}
