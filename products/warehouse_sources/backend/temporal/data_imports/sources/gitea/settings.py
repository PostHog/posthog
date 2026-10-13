from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Gitea's default MAX_RESPONSE_ITEMS is 50 — instances clamp larger `limit` values to it,
# so asking for more only produces confusing short pages.
PAGE_SIZE = 50


@dataclass(frozen=True)
class GiteaEndpointConfig:
    name: str
    path: str  # Path template with a {repository} (owner/repo) placeholder
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    primary_key: str = "id"
    # The order rows actually arrive in from the API. Verified against a live instance —
    # Gitea ignores sort params on several list endpoints, so don't assume.
    sort_mode: Literal["asc", "desc"] = "asc"
    # True only when the endpoint honors the server-side `since` timestamp filter
    # (verified with a future-date probe; e.g. /pulls accepts `since` but ignores it).
    supports_since: bool = False
    # Extra static query params merged into every request.
    extra_params: dict[str, str] = field(default_factory=dict)
    # How the endpoint signals a next page. Several list endpoints send no Link header, only
    # X-Total-Count (or a body `total_count`), so they page by number against that total.
    # "unpaged" endpoints return every row when `page` is omitted. Use it where the endpoint
    # drops rows after paging, because there a short or empty page is not the last page.
    pagination: Literal["link_header", "total_count", "unpaged"] = "link_header"
    # Key of the row list when the response wraps it in an object.
    data_selector: Optional[str] = None
    # Parent endpoint whose rows fan out to this one; `path` then also has an {index}
    # placeholder filled with each parent row's `number`.
    parent: Optional[str] = None
    # Column that carries the parent's `number` onto each child row.
    parent_number_column: Optional[str] = None
    # Error raised instead of the generic "Repository not found" when the endpoint 404s.
    not_found_error: Optional[str] = None
    # Webhook event name (the X-Gitea-Event header value) that can feed this table, if any.
    webhook_event: Optional[str] = None
    # Ordered columns (newest-first, NULLs last) ranking webhook events that share a primary
    # key, so a drain batch collapses to the latest state per id before the delta merge
    # (which doesn't dedupe within a batch).
    version_keys: Optional[list[str]] = None


GITEA_ENDPOINTS: dict[str, GiteaEndpointConfig] = {
    "issues": GiteaEndpointConfig(
        name="issues",
        # type=issues excludes pull requests, which Gitea otherwise mixes into this list.
        path="/repos/{repository}/issues",
        extra_params={"state": "all", "type": "issues"},
        partition_key="created_at",
        # `since` filters server-side on the issue's updated time (inclusive); rows still
        # arrive newest-created-first, so the watermark persists at end of run (desc).
        supports_since=True,
        sort_mode="desc",
        default_incremental_field="updated_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        webhook_event="issues",
        version_keys=["updated_at"],
    ),
    "pull_requests": GiteaEndpointConfig(
        name="pull_requests",
        # /pulls accepts `since` but silently ignores it (verified with a future-date probe),
        # so this table is full refresh only. sort=oldest gives stable created-asc pagination.
        path="/repos/{repository}/pulls",
        extra_params={"state": "all", "sort": "oldest"},
        partition_key="created_at",
        sort_mode="asc",
        incremental_fields=[],
        webhook_event="pull_request",
        version_keys=["updated_at"],
    ),
    "commits": GiteaEndpointConfig(
        name="commits",
        # stat/verification/files=false trims the per-commit payload (diff stats, GPG
        # verification, file lists) that the warehouse doesn't need.
        path="/repos/{repository}/commits",
        extra_params={"stat": "false", "verification": "false", "files": "false"},
        primary_key="sha",
        # Top-level `created` is the commit timestamp; the list always returns newest-first
        # (git log order) and `since` filters server-side on commit time.
        partition_key="created",
        supports_since=True,
        sort_mode="desc",
        default_incremental_field="created",
        incremental_fields=[
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "releases": GiteaEndpointConfig(
        name="releases",
        # No server-side time filter — full refresh only (release lists are small).
        # The list arrives newest-first.
        path="/repos/{repository}/releases",
        partition_key="created_at",
        sort_mode="desc",
        incremental_fields=[],
    ),
    "labels": GiteaEndpointConfig(
        name="labels",
        # Labels carry no timestamps at all: full refresh, no partitioning.
        path="/repos/{repository}/labels",
        incremental_fields=[],
    ),
    "milestones": GiteaEndpointConfig(
        name="milestones",
        path="/repos/{repository}/milestones",
        extra_params={"state": "all"},
        incremental_fields=[],
    ),
    "issue_comments": GiteaEndpointConfig(
        name="issue_comments",
        # Repo-wide plain comments on issues and pull requests. Rows arrive oldest-created
        # first while `since` filters server-side on the comment's updated time, so the
        # watermark persists at end of run (desc).
        path="/repos/{repository}/issues/comments",
        pagination="total_count",
        partition_key="created_at",
        supports_since=True,
        sort_mode="desc",
        default_incremental_field="updated_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "issue_timeline": GiteaEndpointConfig(
        name="issue_timeline",
        # Every event on an issue (comments, state changes, label and assignee changes, ...).
        # Adding a timeline event bumps the issue's updated time, so an incremental run only
        # fans out over issues updated since the watermark. A plain comment edit does not bump
        # it; the issue_comments table carries those edits.
        path="/repos/{repository}/issues/{index}/timeline",
        parent="issues",
        parent_number_column="issue_number",
        # Gitea drops cross-references the token can't read after paging.
        pagination="unpaged",
        partition_key="created_at",
        supports_since=True,
        sort_mode="desc",
        default_incremental_field="updated_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "reviews": GiteaEndpointConfig(
        name="reviews",
        # No time filter on reviews or on the parent /pulls list: full refresh only.
        # `submitted_at` is the review's creation time, so it is stable.
        path="/repos/{repository}/pulls/{index}/reviews",
        parent="pull_requests",
        parent_number_column="pull_request_number",
        # Gitea drops other users' pending reviews after paging.
        pagination="unpaged",
        partition_key="submitted_at",
        incremental_fields=[],
    ),
    "workflow_runs": GiteaEndpointConfig(
        name="workflow_runs",
        # Gitea Actions runs, newest first. No time filter: full refresh only. No partition
        # key: the API exposes no creation time, and `started_at` resets on a re-run.
        path="/repos/{repository}/actions/runs",
        pagination="total_count",
        data_selector="workflow_runs",
        sort_mode="desc",
        incremental_fields=[],
        not_found_error=(
            "Gitea Actions runs are unavailable for this repository. "
            "Syncing workflow runs needs Gitea 1.25 or later with Actions enabled on the repository."
        ),
    ),
}

ENDPOINTS = tuple(GITEA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GITEA_ENDPOINTS.items()
}
