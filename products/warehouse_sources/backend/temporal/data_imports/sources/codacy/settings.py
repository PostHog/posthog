from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class CodacyEndpointConfig:
    name: str
    # Path template with {provider}, {organization}, and (for fan-out endpoints) {repository}
    path: str
    # searchRepositoryIssues is the one POST list endpoint; pagination still rides the query string.
    method: Literal["GET", "POST"] = "GET"
    # Composite keys include the repository name for fan-out children, whose ids are only
    # unique within a repository.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Fan-out: fetched once per repository in the configured organization.
    fan_out_per_repository: bool = False
    # Stable datetime field to partition by (never a mutable field like `updated`).
    partition_key: Optional[str] = None
    sort_mode: Literal["asc", "desc"] = "asc"
    extra_params: dict[str, str] = field(default_factory=dict)
    # Hard cap on pages fetched per repository in a fan-out, to bound runaway pagination.
    # A structured warning is logged if the cap is reached.
    max_pages_per_repository: int = 1000


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
    "files": CodacyEndpointConfig(
        name="files",
        path="/organizations/{provider}/{organization}/repositories/{repository}/files",
        fan_out_per_repository=True,
        # `fileId` identifies a file in a specific branch and commit, so it changes across
        # analyses; the repository-relative path is the stable identity of a file row.
        primary_keys=["repository", "path"],
    ),
    "issues": CodacyEndpointConfig(
        name="issues",
        path="/analysis/organizations/{provider}/{organization}/repositories/{repository}/issues/search",
        method="POST",
        fan_out_per_repository=True,
        primary_keys=["repository", "resultDataId"],
    ),
    "pull_requests": CodacyEndpointConfig(
        name="pull_requests",
        path="/analysis/organizations/{provider}/{organization}/repositories/{repository}/pull-requests",
        fan_out_per_repository=True,
        primary_keys=["repository", "number"],
        # The API returns pull requests last-updated first (verified against the live API).
        sort_mode="desc",
        extra_params={"includeNotAnalyzed": "true"},
    ),
    "commits": CodacyEndpointConfig(
        name="commits",
        # Analysis results for the commits in the repository's main branch on Codacy.
        path="/analysis/organizations/{provider}/{organization}/repositories/{repository}/commits",
        fan_out_per_repository=True,
        primary_keys=["repository", "sha"],
        partition_key="commitTimestamp",
        # The API returns commits newest-first (verified against the live API).
        sort_mode="desc",
    ),
}

ENDPOINTS = tuple(CODACY_ENDPOINTS.keys())

# Codacy's v3 list endpoints expose no server-side updated-since/created-since filters
# (pagination is cursor+limit only), so every endpoint is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in CODACY_ENDPOINTS}
