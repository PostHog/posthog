from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

_UPDATED_ON_CREATED_ON: list[IncrementalField] = [
    {
        "label": "updated_on",
        "type": IncrementalFieldType.DateTime,
        "field": "updated_on",
        "field_type": IncrementalFieldType.DateTime,
    },
    {
        "label": "created_on",
        "type": IncrementalFieldType.DateTime,
        "field": "created_on",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass(frozen=True)
class SecondLevelFanOut:
    """Describes a child endpoint that is fetched once per row of a parent endpoint, which is
    itself walked once per repository in the workspace."""

    # Key in BITBUCKET_ENDPOINTS whose path is walked per repository to produce the parents.
    parent: str
    # Placeholder in the child's path, and the parent field whose value fills it.
    path_param: str
    id_field: str
    # How the parent list is ordered, and the parent field carrying that ordering value.
    # Resuming skips parents the previous attempt already walked past, and an incremental
    # sync stops the walk once the ordering value crosses the watermark.
    order: str  # "id_asc" or "datetime_desc"
    order_field: str
    # Parent walk request shaping: the `sort` value, and the BBQL field for a server-side
    # bound (None when the parent endpoint ignores `q` and the bound is applied client-side).
    parent_sort: Optional[str] = None
    parent_filter_field: Optional[str] = None
    # Parent fields copied onto every child row, as {child column: parent field}. Child rows
    # usually carry no reference back to their parent, and the primary key needs one.
    inject: dict[str, str] = field(default_factory=dict)
    # One request per parent, so an unbounded first sync of a long-lived repository would
    # outlast any rate budget. Later syncs are bounded by the watermark instead.
    max_parents_per_repo: Optional[int] = None


@dataclass(frozen=True)
class BitbucketEndpointConfig:
    name: str
    path: str  # Path template with {workspace} and, for fan-out endpoints, {repo_slug}
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    # Bitbucket's default pagelen is 10; most collections cap at 100 but the pull
    # requests list rejects anything above 50 with "Invalid pagelen".
    page_size: int = 100
    primary_keys: list[str] = field(default_factory=lambda: ["uuid"])
    # Fan-out: fetched once per repository in the workspace, with {repo_slug}
    # substituted into the path and repository context injected into each row.
    fan_out_over_repos: bool = False
    # Two-level fan-out: for every repository, walk a parent endpoint and fetch this path
    # once per parent row. None for top-level and single-level fan-out endpoints.
    fan_out: Optional[SecondLevelFanOut] = None
    # BBQL field for a server-side incremental filter (`q=<field> > "<ts>"`), verified
    # to actually filter (a future-date probe returns 0 rows). None = the endpoint
    # silently ignores `q` (commits, pipelines); incremental sync instead scrolls
    # newest-first and stops client-side once a whole page predates the watermark.
    server_filter_field: Optional[str] = None
    # Value for the `sort` param, or None when the endpoint has a fixed order
    # (commits are always newest-first and ignore sort).
    sort_param: Optional[str] = None
    # Repeated params are legal in Bitbucket's API (e.g. one `state` per PR state),
    # so extra params are (key, value) pairs rather than a dict.
    extra_params: list[tuple[str, str]] = field(default_factory=list)
    should_sync_default: bool = True
    # The pipelines endpoint drops `sort` from the `next` URL it returns, silently
    # reverting page 2+ to oldest-first. Endpoints with this flag paginate by
    # incrementing the `page` param on the original URL instead of following `next`.
    rebuild_page_urls: bool = False


BITBUCKET_ENDPOINTS: dict[str, BitbucketEndpointConfig] = {
    "repositories": BitbucketEndpointConfig(
        name="repositories",
        path="/repositories/{workspace}",
        partition_key="created_on",
        incremental_fields=_UPDATED_ON_CREATED_ON,
        default_incremental_field="updated_on",
        server_filter_field="updated_on",
        sort_param="updated_on",
        primary_keys=["uuid"],
    ),
    "pull_requests": BitbucketEndpointConfig(
        name="pull_requests",
        path="/repositories/{workspace}/{repo_slug}/pullrequests",
        partition_key="created_on",
        incremental_fields=_UPDATED_ON_CREATED_ON,
        default_incremental_field="updated_on",
        server_filter_field="updated_on",
        sort_param="updated_on",
        page_size=50,  # PR list rejects pagelen > 50
        fan_out_over_repos=True,
        # PR ids restart at 1 in every repo, so the parent uuid is required for a
        # table-wide unique key.
        primary_keys=["repository_uuid", "id"],
        # The endpoint defaults to OPEN only; ask for every state explicitly.
        extra_params=[
            ("state", "OPEN"),
            ("state", "MERGED"),
            ("state", "DECLINED"),
            ("state", "SUPERSEDED"),
        ],
    ),
    "commits": BitbucketEndpointConfig(
        name="commits",
        path="/repositories/{workspace}/{repo_slug}/commits",
        partition_key="date",
        # No server-side time filter (the API accepts `q` but ignores it) and the list
        # is always newest-first in topological order, so incremental sync scrolls from
        # the newest commit and stops once an entire page predates the watermark.
        # Topological order means dates aren't strictly monotonic, so an old-dated merge
        # commit surfacing late can be missed — same trade-off as the GitHub source.
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.DateTime,
                "field": "date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="date",
        fan_out_over_repos=True,
        # The same commit hash exists in every fork within the workspace, so the
        # repo uuid keeps the key unique table-wide.
        primary_keys=["repository_uuid", "hash"],
    ),
    "pipelines": BitbucketEndpointConfig(
        name="pipelines",
        path="/repositories/{workspace}/{repo_slug}/pipelines/",
        partition_key="created_on",
        # Pipelines ignore `q` too, but honor `sort`; scroll newest-first and stop
        # client-side at the watermark, like commits.
        incremental_fields=[
            {
                "label": "created_on",
                "type": IncrementalFieldType.DateTime,
                "field": "created_on",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="created_on",
        sort_param="-created_on",
        fan_out_over_repos=True,
        # Pipeline uuids are real UUIDs (globally unique), so no composite key is
        # needed even though this is a fan-out child.
        primary_keys=["uuid"],
        rebuild_page_urls=True,
    ),
    "deployments": BitbucketEndpointConfig(
        name="deployments",
        path="/repositories/{workspace}/{repo_slug}/deployments/",
        # No verified server-side filter or stable sort for deployments, so full
        # refresh only (volume is bounded by actual deploy count per repo).
        incremental_fields=[],
        fan_out_over_repos=True,
        primary_keys=["uuid"],
    ),
    "pull_request_activity": BitbucketEndpointConfig(
        name="pull_request_activity",
        # The repo-level feed carries the activity of every pull request in the repo, so
        # one walk per repo replaces a walk per pull request.
        path="/repositories/{workspace}/{repo_slug}/pullrequests/activity",
        partition_key="activity_date",
        # Entries are polymorphic (comment / update / approval / changes_requested), each
        # carrying its own timestamp, so the transport lifts one to `activity_date`. The
        # endpoint ignores both `q` and `sort` but returns newest-first, so incremental
        # sync scrolls from the newest entry and stops once a whole page predates the
        # watermark, like commits and pipelines.
        incremental_fields=[
            {
                "label": "activity_date",
                "type": IncrementalFieldType.DateTime,
                "field": "activity_date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="activity_date",
        page_size=50,  # the activity feed rejects pagelen > 50
        fan_out_over_repos=True,
        # Activity entries have no id of their own. A pull request cannot record two
        # entries of the same kind at the same microsecond, so the kind and timestamp
        # complete the key.
        primary_keys=["repository_uuid", "pull_request_id", "activity_type", "activity_date"],
    ),
    "pull_request_comments": BitbucketEndpointConfig(
        name="pull_request_comments",
        path="/repositories/{workspace}/{repo_slug}/pullrequests/{pull_request_id}/comments",
        partition_key="created_on",
        incremental_fields=_UPDATED_ON_CREATED_ON,
        default_incremental_field="updated_on",
        server_filter_field="updated_on",
        sort_param="updated_on",
        fan_out=SecondLevelFanOut(
            parent="pull_requests",
            path_param="pull_request_id",
            id_field="id",
            # Sorted on the immutable created_on so ids arrive ascending, which is what lets
            # the resume bookmark skip every pull request below it.
            order="id_asc",
            order_field="id",
            parent_sort="created_on",
            # Posting, editing or deleting a comment bumps its pull request's updated_on, so
            # the server-side bound narrows the walk without missing a changed comment.
            parent_filter_field="updated_on",
        ),
        # Comment ids look globally sequential, but the docs only scope them to their
        # pull request, so the parents complete the key.
        primary_keys=["repository_uuid", "pull_request_id", "id"],
    ),
    "pipeline_steps": BitbucketEndpointConfig(
        name="pipeline_steps",
        path="/repositories/{workspace}/{repo_slug}/pipelines/{pipeline_uuid}/steps/",
        # A step carries started_on and completed_on, but both are unset until the step runs,
        # so neither can act as a cursor. The parent pipeline's immutable created_on is
        # injected instead, which is also what bounds the pipeline walk.
        partition_key="pipeline_created_on",
        incremental_fields=[
            {
                "label": "pipeline_created_on",
                "type": IncrementalFieldType.DateTime,
                "field": "pipeline_created_on",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="pipeline_created_on",
        fan_out=SecondLevelFanOut(
            parent="pipelines",
            path_param="pipeline_uuid",
            id_field="uuid",
            order="datetime_desc",
            order_field="created_on",
            parent_sort="-created_on",
            inject={"pipeline_uuid": "uuid", "pipeline_created_on": "created_on"},
            max_parents_per_repo=2000,
        ),
        # Step uuids are real UUIDs, but the docs only scope them to their pipeline.
        primary_keys=["repository_uuid", "pipeline_uuid", "uuid"],
    ),
    "commit_statuses": BitbucketEndpointConfig(
        name="commit_statuses",
        path="/repositories/{workspace}/{repo_slug}/commit/{commit}/statuses",
        # A status has its own created_on, but nothing on the commit changes when one is
        # posted, so the only bound available for the commit walk is the commit's own date.
        # A status attached to a commit older than the watermark is therefore missed — the
        # same trade-off the commits endpoint already makes.
        partition_key="commit_date",
        incremental_fields=[
            {
                "label": "commit_date",
                "type": IncrementalFieldType.DateTime,
                "field": "commit_date",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        default_incremental_field="commit_date",
        fan_out=SecondLevelFanOut(
            parent="commits",
            path_param="commit",
            id_field="hash",
            order="datetime_desc",
            order_field="date",
            inject={"commit_hash": "hash", "commit_date": "date"},
            max_parents_per_repo=2000,
        ),
        # One request per commit is far more than the other tables cost, so this one is
        # opt-in rather than selected by default.
        should_sync_default=False,
        # Statuses carry no id. Bitbucket addresses one by commit and key
        # (PUT .../commit/{hash}/statuses/build/{key}), so that pair identifies a status.
        primary_keys=["repository_uuid", "commit_hash", "key"],
    ),
    "branches": BitbucketEndpointConfig(
        name="branches",
        path="/repositories/{workspace}/{repo_slug}/refs/branches",
        # A branch has no timestamps of its own; target.date is the tip commit's date and
        # moves on every push, so it is neither a cursor nor a partition key. Full refresh,
        # over a list bounded by the branch count per repository.
        incremental_fields=[],
        # An explicit sort keeps pages from shifting under the paginator when a branch is
        # created or deleted mid-walk.
        sort_param="name",
        fan_out_over_repos=True,
        # Branch names are unique within a repository, and are what pull requests,
        # pipelines and deployments reference.
        primary_keys=["repository_uuid", "name"],
    ),
    "environments": BitbucketEndpointConfig(
        name="environments",
        path="/repositories/{workspace}/{repo_slug}/environments",
        # Environments carry no timestamps; full refresh only (a handful per repo).
        incremental_fields=[],
        fan_out_over_repos=True,
        # Environment uuids are real UUIDs, unique across repositories.
        primary_keys=["uuid"],
    ),
    "projects": BitbucketEndpointConfig(
        name="projects",
        path="/workspaces/{workspace}/projects",
        partition_key="created_on",
        incremental_fields=_UPDATED_ON_CREATED_ON,
        default_incremental_field="updated_on",
        server_filter_field="updated_on",
        sort_param="updated_on",
        primary_keys=["uuid"],
    ),
    "workspace_members": BitbucketEndpointConfig(
        name="workspace_members",
        path="/workspaces/{workspace}/members",
        # Membership objects carry no timestamps; full refresh only (tiny volume).
        incremental_fields=[],
        # Membership rows have no top-level id; the transport injects `user_uuid`
        # from the nested user object.
        primary_keys=["user_uuid"],
    ),
}

ENDPOINTS = tuple(BITBUCKET_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BITBUCKET_ENDPOINTS.items()
}
