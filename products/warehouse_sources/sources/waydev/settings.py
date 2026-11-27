from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField

ENDPOINTS = (
    "Metrics",
    "Incidents",
    "Repositories",
    "Contributors",
    "Teams",
    "TeamMembers",
    "PullRequests",
    "Commits",
)

# No endpoint documents a server-side timestamp filter (the list endpoints only take
# paging and name/state filters, and Metrics is a static catalog), so all sync full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}

# The public reference documents a `limit` param (default 25) with no stated maximum;
# 100 keeps page count down without a documented ceiling to test against.
INCIDENTS_PAGE_SIZE = 100
REPOSITORIES_PAGE_SIZE = 500
# Teams and team members document a default of 10 per page and no maximum.
TEAMS_PAGE_SIZE = 100


@dataclass(frozen=True)
class WaydevFanoutEndpointConfig:
    name: str
    path: str
    # Unused: page sizes go in `parent_params` / `child_params`, because pulls and commits take none.
    page_size: int = 0
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: Optional[str] = None


# Waydev only processes data for selected repositories, so unselected ones have no commits or pulls.
_SELECTED_REPOSITORIES = DependentEndpointConfig(
    parent_name="Repositories",
    resolve_param="repository_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "repository_id"},
    parent_params={"state": "selected", "limit": REPOSITORIES_PAGE_SIZE},
    # A repository removed between the listing and the child request returns 404.
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)

# Parents are listed here only so the fan-out helper can read their paths; they sync through
# `get_resource` like the other top-level endpoints.
FANOUT_ENDPOINTS: dict[str, WaydevFanoutEndpointConfig] = {
    "Repositories": WaydevFanoutEndpointConfig(name="Repositories", path="/repositories"),
    "Teams": WaydevFanoutEndpointConfig(name="Teams", path="/teams"),
    # A developer can belong to several teams, so the team id is part of the key.
    "TeamMembers": WaydevFanoutEndpointConfig(
        name="TeamMembers",
        path="/teams/{team_id}/members",
        primary_keys=["team_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="Teams",
            resolve_param="team_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "team_id"},
            parent_params={"limit": TEAMS_PAGE_SIZE},
            child_params={"limit": TEAMS_PAGE_SIZE},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    "PullRequests": WaydevFanoutEndpointConfig(
        name="PullRequests",
        path="/repositories/{repository_id}/pulls",
        primary_keys=["repository_id", "id"],
        partition_key="created_date",
        fanout=_SELECTED_REPOSITORIES,
    ),
    "Commits": WaydevFanoutEndpointConfig(
        name="Commits",
        path="/repositories/{repository_id}/commits",
        primary_keys=["repository_id", "id"],
        partition_key="date",
        fanout=_SELECTED_REPOSITORIES,
    ),
}
