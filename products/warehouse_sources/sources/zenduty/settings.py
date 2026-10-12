from dataclasses import dataclass, field


@dataclass
class ZendutyEndpointConfig:
    name: str
    # Path relative to https://www.zenduty.com. Team-nested paths carry a `{team_id}`
    # placeholder resolved per parent team during fan-out.
    path: str
    # When True, the endpoint lives under `/api/account/teams/{team_id}/...`, so the transport
    # first lists every team and then walks the child collection once per team, tagging each
    # row with the parent team's id.
    team_nested: bool = False
    primary_keys: list[str] = field(default_factory=lambda: ["unique_id"])
    should_sync_default: bool = True
    page_size: int = 100


# The field injected into every fan-out child row so the parent team is recoverable and the
# composite primary key stays unique table-wide (a child id is only unique within its team).
PARENT_TEAM_ID_FIELD = "_zenduty_team_id"


def _team_nested(name: str, path: str) -> ZendutyEndpointConfig:
    # Child ids are only guaranteed unique within their parent team, so include the parent id in
    # the key — otherwise a merge multi-matches duplicate ids across teams (see the skill's OOM note).
    return ZendutyEndpointConfig(
        name=name,
        path=path,
        team_nested=True,
        primary_keys=[PARENT_TEAM_ID_FIELD, "unique_id"],
    )


# Endpoint catalog. Paths are relative to https://www.zenduty.com. Every path here was confirmed to
# be a real route against the live API (real routes return a 403 "Invalid or Inactive Token" JSON body
# on a bad token; unknown routes return 404). `incidents` is the documented account-level list route;
# our unauthenticated probe was blocked by Zenduty's WAF (HTTP 209), so its exact response shape is
# handled defensively (see `_extract_items_and_next`). The set mirrors the streams a reliability team
# actually warehouses from an incident-management/on-call platform.
ZENDUTY_ENDPOINTS: dict[str, ZendutyEndpointConfig] = {
    # Account-level (top-level) collections.
    "teams": ZendutyEndpointConfig(name="teams", path="/api/account/teams/"),
    "account_members": ZendutyEndpointConfig(name="account_members", path="/api/account/members/"),
    "incidents": ZendutyEndpointConfig(name="incidents", path="/api/incidents/"),
    # Team-nested collections (fan out over every team).
    "services": _team_nested("services", "/api/account/teams/{team_id}/services/"),
    "escalation_policies": _team_nested("escalation_policies", "/api/account/teams/{team_id}/escalation_policies/"),
    "schedules": _team_nested("schedules", "/api/account/teams/{team_id}/schedules/"),
    "team_members": _team_nested("team_members", "/api/account/teams/{team_id}/members/"),
    "roles": _team_nested("roles", "/api/account/teams/{team_id}/roles/"),
    "postmortems": _team_nested("postmortems", "/api/account/teams/{team_id}/postmortem/"),
    "maintenance_windows": _team_nested("maintenance_windows", "/api/account/teams/{team_id}/maintenance/"),
    "slas": _team_nested("slas", "/api/account/teams/{team_id}/sla/"),
    "tags": _team_nested("tags", "/api/account/teams/{team_id}/tags/"),
}

ENDPOINTS = tuple(ZENDUTY_ENDPOINTS.keys())
