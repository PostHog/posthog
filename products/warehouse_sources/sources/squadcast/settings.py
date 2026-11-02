from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How each endpoint is iterated. Squadcast mixes several pagination styles across its API
# versions, so the transport dispatches on this instead of hardcoding per-endpoint branches:
# - "none": a single request returns the full list (no pagination params).
# - "offset": 0-based `offset`/`limit` params with a `meta.total` counter (SLOs).
# - "cursor": `pageSize`/`cursor` params with a `pageInfo.nextCursor` reference (v4 schedules).
# - "incident_export": required `start_time`/`end_time` window, chunked client-side (incidents).
# - "postmortems": required `fromDate`/`toDate`/`limit` window, single request per team.
# - "schedule_rotations": walks each team's v4 schedules and lists the rotations of every schedule.
PaginationStyle = Literal["none", "offset", "cursor", "incident_export", "postmortems", "schedule_rotations"]


@frozen
class SquadcastEndpointConfig:
    path: str  # Path under the regional API base URL, e.g. "/v3/services"
    pagination: PaginationStyle = "none"
    # Query param carrying the team id for team-scoped endpoints ("owner_id" on v3,
    # "teamID" on v4). None means the endpoint is org-level and needs no fan-out.
    team_param: Optional[str] = None
    # Keys to walk in the response body to reach the list of rows.
    envelope: tuple[str, ...] = ("data",)
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: Optional[str] = None  # Stable datetime field used to partition (never a mutable field)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Credential-bearing row fields dropped before rows are yielded, so live keys never
    # land in warehouse tables readable by any PostHog user.
    sensitive_fields: tuple[str, ...] = ()


_CREATED_AT_INCREMENTAL: list[IncrementalField] = [
    {
        "label": "created_at",
        "type": IncrementalFieldType.DateTime,
        "field": "created_at",
        "field_type": IncrementalFieldType.DateTime,
    },
]


SQUADCAST_ENDPOINTS: dict[str, SquadcastEndpointConfig] = {
    "incidents": SquadcastEndpointConfig(
        # The API has no plain incident list endpoint; the JSON export is the documented way to
        # pull incidents in bulk. Its required `start_time`/`end_time` filters key on creation
        # time, which gives us a genuine server-side incremental window. Status changes to
        # incidents created before the cursor are only picked up by a full refresh.
        path="/v3/incidents/export",
        pagination="incident_export",
        team_param="owner_id",
        partition_key="created_at",
        incremental_fields=_CREATED_AT_INCREMENTAL,
    ),
    "postmortems": SquadcastEndpointConfig(
        path="/v3/incidents/postmortem",
        pagination="postmortems",
        team_param="owner_id",
        partition_key="created_at",
        incremental_fields=_CREATED_AT_INCREMENTAL,
    ),
    "services": SquadcastEndpointConfig(
        path="/v3/services",
        team_param="owner_id",
        # `api_key` is the live key alert sources use to send events to the service.
        sensitive_fields=("api_key",),
    ),
    "escalation_policies": SquadcastEndpointConfig(
        # The endpoint documents optional `page_number`/`page_size` params, but their base
        # (0 vs 1) is undocumented and per-team policy counts are small, so we make a single
        # unpaginated request and warn if `meta.total_count` reports more rows than returned.
        path="/v3/escalation-policies",
        team_param="owner_id",
    ),
    "schedules": SquadcastEndpointConfig(
        path="/v4/schedules",
        pagination="cursor",
        team_param="teamID",
    ),
    "schedule_rotations": SquadcastEndpointConfig(
        path="/v4/schedules/{schedule_id}/rotations",
        pagination="schedule_rotations",
        team_param="teamID",
        # Rotation ids are only documented as unique within their schedule.
        primary_keys=("scheduleID", "id"),
    ),
    "runbooks": SquadcastEndpointConfig(
        path="/v3/runbooks",
        team_param="owner_id",
    ),
    "slos": SquadcastEndpointConfig(
        path="/v3/slo",
        pagination="offset",
        team_param="owner_id",
        envelope=("data", "slos"),
    ),
    "squads": SquadcastEndpointConfig(
        # The response carries `pageInfo`, but the endpoint documents no page size or cursor
        # params, so we make one request per team and warn if `pageInfo.hasNext` is set.
        path="/v4/squads",
        team_param="owner_id",
    ),
    "users": SquadcastEndpointConfig(
        path="/v3/users",
    ),
    "teams": SquadcastEndpointConfig(
        path="/v3/teams",
    ),
}

ENDPOINTS = tuple(SQUADCAST_ENDPOINTS.keys())
