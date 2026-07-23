from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Gitea's default MAX_RESPONSE_ITEMS is 50 — instances clamp larger `limit` values to it,
# so asking for more only produces confusing short pages.
PAGE_SIZE = 50


@dataclass
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
}

ENDPOINTS = tuple(GITEA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GITEA_ENDPOINTS.items()
}
