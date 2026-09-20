from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

# Parent resource a fan-out endpoint is requested once per. "commit" walks the organization's
# repositories and then each repository's commits, so it is the only two-level fan-out.
FanOut = Literal["repository", "tool", "commit", "metric"]

# How far back the org-level metric time series is pulled on every sync. The endpoint requires an
# explicit range and the table is full refresh, so this bounds what a sync re-reads.
METRICS_LOOKBACK_DAYS = 365
# Granularity of the metric time series; the API also accepts "week" and "month".
METRICS_PERIOD = "day"


@frozen
class CodacyEndpointConfig:
    name: str
    # Path template with {provider}, {organization}, and the fan-out parent's placeholder
    # ({repository}, {tool_uuid}, {commit}, {metric}).
    path: str
    # searchRepositoryIssues and the metrics time series are the POST list endpoints; pagination
    # still rides the query string.
    method: Literal["GET", "POST"] = "GET"
    # Composite keys include the fan-out parent's identifier, since child ids are only unique
    # within a parent.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    fan_out: Optional[FanOut] = None
    # Stable datetime field to partition by (never a mutable field like `updated`).
    partition_key: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"
    extra_params: dict[str, str] = field(default_factory=dict)
    # Hard cap on pages fetched per fan-out parent, to bound runaway pagination.
    # A structured warning is logged if the cap is reached.
    max_pages_per_parent: int = 1000
    # Only read by the "commit" fan-out: deltaIssues is one request per commit, so the walk stops
    # after this many commits per repository. Commits arrive newest-first, so the cap keeps the
    # most recent ones.
    max_commits_per_repository: int = 500


CODACY_ENDPOINTS: dict[str, CodacyEndpointConfig] = {
    "organizations": CodacyEndpointConfig(
        name="organizations",
        # Lists every organization the token's account belongs to, across Git providers.
        path="/user/organizations",
        primary_keys=["provider", "remoteIdentifier"],
    ),
    "repositories": CodacyEndpointConfig(
        name="repositories",
        # The /analysis listing carries the per-repository quality snapshot (grade, issues,
        # complexity, duplication, coverage, LOC) alongside the repository metadata.
        path="/analysis/organizations/{provider}/{organization}/repositories",
        primary_keys=["provider", "owner", "name"],
    ),
    "people": CodacyEndpointConfig(
        name="people",
        # Resolves the author identities stamped on commits and pull requests.
        path="/organizations/{provider}/{organization}/people",
        # `userId` and `committerId` are both optional — they are null for commit authors who
        # never registered with Codacy — so the email is the only always-present identifier.
        primary_keys=["email"],
    ),
    "files": CodacyEndpointConfig(
        name="files",
        path="/organizations/{provider}/{organization}/repositories/{repository}/files",
        fan_out="repository",
        # `fileId` identifies a file in a specific branch and commit, so it changes across
        # analyses; the repository-relative path is the stable identity of a file row.
        primary_keys=["repository", "path"],
    ),
    "issues": CodacyEndpointConfig(
        name="issues",
        path="/analysis/organizations/{provider}/{organization}/repositories/{repository}/issues/search",
        method="POST",
        fan_out="repository",
        primary_keys=["repository", "resultDataId"],
    ),
    "pull_requests": CodacyEndpointConfig(
        name="pull_requests",
        path="/analysis/organizations/{provider}/{organization}/repositories/{repository}/pull-requests",
        fan_out="repository",
        primary_keys=["repository", "number"],
        # The API returns pull requests last-updated first (verified against the live API).
        sort_mode="desc",
        extra_params={"includeNotAnalyzed": "true"},
    ),
    "commits": CodacyEndpointConfig(
        name="commits",
        # Analysis results for the commits in the repository's main branch on Codacy.
        path="/analysis/organizations/{provider}/{organization}/repositories/{repository}/commits",
        fan_out="repository",
        primary_keys=["repository", "sha"],
        partition_key="commitTimestamp",
        # The API returns commits newest-first (verified against the live API).
        sort_mode="desc",
    ),
    "commit_delta_issues": CodacyEndpointConfig(
        name="commit_delta_issues",
        # The individual issues a commit introduced or fixed, which the flat issues table cannot
        # express — it only holds the issues currently open.
        path="/analysis/organizations/{provider}/{organization}/repositories/{repository}/commits/{commit}/deltaIssues",
        fan_out="commit",
        primary_keys=["repository", "commitSha", "resultDataId"],
        # Commits are walked newest-first, so the rows land newest-first too.
        sort_mode="desc",
    ),
    "tools": CodacyEndpointConfig(
        name="tools",
        # Lookup resolving the toolUuid every issue row carries. Not organization-scoped: the
        # tool catalog is the same for every Codacy account.
        path="/tools",
        primary_keys=["uuid"],
    ),
    "tool_patterns": CodacyEndpointConfig(
        name="tool_patterns",
        path="/tools/{tool_uuid}/patterns",
        fan_out="tool",
        # The API documents pattern ids as unique per tool, not globally.
        primary_keys=["toolUuid", "id"],
    ),
    "metrics_timerange": CodacyEndpointConfig(
        name="metrics_timerange",
        # Codacy's own dashboard numbers, precomputed per period and broken down by repository.
        path="/organizations/{provider}/{organization}/metrics/{metric}/timerange",
        method="POST",
        fan_out="metric",
        primary_keys=["metricName", "date", "repository"],
        partition_key="date",
    ),
}

ENDPOINTS = tuple(CODACY_ENDPOINTS.keys())

# Codacy's v3 list endpoints expose no server-side updated-since/created-since filters
# (pagination is cursor+limit only), so every endpoint is full refresh. The metrics time series
# does take a date range, but the fan-out interleaves one ascending series per metric into a
# single table, so the pipeline's watermark could not advance monotonically.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in CODACY_ENDPOINTS}
