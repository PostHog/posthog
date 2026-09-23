from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import (
    PartitionFormat,
    PartitionMode,
)
from products.warehouse_sources.backend.types import IncrementalField

DEEPSOURCE_API_URL = "https://api.deepsource.com/graphql/"

# DeepSource enforces a flat 5,000 requests/hour rate limit per user account, so page size
# is a direct lever on API cost. The docs don't publish a max page size for Relay `first`
# arguments; 50 is a conservative value verified against similar GraphQL APIs.
DEEPSOURCE_DEFAULT_PAGE_SIZE = 50
# Repository enumeration only pulls names, so a bigger page keeps the fan-out setup cheap.
DEEPSOURCE_REPOSITORY_LIST_PAGE_SIZE = 100
# Checks ride along nested in the analysis-run walk, one per analyzer enabled on the run.
# DeepSource ships far fewer analyzers than this, so a run needing a second page is rare.
DEEPSOURCE_CHECKS_PER_RUN_PAGE_SIZE = 50

# Hard cap per Relay connection walk so a pathological cursor loop can't scan unbounded
# pages. At the default page size this still allows 100k rows per connection.
DEEPSOURCE_MAX_PAGES_PER_CONNECTION = 2000

CREATED_AT = "createdAt"

# All DeepSource connections are Relay cursor-paginated with no server-side timestamp
# filter (verified via schema introspection: connection args are only offset/before/
# after/first/last), so no endpoint qualifies for incremental sync — every schema is
# full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}


@dataclass(frozen=True)
class DeepsourceEndpointConfig:
    primary_keys: list[str]
    # GraphQL connection field on Repository for paginated per-repository fan-out.
    connection_field: str | None = None
    # GraphQL connection field on the root query, walked once for the whole account.
    root_connection_field: str | None = None
    # metrics/reports: fetched as one non-paginated query per repository.
    per_repository_object: bool = False
    # Extra GraphQL variables this endpoint's query declares beyond the shared ones.
    extra_variables: dict[str, Any] = field(default_factory=dict)
    partition_mode: PartitionMode | None = None
    partition_format: PartitionFormat | None = None
    partition_keys: list[str] | None = None
    should_sync_default: bool = True

    def __post_init__(self) -> None:
        shapes = [bool(self.connection_field), bool(self.root_connection_field), self.per_repository_object]
        if sum(shapes) > 1:
            raise ValueError("An endpoint has at most one of: repository connection, root connection, object query")


DEEPSOURCE_ENDPOINTS: dict[str, DeepsourceEndpointConfig] = {
    "repositories": DeepsourceEndpointConfig(
        primary_keys=["id"],
    ),
    "analysis_runs": DeepsourceEndpointConfig(
        primary_keys=["id"],
        connection_field="analysisRuns",
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[CREATED_AT],
    ),
    "checks": DeepsourceEndpointConfig(
        primary_keys=["id"],
        # Checks are fetched nested in the analysis-run walk, so this endpoint pages over
        # analysisRuns and expands each run into one row per analyzer check.
        connection_field="analysisRuns",
        extra_variables={"checkPageSize": DEEPSOURCE_CHECKS_PER_RUN_PAGE_SIZE},
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[CREATED_AT],
    ),
    "pull_requests": DeepsourceEndpointConfig(
        primary_keys=["id"],
        connection_field="pullRequests",
        partition_mode="datetime",
        partition_format="month",
        partition_keys=[CREATED_AT],
    ),
    "issues": DeepsourceEndpointConfig(
        primary_keys=["id"],
        connection_field="issues",
    ),
    "issue_occurrences": DeepsourceEndpointConfig(
        primary_keys=["id"],
        connection_field="issueOccurrences",
    ),
    "vulnerability_occurrences": DeepsourceEndpointConfig(
        primary_keys=["id"],
        connection_field="dependencyVulnerabilityOccurrences",
    ),
    "analyzers": DeepsourceEndpointConfig(
        primary_keys=["id"],
        root_connection_field="analyzers",
    ),
    "metrics": DeepsourceEndpointConfig(
        primary_keys=["id"],
        per_repository_object=True,
    ),
    "reports": DeepsourceEndpointConfig(
        primary_keys=["repositoryId", "key"],
        per_repository_object=True,
    ),
}

ENDPOINTS = tuple(DEEPSOURCE_ENDPOINTS.keys())
