from dataclasses import dataclass, field
from typing import Literal

PaginationStyle = Literal["none", "page", "cursor", "body_cursor"]


@dataclass(frozen=True)
class SemgrepEndpointConfig:
    # Path relative to the API base URL; may contain `{deployment_slug}` / `{deployment_id}`
    # placeholders resolved per deployment during the fan-out.
    path: str
    # Response key carrying the row list (Semgrep wraps every list payload in an object).
    data_key: str
    # `page` = zero-indexed `page`/`page_size` params; `cursor` = `cursor`/`limit` params with the
    # next cursor returned in the response body; `body_cursor` = POST search endpoints that take the
    # page size and cursor in the JSON body; `none` = single unpaginated request.
    pagination: PaginationStyle = "page"
    page_size: int | None = None
    method: Literal["get", "post"] = "get"
    # JSON body field carrying the page size for `body_cursor` endpoints.
    page_size_param: str | None = None
    # Response flag that marks the last page, when the endpoint returns one.
    has_more_key: str | None = None
    # `dependency_repositories` fans out a second level, from each repository with dependencies.
    parent: Literal["deployments", "dependency_repositories"] = "deployments"
    # Static query params sent on every request (e.g. `issue_type`, `dedup`).
    params: dict[str, str] = field(default_factory=dict)
    # Fan-out rows get `deployment_id`/`deployment_slug` injected, and the composite key guards
    # against id collisions if a token ever spans more than one deployment.
    primary_keys: list[str] = field(default_factory=lambda: ["deployment_id", "id"])
    # Stable creation timestamp for datetime partitioning (never a churning field like updated_at).
    partition_key: str | None = None
    # Findings arrive newest-first (`relevant_since` descending, no sort param). Irrelevant for the
    # full-refresh-only sync these endpoints use, but declared truthfully.
    sort_mode: Literal["asc", "desc"] = "asc"


# Semgrep AppSec Platform REST API (https://semgrep.dev/api/v1/docs/). Requires an API token with
# the Web API scope (Team/Enterprise tier). Tokens are scoped to a single deployment, so the
# per-deployment fan-out normally iterates exactly one deployment. No endpoint offers a server-side
# updated-since filter (findings' `since` filters on `relevant_since`, which does not advance when
# a finding's status/triage changes, and scans' `since` filters on creation time while a running
# scan's status changes later), so every table syncs as full refresh (see source.py).
SEMGREP_ENDPOINTS: dict[str, SemgrepEndpointConfig] = {
    "deployments": SemgrepEndpointConfig(
        path="/deployments",
        data_key="deployments",
        pagination="none",
        primary_keys=["id"],
    ),
    "projects": SemgrepEndpointConfig(
        path="/deployments/{deployment_slug}/projects",
        data_key="projects",
        page_size=100,
    ),
    "sast_findings": SemgrepEndpointConfig(
        path="/deployments/{deployment_slug}/findings",
        data_key="findings",
        # Findings allow page_size 100-3000; a bigger page keeps request volume down on large
        # backlogs without inflating per-yield memory beyond the pipeline's buffering thresholds.
        page_size=1000,
        # dedup=true collapses per-branch duplicates so counts match the Semgrep UI.
        params={"issue_type": "sast", "dedup": "true"},
        partition_key="created_at",
        sort_mode="desc",
    ),
    "sca_findings": SemgrepEndpointConfig(
        path="/deployments/{deployment_slug}/findings",
        data_key="findings",
        page_size=1000,
        params={"issue_type": "sca", "dedup": "true"},
        partition_key="created_at",
        sort_mode="desc",
    ),
    "secrets": SemgrepEndpointConfig(
        path="/deployments/{deployment_id}/secrets",
        data_key="findings",
        pagination="cursor",
        page_size=100,
        # The secrets endpoint uses camelCase field names, unlike the findings endpoints.
        partition_key="createdAt",
        sort_mode="desc",
    ),
    # The scans and dependency endpoints are POST searches marked experimental in Semgrep's spec.
    "scans": SemgrepEndpointConfig(
        path="/deployments/{deployment_id}/scans/search",
        data_key="scans",
        pagination="body_cursor",
        method="post",
        page_size=500,
        page_size_param="limit",
        partition_key="started_at",
    ),
    "dependencies": SemgrepEndpointConfig(
        path="/deployments/{deployment_id}/dependencies",
        data_key="dependencies",
        pagination="body_cursor",
        method="post",
        page_size=1000,
        page_size_param="pageSize",
        has_more_key="hasMore",
        # Dependency rows carry no id; `dependency_key` is a hash of the fields that identify one.
        primary_keys=["deployment_id", "dependency_key"],
    ),
    "dependency_repositories": SemgrepEndpointConfig(
        path="/deployments/{deployment_id}/dependencies/repositories",
        data_key="repositorySummaries",
        pagination="body_cursor",
        method="post",
        page_size=100,
        page_size_param="pageSize",
        has_more_key="hasMore",
    ),
    "dependency_lockfiles": SemgrepEndpointConfig(
        path="/deployments/{deployment_id}/dependencies/repositories/{repository_id}/lockfiles",
        data_key="lockfileSummaries",
        pagination="body_cursor",
        method="post",
        page_size=100,
        page_size_param="pageSize",
        has_more_key="hasMore",
        parent="dependency_repositories",
        primary_keys=["deployment_id", "repository_id", "lockfilePath"],
    ),
}

ENDPOINTS = tuple(SEMGREP_ENDPOINTS.keys())
