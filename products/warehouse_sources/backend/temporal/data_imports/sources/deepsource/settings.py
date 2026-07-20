from dataclasses import dataclass

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
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

# Hard cap per Relay connection walk so a pathological cursor loop can't scan unbounded
# pages. At the default page size this still allows 100k rows per connection.
DEEPSOURCE_MAX_PAGES_PER_CONNECTION = 2000

CREATED_AT = "createdAt"

# All DeepSource connections are Relay cursor-paginated with no server-side timestamp
# filter (verified via schema introspection: connection args are only offset/before/
# after/first/last), so no endpoint qualifies for incremental sync — every schema is
# full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}


@dataclass
class DeepsourceEndpointConfig:
    primary_keys: list[str]
    # GraphQL connection field on Repository for paginated per-repository fan-out.
    connection_field: str | None = None
    # metrics/reports: fetched as one non-paginated query per repository.
    per_repository_object: bool = False
    partition_mode: PartitionMode | None = None
    partition_format: PartitionFormat | None = None
    partition_keys: list[str] | None = None
    should_sync_default: bool = True

    def __post_init__(self) -> None:
        if self.connection_field and self.per_repository_object:
            raise ValueError("An endpoint is either a paginated connection or a per-repository object, not both")


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
