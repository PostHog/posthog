from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Raw-data resources under the per-workspace Customer API (`https://<workspace>.appfireflow.com/v3/customer/core/`).
CORE_ENDPOINTS = (
    "Users",
    "Teams",
    "Commits",
    "PullRequests",
    "Repos",
    "Tickets",
    "UserAliases",
    "TeamMemberships",
    "PullRequestProjects",
    "TicketProjects",
    "PullRequestComments",
    "TicketEvents",
)

# Aggregate report resources under the shared Metrics API host (`https://api.appfireflow.com/`).
# Unlike the core endpoints, these return one summary object for a requested date range rather than
# a paginated list of records.
METRIC_ENDPOINTS = (
    "CodingMetrics",
    "CollaborationMetrics",
    "TicketMetrics",
    "DoraLeadTime",
    "DoraDeploymentFrequency",
    "DoraChangeFailureRate",
    "DoraTimeToRestore",
)

ENDPOINTS = CORE_ENDPOINTS + METRIC_ENDPOINTS

# Path of each core endpoint under `/v3/customer/core/`.
CORE_ENDPOINT_PATHS: dict[str, str] = {
    "Users": "users/",
    "Teams": "teams/",
    "Commits": "commits/",
    "PullRequests": "pull_requests/",
    "Repos": "repos/",
    "Tickets": "tickets/",
    "UserAliases": "user_alias/",
    # Flow documents this path without a trailing slash, but only `team_membership/` routes to the API.
    "TeamMemberships": "team_membership/",
    "PullRequestProjects": "pull_request_projects/",
    "TicketProjects": "ticket_projects/",
    "PullRequestComments": "pull_request_comments/",
    "TicketEvents": "ticket_events/",
}

# Path of each metrics endpoint under the shared collaboration host.
METRIC_ENDPOINT_PATHS: dict[str, str] = {
    "CodingMetrics": "/collaboration/code/metrics/",
    "CollaborationMetrics": "/collaboration/pullrequest/metrics/",
    "TicketMetrics": "/ticket-delivery/metrics/",
    "DoraLeadTime": "/dora/build-release/change/lead_time/",
    "DoraDeploymentFrequency": "/dora/build-release/deployment/frequency/",
    "DoraChangeFailureRate": "/dora/build-release/incident/change_failure_rate/",
    "DoraTimeToRestore": "/dora/build-release/incident/time_to_restore/",
}

# Each metrics API family expects its `date_range` window in a different shape:
# collaboration `[YYYY-MM-DD:YYYY-MM-DD]`, ticket delivery a JSON list of two offset datetimes,
# and DORA two comma-separated offset datetimes.
MetricDateRangeStyle = Literal["bracket", "json_list", "comma"]

METRIC_DATE_RANGE_STYLES: dict[str, MetricDateRangeStyle] = {
    "CodingMetrics": "bracket",
    "CollaborationMetrics": "bracket",
    "TicketMetrics": "json_list",
    "DoraLeadTime": "comma",
    "DoraDeploymentFrequency": "comma",
    "DoraChangeFailureRate": "comma",
    "DoraTimeToRestore": "comma",
}

# Every Customer API object exposes `id` as its primary key (confirmed for Users, Commits,
# Pull requests, Teams, and Tickets in the API reference; Repos follows the same convention).
CORE_PRIMARY_KEYS: dict[str, list[str]] = {name: ["id"] for name in CORE_ENDPOINTS}

# The metrics endpoints return one row per requested window, so the window we asked for is the
# natural (and only) unique key for a synced row.
METRIC_PRIMARY_KEYS: dict[str, list[str]] = {name: ["date_range"] for name in METRIC_ENDPOINTS}

PRIMARY_KEYS: dict[str, list[str]] = {**CORE_PRIMARY_KEYS, **METRIC_PRIMARY_KEYS}

TABLE_NAMES: dict[str, str] = {
    "Users": "users",
    "Teams": "teams",
    "Commits": "commits",
    "PullRequests": "pull_requests",
    "Repos": "repos",
    "Tickets": "tickets",
    "UserAliases": "user_aliases",
    "TeamMemberships": "team_memberships",
    "PullRequestProjects": "pull_request_projects",
    "TicketProjects": "ticket_projects",
    "PullRequestComments": "pull_request_comments",
    "TicketEvents": "ticket_events",
    "CodingMetrics": "coding_metrics",
    "CollaborationMetrics": "collaboration_metrics",
    "TicketMetrics": "ticket_metrics",
    "DoraLeadTime": "dora_lead_time",
    "DoraDeploymentFrequency": "dora_deployment_frequency",
    "DoraChangeFailureRate": "dora_change_failure_rate",
    "DoraTimeToRestore": "dora_time_to_restore",
}

# Stable datetime field to partition on, for endpoints where one is confirmed by the API docs.
# Repos and TeamMemberships have no documented date field, and the metrics endpoints return one aggregate row per
# sync, so neither partitions.
PARTITION_KEYS: dict[str, str] = {
    "Users": "created_at",
    "Teams": "created_at",
    "Commits": "author_date",
    "PullRequests": "created_at",
    "Tickets": "created_at",
    "UserAliases": "created_at",
    "PullRequestProjects": "created_at",
    "TicketProjects": "created_at",
    "PullRequestComments": "created_at",
    "TicketEvents": "created_at",
}

# Only endpoints with a documented `<field>__gte`/`<field>__lt`-filterable timestamp get an entry.
# Repos, TeamMemberships, PullRequestProjects, TicketProjects, PullRequestComments, TicketEvents and the
# metrics endpoints are full refresh: the core ones document no date filter, and the metrics endpoints already require an explicit
# date-range window on every call.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Users": [incremental_field("last_activity_at", IncrementalFieldType.DateTime)],
    "Teams": [incremental_field("created_at", IncrementalFieldType.DateTime)],
    # Flow's docs recommend filtering commits by author_date rather than committer_date.
    "Commits": [incremental_field("author_date", IncrementalFieldType.DateTime)],
    # Pull requests have no generic `updated_at`; a PR whose state changes after it first
    # matches the incremental window (e.g. merged much later) won't be re-fetched.
    "PullRequests": [incremental_field("created_at", IncrementalFieldType.DateTime)],
    "Tickets": [incremental_field("updated_at", IncrementalFieldType.DateTime)],
    # `last_activity_at` is null for an alias with no activity yet, and a `__gte` filter would never
    # return it. Merging an alias into another apex user does not move `created_at`, so only a
    # full refresh picks up that change.
    "UserAliases": [incremental_field("created_at", IncrementalFieldType.DateTime)],
}

# Maximum page size documented for the Customer API's `limit` parameter.
MAX_PAGE_SIZE = 1000

# Coding metrics trend fields only populate once the requested window spans 4+ full
# Mon-Sun weeks, so each full-refresh sync requests a trailing 90-day window by default.
DEFAULT_METRICS_LOOKBACK_DAYS = 90
