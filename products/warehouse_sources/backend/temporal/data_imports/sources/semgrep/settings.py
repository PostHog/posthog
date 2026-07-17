from dataclasses import dataclass, field
from typing import Literal

PaginationStyle = Literal["none", "page", "cursor"]


@dataclass
class SemgrepEndpointConfig:
    # Path relative to the API base URL; may contain `{deployment_slug}` / `{deployment_id}`
    # placeholders resolved per deployment during the fan-out.
    path: str
    # Response key carrying the row list (Semgrep wraps every list payload in an object).
    data_key: str
    # `page` = zero-indexed `page`/`page_size` params; `cursor` = `cursor`/`limit` params with the
    # next cursor returned in the response body; `none` = single unpaginated request.
    pagination: PaginationStyle = "page"
    page_size: int | None = None
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
# a finding's status/triage changes), so every table syncs as full refresh (see source.py).
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
}

ENDPOINTS = tuple(SEMGREP_ENDPOINTS.keys())
