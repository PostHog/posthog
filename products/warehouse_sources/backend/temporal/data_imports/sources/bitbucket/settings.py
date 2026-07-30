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


@dataclass
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
