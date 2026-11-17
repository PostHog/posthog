from dataclasses import dataclass, field


@dataclass(frozen=True)
class ZendutyEndpointConfig:
    name: str
    # Path relative to https://www.zenduty.com. Fan-out paths carry the parent's placeholder
    # (`{team_id}` or `{incident_number}`), resolved per parent row.
    path: str
    # Key into FAN_OUT_PARENTS when the endpoint is a per-parent child collection: the transport
    # first lists every parent, then walks the child collection once per parent, tagging each row
    # with the parent's id. None for a top-level collection.
    parent: str | None = None
    primary_keys: list[str] = field(default_factory=lambda: ["unique_id"])
    should_sync_default: bool = True
    page_size: int = 100


@dataclass(frozen=True)
class ZendutyFanOutParent:
    # Top-level endpoint that lists the parents.
    endpoint: str
    # Field on the parent row whose value fills the child path.
    id_field: str
    # Child path placeholder. Also the ZendutyResumeConfig field that holds the in-progress parent.
    path_param: str
    # Injected into every child row so the parent is recoverable and the composite primary key
    # stays unique table-wide (a child id is only guaranteed unique within its parent).
    injected_field: str


PARENT_TEAM_ID_FIELD = "_zenduty_team_id"
PARENT_INCIDENT_NUMBER_FIELD = "_zenduty_incident_number"

FAN_OUT_PARENTS: dict[str, ZendutyFanOutParent] = {
    "teams": ZendutyFanOutParent(
        endpoint="teams", id_field="unique_id", path_param="team_id", injected_field=PARENT_TEAM_ID_FIELD
    ),
    "incidents": ZendutyFanOutParent(
        endpoint="incidents",
        id_field="incident_number",
        path_param="incident_number",
        injected_field=PARENT_INCIDENT_NUMBER_FIELD,
    ),
}


def _fan_out(name: str, path: str, parent: str, should_sync_default: bool = True) -> ZendutyEndpointConfig:
    return ZendutyEndpointConfig(
        name=name,
        path=path,
        parent=parent,
        primary_keys=[FAN_OUT_PARENTS[parent].injected_field, "unique_id"],
        should_sync_default=should_sync_default,
    )


def _team_nested(name: str, path: str) -> ZendutyEndpointConfig:
    return _fan_out(name, path, parent="teams")


def _incident_nested(name: str, path: str) -> ZendutyEndpointConfig:
    # One request per incident on every full refresh, so these stay opt-in.
    return _fan_out(name, path, parent="incidents", should_sync_default=False)


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
    "priorities": _team_nested("priorities", "/api/account/teams/{team_id}/priority/"),
    # v2 groups the current on-call users by escalation policy and rule, one row per policy.
    "oncall": _team_nested("oncall", "/api/v2/account/teams/{team_id}/oncall/"),
    # Incident-nested collections (fan out over every incident).
    "incident_alerts": _incident_nested("incident_alerts", "/api/incidents/{incident_number}/alerts/"),
    "incident_responders": _incident_nested("incident_responders", "/api/v2/incidents/{incident_number}/responders/"),
}

ENDPOINTS = tuple(ZENDUTY_ENDPOINTS.keys())
