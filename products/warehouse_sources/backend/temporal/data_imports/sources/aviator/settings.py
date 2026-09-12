from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class AviatorEndpointConfig:
    name: str
    path: str
    # Primary key columns for the merge upsert. Fan-out endpoints aggregate rows from every
    # repository, so their keys always include the repository (org/repo) to stay unique
    # table-wide — a bare `number` or `date` would collide across repos.
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-style field to partition by (never a mutable `updated_at`).
    partition_key: Optional[str] = None
    # When True the endpoint is called once per repository discovered via GET /repo, injecting
    # the repo's org/name into the request. When False it is a single top-level request.
    fan_out_over_repos: bool = False
    # Order rows arrive in. Fan-out endpoints report "desc" so the incremental watermark persists
    # only at successful job end — a partial run's max value says nothing about repos it never
    # reached. Top-level endpoints declare whatever the API actually returns.
    sort_mode: Literal["asc", "desc"] = "asc"
    default_incremental_field: Optional[str] = None
    # First-sync window (days) for date-windowed incremental endpoints, so the initial sync
    # doesn't try to pull the entire history at once.
    default_lookback_days: Optional[int] = None
    # Whether the table is selected for sync by default in the schema picker.
    should_sync_default: bool = True


# Endpoint catalog. Aviator's public JSON API lives at api.aviator.co/api/v1 and is authenticated
# with a self-serve user access token (`Authorization: Bearer av_uat_...`).
#
# Only `merge_queue_analytics` is synced incrementally: its GET /analytics endpoint is defined by a
# `start`/`end` UTC date window, which is a genuine server-side filter (the endpoint returns per-day
# aggregate rows bounded by that window). Every other endpoint is a current-state snapshot or a small
# list with no reliable server-side timestamp filter, so it ships as full refresh. GET /config/history
# documents optional `start`/`end` params, but we could not curl-verify that they actually filter
# server-side (no test credentials), so it stays full refresh conservatively — config changes are
# low volume, so re-reading them each sync is cheap. GET /user_actions carries a `timestamp` but only
# filters on `entity`, `action` and `page`, so it is full refresh too.
AVIATOR_ENDPOINTS: dict[str, AviatorEndpointConfig] = {
    "repositories": AviatorEndpointConfig(
        name="repositories",
        path="/repo",
        # GET /repo returns {active, name, org, paused} with no id; a repo is identified by org + name.
        primary_keys=["org", "name"],
    ),
    "merge_queue_analytics": AviatorEndpointConfig(
        name="merge_queue_analytics",
        path="/analytics",
        # One row per (repo, date) merging the endpoint's five daily series.
        primary_keys=["repo", "date"],
        partition_key="date",
        fan_out_over_repos=True,
        sort_mode="desc",
        default_incremental_field="date",
        # Merge-queue analytics are daily aggregates; a year of history is a reasonable first sync.
        default_lookback_days=365,
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            },
        ],
    ),
    "queued_pull_requests": AviatorEndpointConfig(
        name="queued_pull_requests",
        path="/pull_request/queued",
        # A snapshot of currently-queued PRs; PR number is unique within a repo, not globally.
        primary_keys=["org", "repo", "number"],
        partition_key="created_at",
        fan_out_over_repos=True,
        sort_mode="desc",
    ),
    "queue_stats": AviatorEndpointConfig(
        name="queue_stats",
        path="/queue/stats",
        # Live queue depth: a single current-state row per repository.
        primary_keys=["org", "repo"],
        fan_out_over_repos=True,
        sort_mode="desc",
    ),
    "branches": AviatorEndpointConfig(
        name="branches",
        path="/branches",
        # GET /branches returns one entry per base-branch glob configured on the repo; the pattern
        # is unique within a repository, so (org, repo, pattern) is the key.
        primary_keys=["org", "repo", "pattern"],
        fan_out_over_repos=True,
        sort_mode="desc",
    ),
    "bot_pull_requests": AviatorEndpointConfig(
        name="bot_pull_requests",
        path="/bot_pull_request",
        # The batch PR's own number, unique within a repository.
        primary_keys=["org", "repo", "number"],
        fan_out_over_repos=True,
        sort_mode="desc",
        # Aviator only creates bot PRs in parallel mode, and the endpoint is a per-PR lookup, so the
        # table costs one request per queued PR. Off by default: repos on serial mode sync nothing.
        should_sync_default=False,
    ),
    "user_actions": AviatorEndpointConfig(
        name="user_actions",
        path="/user_actions",
        # The audit log carries no id, so the whole record is the key.
        primary_keys=["timestamp", "actor", "action", "entity", "target"],
        partition_key="timestamp",
        # The endpoint documents it returns actions newest-first.
        sort_mode="desc",
        # Audit logs are an Aviator Enterprise feature, so the endpoint is unavailable on other plans.
        should_sync_default=False,
    ),
    "config_history": AviatorEndpointConfig(
        name="config_history",
        path="/config/history",
        # No id; a config change is identified by repo + when it was applied.
        primary_keys=["org", "repo", "applied_at"],
        partition_key="applied_at",
        fan_out_over_repos=True,
        sort_mode="desc",
    ),
}

ENDPOINTS = tuple(AVIATOR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AVIATOR_ENDPOINTS.items()
}
